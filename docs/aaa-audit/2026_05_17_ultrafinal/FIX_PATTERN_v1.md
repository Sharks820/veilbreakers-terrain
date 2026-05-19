# FIX_PATTERN_v1 — Canonical CE-grounded Fix Workflow

**Authored:** 2026-05-19 (session resume after 2026-05-18 evening pause).
**Anchors:** Y04 v3 fix order (`MASTER_FINAL.md` Part P §P.8); Y04 v2 (`Y04_v2_FIX_ORDER_2026_05_18.md`); 140 P0 / 155 line items / 16-node critical path.
**Methodology:** Compound Engineering (Kieran Klaassen / EveryInc) — plan-first, parallel-review, compound-after.
**Plugin:** `compound-engineering-plugin` installed at `~/.claude/plugins/marketplaces/compound-engineering-plugin/`.

This document is the canonical answer to: "I have a fix to do. What do I do?" It maps every Y04 v3 line item to one of 9 categories and gives each category a concrete CE-grounded recipe. The pattern is the system that the next 13–17 weeks of work runs through.

---

## 0. Purpose, scope, and the one rule

**Purpose.** Every Y04 v3 fix — F1, T-prep-0, T0-1..T0-8, T0.5-1..T0.5-9, T1-1..T1-47, PR-OG-A..F, PR-VV-A..E, T2-1..T2-41, T3-1..T3-16, T4-1..T4-31 — moves through the same Unified Spine (§2), then takes a category-specific recipe (§3) for ceremony that the spine does not cover.

**Scope.** Lives alongside MASTER_FINAL.md and Y04 v2 in `docs/aaa-audit/2026_05_17_ultrafinal/`. Authoritative until superseded by a `FIX_PATTERN_v2.md`. CLAUDE.md will point every future agent here.

**The one rule.** Trust the spine. If a fix feels like it needs to skip a spine step, that is the signal that the fix is misclassified — re-classify it before deviating.

---

## 1. CE methodology reminder (one paragraph)

Compound Engineering: each unit of engineering work must make subsequent units easier. **Plan + Review = 80% of value; execution + compounding = 20%.** The loop is `/ce-strategy → /ce-ideate → /ce-brainstorm → /ce-plan → /ce-work → /ce-code-review → /ce-compound`. Skills live in `~/.claude/plugins/marketplaces/compound-engineering-plugin/`; 50+ specialist agents are dispatched via `Agent` tool with `subagent_type` matching `compound-engineering:ce-*-reviewer`. The 7 beliefs (extract taste into systems; 50/50 rule; trust safety nets; agent-native; parallelization; plans are the new code; core principles everywhere) define the posture. Canonical external references: the upstream CE plugin guide at `https://every.to/guides/compound-engineering` and the plugin source at `https://github.com/EveryInc/compound-engineering-plugin`.

> **Note on memory citations in this document.** This doc cites memory entries (e.g. `reference_compound_engineering.md`, `feedback_*.md`, `project_*.md`) that live in Claude Code's per-user auto-memory at `~/.claude/projects/<repo-slug>/memory/`. They are NOT in-repo files; they are session-persistent notes the agent maintains across runs. Treat them as the agent's accumulated taste, not as repo-canonical documentation. Where a memory citation is load-bearing for an external reader, the relevant content is also inlined in this document or in an `docs/solutions/` entry.

---

## 2. The Unified Spine (every fix, every category)

Seven steps. No skips.

### S-1 Learnings sweep (5 min)
Spawn `compound-engineering:ce-learnings-researcher` with the fix's domain keywords. It searches `docs/solutions/**/*.md` for prior fixes. If a prior solution exists, read it before designing. The four existing entries are: `pool-deepening-delta-double-apply-2026-05-03.md` (logic-errors), `erosion-profile-hardcoded-temperate-2026-05-03.md` (logic-errors), `biome-grammar-features-orphaned-pass-wiring-2026-05-03.md` (architecture-patterns), `visual-render-camera-proof-2026-05-04.md` (best-practices).

### S-2 Codebase research (10–30 min)
Spawn `compound-engineering:ce-repo-research-analyst` for non-trivial fixes; for known-anchor fixes, read the target file directly with Read. Always: (a) read the target file ±50 lines, (b) read the closest existing test file as pattern template, (c) check `Y04_v2_FIX_ORDER_2026_05_18.md` for the canonical dependency / blast-radius / HW row.

### S-3 Plan (15–60 min)
Write a plan as a top-level comment in the worktree's first commit, OR a doc at `docs/plans/2026-MM-DD-NNN-<scope>.md`. Plan contains: (i) Y04 v3 ordinal + category from §3, (ii) blast radius, (iii) test design (what failing test proves the bug — see §4), (iv) gate plan (which of the 4 local gates apply), (v) review-agent roster from category recipe.

### S-4 Worktree isolation (mandatory per `CLAUDE.md` / `AGENTS.md`)
Pre-flight verification BEFORE any worktree command (per `AGENTS.md` "Branch And Merge Protocol"):
```powershell
git status --short                # confirm clean working tree at current location
git branch --show-current         # confirm NOT on main
```
Then create the worktree:
```powershell
git worktree add ..\veilbreakers-terrain-<scope> -b <type>/<scope> origin/main
```
`<type>` is `fix` | `feat` | `audit` | `docs` | `ci` per `CLAUDE.md` rule. **Never edit `main` directly.** Each fix gets its own worktree even if another fix is in-flight; this is non-negotiable on this repo.

### S-5 Implementation with test-first regression net (varies)
**Prerequisite scan before any code is written.** Look up the fix's Y04 v3 ordinal in §6, then read its row in `Y04_v2_FIX_ORDER_2026_05_18.md`. If the row lists a `Blocked by` predecessor that is NOT yet on `main`, STOP and either land the predecessor first or document a hard-gated continuation in the plan doc. Example: T0-4's row in §6 says "needs T0.5-3" — T0-4 must NOT be started until T0.5-3 is merged on `main`.

Order of code-writing by category:
- **C3 / C4 / C5 / C6**: write the failing test FIRST and confirm it fails for the reason you expect, THEN implement the fix and confirm the test passes.
- **C7**: write the public API + types first, then the contract test for each public method, then implement (per the C7 recipe in §3). The contract test IS the design; this is test-first at the API level, not the bug-reproduction level.
- **C1 / C2 / C8 / C9**: test-first is less applicable as a unit-test reproduction; capture a baseline/manifest/measurement as the equivalent "before" artefact (e.g., `git log --all -p -- '<path>'` empty post-rewrite for C2; before/after VRAM table for C9).

### S-6 Local 4-gate (mandatory before push, per `feedback_pre_commit_verifier_workflow.md`)
Run these in order; each must pass before push. Skip-or-bypass is forbidden.
```powershell
python scripts\pyright_strict_baseline_gate.py
python scripts\callable_census_gate.py --strict-zero
python scripts\terrain_best_practice_guardrail.py --strict-verification
python -m pytest veilbreakers_terrain\tests\<the new test> -x -v
python -m pytest veilbreakers_terrain\tests -x --no-header -q   # full suite
```
On Windows + this repo, `python -m pytest` from repo root is the canonical invocation.

### S-7 Review wave → compound (per fix)
Spawn the category-specific CE review-agent roster (§3) in **parallel** in a single Agent call block. Wait for all to return.

**Verdict aggregation rule.** Treat any P0 from any reviewer as a hard block — fix before merge. Treat any P1 from any reviewer as a soft block — fix or document a deliberate accept-with-deferral note in the PR description. P2 is advisory.

**Reviewer conflict resolution.** When two reviewers disagree on the same diff (e.g., `ce-correctness-reviewer` returns GO and `ce-security-reviewer` returns BLOCK):
1. **Security-class reviewers always win on a BLOCK** (`ce-security-reviewer`, `ce-security-sentinel`, `ce-security-lens-reviewer`). A security BLOCK is non-overridable except by explicit user gate.
2. **Otherwise, BLOCK wins over GO** unless the BLOCK is a pure-stylistic finding (e.g., `ce-code-simplicity-reviewer` calling a 30-LOC helper "premature abstraction" while `ce-correctness-reviewer` says the helper is load-bearing). Style BLOCKs may be accepted-with-deferral with a 1-line rationale in the PR description.
3. **When BLOCKs disagree on substance**, escalate to user via `AskUserQuestion` with the two verdicts inline. Do not guess.
4. **Document the resolution path taken** in the PR description's "CE review verdicts" section so the next reviewer wave on a similar fix has a precedent.

After merge, `/ce-compound` (or write directly to `docs/solutions/<category>/<slug>-<date>.md` using the existing format). Update `MEMORY.md` index if the learning is durable.

---

## 3. The 9 Categories

Each recipe is self-contained — a future agent reading only its own category section should have everything needed to drive a fix from queue → merge.

### C1 — Credential rotation / supply-chain hardening

**When this category applies.** Rotating leaked credentials, pinning third-party SHAs, adding `permissions:` blocks to workflows, installing pre-commit hooks, setting up Dependabot / pip-audit / detect-secrets.

**Y04 v3 items in this category.** T-prep-0 (supply-chain guard), T0-1 (Tripo + 3 MCP keys), T0-6 (CI permissions + SHA-pin 16 `uses:`), T2-7 (path-traversal centralization — adjacent), T4-NEW-ZZ4-05 (required-check drift), T4-NEW-ZZ4-06 (lfs install), T4-NEW-ZZ4-07 (pyright-strict baseline cleanup).

**Pre-flight (before any work).**
- ⚠️ State the cost: tell the user which credentials get invalidated. No silent rotation.
- ⚠️ Verify the leak surface first (where does the secret currently live?) before deciding rotation order.
- ⚠️ For T0-1: Tripo JWT is **already expired** per ULTRAFINAL memory — rotation order is `delete .env.tripo_studio` → `invalidate session via dashboard` → re-issue. Do NOT just rotate the file; the session must be invalidated.

**CE planning agents (sequential).**
- `compound-engineering:ce-best-practices-researcher` — query Context7 for `/ibm/detect-secrets`, `/dependabot/dependabot-core`, GitHub `actions/checkout` SHA pinning practices.
- `compound-engineering:ce-framework-docs-researcher` — for any non-obvious cred-store API.

**Implementation order.**
1. Land guard (`pre-commit install` + `.secrets.baseline` + `.gitignore` `.env*`/`.mcp*` block) BEFORE rotation. Rotating-then-guarding re-leaks the next key.
2. Rotate, invalidate, re-issue.
3. Verify post-rotation via three signals (the GitHub Actions secrets REST API does NOT expose the secret value or a value-derived hash — only metadata, so use these instead): (a) `gh api repos/<o>/<r>/actions/secrets/<NAME>` shows a fresh `updated_at` timestamp post-rotation; (b) a no-op workflow run using the secret succeeds; (c) `gh api repos/<o>/<r>/secret-scanning/alerts` shows the old-key alert as `resolved`.

**Local gates beyond S-6.** `detect-secrets scan --update .secrets.baseline` — must show 0 net-new live secrets.

**CE review agents (parallel — single Agent block).**
- `compound-engineering:ce-security-reviewer` — diff-level security review.
- `compound-engineering:ce-security-sentinel` — OWASP / injection / hardcoded-secrets audit.
- `compound-engineering:ce-deployment-verification-agent` — produces Go/No-Go checklist + rollback procedure.

**Visual proof requirement.** None (no UI surface). Manifest-style proof: post-rotation `gh secret list` showing the new SHA.

**Compound entry path.** `docs/solutions/security/<slug>-YYYY-MM-DD.md`.

**Example fix walked end-to-end.** T0-1 Tripo JWT + 3 MCP keys rotation: S-1 search returns no prior credential-rotation entry → S-2 read `.env*` + `.mcp.json` to enumerate leak surfaces → S-3 plan `docs/plans/2026-05-19-T0-1-credential-rotation.md` including rollback (re-issue from dashboard if rotation breaks CI) → S-4 worktree `fix/credential-rotation-t0-1` → S-5 sequenced 3-step rotation → S-6 + `detect-secrets scan` → S-7 3 security reviewers + compound to `docs/solutions/security/`.

---

### C2 — Git-history rewrite

**When this category applies.** When a secret or sensitive file landed in git history and needs to be scrubbed from all reachable commits (not just `HEAD`).

**Y04 v3 items in this category.** **F1 NEW** (`.mcp.json` git-history scrub via BFG / `git filter-repo`) — the only canonical entry today.

**Pre-flight (mandatory).**
- ⚠️ Force-push gate: this category produces destructive operations. **Always confirm with user before force-push** per `CLAUDE.md` ("Never edit, commit, or push directly on `main`" + branch protection respect) and the system-prompt "Git Safety Protocol" ("Never run destructive git commands ... unless the user explicitly requests these actions"). Durable-instructions-only authorization.
- ⚠️ Warn-collaborators: anyone with the old `main` cloned will have to re-clone. Compose the announcement BEFORE the force-push.
- ⚠️ Backup: `git push origin main:backup/pre-history-rewrite-YYYY-MM-DD` BEFORE any rewrite.

**CE planning agents.**
- `compound-engineering:ce-git-history-analyzer` — survey the leak surface, identify ALL commits touching the file.
- `compound-engineering:ce-best-practices-researcher` — query Context7 for `/newren/git-filter-repo` and BFG canonical command sequence.

**Implementation order.**
1. Backup branch push.
2. `git filter-repo --replace-text expressions.txt` OR `bfg --replace-text expressions.txt` (filter-repo preferred — actively maintained).
3. Force-push to `main` AFTER user explicit confirmation.
4. Force-push all branches that had reachability.
5. Trigger GitHub's secret-scan re-run via `gh api repos/<o>/<r>/secret-scanning/alerts`.
6. Rotate the secrets that were in the scrubbed file (overlap with C1 — chain F1 → T0-1).

**Local gates beyond S-6.** `git log --all -p -- '<path>'` must return empty after rewrite. `gh api repos/<o>/<r>/secret-scanning/alerts` should show closed/resolved.

**CE review agents (parallel).**
- `compound-engineering:ce-security-reviewer`
- `compound-engineering:ce-security-sentinel`
- `compound-engineering:ce-git-history-analyzer` (re-spawn to verify post-state).

**Visual proof requirement.** None. Manifest: `git log --all -p -- '<scrubbed path>'` empty stdout pasted into PR description.

**Compound entry path.** `docs/solutions/security/git-history-rewrite-<slug>-YYYY-MM-DD.md`.

---

### C3 — Silent-corruption gate flip

**When this category applies.** Flipping a gate from "permissive" (`status="warning"`, `allow_pickle=True`, `allow_nan=True`) to "strict". The flip itself is 5 chars to 1 line of code; the danger is **the test surface that the gate has been disabling is unknown.**

**Y04 v3 items in this category.** T0-4 (warning-bypass flip + ChannelOwnershipError + `_restore_pass_state` on 3 raise paths), T0.5-2 (14 `status="warning"` → `"ok"`-strict lines tightened), T0.5-8 (`json.dumps(allow_nan=False)`), T0-7 (RCE — `allow_pickle=False`), T2-13 (validation discipline inversion).

**Pre-flight (mandatory).**
- ⚠️ **Regression net must land first.** For T0-4 specifically: T0.5-3 (`test_restore_pass_state.py`) MUST land before T0-4 per Y04 v3 §P.8.2. Verify the regression net exists and is green at `HEAD~1`.
- ⚠️ Estimate the cascade: spawn `compound-engineering:ce-correctness-reviewer` with `--dry-run-flip` prompt — "how many tests will fail when this gate flips to strict, and why?" — to know what you're walking into.
- ⚠️ Boundary classification: is this Shape A (silent), B (loud), or C (hybrid) per ZZ4-A6 §P.5.1?

**CE planning agents.**
- `compound-engineering:ce-correctness-reviewer` (planning phase, not review yet) — pre-flight failure-shape estimate.
- `compound-engineering:ce-testing-reviewer` (planning phase) — verify regression-net adequacy.

**Implementation order.**
1. Confirm regression-net green at `HEAD~1`.
2. Single-commit flip (no bundled refactor).
3. Run **only** the regression-net first — must go from green→red→green as fix lands.
4. Run full suite; collect every now-failing test.
5. Triage failures into: (a) latent-bug-this-flip-exposed (FIX_QUEUE, file separately), (b) test-needs-update-to-strict-semantics (fix in same PR), (c) actual regression in the flip (revert).

**Local gates beyond S-6.** Cascade-count assertion: PR description must list "this flip caused N tests to fail; M were latent bugs, K were test-side updates, 0 were flip-side regressions."

**CE review agents (parallel).**
- `compound-engineering:ce-correctness-reviewer` — logic / state-management review.
- `compound-engineering:ce-testing-reviewer` — assertion-quality review of the new tests.
- `compound-engineering:ce-data-integrity-guardian` — was state correctly restored on the now-raising paths?
- `compound-engineering:ce-adversarial-reviewer` — actively try to break the rollback (concurrent passes, partial mutations).

**Visual proof requirement.** None for the flip itself. If the gate's purpose is visual integrity (e.g. NaN→magenta), then yes — full Wave-VV 11-camera FSM proof.

**Compound entry path.** `docs/solutions/logic-errors/<slug>-YYYY-MM-DD.md`.

---

### C4 — Boundary contract / channel-unit registry

**When this category applies.** Fixing channel name-drift, unit name-drift (`water_depth` vs `water_depth_m`), introducing typed registries (`Channel.SLOPE_RAD` enum), or installing boundary round-trip tests at Unity / Blender / JSON export hops.

**Y04 v3 items in this category.** T0.5-1 (typed Channel `Enum` registry — closes Shape A class entirely), T0.5-4 (boundary round-trip tests at Unity export), T0.5-5 (per-channel unit normaliser), β9 4-P0 name-drift cluster, T2-3 (Unity importer manifest), T2-34 (water elevation drift Python→C#), PR-OG-A pre-flight gate (6 detectors at pass entry), PR-OG-C post-gen validator (8 Unity-import validators).

**Pre-flight.**
- Enumerate every producer + every consumer of the channel. Use Grep with `output_mode: content` for the channel name as bare string AND the suffixed canonical form (`water_depth` AND `water_depth_m`).
- Look for the 5 silent-corruption chains catalogued in Part P §P.4 / ZZ4-A6 — your channel may be in chain β10-01..05.
- Note that some channels are **diagnostic-already-applied** (e.g. `pool_deepening_delta` per `docs/solutions/logic-errors/pool-deepening-delta-double-apply-2026-05-03.md`); don't move them into the integrator without confirming they're not already-applied.

**CE planning agents.**
- `compound-engineering:ce-api-contract-reviewer` — model the producer/consumer surface.
- `compound-engineering:ce-data-integrity-guardian` — flag any channels that mutate shared height across passes.
- `compound-engineering:ce-best-practices-researcher` — Context7 query for `/python/typing` Enum + Literal patterns at boundaries.

**Implementation order.**
1. Write boundary round-trip test FIRST (input radian, parse output, assert degrees). Test must fail before fix.
2. Introduce typed-registry `Channel.WATER_DEPTH_M` etc. with both old and new accessors during migration; never delete old accessor in same PR.
3. Migrate one producer at a time; after each, run full suite (cascade detection per ZZ4-A6 Shape B).
4. After all producers migrated, migrate consumers.
5. Final PR removes old string-keyed accessor.

**Local gates beyond S-6.** Boundary round-trip test must be in the suite. AST regression test: `grep -n 'stack\.set("` should return 0 hits after migration completes (string-key writes forbidden post-registry).

**CE review agents (parallel).**
- `compound-engineering:ce-api-contract-reviewer` — breaking-contract review.
- `compound-engineering:ce-data-integrity-guardian` — unit-leak audit.
- `compound-engineering:ce-correctness-reviewer` — rad/deg / m/cm conversion correctness.
- `compound-engineering:ce-pattern-recognition-specialist` — any remaining string-key sites flagged.

**Visual proof requirement.** Required for any channel that reaches a renderable surface (height, water_depth_m, slope_rad, normal_y, splatmap weights). 4-shot Wave-VV proof: aerial + ground + side + top-down for the affected biome.

**Compound entry path.** `docs/solutions/architecture-patterns/<slug>-YYYY-MM-DD.md`.

---

### C5 — Numerical / unit conversion fix

**When this category applies.** Single-site or small-cluster fix where a number is computed in wrong unit, wrong scale factor, or wrong domain (rad vs deg, m vs cm, accumulator overflow, divide-by-near-zero).

**Y04 v3 items in this category.** T0-4.5 (rad→deg at 2 Unity export sites), T1 NaN-safety cluster (T1-4/5/5b/5c/6), T1 sim/foam cluster (T1-40/41/42/43 + T2-40), T2-39 (sun AREA→SUN — color-temperature unit), erodibility 1000× bug (E-1 from prior 2026-04-27 audit), `UNITY_SCALE_FACTOR` confusion family.

**Pre-flight.**
- Trace the number from declaration to consumption. Use `Grep` with `output_mode: content` to find every site.
- Identify the canonical unit. Add a type-suffix or comment at declaration ("// degrees, NOT radians").
- For NaN/Inf: identify the producing operation (divide, log, sqrt-of-negative, accumulator).

**CE planning agents.**
- `compound-engineering:ce-correctness-reviewer` (planning) — flag any silent fallback that would swallow a NaN.
- `compound-engineering:ce-best-practices-researcher` — Context7 query for the upstream library (e.g. `numpy.errstate`, `math.degrees`, `np.nan_to_num`).

**Implementation order.**
1. Write boundary assertion test: input known value, assert output equals expected (e.g. `assert write_animation_clip_yaml(angle_rad=math.pi/2)['m_EulerCurves'][0] == pytest.approx(90.0)`).
2. Apply the unit conversion at the single boundary site.
3. If multi-site, apply in dependency order (innermost first).

**Local gates beyond S-6.** Numerical-precision tolerance: `pytest.approx(expected, rel=1e-6)` not `==`. Random-seed pin per `feedback_channel_ownership_pattern.md` and the W04 `_rng_from_seed` family.

**CE review agents (parallel).**
- `compound-engineering:ce-correctness-reviewer`
- `compound-engineering:ce-data-integrity-guardian`
- `compound-engineering:ce-testing-reviewer`

**Visual proof requirement.** For renderable channels: yes. For internal-only channels: optional but recommended at 1 representative shot.

**Compound entry path.** `docs/solutions/logic-errors/<slug>-YYYY-MM-DD.md`.

---

### C6 — Regression-net (test-first)

**When this category applies.** Pure test authoring — no production code change. The PR's value is **the safety net that lets another PR land safely.**

**Y04 v3 items in this category.** **Entire Tier-0.5** (T0.5-1..T0.5-9 — 9 entries, ~12.5 days). Specifically T0.5-3 (15 new test files covering 30 highest-risk untested functions per Part P §P.4.2). Also: T1-19/30/34/44/45 (cross-process / test-infra cluster), T2-27 (57-site RandomState migration), T2-10 (WeakKeyDictionary conftest reform), T4-NEW-ZZ4-01 (long-tail citation update), T4-NEW-ZZ4-02 (inspect.getsource pin replacement).

**Pre-flight.**
- Read Part P §P.4.2 list of 30 highest-risk untested functions.
- For each: read the function's source ±50 lines, identify behaviour-under-test (entry-point semantics, side-effects, raise paths, return contract).
- **Crucial:** the test should fail in a useful way today if the function is broken, AND it should pin behaviour so future regressions get caught.

**CE planning agents.**
- `compound-engineering:ce-testing-reviewer` (planning phase) — sketch the assertion grid.
- `compound-engineering:ce-pattern-recognition-specialist` (planning) — identify which existing test file is the closest sibling so we follow its conventions.

**Implementation order.**
1. Read closest sibling test file fully (e.g. `test_terrain_pipeline_smoke.py` for any pipeline-related test).
2. Copy its imports, fixtures, helpers. **Do not invent new fixtures unless the existing ones genuinely don't fit.**
3. Write one test per behaviour: success-case + each raise-path + each side-effect.
4. Confirm each test fails for the right reason when you sabotage the production code locally (don't commit the sabotage; just verify the test is load-bearing).
5. Restore production code; tests should pass against current behaviour OR fail with a precise diagnostic message that names the bug.

**"Test passes today" guidance.** If a test you wrote PASSES against current production code, that is a signal — STOP. Either (a) the function works correctly today and the test merely pins behaviour (legitimate — keep, don't xfail), OR (b) the test doesn't actually exercise the bug it claims (mis-targeted — re-design). Do NOT mark passing tests as `xfail`; xfail is only for tests that prove a KNOWN future fix is required.

**Specific recipe for `test_restore_pass_state.py` (T0.5-3, our prototype).** Three test classes:
   - `TestRestorePassStateRoundTrip`: take snapshot → mutate stack → restore → assert byte-identical for declared channels + `populated_by_pass` + `dirty_channels` + `content_hash` + `height_min_m` + `height_max_m`. **Should pass today.**
   - `TestRollbackOnPassFuncRaise`: register a pass whose `func` raises `RuntimeError` → call `run_pass` → assert state is restored (this path EXISTS today at `terrain_pipeline.py:935`; test should pass).
   - `TestRollbackOnPassContractError`: ONE test per raise-path (so partial T0-4 sub-PRs don't break the strict-xfail). Four sub-tests:
     - `test_rollback_on_wrong_return_type` — raises at line 948; `@pytest.mark.xfail(reason="T0-4 sub-path 948 not yet landed", strict=True)` until T0-4 lands.
     - `test_rollback_on_missing_produced_channel` — raises at line 967; same xfail-strict scoped to 967.
     - `test_rollback_on_nan_in_produced_channel` — raises at line 985; same xfail-strict scoped to 985.
     - `test_rollback_on_nan_in_override_channel` — raises at line 995; same xfail-strict scoped to 995.

   This per-raise-path xfail granularity is mandatory because Y04 v3 recommends T0-4 may be split into sub-PRs; a single bundled `xfail(strict=True)` flips ERROR mid-T0-4 if only some raise paths are fixed. Per-raise-path xfails flip one-at-a-time.

**Local gates beyond S-6.** `pytest --tb=short -v` showing each new test's run line and status. Coverage delta: `pytest --cov=veilbreakers_terrain.handlers.terrain_pipeline --cov-report=term-missing` before/after.

**CE review agents (parallel).**
- `compound-engineering:ce-testing-reviewer` — assertion quality.
- `compound-engineering:ce-pattern-recognition-specialist` — convention conformance with sibling tests.
- `compound-engineering:ce-correctness-reviewer` — does the test actually exercise the bug it claims to?

**Visual proof requirement.** None.

**Compound entry path.** `docs/solutions/best-practices/<slug>-YYYY-MM-DD.md` if the test pattern is reusable; otherwise no compound entry (test PR is its own documentation).

---

### C7 — New operational framework code

**When this category applies.** New module(s) with no in-tree predecessor: pre-flight gates, post-gen validators, self-healing loops, Blender/Unity guardrail extensions. These are NOT bug fixes; they are **defensive depth that closes silent-corruption chains structurally**.

**Y04 v3 items in this category.** PR-OG-A (~620 LOC pre-flight gate), PR-OG-B (~510 LOC corruption-watcher), PR-OG-C (~800 LOC post-gen validator), PR-OG-D (~400 LOC self-healing loop), PR-OG-E (~5,100 bpy LOC Blender extension), PR-OG-F (~2,680 C# LOC Unity 7-layer). Combined ~13,000 LOC — every entry in this category goes through brainstorm + plan; none should be coded straight from spec.

**Pre-flight.**
- Read the design doc verbatim (`_ZZ4_B3_preflight.md`, `_ZZ4_B4_corruption_watcher.md`, etc.).
- Read the existing module that the new code wraps (e.g. PR-OG-A wraps `terrain_pipeline.py:906`'s `run_pass`).
- Identify the seam: where does new code meet existing code? That seam needs the tightest review.

**CE planning agents (full brainstorm + plan loop).**
- `compound-engineering:ce-best-practices-researcher` — Context7 query per dependency (skimage, trimesh, jsonschema, PIL for PR-OG-C; bpy ScriptingOps for PR-OG-E).
- `compound-engineering:ce-architecture-strategist` — does this fit the existing pass / handler / module structure? Or is it a new tier (likely)?
- `compound-engineering:ce-feasibility-reviewer` — Y04 v3 says ~10 eng-days; does that match?
- Optional: `/ce-brainstorm` slash command for interactive Q&A on edge cases before committing.

**Implementation order.**
1. **Write the public API + types first** (single file, ≤50 LOC). Stub every method. Type-check passes (pyright strict).
2. Write the contract test for each public method.
3. Implement one method at a time, with test going green each time.
4. After all methods green, wire into the production seam.
5. Run full suite — cascade detection ZZ4-A6 Shape B applies (a bug here cascades into 47+ tests).

**Local gates beyond S-6.** Wall-clock budget: PR-OG-C says <60s at 4097² + 12 meshes + 10 PNGs; assert in test. LOC budget: PR-OG-A says ~620 LOC; if your impl is >900, simplify.

**CE review agents (parallel — bigger roster).**
- `compound-engineering:ce-architecture-strategist`
- `compound-engineering:ce-maintainability-reviewer`
- `compound-engineering:ce-code-simplicity-reviewer` ← critical for this category; new modules drift toward over-engineering.
- `compound-engineering:ce-pattern-recognition-specialist`
- `compound-engineering:ce-testing-reviewer`
- `compound-engineering:ce-correctness-reviewer`
- `compound-engineering:ce-performance-reviewer` (for PR-OG-C 38-validator suite; budget-bound).

**Visual proof requirement.** For PR-OG-E (Blender) and PR-OG-F (Unity): mandatory full Wave-VV 11-camera FSM proof — these extensions enforce visual mandate by design.

**Compound entry path.** `docs/solutions/architecture-patterns/<slug>-YYYY-MM-DD.md` — these become reference architecture for future agents.

---

### C8 — Visual mandate

**When this category applies.** Any fix that touches a channel reaching the renderable surface, or any new visual feature. Per `feedback_visual_verification_mandate_2026_05_17.md` — Wave-VV mandate is **HARD**: "all guard rails must acknowledge and require visual verification ... CONTINUE THE TASK UNTIL THE PHOTO IS TAKEN AND VERIFIED BY THE AGENT."

**Y04 v3 items in this category.** PR-VV-A (visual primitives + 4 guardrail sites), PR-VV-B (10 more sites — per-pass debug PNG fan-out), PR-VV-C (visual readiness gate upgrade), PR-VV-D (Unity visual handshake), PR-VV-E (agent enforcement docs + 18 X06 safeguards), T0-3 (golden bake reset), T2-15+T2-16 bundle (per-pass channel-debug PNG framework), T3-15 (golden baselines tree), T3-16 (Cycles GPU helper). Also: **any C4/C5 fix to a renderable channel chains here.**

**Pre-flight.**
- Identify the affected biome(s).
- Pick the camera set by scope: **single-biome single-channel fix** = 4-shot proof (aerial + ground + side + top-down). **Multi-biome OR shader-touching OR new visual feature** = full 11-cam FSM (mandatory per Wave-VV).
- ⚠️ **Render harness prerequisite (P1 from feasibility review 2026-05-19):** The canonical proof harness at `scripts/render_coastal_camera_proof.py` (cited in `docs/solutions/best-practices/visual-render-camera-proof-2026-05-04.md`) does NOT currently exist in `scripts/`. Either (a) build it before the first C8 fix (the solution doc has the spec verbatim — ~150 LOC), or (b) use the closest existing renderer (`scripts/render_aaa_v8_mountain.py` for biome-scope, `scripts/render_bridge_visual.py` / `render_cliff_cave_visual.py` / `render_road_visual.py` for feature-scope) AND author a small wrapper that emits `RENDER_MANIFEST.json` with the 6 byte_size + non-black assertions from the solution doc. Pick (a) for any agent doing >2 C8 fixes; (b) for one-off.
- For Blender: bypass `mcp__blender__.get_viewport_screenshot` (broken on Windows 11 + Blender 4.5 — returns all-zero PNG per the existing solution doc). Use `bpy.ops.render.render(write_still=True)` per camera as the replacement.

**CE planning agents.**
- `compound-engineering:ce-design-implementation-reviewer` (planning) — what does "correct" look like visually for this biome / channel?
- `compound-engineering:ce-best-practices-researcher` — Context7 query for `/blender/cycles` denoiser / GPU device pinning for T3-16 dependents.

**Implementation order.**
1. Author the fix (channel / shader / mesh / scatter).
2. Bake the affected biome(s) at canonical resolution (1600×900 @ 64 samples Standard view transform per the prior solution).
3. Run `scripts/render_coastal_camera_proof.py --unit-id <fix-id> --cameras <11-cam-list> --resolution 1600 900 --samples 64`.
4. The harness asserts per-PNG: byte_size ≥ 50,000B AND non-black ratio ≥ 0.005. PNG fails either → fix is not done.
5. Commit `renders/<scope>/<fix-id>/*.png` + `RENDER_MANIFEST.json` to the PR.
6. Read every PNG before claiming success (per `feedback_visualize_renders_carefully_2026_05_09.md`). Describe what's literally visible. No "looks good" without per-image visualization.

**Local gates beyond S-6.** Render manifest committed to PR. Camera-count FSM state in PR description, sized to chosen scope: "11/11 cameras passed" for full FSM, "4/4 cameras passed (single-biome scope)" for sub-scope. In either case: "non-black ratio range [min, max]; mean byte size N KB; affected biomes: A/B/C."

**CE review agents (parallel).**
- `compound-engineering:ce-design-implementation-reviewer` — visual fidelity vs intent.
- `compound-engineering:ce-testing-reviewer` — render manifest assertion quality.
- `compound-engineering:ce-correctness-reviewer` — does the channel actually reach the surface?

**Visual proof requirement.** Mandatory 11-camera proof. **Tier-3 skip is FORBIDDEN** per Wave-VV.

**Compound entry path.** `docs/solutions/best-practices/visual-<slug>-YYYY-MM-DD.md`.

---

### C9 — Performance / HW envelope

**When this category applies.** A fix that changes memory peak, wall-clock, or VRAM. The 4060 Ti 8GB constraint is hard per `project_hardware_8gb_vram_2026_05_07.md`; cloud bake-rig $31/mo only for items explicitly flagged HW-marginal in Y04 v2.

**Y04 v3 items in this category.** T0-8 (deepcopy 4-site split — 24-28 GB → <500 MB), T0-3.5 (`bm.free()` 17 sites — process stability), T3-1 (E-3 erosion Numba @njit), T3-4 (hero rock pipeline 4-6 GB), T3-6 (foliage GPU-instanced cull — `RenderMeshIndirect`), T3-10 (per-tile VRAM/RAM budget), T2-41 (MaterialPropertyBlock SRP-Batcher restore), T2-1 (Unity texture pipeline 8K BC7 — 4-6 GB peak).

**Pre-flight.**
- ⚠️ Before/after measurement plan. What's the metric? Wall-clock, peak RSS, peak VRAM, frames-per-second, draws-per-frame? Don't ship a perf fix without numbers.
- Identify the budget. T0-8 says <500 MB per worker post-fix. T3-1 says 10× faster at 2048².
- For VRAM: check 8GB envelope explicitly. T2-1 says 4-6 GB peak — that's tight; verify on your 4060 Ti before merging.

**CE planning agents.**
- `compound-engineering:ce-performance-oracle` (planning) — algorithmic-complexity analysis, hot-path identification.
- `compound-engineering:ce-best-practices-researcher` — Context7 query for `/numba/numba`, `/numpy/numpy` vectorization, Unity SRP-Batcher rules.

**Implementation order.**
1. Capture baseline metrics first (`memory_profiler`, `cProfile`, Unity Profiler / Frame Debugger).
2. Apply fix at smallest scope (one site, not all).
3. Capture post-fix metrics for the same workload.
4. Compute delta. If delta isn't ≥80% of the target, re-design.
5. Apply to remaining sites.

**Local gates beyond S-6.** PR description includes a before/after table. CI perf budget: optional pytest-benchmark threshold if the metric is unit-test-scoped.

**CE review agents (parallel).**
- `compound-engineering:ce-performance-oracle`
- `compound-engineering:ce-performance-reviewer`
- `compound-engineering:ce-reliability-reviewer` — did the perf fix introduce a memory leak / handle leak (esp. for bmesh)?

**Visual proof requirement.** For Unity rendering perf (T2-41, T3-6): yes, full 11-cam FSM + draw-call count in PR description. For Python pipeline perf (T0-8, T3-1): no visual, but include determinism check (same output post-fix).

**Compound entry path.** `docs/solutions/performance/<slug>-YYYY-MM-DD.md`.

---

## 4. The test-first cascade rule (cross-category)

A repeated finding across the audit: **the order of test-vs-fix determines whether the work is regression-net or regression-hazard.**

- For **C3, C4, C5, C6**: write the failing test FIRST. If the test passes against current behaviour, the test is wrong (it doesn't actually exercise the bug). Sabotage the production code locally to confirm the test goes red, then restore.
- For **C7**: write the API + contract test first, then implement. The contract test is the design.
- For **C1, C2, C8, C9**: test-first is less applicable; capture baseline / manifest / measurement as the equivalent "before" artefact.

The cascade-failure shapes from ZZ4-A6:
- **Shape A (silent)**: 0 cascade. Detection requires boundary round-trip test (C4 recipe).
- **Shape B (loud-cascade)**: ≥17 tests fail. This IS the "20 changes per generation" pain. Mitigation: split test files per-bundle (Tier-0.5 R4) so one bug fails one bundle's tests, not the whole suite.
- **Shape C (misdirected)**: ~12 scenarios poisoned. Mitigation: per-channel unit normaliser (T0.5-5, Tier-0.5 R5).

---

## 4.5 Multi-category collision resolution

35 of 155 Y04 v3 items carry dual-category tags in §6 (e.g. T0-5 = C3+C8, T0-7 = C3+C1, T0.5-8 = C3+C5, T2-1 = C9+C8, T2-41 = C9+C8, PR-OG-E = C7+C8, PR-OG-F = C7+C8). When a fix spans two categories:

**Lead-category rule.** Use the category whose `Pre-flight` mandates the **most-destructive or most-irreversible** check as the LEAD. Order of destructiveness (highest first):
1. **C2** (git-history rewrite) — irreversible
2. **C1** (credential rotation) — invalidates external state
3. **C3** (gate flip) — exposes latent cascade
4. **C9** (perf / HW envelope) — measurement-bound
5. **C8** (visual mandate) — renderable surface
6. **C7** (new operational code) — new seam
7. **C4** (boundary contract) — multi-site migration
8. **C5** (numerical / unit) — single-site
9. **C6** (regression-net) — test-only

**Recipe combination.** Run the LEAD category's recipe in full. Then, for the SECONDARY category, run ONLY its `Pre-flight` checks and append its CE review-agent roster to the parallel review wave. Example for T0-7 (C3+C1): lead C3 (gate flip is the primary action — `allow_pickle=False`), then add C1's `detect-secrets scan` gate and security-reviewer roster. Both compound entries written: `docs/solutions/logic-errors/...` (C3 destination) + `docs/solutions/security/...` (C1 destination).

**§6 syntax convention.** In the mapping table, the first-listed category is the LEAD. "C3 + C1" means lead-C3, secondary-C1. "C3 / C5" (slash) means the agent must decide — annotate the decision in the plan doc.

---

## 5. Unified PR description template

Every PR uses this template. Sections marked `*` are mandatory; others fill in if applicable.

```markdown
## Y04 v3 anchor*
- Fix ID: <T0.5-3 | T0-4 | PR-OG-A | etc.>
- Category: <C1 | C2 | ... | C9>
- Y04 v2 ordinal: <v2-ord #N | new-in-v3>
- Critical-path node: <yes / no>
- Blocks: <list of Y04 v3 entries that wait on this>
- Blocked by: <list of Y04 v3 entries this waits on>

## Plan reference*
- Plan doc: `docs/plans/2026-MM-DD-NNN-<scope>.md` (or first-commit message)
- CE planning agents run: <ce-best-practices-researcher | ce-architecture-strategist | ...>

## Test evidence*
- New test files: <paths>
- Failing-before-fix: <commit SHA + 1-line stderr showing the assertion that fails>
- Passing-after-fix: <commit SHA + summary>
- Cascade-count for gate-flip categories: "this flip caused N tests to fail; M latent / K test-side updates / 0 regressions"

## Gate evidence*
- pyright_strict_baseline_gate: PASS / N new findings vs baseline
- callable_census_gate --strict-zero: PASS
- terrain_best_practice_guardrail --strict-verification: PASS
- pytest (new tests): N passed
- pytest (full suite): N passed / M xfail

## CE review verdicts*
Each reviewer agent returned: <verdict + summary>. Any P0/P1 finding from any reviewer is a blocker.
- ce-correctness-reviewer: <verdict>
- ce-<category-specific-1>: <verdict>
- ...

## Visual proof (C4/C5/C7/C8 only)
- Cameras run: <11/11 | subset list>
- Manifest: `renders/<scope>/<fix-id>/RENDER_MANIFEST.json`
- Non-black ratio range: [min, max]
- Per-image verbal description: 1 line per camera, what is visible

## Risk / rollback
- Blast radius: <files / users / runtime>
- Rollback procedure: <git revert SHA | toggle flag | manual sequence>

## Compound entry (filled in post-merge)
- `docs/solutions/<category>/<slug>-YYYY-MM-DD.md`
```

---

## 6. Y04 v3 → category mapping (all 155 items)

Compact partition. Use this when picking up any fix to find its recipe in §3.

| Tier | Entries | Category | Notes |
|---|---|---|---|
| **Tier-0 Emergency** | T-prep-0 | C1 | supply-chain guard |
| | **F1 NEW** | C2 | `.mcp.json` git-history scrub |
| | T0-1 | C1 | Tripo + 3 MCP keys rotation |
| | T0-2 | C7 (small) | CLI rewire — new wiring, no test today |
| | T0-3 | C8 | golden bake reset |
| | T0-3.5 | C9 | bm.free() process stability |
| | T0-4 | C3 | warning-bypass flip — needs T0.5-3 |
| | T0-4.5 | C5 | rad→deg at Unity export |
| | T0-5 | C3 + C8 | N18 road reform (parameter shadow flip + visual) |
| | T0-6 | C1 | CI permissions + SHA-pin |
| | T0-7 | C3 (allow_pickle=False) + C1 (RCE chain) | hybrid |
| | T0-8 | C9 | deepcopy 4-site split |
| **Tier-0.5 NEW** | T0.5-1 | C4 | typed Channel Enum registry |
| | T0.5-2 | C3 | 14 status="warning" → "ok"-strict |
| | T0.5-3 | C6 | 15 new test files (our prototype) |
| | T0.5-4 | C4 | boundary round-trip tests |
| | T0.5-5 | C4 | per-channel unit normaliser |
| | T0.5-6 | C6 | smoke-test stub-seam refactor |
| | T0.5-7 | C6 | tautological delete |
| | T0.5-8 | C3 / C5 | json allow_nan=False |
| | T0.5-9 | C6 | split test_full_terrain_pipeline per-bundle |
| **Tier-1 OG** | PR-OG-A | C7 | pre-flight gate ~620 LOC |
| | PR-OG-B | C7 | corruption-watcher ~510 LOC |
| | PR-OG-C | C7 | post-gen validator ~800 LOC |
| | PR-OG-D | C7 | self-healing loop ~400 LOC |
| **Tier-1 (existing)** | T1-1, T1-22, T1-28/29 | C8 | shader cluster — visual |
| | T1-3/16/17 | C8 + C5 | glacial / coastline / environment |
| | T1-4/5/5b/5c/6 | C5 | NaN-safety cluster |
| | T1-8 | C4 | LOD descriptor |
| | T1-10/47 | C3 | validation cluster |
| | T1-11/12/13/23/24 + T4-15 | C6 + C5 | RNG cluster (5 PRs) |
| | T1-15, T1-20 | C5 | mesh bridge |
| | T1-18 | C7 (tiny) | PowerShell dispatch |
| | T1-19/30/34/44/45 | C6 | cross-process / test-infra |
| | T1-21 | C5 | Blender 4.5 drift |
| | T1-25/26/31/27 | C5 + C4 | saliency / stratigraphy / sculpt |
| | T1-32/33/36/37 | C7 (tiny) | hardcoded-path bundle |
| | T1-37/38/39 | C4 | build_scene_v3 cluster |
| | T1-40/41/42/43 + T2-40 | C5 | sim/foam cluster |
| **VV-Tier** | PR-VV-A..E | C8 | visual mandate spine |
| **Tier-2** | T2-1 | C9 + C8 | Unity texture pipeline 4-6 GB |
| | T2-2 | C4 | 14 unscheduled passes |
| | T2-3, T2-34 | C4 | Unity importer + water elevation drift |
| | T2-5 | C7 | decal/sidecar 18 GameObject classes (NEW) |
| | T2-6/T2-39 | C5 + C8 | climate + sun AREA→SUN |
| | T2-7 | C1 | path-traversal centralization |
| | T2-8 | C4 | _DELTA_CHANNELS contract |
| | T2-9 | C6 | pyright theatre flip |
| | T2-10 | C6 | conftest reform |
| | T2-11/T2-12 | C8 | grass density + tree (N,5)→(N,7) |
| | T2-13 | C3 | validation discipline inversion |
| | T2-14 | C9 (tiny) | render-script GPU device |
| | T2-15/T2-16 (bundled) | C8 | per-pass channel-debug PNG framework |
| | T2-17 | C7 | Unity runtime full reform ~600 LOC C# |
| | T2-18/22/30/31/32/35/36 | C1 | governance / asmdef / YAML / gitignore |
| | T2-19 | C7 | Sabine acoustic physics |
| | T2-20/T2-21 | C8 | wetness map + reflection probe |
| | T2-23/24 | C4 | N06 orchestration / Wave-L importer |
| | T2-26 | C4 | LOD distance centralization (pair w/ T1-8) |
| | T2-27 | C6 | 57-site RandomState |
| | T2-28 | C6 | 3 CI-flake timing |
| | T2-29 | C4 | cross-file invariants (S05 9 P0) |
| | T2-37 | C8 | 6 procmeshes (3 P0 Y-flatten / lathe-zero) |
| | T2-38 | C5 | pbd_cloth stiffness=0 |
| | T2-41 | C9 + C8 | MaterialPropertyBlock SRP-Batcher |
| **Tier-2.5 NEW** | PR-OG-E | C7 + C8 | Blender 6-layer extension |
| | PR-OG-F | C7 + C8 | Unity 7-layer extension |
| **Tier-3** | T3-1 | C9 | erosion Numba @njit |
| | T3-2 | C8 | Crest 4.22.4 wiring |
| | T3-3 | C8 | Boat Attack reference scene |
| | T3-4 | C9 + C8 | hero rock pipeline |
| | T3-5 | C7 | AssetCache content-addressed |
| | T3-6 | C9 + C8 | foliage GPU-instanced cull |
| | T3-7 | C6 | Hypothesis property-based testing |
| | T3-8 | C5 + C8 | differential erosion |
| | T3-9 | C8 | hero-shot baked impostor |
| | T3-10 | C9 | per-tile VRAM/RAM budget |
| | T3-11 | C9 | shader variant stripping |
| | T3-12 | C7 | DCC bridge (Houdini / FBX) |
| | T3-13 | C8 | Cinemachine + photo-mode |
| | T3-14 | C7 | crash telemetry |
| | T3-15 | C6 + C8 | render_goldens tree |
| | T3-16 | C7 (helper) | enable_cycles_gpu() |
| **Tier-4** | T4-1 (procmesh split) | C7 (refactor) | 24-file split |
| | T4-2..T4-26 | mixed C1/C6/C7 | Wave-O cleanup |
| | T4-27..T4-31 | C1 (hygiene) | deprecated script delete / temp dirs / md moves |
| | T4-NEW-ZZ4-01..07 | C6 (tests) + C1 (CI) | Wave-ZZ-4 augmentations |

If an entry doesn't fit any category, that is a signal — either it's mis-scoped or this taxonomy needs a v2. File a delta against `FIX_PATTERN_v2.md` rather than forcing it into the wrong recipe.

---

## 7. The compound loop

After every fix lands on `main`, before the next fix starts:

1. **Write `docs/solutions/<category-dir>/<slug>-YYYY-MM-DD.md`** using the existing entry format (see `docs/solutions/logic-errors/pool-deepening-delta-double-apply-2026-05-03.md` as template). Sections: Problem / Symptoms / What Didn't Work / Solution / Why This Works / Prevention / Related Issues.
2. **If the fix surfaced a pattern misfit** with this doc (e.g. a category recipe missed a step), append a `FIX_PATTERN_v1.md` deltum and roll to v2 when ≥5 deltas accumulate.
3. **Update `MEMORY.md` index** if the learning is durable (cross-session-relevant). One-line entry only; full content in `docs/solutions/`.
4. **Update `CLAUDE.md`** only if the learning is project-wide policy (e.g. "always include `.mcp*` in `.gitignore`"). Project policy lives in CLAUDE.md; per-fix learnings live in `docs/solutions/`.

The compound loop is what makes the system get easier as it runs. Skip it and every fix gets fresh-mind-cost; respect it and the next 100 fixes get cheaper than the first.

---

## 8. Quick reference card (paste this at top of every fix's plan doc)

```text
Y04 v3 ord: ___
Category: C__ (per FIX_PATTERN_v1 §3)
Blocked by: ___
Blocks: ___
CE planning agents to spawn: ___
CE review agents to spawn (parallel): ___
Local gates: pyright + callable_census + terrain_best_practice_guardrail + pytest
Visual proof required: Y / N
Compound destination: docs/solutions/<dir>/<slug>-YYYY-MM-DD.md
```

---

## 9. Anti-patterns (do NOT do)

- **Skip the local 4-gate** ("CI will catch it"). The 4-gate exists because CI is reactive; local catches it before push. Per `feedback_pre_commit_verifier_workflow.md`.
- **Skip the worktree** ("I'm only changing one line"). Worktrees keep parallel work from cross-contaminating mask_stack changes; one-line fixes are exactly when worktree discipline pays off.
- **Mock the database / production handler in C3 / C4 / C5 tests.** Per `feedback_audit_strictness.md` adjacent: mocks pass against false signal. Integration tests in this repo run against real `TerrainPassController`.
- **Run pytest inside a subagent.** Subagents must NOT run pytest (per `feedback_no_pytest_in_agents.md`); only the primary agent runs the full suite. Subagents may run targeted file tests for verification.
- **Force-push without explicit user confirmation** (C2 only; per the executing-actions-with-care posture in CLAUDE.md / system prompt).
- **Claim visual success without per-image visualization.** Per `feedback_visualize_renders_carefully_2026_05_09.md` — read every PNG, describe what's visible, identify defects honestly.
- **Bundle a refactor with a fix.** One fix per PR. Refactors go to Tier-4. Bundling makes review-agent verdicts noisy and rollback impossible.
- **Promote a learning to memory or CLAUDE.md before the fix is on `main`.** Memory is for what's true; an unmerged fix isn't true yet.

---

## 10. Versioning

- **v1** (this file): 9 categories, mapping covers Y04 v3's 155 items. Authored at HEAD `56e9dc9e`.
- **v1.1 patch deltas applied 2026-05-19 from 5-agent CE doc-review wave (PR #74):**
  - S-4: added `git status --short` + `git branch --show-current` pre-flight (feasibility P1-3).
  - S-5: clarified C7 test-first rule (coherence P0); added "prerequisite scan" forcing Y04 v3 §6 + Y04 v2 lookup before code-write (coherence P0).
  - S-7: added verdict aggregation rule + reviewer conflict resolution path with security-class priority (design P0).
  - §4.5 NEW: Multi-category collision resolution rule with destructiveness-ordered lead-category and slash-vs-plus syntax convention (design P0 + coherence P0).
  - C2: replaced wrong memory citation with CLAUDE.md + system prompt (feasibility P1-4).
  - C6: added "test passes today" guidance + per-raise-path xfail-strict granularity (coherence P1 + feasibility P1-2).
  - C8: flagged missing `render_coastal_camera_proof.py` harness as known prerequisite with alternative-renderer fallback (feasibility P1-1). Made camera count scope-sensitive (4 vs 11 — coherence P1).

- **v2 candidate deltas (queued for re-roll when ≥5 friction deltas accumulate from execution):**
  - D-01 (adversarial): collapse 9 categories → 2 risk tiers (high-ceremony C2/C3/C7/C8/C9 vs low-ceremony C1/C4/C5/C6) to right-size ceremony for trivial fixes.
  - D-02 (scope-guardian): extract §6 mapping table to sibling `Y04_V3_CATEGORY_MAP.md` to decouple queue churn from recipe-doc stability.
  - D-03 (scope-guardian): add C7 LOC-threshold note (<100 LOC → drop architecture-strategist + feasibility-reviewer from the roster).
  - D-04 (design-lens): move §8 Quick reference card to §1 (top) so cold-start readers hit the actionable card first.
  - D-05 (design-lens): trim AI-slop padding in §1 (7-beliefs paragraph) and §7 (compound-loop coda).
  - D-06 (coherence): clarify "155 items" enumeration in §6 (per-row breakdown).
  - D-07 (adversarial): reconcile per-PR CE-agent overhead with Y04 v3's 13-17 week ship estimate; add explicit time budget per category.
- **v2** (future): re-roll when ≥5 friction deltas accumulate from execution. Add a `## Changelog` section listing each absorbed delta.

```
FIX_PATTERN_v1 ready_for_use=true categories=9 items_mapped=155 critical_path_node_count=16
spine_steps=7 review_agent_roster_per_category=variable compound_loop=mandatory
anchored_to=Y04_v3 (MASTER_FINAL.md Part P §P.8)
```
