# scripts/experiments/

Throwaway / iteration scripts. **Untracked by default** — these are work-in-progress experiments where the canonical successor lives elsewhere.

## Why this dir exists

The repo accumulates render iteration scripts (`render_aaa_v2.py`, `v3.py`, ...) as we explore visual approaches. Only the **latest canonical version** belongs in `scripts/` (or `scripts/renders/`). Older iterations stay here for reference but should not be relied on.

## Current canonical pointers

| Family | Canonical | Older iterations (here) |
|---|---|---|
| AAA mountain pass render | `scripts/render_aaa_v8_mountain.py` | `render_aaa_v2.py`..`v7.py`, `render_aaa_v5_fullnode.py`, `render_aaa_demo.py` |

## When to delete

- An iteration has nothing the canonical doesn't (delete)
- The iteration shows an approach we deliberately rejected (keep with a `# REJECTED:` header noting why)
- The iteration is mid-port to canonical (keep until merged)

## Why we don't `git add` these

Each is a snapshot of an experimental approach. Committing them every iteration spams git history. If a specific experimental script becomes the new canonical, *move it out* of `experiments/` and into `scripts/` or `scripts/renders/` at promotion time.
