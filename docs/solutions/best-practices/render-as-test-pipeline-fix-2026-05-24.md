# Render-as-test forces generation bugs out of the pipeline (fix the generator, never the render)

**Date:** 2026-05-24
**Category:** best-practices
**Context:** Building the v8 full-pipeline showcase node (`scripts/build_terrain_aaa_node_v8.py`) + the CE-audit water/road/scatter fixes (PRs #145/#146/#147).

## The pattern

Treat a render as a **disposable visual test of the generator**, not a deliverable. When a render looks wrong, the bug is in the generation pipeline — fix it there and re-render, never patch the render output. Rendering *variants often* (different terrain, season, resolution) is how you surface pipeline bugs that unit tests miss, because the render exercises the whole pass DAG on real-scale data.

This session, the v8 showcase render surfaced **two real pipeline bugs that no test had caught**, plus CE review caught a third before it shipped.

## What worked

### 1. Drive the showcase through the PRODUCTION seam, not a hand-rolled pass loop
v8's first attempt hand-built a `TerrainPipelineState` and ran passes directly → every pass self-reported `status="failed"` (protocol violation: no `scene_read`/`viewport_vantage`). The fix was to route through `_execute_terrain_pipeline(controller_params)` — the same internal `handle_generate_terrain` uses — with:
- `out_of_view_ok=True` (headless: opt out of Protocol Rule 2, which otherwise demands a viewport vantage),
- `bulk_edit=True` + `cells_affected` + a minimal `scene_read`,
- **`height=<my heightmap>`** to inject hand-authored relief, and
- a **decoration-only `pipeline=[...]`** that excludes the height-*generating* passes.

Result: 41–43/44 passes run **protocol-clean** on quality relief → rich materials/scatter/water in the render.

### 2. Exclude the height-DISTORTING passes when injecting relief
The default sequence's height generators (`pass_generate_low_freq_hmap`/`high_freq`/`composite`) overwrite injected height. **Also exclude `banded_macro`** — isolation showed it regenerates ±380 m needle-spike relief (gradient max ~350 from a 0.94-smooth input) under the "mountains" profile, and `pass_banded_advanced` (Kuwahara) *over-flattens* it. (Filed: `banded_macro` is a generation-quality defect — it is *why the raw `_terrain_world` path renders spiky*.)

### 3. The two pipeline bugs the render forced out
- **Scatter O(N²) OOM (P0):** `validate_asset_density_and_overlap` built an (N×N) float64 matrix — `# O(n^2) is fine — asset counts are bounded per tile` — which is a **landmine comment**: at N=90,449 placements that array is 61 GiB and crashes the pass. Fixed → `scipy KDTree.query(k=2)` (each point's nearest neighbour; O(N) memory, strict `< radius`). Keep an exact O(N²) path for n≤256 so small-fixture behaviour is byte-identical. **Guard non-finite coords** (KDTree raises on them; the old path silently ignored them — a path-dependent crash).
- **Road cascade flood (CE-caught, would have shipped):** wiring a scalar `water_level` into `pass_road_network` *armed* a latent bug — `compute_road_network` built its A* water-cost from `hmap < water_level` (terrain-vs-scalar), flooding whole tiles into 62 phantom bridges. Root fix: build the cost layer from the real per-cell `water_mask`. The naive fix's test only asserted `bridge_count > 0` — so it *passed on the 62-bridge garbage*. **A passing test that can't distinguish correct from catastrophic is not a test.**

## What the pattern missed (gaps to close next time)
- **`scipy` stub gotchas under pyright-strict:** `from scipy.spatial import cKDTree` is `reportAttributeAccessIssue` ("unknown import symbol") — use `KDTree` (the stubbed alias; same class at runtime). `query_pairs(output_type="ndarray")` is stub-typed `set`; cast the *instance* (`cast(Any, KDTree(xy))`) so the method access + ndarray ops are clean.
- **Per-push bot re-review churn:** every push to a PR re-triggers CodeRabbit/Copilot/Codex → new threads → resolve loop. Batch fixes; resolve minor showcase-script/doc nits as *acknowledged-with-rationale* rather than chasing each through another CI cycle.
- **Strict-up-to-date merge dance:** with `required_status_checks.strict=true`, the first PR to merge moves `main` and the others go `BEHIND` → need a merge-up. Auto-merge does **not** auto-update the branch.

## Reusable sub-patterns
- **Validate the pipeline in system Python before paying for a Blender render.** `_execute_terrain_pipeline` is pure-data (numpy/scipy) until the bpy mesh build — run it under system `python` (scipy 1.17.1) to check pass statuses + height range in seconds, and only invoke Blender (scipy bundled 1.17.0) for the actual render.
- **Any `# O(n) is fine because <input is bounded>` comment is a latent OOM/perf bug** — verify the bound holds at production scale (here: 90 k placements on a dense tile).
- **When a fix "wires up" a previously-dead code path, adversarially check what that path now does** — it may *arm* a latent bug (the road cost-flood).

See also: `docs/aaa-audit/2026_05_24_CE_5AGENT_AUDIT.md` (+ `_ADDENDUM.md`); user-memory `project-session-2026-05-24-overnight-3prs`.
