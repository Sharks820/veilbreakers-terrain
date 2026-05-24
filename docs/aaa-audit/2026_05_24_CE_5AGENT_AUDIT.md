# CE 5-Agent Codebase Audit — 2026-05-24

**Branch:** `feat/generator-water-source-of-truth` (HEAD `ff1a152f`, off origin/main `d1a8ad9a`)
**Method:** 5 parallel Compound-Engineering reviewer agents, MAX-REASONING, read-only, each a distinct facet. Findings below are verified against live code; confidence noted per item. This is the canonical capture — synthesis only, **no fixes applied yet**.

**Agents:** (1) adversarial bugs+wiring, (2) test health, (3) maintainability/stale-files, (4) project-standards/gate-integrity, (5) AAA-direction research.

---

## 0. Unified ranked action queue (deduped)

| # | Sev | Item | Where | Agent |
|---|-----|------|-------|-------|
| 1 | P1 | Seasonal WET/FROZEN water flood (binary mask + 0.15 → floods bodies to global terrain max, silent) | `terrain_water_variants.py:811-842` | adversarial |
| 2 | P1 | Road water-avoidance + bridges DEAD in pipeline (`pass_road_network` never sets `water_level`) | `road_network.py:1463,1603,1821-1830` | adversarial |
| 3 | P0 | Guardrail `--strict-verification` is name-match theater; CI validates it against self-regenerated data | `terrain_best_practice_guardrail.py:243,269-284`; `build_verification_matrix.py:117,126-205`; `python-package.yml:84-86` | gate |
| 4 | P0 | Grade-quality blocks are no-ops (all rows P3/LOW → 741 sub-A incl 1 F/3 D/181 D+ pass) | `terrain_best_practice_guardrail.py:53-60,230-241` | gate |
| 5 | P1 | census + guardrail only scan `handlers/*.py` → **18 production modules blind** (incl. `sim/pbd_cloth`, `sim/foam`, `procedural_meshes`, `cli`, `socket_server`, `providers/*`) | `grade_audit_shared.py:15,97,99` | gate |
| 6 | P1 | 568 MB escaped git worktree inside the tree, NOT gitignored | `UsersConnerOneDriveDocumentsveilbreakers-terrain-wave5-bundle2/` | maintainability |
| 7 | P1(ROI) | Wire wear-state masks (erosion/curvature/cavity) into material **albedo** (the Decima look) — data already computed | `_terrain_erosion.py:51-69` → `_terrain_noise.py:1023-1115` | AAA |
| 8 | P1(ROI) | Wire Cordonnier stream-power erosion solver + raise 8192 droplet cap | `_terrain_erosion.py:293-297`; `terrain_pipeline.py:421` | AAA |
| 9 | P2 | `water_surface_mask` wet-threshold divergence (`>0.0` vs `>0.5` vs `>0`) — root of #1 | `terrain_water_variants.py:836` vs `:1713`; `procedural_grass.py:372` | adversarial |
| 10 | P2 | `terrain_checkpoints_ext.py` tested-but-unwired + latent swallowed `TypeError` (`_save_checkpoint` missing `result` arg) | `terrain_checkpoints_ext.py` | maintainability |
| 11 | P2 | Scatter rotation key has 3 incompatible unit meanings; `_read_rotation_*` can't disambiguate degrees-unmarked | `environment_scatter.py:935-968,3900` | adversarial + AAA |
| 12 | P2 | Destructive `scripts/update_r9_grades.py` rewrites `GRADES_VERIFIED.csv` in place with stale data | `scripts/update_r9_grades.py` | maintainability |
| 13 | P2 | Weak tests give false confidence (caplog-not-asserted; tautological sentinel) | `test_asset_generation.py:385-389,438-440`; `test_wave6_protected_zone_silent_defeat.py:63-70` | test |
| 14 | P2(ROI) | Scatter has no ecosystem sim (competition/age/dispersal); `vb_canopy_openness` unwired | `_scatter_engine.py:36-234` | AAA |
| 15 | P3 | output `_*.log` (18) + `_*.py` (5) debris; gitignore `output/_*` | `output/` | maintainability |
| — | gap | Production mesh-from-heightmap geometric quality has **NO active regression net** | `test_geometric_quality.py:90` (xfail, needs real bpy) | test |

---

## 1. Adversarial — generator bugs + wiring (HEAD `ca537617`)

### P1 — Seasonal WET/FROZEN water flood (confidence 72)
`terrain_water_variants.py:811-842`. WET does `water_surface_mask = clip(mask + 0.15, 0, 1)`, FROZEN `+0.1`, on a **binary {0,1}** channel (produced `(water_surface > 0.0).astype(f32)` at `:998`). Every dry cell becomes `>0.0`. The HOTFIX-7j change on this branch then recomputes `water_surface_elevation_m = _compute_spill_rim_elevation(height, mask > 0.0)` (`:834-836`) → whole tile = one wet body → elevation collapses to global terrain max → `pass_water_depth` fills bodies to mountain height. Bathymetry's `>0.5` gate (`:1713`) rescues dry land but leaves wet bodies inflated. Silent (no NaN → T0-4b gate misses). **Fix:** re-binarize (`>0.5`) before the spill-rim recompute. Trigger: `composition_hints['seasonal_state'] in {'wet','frozen'}` (supported; default in AAA scene-read bakes, `terrain_pipeline.py:501`).

### P1 — Road water-avoidance + bridges dead in pipeline (confidence 90)
`road_network.py`. `pass_road_network` reads `water_surface_mask`/`water_surface_elevation_m` and forwards them (`:1825-1826`, declared optional_channels `:1950-1953`) but **never sets `water_level`**. The cost-penalty block (`:1463`) and bridge-detection (`:1603`) both gate on `water_level is not None` → skipped → pipeline roads route straight through water, zero bridges. The MCP handler `handle_compute_road_network` (`:2007`) forwards `params['water_level']` so the external path works. **Fix:** derive `water_level` from `water_surface_elevation_m` in `pass_road_network`, or gate the branches on `water_mask is not None`.

### P2 — water_surface_mask threshold divergence (confidence 70)
Same binary channel read as `>0.0` (`:836`, seasonal), `>0.5` (`:1713/1726`, bathymetry), `>0` (`procedural_grass.py:372`). Root enabler of the P1. **Fix:** one canonical `_is_wet()` helper at `>0.5`; document in `_channels.py`.

### P2 — Scatter rotation 3-way unit ambiguity (confidence 62)
`environment_scatter.py:935-968`. `'rotation'` key = radians (raw `_scatter_pass`), degrees+`_filtered` (post-filter), OR degrees-unmarked (`context_scatter`, `_scatter_engine.py:888`). `_read_rotation_*` can't tell degrees-unmarked from radians-fallback → misclassifies. Currently dodged by a special-case at `:3900` (HOTFIX-7k). Latent landmine if scatter paths are consolidated. **Fix:** stamp `rotation_rad` (or a unit marker) at every degrees producer.

### Residual risks
- `_mesh_bridge.py:1702-1703` per-face material assign relies on `bm.to_mesh()` face order (its own comment says not guaranteed); count-gate passes even if permuted.
- `_channels.py:104-120` YAW_DEG docstring claims producer writes radians — **stale**; producer fixed (`terrain_assets.py:833` writes degrees). Misleading doc-drift.
- `atmospheric_volumes.py:181-243` BIOME_ATMOSPHERE_RULES covers 10/18 biomes; 8 fall to fog-only default.
- `terrain_cliffs.py:420-441` always writes `cliff_contour_spline` (empty `(0,2)` on flat tiles); consumers must guard.

### Confirmed SOLID (do NOT re-fix)
Unity `write_animation_clip_yaml` rad→deg + tangent conversion; `_write_json` `allow_nan=False`; T0-4b NaN/Inf gate widening; strata `(H,W,3)` shape contracts; atmosphere biome-vocab rename (all 10 keys verified); road `legacy_fallback` (re-raise via `VEILBREAKERS_ROAD_STRICT=1`); `_protected_zones.py` resolver; YAW_DEG producer.

---

## 2. Project-standards — gate integrity

### P0 — `--strict-verification` is theater (confidence 90)
`terrain_best_practice_guardrail.py:243,269-284` blocks only on `risk_counts.{BLOCKER,HIGH}`/`false_grade_count` from `CALLABLE_VERIFICATION_SUMMARY.json`, which `build_verification_matrix.py` computes by **AST name-matching** (`:117,126-134,194-205`): `direct_test` = any test file contains the callable's simple name; `live_probe` = a test file's text contains 'live'/'bpy'/'visual' anywhere (incl. comments). Current state: 1922 LOW, 0 false-grade → blocks on nothing. CI regenerates this summary (`python-package.yml:84`) immediately before validating against it (`:86`) — **self-referential**. **Fix:** drive evidence from `coverage.py` arc data (the `--cov-branch` run already exists), not name-matching.

### P0 — Grade-quality blocks no-op (confidence 88)
`terrain_best_practice_guardrail.py:53-60,230-241`. Newest matrix tags ALL 1942 rows `upgrade_tier=P3`, 1940 `verification_risk_level=LOW`. `--strict-p0` matches 0 rows; the non-A check short-circuits on `risk != 'LOW'`, so all **741 sub-A rows (1 F, 3 D, 181 D+, …) pass unblocked**. The 140-P0 audit reality is invisible. **Fix:** remove the `risk != 'LOW'` short-circuit (`:240`); reconcile the matrix's blanket P3/LOW tagging.

### P1 — pyright "strict" is a ratchet (confidence 80)
`pyright_strict_baseline_gate.py:154-180` baselines **968 errors across 406 buckets**; per-bucket (not global) granularity allows shuffling within a bucket. Legitimate ratchet, but "strict" overstates it (AGENTS.md already tempers this). **Fix:** add a monotonically-decreasing global cap.

### P1 — Gates scan only `handlers/*.py` → 18 modules blind (confidence 85)
`grade_audit_shared.collect_callables` globs only `HANDLERS_DIR` (`:15,97,99`). Invisible to census `--strict-zero` AND guardrail: `procedural_meshes.py`, `sim/pbd_cloth.py`, `sim/foam.py`, `sim/catenary.py`, `providers/{meshy,hunyuan3d2,external_asset}_provider.py`, `cli.py`, `socket_server.py` — incl. the Y04-flagged-buggy `pbd_cloth`/`foam`. **Fix:** scan the full `veilbreakers_terrain/` tree (ex `tests/`).

### P2 — others
- Duplicate-name detection informational; `--strict-duplicates` not in 4-gate/CI; allowlist `CALLABLE_DUPLICATE_REVIEW.json` can silence (e.g. `priority_flood_d8` ×3, `derive_pass_seed`).
- CLAUDE.md/AGENTS.md required-checks list **stale**: omits `subprocess-determinism (18/18)`, `pip-audit`, `pyright-strict` lane, `visual-testing-readiness` (all enforced in CI).
- No per-pass NaN coverage gate (finite-array guard `terrain_pipeline.py:1144-1203` only fires for passes a test runs; floor is `--cov-fail-under=72`). Determinism CI matrix bakes only 32×32 tile (0,0).
- Note: `GRADES_VERIFIED.csv` grade *correctness* is unaudited — `--strict-zero` only proves a row exists.

---

## 3. Maintainability — stale files / dead / unwired

- **P1** — 568 MB git worktree escaped INTO the tree as literal-path dir `UsersConnerOneDriveDocumentsveilbreakers-terrain-wave5-bundle2/` (branch `fix/wave5-2-5-6-cleanup`, work merged via PR #141), NOT gitignored. **Fix:** `git worktree remove --force` + `git worktree prune`; delete stray `C:UsersConner…tmppr140_conflicts.txt`.
- **P2** — `terrain_legacy_bug_fixes.py` self-declared dead auditor (`# AUDITOR_MODULE`), greps `terrain_advanced.py` at HARDCODED stale line numbers → false green (BUG-109). Delete or convert to AST search.
- **P2** — `terrain_checkpoints_ext.py` not in registrar/pipeline; 6/10 callables R10 unwired; `save_every_n_operations` calls `_save_checkpoint(pass_name)` missing required `result` arg → every Nth pass raises `TypeError` swallowed silently (BUG-R8-A1-008). Wire+fix or delete.
- **P2** — R9–R13/Wave10 audit generators at `scripts/` root untouched 19-30d; `update_r9_grades.py` (988 LOC) hardcodes + rewrites `GRADES_VERIFIED.csv` in place with a frozen R9 snapshot. Move to `scripts/deprecated/`, guard destructive ones.
- **P3** — `output/_*.log` (18, ~2.4 MB) + `output/_*.py` (5 scratch) untracked debris. Delete + gitignore `output/_*`.
- **Residuals:** fixture↔generator water mid-migration (rivers still use `make_water_material` `build_scene_v3.py:836,1537` — known/intentional, lake done at `:1494`); `coverage_gap_analysis.py` zero-consumer runpy shim; `_cycles_gpu.py` (now committed via v7); `.planning/proposals/2026-05-10_repo_reorg.md` overlaps (its worktree-clean claim now stale). **Testing gap:** 183 callables R10 TEST_ONLY_OR_UNWIRED (most benign internal helpers; the whole-module ones — checkpoints_ext, legacy_bug_fixes — let broken paths pass green).

---

## 4. Test health (suite GREEN — 4996 passed, 1 skip, 1 xfail)

Architecture strong: tests pure-numpy logic directly or via hand-built fake node-models (`test_procedural_material_builder_contracts.py` = gold standard), so the conftest MagicMock-bpy theater risk is largely avoided. `strict_provenance` autouse fixture surfaces stack-bypass bugs.

- **Weak (false confidence):** `test_asset_generation.py:385-389,438-440` — `caplog.at_level("WARNING")` then assert NOTHING (SUT does warn at `asset_generation.py:400,506`); fix first. `test_wave6_protected_zone_silent_defeat.py:63-70` — `result[0] >= -1e18 and result[2] <= 1e18` tautology (any value passes); should be `== (-1e9,-1e9,1e9,1e9)`.
- **Mock-limited:** `test_t1_build_scene_v3_cluster.py:132-150` — `scatter_water_surface_assets` test is signature-smoke only (MagicMock bpy can't prove the loop runs); needs `importorskip('bpy')` integration or factor-out the count.
- **Brittle source-pins (redundant):** `test_terrain_erosion_filter.py:103` (+ `test_phase_b_d24_nan_inf_assertions.py:413,425`, `test_terrain_cliffs.py:966-967`, `test_phase_a_d12_...:160,191`) use `inspect.getsource` substring greps backed by real behavioral checks — delete the redundant ones.
- **Gaps:** production mesh-from-heightmap geometric quality (manifold/normals/degenerate) — **no active net** (xfail `test_geometric_quality.py:90`, target `environment._create_terrain_mesh_from_heightmap:1758`, needs real bpy); `create_biome_terrain_material` node-graph wiring unverified (only dedup call_count checked); `scatter_water_surface_assets` placement-count untested.

---

## 5. AAA directional gaps (vs Gaea 2 / Houdini / UE5 PCG+Nanite+RVT / World Creator / Decima)

Algorithmically deep but **architecturally 2.5D**; the gaps are output-representation + simulation-fidelity + ecosystem realism, not missing math. Agrees with the project's own X05 matrix (`docs/aaa-audit/2026_05_17_ultrafinal/MASTER_FINAL.md:7782-7824`).

1. **2.5D heightfield, no Nanite/RVT/clipmap** (`terrain_chunking.py:16-31` bilinear LOD only; `terrain_unity_export.py` RAW). Caps overhangs/cliffs. Near-term: wire Unity RVT for splat composition. High effort for full path.
2. **Erosion ~8192-droplet cap, single-pass** (`_terrain_erosion.py:293-297`; one erosion insert `terrain_pipeline.py:421`). Cordonnier stream-power solver `compute_stream_power_erosion` may be **unwired** — verify+wire (low-effort, high-value). Add multi-scale erosion cascade.
3. **D8-only hydrology** (`_water_network.py:678,704`; Manning proxy `:799-803`). Add D∞/MFD; couple erosion↔flow feedback.
4. **Scatter = stateless rules** (`_scatter_engine.py:36-234`), no competition/age/succession/dispersal; `vb_canopy_openness` computed but unwired. Add competition/age/thinning + mother-tree dispersal.
5. **Multi-scale detail is roughness-only** (`terrain_multiscale_breakup.py:107-108`; `terrain_materials_v2.py:1153` 0.05m disp scalar). Add a true detail-displacement band.
6. **Wear masks under-wired to albedo** (`_terrain_erosion.py:51-69` signals exist; `_terrain_noise.py:1023-1115` rules are slope/alt-only). Route deposition→sediment, erosion/convexity→exposed rock, cavity→moss. **Highest-ROI, data exists.**
7. **No footprint deformation / DCC bridge** (one-way RAW→Unity). FBX round-trip first.

**Top-3 ROI (no engine rewrite):** (6) wear-masks→albedo, (2) stream-power solver + droplet cap, (4) scatter competition/age.

---

## 6. Session context (what produced this branch)

- `docs/GENERATION_TRUTH_RULE.md` — generator is the product; fix it, never the render/fixture.
- scene_v3 lake + v7 gorge node both routed to generator water (commits `333ded20`, `ca537617`, `ff1a152f`). v7 = v6-quality gorge + generator water, visually verified.
- scipy/Blender isolated-mode unblock (`VB_BLENDER_DEPS` bootstrap) — the root cause fixtures existed. See user-memory `project_blender_scipy_isolated_mode_2026_05_23`.
- **Un-masked by the scipy fix:** scene_v3 `bridge_paths` fails `route_0 grade 0.923 > budget 0.335` — real pre-existing bug scipy was hiding (relates to action item #2).
