## Scope

- [ ] Focused branch, not `main`.
- [ ] No unrelated generated output or audit churn included.
- [ ] Other active agents/worktrees checked for overlap.

## Verification

- [ ] Focused tests run or reason documented.
- [ ] Callable/wiring checks run if pass registration, handlers, or audit scripts changed.
- [ ] Unity export checks run if Unity manifest/import/export code changed.
- [ ] Blender/render evidence attached or explicit no-runtime caveat included for visual claims.

## Merge

- [ ] Required checks green: `ci (3.11)`, `ci (3.12)`, `pyright`, `callable-census`, `Analyze (python)`, `Analyze (actions)`.
- [ ] Squash merge selected unless preserving clean commit history is intentional.
