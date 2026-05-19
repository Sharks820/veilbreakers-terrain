# Claude Repo Rules

Follow `AGENTS.md`. These merge rules are mandatory:

- Never edit, commit, or push directly on `main`.
- Start implementation from a focused branch: `fix/<scope>`, `feat/<scope>`, `audit/<scope>`, `docs/<scope>`, or `ci/<scope>`.
- If another agent is active, use a separate worktree:
  `git worktree add ..\veilbreakers-terrain-<scope> -b fix/<scope> origin/main`.
- Open PRs into `main`; do not bypass PR checks.
- Use squash merge by default: `gh pr merge --squash --auto`.
- Do not loosen branch protection to merge failing work.
- Required checks: `ci (3.11)`, `ci (3.12)`, `pyright`, `callable-census`, `Analyze (python)`, `Analyze (actions)`.

If instructions conflict, `AGENTS.md` wins.

## Y04 v3 fix workflow — read `FIX_PATTERN_v1.md` BEFORE starting any fix

Every fix from the Y04 v3 queue (140 P0 / ~155 line items / 16 critical-path nodes) routes through **`docs/aaa-audit/2026_05_17_ultrafinal/FIX_PATTERN_v1.md`** — the canonical Compound-Engineering-grounded workflow.

- **The Unified Spine (§2)** — 7 steps every fix follows: S-1 learnings sweep → S-2 codebase research → S-3 plan → S-4 worktree → S-5 implementation (test-first per category) → S-6 local 4-gate → S-7 CE review wave + compound.
- **9 Fix Categories (§3)** — C1 credential, C2 git-history rewrite, C3 silent-corruption gate flip, C4 boundary contract, C5 numerical/unit, C6 regression-net, C7 new operational code, C8 visual mandate, C9 perf/HW. Each has a recipe with specific CE review-agent roster.
- **§4.5 Multi-category collision** — 35 of 155 items dual-tagged; destructiveness-ordered lead-category rule (C2 > C1 > C3 > C9 > C8 > C7 > C4 > C5 > C6).
- **§5 PR template** — every PR uses the same template (Y04 v3 anchor + plan + test evidence + gate evidence + CE review verdicts + visual proof + rollback + compound entry path).
- **§6 mapping** — Y04 v3 ord → category; look up your fix here first.

**Y04 v3 fix order** lives in `docs/aaa-audit/2026_05_17_ultrafinal/MASTER_FINAL.md` Part P §P.8. Strict CPM ordering in `docs/aaa-audit/2026_05_17_ultrafinal/Y04_v2_FIX_ORDER_2026_05_18.md`.

**Compounding (§7)** — after every fix lands on `main`, write a `docs/solutions/<category>/<slug>-YYYY-MM-DD.md` entry capturing what worked, what the pattern missed, and any reusable sub-pattern. See `docs/solutions/best-practices/regression-net-per-raise-path-xfail-strict-2026-05-19.md` as the canonical example from T0.5-3 / PR #75.

**Local 4-gate** (per `feedback_pre_commit_verifier_workflow.md` in user-memory; mandatory before every push):

```powershell
python scripts\pyright_strict_baseline_gate.py
python scripts\callable_census_gate.py --strict-zero
python scripts\terrain_best_practice_guardrail.py --strict-verification
python -m pytest veilbreakers_terrain\tests -x --no-header -q
```

If a fix doesn't fit any of the 9 categories in `FIX_PATTERN_v1.md` §3, that is a signal — re-classify before deviating, or file a delta against `FIX_PATTERN_v2.md` (see §10 versioning).
