# Branching And Merge Policy

## Goal

Keep `main` releasable. All implementation work flows through focused branches, pull requests, required checks, and squash/rebase merge.

## Required Path

1. Start from fresh `main`.

   ```powershell
   git fetch origin
   git switch main
   git pull --ff-only origin main
   ```

2. Create a focused branch.

   ```powershell
   git switch -c fix/<short-scope>
   ```

3. If another agent is active, use a separate worktree.

   ```powershell
   git worktree add ..\veilbreakers-terrain-<scope> -b fix/<scope> origin/main
   ```

4. Commit and push only the focused branch.

   ```powershell
   git add <files>
   git commit -m "Fix <scope>"
   git push -u origin fix/<scope>
   ```

5. Open a PR into `main`.

   ```powershell
   gh pr create --base main --head fix/<scope> --fill
   ```

6. Let required checks pass.

   Required checks:

   - `ci (3.11)`
   - `ci (3.12)`
   - `pyright`
   - `callable-census`
   - `Analyze (python)`
   - `Analyze (actions)`

7. Merge.

   Default:

   ```powershell
   gh pr merge --squash --auto
   ```

   Use rebase merge only for a clean branch with commits worth preserving.

## Never Do

- Never direct-push `main`.
- Never loosen branch protection to merge failing work.
- Never merge with red required checks.
- Never use merge commits.
- Never let two agents edit the same worktree/scope.
- Never claim visual quality from stub renders or no-Blender runs.

## Lightweight Local Checks

Run checks matching the touched surface before PR when practical.

Core Python or handler changes:

```powershell
python -m ruff check --select F821 veilbreakers_terrain/handlers
python -m pytest <focused-tests> -q
```

Callable or wiring changes:

```powershell
python scripts/callable_census_gate.py --strict-zero
python scripts/scan_callable_wiring.py --strict-no-risk
```

Unity export changes:

```powershell
python -m pytest veilbreakers_terrain/tests/test_terrain_unity_export_bridge.py -q
```

Visual or Blender claims:

```powershell
python scripts/visual_testing_readiness_gate.py
```

If Blender runtime is unavailable, mark visual proof as blocked or caveated.
