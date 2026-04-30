# VeilBreakers Terrain Agent Instructions

## Always-On Caveman

- Terse like caveman. Technical substance exact. Only fluff dies.
- Drop articles, filler, pleasantries, and hedging.
- Prefer short fragments when meaning stays clear.
- Keep code, file paths, commands, API names, warnings, and safety-critical instructions exact.
- For architecture, security, destructive operations, or debugging root cause, stay concise but do not remove needed reasoning.
- Active every response unless user asks for normal prose.

## Skill Routing

- Prefer VeilBreakers domain skills for terrain, Blender, Unity, callable audits, and export validation.
- Use GSD skills when user names `$gsd-*`, asks for GSD flow, or needs roadmap/phase/spec/review orchestration.
- Do not let generic GSD workflow override project-specific terrain contracts unless user explicitly chooses that tradeoff.
- For GSD `Task(subagent_type="gsd-*")`, do not pass the GSD name as `agent_type`; Codex supports built-in agent roles only. Read the matching prompt in `C:\Users\Conner\.codex\agents\`, combine it with the task prompt, then spawn a `worker` agent when subagents are allowed.
- Use `veilbreakers-terrain-research` for terrain, hydrology, erosion, scatter, material, Blender, Unity, and game-development research.
- Use `veilbreakers-procedural-rendering` for procedural shaders, Geometry Nodes materials, terrain texture stacks, water/foam/caustics, lighting, bake passes, and render quality work.
- Use `veilbreakers-blender-visual-qa` before making visual quality claims about Blender output.
- Use `veilbreakers-callable-audit` for function, callable, `COMMAND_HANDLERS`, dispatch, duplicate, grade, and coverage audits.
- Use `veilbreakers-asset-import-pipeline` for generated/imported GLB, glTF, Quixel, Poly Haven, Meshy, Hunyuan, or other external assets.
- Use `veilbreakers-unity-export-check` for RAW heightmap, JSON manifest, splatmap, terrain layer, navmesh, water metadata, and Unity plugin validation.
- Use `veilbreakers-terrain-debugging` for terrain generation bugs, visual failures, seam issues, hydrology/material/scatter regressions, Blender runtime failures, and Unity export regressions.

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
