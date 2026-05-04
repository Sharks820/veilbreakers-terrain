# VeilBreakers Terrain Agent Instructions

## Always-On Caveman

- Terse like caveman. Technical substance exact. Only fluff dies.
- Drop articles, filler, pleasantries, and hedging.
- Prefer short fragments when meaning stays clear.
- Keep code, file paths, commands, API names, warnings, and safety-critical instructions exact.
- For architecture, security, destructive operations, or debugging root cause, stay concise but do not remove needed reasoning.
- Active every response unless user asks for normal prose.

## Skill Routing

- Compound Engineering is the workflow source of truth for non-trivial repo work.
- Do not use GSD skills, GSD agents, GSD planning docs, or `$gsd-*` command flows for this repo unless the user explicitly reverses this rule in a future message.
- If a user mentions a GSD command, translate the intent to the nearest Compound Engineering workflow instead and state the substitution briefly.
- Start with the matching `ce-*` skill before ad hoc implementation, review, or verification.
- Use Compound Engineering agents/reviewers for parallel audit and validation whenever the task has multiple files, risky behavior changes, or review/verification scope.
- VeilBreakers domain skills remain required for terrain/Blender/Unity specifics, but they supplement the Compound Engineering workflow instead of replacing it.
- Prefer VeilBreakers domain skills for terrain, Blender, Unity, callable audits, and export validation.
- For strategy/roadmap/spec/review orchestration, use `ce-strategy`, `ce-ideate`, `ce-brainstorm`, `ce-plan`, `ce-doc-review`, `ce-work`, and `ce-code-review`.
- Use `veilbreakers-terrain-research` for terrain, hydrology, erosion, scatter, material, Blender, Unity, and game-development research.
- Use `veilbreakers-procedural-rendering` for procedural shaders, Geometry Nodes materials, terrain texture stacks, water/foam/caustics, lighting, bake passes, and render quality work.
- Use `veilbreakers-blender-visual-qa` before making visual quality claims about Blender output.
- Use `veilbreakers-callable-audit` for function, callable, `COMMAND_HANDLERS`, dispatch, duplicate, grade, and coverage audits.
- Use `veilbreakers-asset-import-pipeline` for generated/imported GLB, glTF, Quixel, Poly Haven, Meshy, Hunyuan, or other external assets.
- Use `veilbreakers-unity-export-check` for RAW heightmap, JSON manifest, splatmap, terrain layer, navmesh, water metadata, and Unity plugin validation.
- Use `veilbreakers-terrain-debugging` for terrain generation bugs, visual failures, seam issues, hydrology/material/scatter regressions, Blender runtime failures, and Unity export regressions.

## Compound Engineering Skill Map

- `ce-work`: default execution path for non-trivial repo changes; scan, task-list, implement, test continuously, review.
- `ce-debug`: root-cause bugs with hypotheses, smallest proof steps, and test-first fixes.
- `ce-code-review`: review code changes with CE reviewer/persona logic; run before PR or after risky edits.
- `ce-simplify-code`: simplify recent changes for reuse, quality, and efficiency after implementation clusters.
- `ce-plan`: create implementation plans for multi-step work when scope is not already clear.
- `ce-brainstorm`: clarify requirements before planning when problem/solution shape is uncertain.
- `ce-ideate`: compare possible approaches before brainstorming/planning.
- `ce-strategy`: maintain durable project direction and upstream grounding.
- `ce-product-pulse`: summarize user/runtime outcomes over a time window.
- `ce-doc-review`: review plans/specs/docs with parallel role-specific feedback.
- `ce-proof`: create/share Proof docs when human review of an artifact is needed.
- `ce-demo-reel`: capture visual evidence for UI/visual PRs.
- `ce-polish-beta`: post-review polish and human-test checklist when supported.
- `ce-test-browser` / `ce-test-xcode`: platform-specific browser/iOS verification when applicable.
- `ce-commit`, `ce-commit-push-pr`, `ce-clean-gone-branches`, `ce-worktree`: CE git workflow tools.
- `ce-resolve-pr-feedback`: handle PR comments/review threads.
- `ce-compound`, `ce-compound-refresh`: document and refresh solved-problem learnings.
- `ce-sessions`, `ce-session-inventory`, `ce-session-extract`: prior-session context research.
- `ce-setup`, `ce-update`, `ce-release-notes`, `ce-report-bug`: CE environment and plugin maintenance.
- `ce-optimize`: iterative optimization with measurement gates and parallel experiments.
- `ce-agent-native-architecture`, `ce-agent-native-audit`: agent-native architecture design/review.
- `ce-frontend-design`, `ce-gemini-imagegen`, `ce-dhh-rails-style`: domain-specific CE support when relevant.
- `ce-slack-research`: organizational context research when configured.
- `lfg` / `ce-work-beta`: CE autonomous/beta workflows only when explicitly appropriate; never substitute GSD.

## Solutions Knowledge Base

`docs/solutions/` contains CE-documented solutions indexed by YAML frontmatter (`module`, `component`, `tags`, `problem_type`). Categories map to subdirectories: `logic-errors/`, `architecture-patterns/`, `runtime-errors/`, `best-practices/`, etc.

**Search before implementing** any fix or pass change in a documented module:
```bash
grep -r "module: <module-name>" docs/solutions/
grep -r "<keyword>" docs/solutions/
```
Frontmatter fields to search: `module`, `component`, `tags`, `title`. Check the matching `docs/solutions/<category>/` directory first when the problem type is clear.

## Compound Engineering Best Practices

- Treat CE plans and docs as decision artifacts; progress lives in git status, commits, task tracker, and verification output.
- For bare prompts, scan likely files, tests, and patterns first; choose trivial/small/large route before editing.
- Build/update a task list for small/medium/large work; skip only for truly trivial changes.
- Before edits, check branch and dirty state; never implement directly on `main`.
- Use parallel agents only for independent work with clear file ownership; otherwise use serial agents or inline work.
- Cap parallel agent dispatch at **6–8 agents per wave** — pick the most relevant specialists for the task; do not fire all available agents at once. Run sequential waves if broader coverage is needed.
- Every spawned subagent prompt must state that Compound Engineering is the workflow source of truth and GSD is prohibited for this repo.
- Subagents must know they share a codebase unless isolated by worktree; they must not revert or overwrite others.
- Read plan references and local analogs before inventing abstractions.
- Discover tests next to affected files; behavior changes need matching tests or explicit justification.
- Run focused tests after each meaningful change; fix failures immediately.
- Before calling work done, run the matching verification gates and code review depth appropriate to risk.
- Use `ce-code-review` or CE-scoped reviewer agents for risky/multi-file diffs before final handoff.
- Use `ce-simplify-code` after clusters of changes when duplication or pass-only cleanup risk appears.
- Treat permissive `typings/` stubs as type-checking shims only; never treat them as Blender API correctness or visual-quality proof.
- Treat pyright baseline updates as ratchet bookkeeping only; code strength requires runtime tests, focused checks, or visual proof as applicable.

## MCP Preferences

- Always use Serena for codebase work unless task is trivial single-file inspection or Serena is unavailable.
- Use Serena before broad manual code reading for symbol-level code understanding, refactor planning, call graph inspection, callable audits, and large-file navigation.
- Always use Context7 for third-party library, framework, SDK, API, or tool documentation unless the answer must come from local repo docs.
- Use Context7 before relying on memory for Blender Python APIs, Unity APIs/packages, Python libraries, JavaScript packages, MCP/tool docs, and build/test framework docs.
- If Serena or Context7 cannot be used, state why briefly and use best fallback.
- Use OpenAI Developer Docs MCP for OpenAI/Codex/API questions.
- Use GitHub MCP or `gh` for PRs, issues, actions, and remote repo context.
- Use Semgrep only if explicitly available in the active tool/config surface; it is not a default MCP here.
- Use Sequential Thinking as the default scaffold when a task has 3+ moving parts, unclear cause, conflicting evidence, high rollback cost, or likely false-positive risk.
- Sequential Thinking workflow: define exact goal; list known facts from live repo/tool evidence; split unknowns from assumptions; choose the smallest proof step; run it; update conclusion; repeat until decision is evidence-backed.
- Use Sequential Thinking often for PR review, callable audits, terrain generation bugs, Unity/Blender export regressions, MCP/tool failures, conflicting docs, implementation ordering, and go/no-go decisions.
- For VeilBreakers review work, Sequential Thinking should drive "real vs exaggerated" findings: prove symptom, root cause, affected runtime surface, test/evidence status, and safe next action.
- Use Exa, Tavily, Firecrawl, GitMCP, and arXiv for online research depending on source type.
- Use Graphify as a local CLI/skill workflow, not MCP, unless a working `graphify --mcp` server exists in the installed version. Treat `graphify-out/` as generated repo-map output.
- Use the repo's typed Blender MCP/dispatch bridge before generic Blender MCP for production terrain operations.
- Use generic Blender MCP only for bounded Blender inspection/experimentation not exposed by the VeilBreakers bridge.
- Use Unity MCP for Editor-side validation when Unity is open and the project is available.

## Hard Rules

- Never claim visual quality without real Blender viewport/render evidence or an explicit no-runtime caveat.
- Never add one-shot terrain builders that bypass canonical pass contracts.
- Never accept scatter without point-table/asset-manifest evidence for production terrain.
- Never accept water without surface elevation, depth, flow, and metadata.
- Never accept material export without normalized layer/weight evidence.
- Do not commit or hardcode API keys, MCP tokens, or provider secrets.

## Branch And Merge Protocol

- Never edit, commit, or push directly on `main` for implementation work.
- Before edits, run `git status --short` and `git branch --show-current`.
- If current branch is `main`, create a focused branch before changing files:
  `git switch -c fix/<short-scope>`.
- If another agent is active, use a separate worktree and branch:
  `git worktree add ..\veilbreakers-terrain-<scope> -b fix/<scope> origin/main`.
- One agent owns one branch/worktree/scope. Do not edit files another active agent is likely changing.
- Branch names: `fix/<scope>`, `feat/<scope>`, `audit/<scope>`, `docs/<scope>`, `ci/<scope>`.
- Keep branches narrow. Split unrelated terrain, Unity, CI, and docs work into separate PRs.
- Push branch and open PR into `main`; never direct-push `main`:
  `gh pr create --base main --head <branch> --fill`.
- Default merge method is squash:
  `gh pr merge --squash --auto`.
- Use rebase merge only when preserving a clean, meaningful commit sequence matters.
- Never use merge commits. Repo linear history requires squash or rebase.
- If required checks fail, fix on same branch and push again. Do not loosen branch protection to merge.
- Required checks before merge: `ci (3.11)`, `ci (3.12)`, `pyright`, `callable-census`, `Analyze (python)`, `Analyze (actions)`.
- For terrain protocol, callable, Unity export, Blender visual, or pipeline changes, run the matching focused local checks before PR when practical.
- If a visual-quality claim depends on Blender output and no Blender runtime is available, mark the PR as blocked or caveated. Do not represent stub renders as proof.
- After PR merge, update local main with `git switch main` then `git pull --ff-only origin main`.
