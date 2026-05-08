---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: active
stopped_at: Phase B in flight (D24/D25 remaining)
last_updated: "2026-05-08T07:30:00.000Z"
progress:
  total_phases: 8
  completed_phases: 6
  total_plans: 27
  completed_plans: 20
  percent: 74
---

# Project State

**Project:** VeilBreakers Terrain Generator
**Last Updated:** 2026-05-08
**Status:** Active — Phase A complete (V1+V2 GO 2026-05-08); Phase B in flight (D24/D25 remaining)

## §17 60-Day Plan Progress (Phase A-E)

### Phase A (D1-15) — Bake-side blockers ✅ COMPLETE 2026-05-08

| Day | Item | PR | Status |
|-----|------|----|--------|
| D6-7 | B15-P0-01 affine rescale + B15-P0-02 biome canonical invariant | #35 | ✅ MERGED |
| D8-9 | Bundle I orphan-pass scheduling (wind_erosion + coastline) | #36 | ✅ MERGED |
| D10-11 | W-1 channel migration (water_surface → water_surface_mask) | #37 | ✅ MERGED |
| D12-13 | B15-P0-08 hydraulic mass leak (3 break sites) | #38 | ✅ MERGED |
| D14-15 (GATE D15) | B15-P0-17 + P0-18 + P0-21 + foam Beaufort cubic | #39 | ✅ MERGED |
| D15.5 hotfix | End-of-lifetime mass leak via for-else clause | #40 | ✅ MERGED |

**Phase A V1+V2 verifiers (2026-05-08):** BOTH GO. Compliance/breadth + adversarial/quality converged.

### Phase B (D16-25) — Determinism, RNG migration, splat truncation ⚙️ IN PROGRESS

| Day | Item | PR | Status |
|-----|------|----|--------|
| D17-18 | chunk_seed BLAKE2b + Bug-A unification | #41 | ✅ MERGED |
| D19 (Bug-E) | terrain_features.py 14 RNG sites → derive_pass_seed | #42 | ⚙️ OPEN, auto-merge enabled |
| D20-22 | Bulk RNG migration 32 sites / 12 files | #43 | ⚙️ OPEN, auto-merge enabled |
| D23 | 6 hash hazards → derive_pass_seed | #44 | ✅ MERGED |
| D24 | Atomic manifest writes + NaN/Inf assertions | TBD | ⚙️ Implementation in flight (subagent) |
| D25 + GATE D25 | B15-P0-07 splatmap L>4 truncation + subprocess-determinism CI matrix | TBD | ⚙️ Implementation in flight (subagent) |

### Phase C-E

- Phase C (D26-35): orphan-pass wiring + label-stamping + stream cap. NOT STARTED.
- Phase D (D36-45): Unity ingestion + Block 5a visual gate. **BLOCKED BY 4 USER DECISIONS** (water/clouds/fog/upscaler) for HDRP→URP rewrite.
- Phase E (D46-60): Performance, atmosphere, audio, hero render. NOT STARTED.

## Mandatory Pre-Push Verifier Workflow

Before EVERY push, run all 4 local gates:

1. `python scripts/pyright_strict_baseline_gate.py` — must pass (no new buckets)
2. `python scripts/callable_census_gate.py --strict-zero` — must pass
3. `python scripts/terrain_best_practice_guardrail.py --strict-grade-status --strict-verification` — must pass (after running prerequisite scan_callable_wiring + build_verification_matrix + build_industry_best_practice_callable_matrix in CI order)
4. `pytest <related test files>` — must pass

## Legacy Status (Pre-§17 Plan, preserved for context)

| Phase | Name | Status | Plans | Notes |
|-------|------|--------|-------|-------|
| 1–6   | Crash fixes + Pass graph + Data integrity + Perf + Algos + Infra | ✓ Complete | — | 2342 tests passing |
| 7     | AAA Algorithm Upgrades | Subsumed by §17 Phase A-E | 0 | Priority-Flood, thermal consolidation |
| 8     | Road System Rebuild | Pending | 0 | 24-dir A*, Rune road pipeline |
| 9     | Scatter + Vegetation Wire-Up | Pending | 0 | channel disconnects |
| 10    | Texturing Formula Upgrades | Pending | 0 | structural labeling |
| 11    | Noise System Upgrades | Pending | 0 | Phacelle, OpenSimplex2S |
| 12    | Erosion Architecture | Subsumed by §17 Phase A | 0 | Hydraulic mass leak fix shipped |
| 13    | Content Consistency | ✓ Complete | 3 | foam vertex alpha, wind bend vertex color |
| 14    | Terrain Features Quality | ✓ Complete | 4 | BUG-94/96/98/99 |

## Key Decisions

- **Scale:** 1m = 0.85 Unity units; camera at clavicle height
- **Reference:** Rune Skovbo Johansen LayerProcGen for roads + scatter architecture
- **Render pipeline:** URP 17.3 (NOT HDRP — committed 2026-05-07; 6-agent fleet audit + Unity batch-mode setup verified)
- **Hardware constraint:** RTX 4060 Ti 8GB hard cap
- **Determinism:** SHA-256 over JSON-encoded tuple (PYTHONHASHSEED-independent); BLAKE2b for chunk_seed
- **Splatmap layers:** Effective 4 at 8GB (Unity 2022+ supports 8 but spec locks 4)

## Test Baseline (last verified)

- **Tests passing:** 3,667 / 0 failed (after FIX_ORDER_CODEX sweep)
- **Branch:** docs/biome-render-rebuild-spec (current working branch)
- **Main HEAD:** `5185137` (PR #44 merge) — pending PR #41 squash merge as of 2026-05-08T07:21:58Z

## Phase 14 Legacy Session (2026-04-19, preserved)

- **Plans completed:** 14-01 bug fixes, 14-02 biome/atmospheric upgrades, 14-03 mesh quality + erosion, 14-04 wind/waterfall/POI
- **New tests:** +96 (2614 → 2710 passing, +3 skipped unchanged)
- **Key decisions:** BUG-96 XOR hash seed; BUG-99 full-delta k_mod; scipy EDT for carve_u_valley; AABB slab for tile contracts; Fix 7.20b HEIGHT_SCALE for macro world heightmap
