# Design — Generation Truth rule + water as the worked example

**Date:** 2026-05-23
**Branch:** `feat/generator-water-source-of-truth`
**Status:** Approved (verbal) — execution doc
**FIX_PATTERN category:** C8 (visual mandate) lead + C4 (boundary contract). Per §4.5 destructiveness order, C8 leads.

---

## 1. Problem (the reframe)

The **generator** (`veilbreakers_terrain/` — the ~35 passes and their callables) is the product. The **nodes** built by `scripts/build_*` and the **renders** produced by `scripts/render_*` are **disposable verification fixtures** that exercise generator callables — *not* assets to keep or polish.

We have been **fixing defects at the wrong layer**: editing render scripts / build-fixture code / output artifacts to make a picture look right, instead of fixing the generator callable that produced the bad data. A wrong-looking render is (almost always) a **generation defect**, and the fix belongs in the pass that owns it — after which we *regenerate → re-render → visually verify*.

Two exhibits found while scoping:
- **Exhibit A:** `scripts/build_scene_v3.py:make_water_material` (line 811) — graded **D+** in `docs/aaa-audit/R13_FULL_MANUAL_CALLABLE_REVIEW.csv:1920` with the note *"Standalone script callable… not a default terrain runtime path."* The water in every `scene_v3` render comes from this fixture function, **bypassing the generator's wired water path entirely**.
- **Exhibit B:** `output/` render PNGs/`.blend`s are Git-LFS-tracked and the prior session wrote raw bytes over LFS paths, producing constant version-control churn. Render artifacts are being treated as deliverables at the repo level.

---

## 2. Deliverable A — the "Generation Truth" rule

A short, enforced project rule (written to `docs/GENERATION_TRUTH_RULE.md`, linked from `AGENTS.md`/`CLAUDE.md`):

1. A render / `.blend` / PNG is **verification evidence, never a deliverable.** Never hand-edit a `.blend` or tweak a render to make a defect "look fixed."
2. A visual defect **routes to the generator callable** in `veilbreakers_terrain/` that produced the data, and is fixed there.
3. **`scripts/` build & render files drive output through generator callables / `COMMAND_HANDLERS`** — they never reimplement generation. A standalone material/mesh/water factory in `scripts/` is a smell (Exhibit A).
4. After a generator fix: **regenerate → re-render → visually verify** (read the PNG, state what is literally there) before "done."
5. **Render / test `.blend` artifacts are not committed.** Scope the exact ignore globs carefully — CI gates read some `output/` files (e.g. `output/verification/*GUARDRAIL_REPORT.json`, `output/spreadsheet/CALLABLE_WIRING_*`). Those stay. Render PNGs, test `.blend`/`.blend1`, and scratch logs go. Coordinate with existing LFS tracking (do not orphan LFS objects CI still needs).

**Enforcement (Phase 3):** a guard test that fails if any file under `scripts/` defines a water-material factory (and, extensibly, other generation factories). The rule becomes executable, not aspirational.

---

## 3. Deliverable B — water worked example

### 3.1 Code reality (verified at HEAD)

| Component | State |
|---|---|
| `environment.py:_ensure_water_material` (6773) | **Good.** Depth color via `flow_vc` vertex colors deep↔shallow mix (6868–6896); Volume Absorption (6928); riverbed caustics (6976–7007); Fresnel-correct Principled. **Gap: surface normal is *static* noise bump (6951–6969) — no time/flow animation.** Matches the C-grade "no animated normals" (`docs/TERRAIN_UPGRADE_MASTER_AUDIT.md:2261`). |
| `environment.py:_build_level_water_surface_from_terrain` (7210) | Authors `flow_vc` + `FlowData` (depth_factor, D8 flow dirs 7380–7406, Manning speed 7408–7426). Depth/flow gradients only appear when the surface is built here. Requires a **regular-grid terrain mesh**. |
| `build_scene_v3.py:make_water_material` (811) | Flat Diffuse+Glossy, no depth, no flow. Docstring: exists to **dodge a "grey-mirror / white-glass-sheet artifact"** from Principled+Transmission at oblique angles. |
| `build_scene_v3.py:_build_water_depth_disk` (1078) | Lake = **flat plane, no vertex colors**, bed mesh `hide_render=True`. Flat *by construction* — material swap alone cannot add depth; the mesh carries no depth data. |
| `build_scene_v3.py:build_water_surfaces` (1542) | Orchestrates lake + rivers + waterfall + plunge + foam + mist, all via fixture-local builders. |

### 3.2 Phased plan (render-gated — do not advance a phase until the prior render verifies)

**Phase 0 — prove the loop (lake only):**
- Harden `_ensure_water_material`: (a) add **flow-driven animated normals** — a time driver (`#frame`) offsetting the noise/normal along the per-vertex flow direction so water *can* flow (proof of motion needs a multi-frame render or Unity; the still proof is plumbing-correct); (b) **artifact-robustness** — eliminate the oblique-angle grey-mirror that `make_water_material` was built to dodge (clamp/Fresnel-limit the reflective lobe; verify at a low grazing camera).
- Route the **lake** in `build_scene_v3.py` from `_build_water_depth_disk` → `_build_level_water_surface_from_terrain` + `_ensure_water_material`.
- Regenerate `scene_v3`; render `render_hero`, `11_large_water_shoreline`, `09_large_water_bank_exit`; **visually verify**: depth gradient present, surface reads as water (not flat slab), no grey-mirror at grazing angle. ← first visible win.

**Phase 1 — rivers:** route ribbon-mesh rivers to the generator material; author `flow_vc`/`FlowData` on ribbons (the level-surface builder does not apply to ribbons — different path). Verify `06_river_bank_entry`.

**Phase 2 — waterfall / plunge:** route `_build_waterfall_volume` (1167) + `_build_plunge_pool` (1259) to the generator water material. Fix the broken `05_waterfall_closeup` *at the generator/geometry level*, not by moving the camera. Verify.

**Phase 3 — retire the fixture + enforce:** delete `make_water_material` and `_build_water_depth_disk` (now dead); add the guard test from §2.

### 3.3 Test strategy (test-first per phase)

- Generator-material tests (extend `test_terrain_materials_v2.py` / water material tests): assert `_ensure_water_material` builds the expected node graph — Volume Absorption present, flow-driven normal animation node/driver present, reflective lobe capped (artifact guard), depth-color path wired to `flow_vc`.
- Surface-builder tests: `_build_level_water_surface_from_terrain` authors `flow_vc` + `FlowData` with depth_factor in [0,1] and non-zero D8 flow vectors on wet vertices (extend `test_w2_w4_water_depth_seam.py` / `test_terrain_water_vegetation_depth.py`).
- Boundary-contract test (C4): a test pinning that `build_scene_v3` water flows through the generator callables (import-site / call-site assertion), guarding against future fixture divergence.
- Guard test (Phase 3): scan `scripts/` for water-material factory definitions → fail if found.

---

## 4. Risks & pushback (acknowledged)

1. **Grey-mirror regression.** The fixture material exists because Principled+Transmission grey-mirrors at oblique angles. Phase 0 *must* fix this in the generator (proven by a grazing-angle render) or the swap regresses close water shots. **Mitigation:** explicit artifact-guard render before advancing.
2. **Heterogeneous water.** Lake (grid footprint), rivers (ribbons), waterfall (volume) need different routing — not one uniform swap. **Mitigation:** phased, each verified.
3. **Lake shape may change.** `_build_level_water_surface_from_terrain` derives the lake from the submerged terrain footprint; the fixture uses an art-directed `lake_shore_radius`. The data-driven lake may differ. **Mitigation:** Phase 0 render review decides if acceptable; if not, pass a mask center/radius to constrain footprint (the builder supports `mask_center`/`mask_radius`).
4. **LFS / output policy.** Ceasing to track render artifacts interacts with existing LFS tracking and CI-consumed report globs. **Mitigation:** scope ignore globs precisely; keep `output/verification/*` and `output/spreadsheet/*` tracked.

---

## 5. Out of scope (explicit — later work)

- **GPU+CPU performance layer** (CPU-multiprocessed passes + Taichi-CUDA erosion + static CPU+GPU co-render). This is the *next* project after water lands. Note: "GPU runs then CPU toggles at a threshold" is not how Cycles works — devices are static at render start; the real win is GPU-accelerated generation passes + the 12-core CPU on numpy passes.
- **Cliff/rock material defect** (`12_cliff_face` shows grass on steep terrain — splatmap slope-threshold). A separate worked example under the same rule.
- **Unity water mesh dead code** (`VbTerrainImporter.cs` skips water mesh; `BuildWaterPlaneMesh`/`GetOrCreateWaterMaterial` dead). Downstream of generator; separate.

---

## 6. Process

Per `docs/aaa-audit/2026_05_17_ultrafinal/FIX_PATTERN_v1.md`: test-first per phase, local 4-gate before each push (`pyright_strict_baseline_gate`, `callable_census_gate --strict-zero`, `terrain_best_practice_guardrail --strict-verification`, `pytest`), `ce-adversarial-reviewer` wave after implementation, squash-merge PR into `main`, compound doc at `docs/solutions/<category>/<slug>-2026-05-23.md` after merge.
