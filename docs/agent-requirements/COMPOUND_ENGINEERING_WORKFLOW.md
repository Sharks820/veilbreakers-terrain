# Compound Engineering Workflow Requirements

Version researched: `compound-engineering` plugin `3.4.1`

Source inspected:

- `%USERPROFILE%\.codex\plugins\cache\compound-engineering-plugin\compound-engineering\3.4.1\README.md`
- `%USERPROFILE%\.codex\plugins\cache\compound-engineering-plugin\compound-engineering\3.4.1\skills`
- `%USERPROFILE%\.codex\plugins\cache\compound-engineering-plugin\compound-engineering\3.4.1\agents`
- `%USERPROFILE%\.codex\plugins\cache\compound-engineering-plugin\compound-engineering\3.4.1\.codex-plugin\plugin.json`

## Decision

Compound Engineering is the primary planning/execution workflow layer for Codex and Claude Code sessions in this repo. It is not the repo contract source of truth.

Repo hard rules still live in `AGENTS.md` and `CLAUDE.md`. When CE guidance conflicts with VeilBreakers domain routing, branch protocol, safety policy, or visual-proof requirements, the repo rules win.

VeilBreakers project skills remain domain specialists for terrain, Blender, Unity, callable audits, asset import, and export validation.

Caveman remains communication style only. It does not own workflow, evidence rules, branch protocol, PR process, or safety policy.

## Health Check

Command used:

```powershell
Push-Location "$env:USERPROFILE\.codex\plugins\cache\compound-engineering-plugin\compound-engineering\3.4.1"
bash scripts/check-health --version 3.4.1
Pop-Location
```

Result:

- Installed: plugin `3.4.1`, `gh`, `agent-browser`, `jq`, `silicon`, `ffmpeg`, `ast-grep`
- Installed CE skill: global `ast-grep` agent skill
- Intentionally skipped: `vhs`
- Repo fix applied: `.compound-engineering/config.local.example.yaml`

WSL `bash.exe` failed because WSL needs update. Git Bash worked. The health script belongs to the plugin install, not this repo.
Do not run `scripts/check-health` from the repository root; it is not a VeilBreakers repo script.

Latest CE health after install:

- Tools: `6/7`
- Skills: `1/1`
- Only warning: `vhs` missing by user choice.

## Installed Tool Usage

These tools must be used when they are the best-fit proof or implementation tool:

| Tool | Best-practice use |
|---|---|
| `agent-browser` | Browser automation, screenshot capture, UI flow validation, browser console/network checks, and CE `ce-test-browser` / `ce-demo-reel` support when a runnable surface exists. |
| `jq` | Parse JSON from `gh`, GitHub Actions, generated terrain reports, manifests, config files, and audit outputs. Prefer over fragile string splitting. |
| `ffmpeg` | Convert/process demo videos, browser recordings, visual QA clips, and evidence artifacts for PRs or audit docs. |
| `silicon` | Generate clean code screenshots for PR/docs when code-image evidence is useful. Do not use for routine code review. |
| `ast-grep` CLI | Structural search/refactor checks when matching syntax shape matters more than text. |
| global `ast-grep` skill | Load when a task asks for AST/code-structure search or broad structural audits. |
| `vhs` | Not installed by user choice. Do not make workflows depend on it. Use `agent-browser`, screenshots, terminal text, or `ffmpeg` instead. |

## Primary CE Routing

Use this order unless the user explicitly routes elsewhere:

For terrain, Blender, Unity, callable audit, asset import, and export-validation work, first load the matching VeilBreakers domain skill from `AGENTS.md`; then use the CE skill below as the process wrapper.

1. `ce-strategy`: durable direction, product target, metrics, roadmap tracks.
2. `ce-ideate`: generate and critique improvement options before picking work.
3. `ce-brainstorm`: turn ambiguous or high-scope ideas into requirements.
4. `ce-plan`: create or deepen multi-step implementation/research/audit plans.
5. `ce-work`: execute clear work or a plan.
6. `ce-debug`: investigate failures, regressions, CI breaks, runtime bugs, and root-cause questions.
7. `ce-code-review`: review changed code before PR or merge readiness.
8. `ce-simplify-code`: reduce complexity after substantial changes.
9. `ce-commit` or `ce-commit-push-pr`: save, push, and open/update PRs.
10. `ce-compound` and `ce-compound-refresh`: capture or refresh solved-problem knowledge.

## Skill Function Map

| Skill | Workflow role |
|---|---|
| `ce-agent-native-architecture` | Design agent-native tools, MCPs, self-modifying systems, and action/context parity. |
| `ce-agent-native-audit` | Score agent-native architecture against CE principles. |
| `ce-brainstorm` | Interactive requirements discovery before planning. |
| `ce-clean-gone-branches` | Remove local branches whose remote tracking branches are gone. |
| `ce-code-review` | Multi-agent code review with confidence gating and deduped findings. |
| `ce-commit` | Create value-communicating commits. |
| `ce-commit-push-pr` | Commit, push, open PR, update PR description, or draft PR description. |
| `ce-compound` | Capture solved problems as durable learnings. |
| `ce-compound-refresh` | Audit and refresh stale `docs/solutions/` learnings. |
| `ce-debug` | Reproduce, trace, prove root cause, then fix with tests. |
| `ce-demo-reel` | Capture GIF/screenshot/terminal proof for observable changes. |
| `ce-dhh-rails-style` | Apply DHH/37signals style to Ruby/Rails work. |
| `ce-doc-review` | Multi-persona review of plans, specs, and requirements docs. |
| `ce-frontend-design` | Build production-grade frontend UI with screenshot verification. |
| `ce-gemini-imagegen` | Generate/edit images through Gemini/Nano Banana Pro. |
| `ce-ideate` | Generate and critically evaluate grounded ideas. |
| `ce-optimize` | Run measured experiment loops for quality, performance, search, prompts, or other metrics. |
| `ce-plan` | Build structured plans and deepen existing plans. |
| `ce-polish-beta` | Human-in-loop polish after review with browser/dev-server checks. |
| `ce-product-pulse` | Time-windowed report on usage, quality, errors, and follow-ups. |
| `ce-proof` | Share and iterate Markdown docs through Proof editor. |
| `ce-release-notes` | Inspect recent or historical CE plugin release notes. |
| `ce-report-bug` | Report a bug against the CE plugin. |
| `ce-resolve-pr-feedback` | Evaluate and resolve PR review comments. |
| `ce-session-extract` | Extract skeleton/errors from a selected session file. |
| `ce-session-inventory` | Inventory Codex/Claude/Cursor session files. |
| `ce-sessions` | Query prior agent sessions for context and failed attempts. |
| `ce-setup` | Diagnose CE tool/install/config health. |
| `ce-simplify-code` | Simplify recent code while preserving behavior. |
| `ce-slack-research` | Synthesize Slack decision/context history when available. |
| `ce-strategy` | Create/update `STRATEGY.md`. |
| `ce-test-browser` | Run browser tests on affected pages. |
| `ce-test-xcode` | Build/test iOS apps with XcodeBuildMCP. |
| `ce-update` | Check CE plugin version and stale cache where supported. |
| `ce-work` | Execute implementation systematically. |
| `ce-work-beta` | Experimental CE work with external delegate support. |
| `ce-worktree` | Create/manage isolated git worktrees. |
| `lfg` | Full autonomous engineering workflow. Use only when broad autonomous execution is appropriate. |

## Agent Function Map

CE agents are not called directly by default. CE skills dispatch them when needed.

| Agent | Best use |
|---|---|
| `ce-adversarial-document-reviewer` | Stress-test high-stakes or large docs. |
| `ce-adversarial-reviewer` | Construct failure scenarios for large/risky diffs. |
| `ce-agent-native-reviewer` | Check action/context parity for agent-facing changes. |
| `ce-ankane-readme-writer` | Write concise Ankane-style Ruby gem READMEs. |
| `ce-api-contract-reviewer` | Detect breaking API/type/serialization changes. |
| `ce-architecture-strategist` | Check architectural fit and pattern compliance. |
| `ce-best-practices-researcher` | Research external standards and examples. |
| `ce-code-simplicity-reviewer` | Find simplification and YAGNI opportunities. |
| `ce-coherence-reviewer` | Find contradictions and terminology drift in docs. |
| `ce-correctness-reviewer` | Find logic, state, and edge-case bugs. |
| `ce-data-integrity-guardian` | Review data constraints, migrations, and persistence safety. |
| `ce-data-migration-expert` | Validate production data transformations. |
| `ce-data-migrations-reviewer` | Review migration/schema/backfill diffs. |
| `ce-deployment-verification-agent` | Build go/no-go deployment checklists. |
| `ce-design-implementation-reviewer` | Compare UI implementation against Figma. |
| `ce-design-iterator` | Iterate UI via screenshot-analyze-improve cycles. |
| `ce-design-lens-reviewer` | Review docs for UI/flow/design gaps. |
| `ce-dhh-rails-reviewer` | Rails review from DHH perspective. |
| `ce-feasibility-reviewer` | Check whether plans survive implementation reality. |
| `ce-figma-design-sync` | Sync UI implementation to Figma. |
| `ce-framework-docs-researcher` | Gather framework/library docs and version constraints. |
| `ce-git-history-analyzer` | Trace code evolution and historical rationale. |
| `ce-issue-intelligence-analyst` | Analyze GitHub issue patterns. |
| `ce-julik-frontend-races-reviewer` | Review async frontend race/timing issues. |
| `ce-kieran-python-reviewer` | Strict Python clarity/type/maintainability review. |
| `ce-kieran-rails-reviewer` | Strict Rails convention review. |
| `ce-kieran-typescript-reviewer` | Strict TypeScript type/clarity review. |
| `ce-learnings-researcher` | Search prior `docs/solutions/` learnings. |
| `ce-maintainability-reviewer` | Review coupling, naming, dead code, and abstraction debt. |
| `ce-pattern-recognition-specialist` | Map patterns, anti-patterns, duplication. |
| `ce-performance-oracle` | Deep performance and complexity analysis. |
| `ce-performance-reviewer` | Review performance-sensitive diffs. |
| `ce-pr-comment-resolver` | Resolve PR comment threads. |
| `ce-previous-comments-reviewer` | Check prior PR feedback closure. |
| `ce-product-lens-reviewer` | Challenge product framing and goal alignment in docs. |
| `ce-project-standards-reviewer` | Enforce repo `AGENTS.md`/`CLAUDE.md` standards. |
| `ce-reliability-reviewer` | Review retries, timeouts, errors, async reliability. |
| `ce-repo-research-analyst` | Research repo structure and conventions. |
| `ce-schema-drift-detector` | Detect unrelated schema drift. |
| `ce-scope-guardian-reviewer` | Challenge scope creep and unjustified complexity. |
| `ce-security-lens-reviewer` | Review plan-level security gaps. |
| `ce-security-reviewer` | Review exploitable vulnerabilities. |
| `ce-security-sentinel` | Security audit for vulnerabilities and hardcoded secrets. |
| `ce-session-historian` | Search prior Claude/Codex/Cursor sessions. |
| `ce-slack-researcher` | Search Slack context when configured. |
| `ce-spec-flow-analyzer` | Find user-flow and requirements gaps. |
| `ce-swift-ios-reviewer` | Review Swift/iOS diffs. |
| `ce-testing-reviewer` | Find weak/missing tests. |
| `ce-web-researcher` | Structured external web research. |

## VeilBreakers Overlay

Use CE for process. Use VeilBreakers skills/tools for domain proof:

- `veilbreakers-terrain-research`: terrain, erosion, hydrology, scatter, materials, game-dev research.
- `veilbreakers-procedural-rendering`: shaders, Geometry Nodes materials, terrain texture stacks, water/foam/caustics, lighting, bake passes.
- `veilbreakers-blender-visual-qa`: Blender viewport/render proof before visual claims.
- `veilbreakers-callable-audit`: callable, `COMMAND_HANDLERS`, dispatch, coverage, grade, duplicate audits.
- `veilbreakers-asset-import-pipeline`: GLB/glTF/Quixel/Poly Haven/Meshy/Hunyuan/external assets.
- `veilbreakers-unity-export-check`: Unity RAW, manifests, splatmaps, terrain layers, navmesh, water metadata.
- `veilbreakers-terrain-debugging`: terrain generation bugs and export/render regressions.

## MCP Retention Rules

Keep an MCP when it has a recurring job and no better local replacement.

Current keep list:

- Serena: symbol navigation and safe code edits.
- Context7: live framework/API/library docs.
- GitMCP docs: repository docs when a docs URL/repo source matters.
- Sequential Thinking: high-risk multi-part investigations.
- Blender: runtime scene/material/viewport checks.
- Unity Editor: Editor-side import/export/build checks.

Remove candidates only after confirming:

- no task class still needs it,
- it is broken or redundant,
- repo/local tools cover the same work,
- removal will not break terrain visual/export validation.

## Session Startup Checklist

1. Read `AGENTS.md` and `CLAUDE.md`.
2. Apply VeilBreakers domain skill routing for terrain-specific work.
3. Check branch/status before edits.
4. Use CE for planning, execution, debugging, PR feedback, and commit workflow after domain routing is clear.
5. Keep visual claims blocked until real Blender/Unity proof exists.
6. Use PR path, not direct `main` pushes.
