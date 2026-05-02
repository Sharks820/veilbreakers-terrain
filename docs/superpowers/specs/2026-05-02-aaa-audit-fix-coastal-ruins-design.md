# AAA Terrain Audit-Fix + Sunken Coastal Ruins Node — Design Spec

**Date:** 2026-05-02  
**Branch:** `codex/aaa-terrain-golden-semantics`  
**Author:** Claude (Sonnet 4.6) + Conner  
**Approach:** Sequential (Approach A) — each phase fully verified before next starts

---

## Context

- 429 confirmed audit items across Batches 0–13 in `FIX_ORDER_CODEX_2026_04_27.md`
- 629 GitHub CodeQL alerts, ~72 true/wiring findings mapped to FIX entries, ~187 false positives refuted
- Test suite: 3,667 passed / 0 failed as of 2026-04-29
- Existing nodes: Ashen Caldera v1/v2, Mountain Pass v1
- **New node:** Sunken Coastal Ruins (sea-cliff coastline, tide pools, eroded rock stacks, submerged ruin foundations)

---

## Execution Phases

### Phase 1 — Batch 14 Deep Scan

Sequential domain-by-domain scan of the live codebase for new bugs not yet in the codex:

| Domain | Scan targets |
|---|---|
| Water / coastline | Orphaned channel writes, never-flushed labels, double-wired semantics |
| Erosion / geology | Dead pass registrations, wrong units, silent skips, delta never applied |
| Materials / splatmap | Orphaned layer configs, missing `stack.set()`, dead template slots |
| Scatter / foliage | Duplicate wiring paths, missing collision exclusion, dead spec fields |
| Unity export / C# | Importer gaps, attribute mismatch, off-mesh JSON orphans |
| Procedural meshes | Never-called generators, dead UV / vertex-color slots |
| Roads / navmesh | Unregistered passes, incomplete A* cost tables |
| Atmospheric / VFX | `pz=0.0` descendants, orphaned volume configs |
| Tests / guardrails | Test-only callables with no runtime callers, mock leaks |
| CodeQL 629-alert audit | Map every alert to a FIX entry or REFUTED |
| Hunyuan3D-2 provider | Verify provider wiring, VRAM guard, texture pipeline |
| Visual pipeline / renders | Script wiring, output manifest, Blender 4.5 API compat |

Output: `docs/aaa-audit/BATCH14_FINDINGS.md` with structured findings.

**Gate:** Scan complete, findings documented.

---

### Phase 2 — Opus Consolidation + Open-Item Verification

Single Opus agent reads live code for every active item in Batches 0–13 plus all Batch 14 findings.

For each item:
- `FIXED` — code already corrects it → skip
- `ACTIVE` — still present → include in implementation
- `REFUTED` — evidence contradicts finding → mark and remove

Outputs:
- Updated `FIX_ORDER_CODEX_2026_04_27.md` with Batch 14 appended
- `docs/aaa-audit/REFUTED_2026_05_02.md` for removed items
- `docs/aaa-audit/ACTIVE_ITEMS_FINAL_2026_05_02.json` as implementation work list
- `docs/aaa-audit/GRADES_VERIFIED.csv` updated for any grade changes

**Gate:** All items classified, codex updated, 629 CodeQL alerts fully mapped.

---

### Phase 3 — Implementation (Sequential batches, Sonnet agents)

Strict order matching `FIX_ORDER_CODEX` dependency chain:

| Step | Batch | Content | Opus checkpoint |
|---|---|---|---|
| 3.0 | Batch 0 | 7 critical-path single-line fixes (slope units, water threshold, erodibility, NaN export, road_mask, pool_delta, + 1) | Full test suite + callable census |
| 3.1 | Batch 1 | Pipeline wiring — pass appends, `stack.set()` calls (12 fixes) | Test slice + callable census |
| 3.2 | Batch 2 | Export contracts — binary channels, splatmap, Unity (10 fixes) | Unity manifest validation |
| 3.3 | Batch 3 | Math / algorithm correctness — wrong formulas, wrong units (18 fixes) | Test suite + golden diff |
| 3.4 | Batch 4 | Simulation completeness — stubs replaced with real algorithms (14 fixes) | Extended test suite |
| 3.5 | Batch 5 | Orphan system wiring — complete code, zero callers (10 fixes) | Callable census zero |
| 3.6 | Batch 6 | Quality / density floors — below-AAA output floors (12 fixes) | Full suite |
| 3.7 | Batches 7–9 | S22 sweep — triplanar UV, deepcopy OOM, parallel merge setattr, Rule-1 gate, etc. (67 fixes) | Full suite + callable census |
| 3.8 | Batches 10–11 | CodeQL true findings — 34 errors, 38 orphaned wiring, 370 quality upgrades | CodeQL re-scan green |
| 3.9 | Batches 12–13 | Deep scan — inert erosion, water physics, Unity import orphans, delta bugs (66 fixes) | Full suite |
| 3.10 | Batch 14 | New findings from Phase 1 scan | Full suite + callable census zero |

After **every step**: Opus reads changed files, verifies fix matches codex spec, confirms tests pass, approves before next step starts.

**Gate:** All batches complete, test suite green, callable census zero, CodeQL alerts resolved.

---

### Phase 4 — Sunken Coastal Ruins Terrain Node

#### 4.1 Visual Reference Research

Web-search for:
- Real-world: Isle of the Dead (Baltic Sea), Tintagel cliffs (Cornwall), Dunluce Castle (Ireland), Makapuu tidepools (Hawaii)
- AAA game: God of War coastal zones, AC Odyssey sea-cliffs, Horizon Forbidden West shoreline, Sea of Thieves coastline
- Select 3–5 hero reference images; save to `output/aaa_sunken_coastal_ruins/references/`

#### 4.2 Node Architecture

```
HeightmapGen
  ├─ Cliff-eroded coastal shelf (50–120m cliff face, tidal shelf 0–15m, deep water -30m)
  ├─ Hydraulic erosion (cliff-face drainage gullies, 10k+ iterations)
  ├─ Water system (tide pools + surge channel + wave foam)
  ├─ Coastline pass (5-zone: subtidal / intertidal / splash / spray / supralittoral)
  ├─ Scatter
  │   ├─ Driftwood logs × 40–80 instances
  │   ├─ Wave-worn boulders × 60–120 instances
  │   ├─ Eroded rock stacks × 15–25 instances
  │   ├─ Ruin column fragments × 20–40 instances
  │   ├─ Kelp / seaweed clumps × 100–200 instances
  │   └─ Barnacle clusters × 200–400 instances (micro-scatter)
  ├─ Atmospheric volumes (sea mist, spume, fog sheets in sea caves)
  └─ Unity export (HDRP channels + LOD 0–3 + navmesh + foliage manifest)
```

#### 4.3 Hunyuan3D-2 Props

Generate and texture all environmental props using Hunyuan3D-2 local server:

| Prop | Variants | Texture target |
|---|---|---|
| `dead_tree_coastal` | 3 | Bleached bark, salt-weathered, lichen-crusted |
| `boulder_wave_worn` | 5 | Wet basalt, barnacle patches, tidemark staining |
| `log_driftwood` | 4 | Grey-bleached, waterlogged dark, kelp-draped |
| `rock_stack_eroded` | 6 | Layered sedimentary strata, spray-wet surface |
| `ruin_column_fragment` | 3 | Worn limestone, algae-stained, half-submerged |
| `kelp_clump` | 4 | Dark olive-green, translucent edges, wet sheen |

Each prop: Hunyuan3D-2 mesh → UV unwrap → ambientCG / Poly Haven CC0 texture bake → LOD chain → Unity HDRP export.

#### 4.4 Visual Proof Deliverables

All committed to `output/aaa_sunken_coastal_ruins/` and pushed to GitHub:

| File | Content |
|---|---|
| `render_hero.png` | Cliff face with ruins, tide pools, sea mist |
| `render_waterline.png` | Water surface + foam + wet_rock material |
| `render_cave_entrance.png` | Sea cave with atmospheric fog volumes |
| `orbit/orbit_00..07.png` | 8-direction orbit renders |
| `hunyuan_props_proof.png` | Mosaic of all generated props with textures |
| `CROSS_SECTIONS.png` | Heightmap + splatmap + water channel visualization |
| `BUILD_SUMMARY.json` | Node metadata, pass results, quality metrics |

#### 4.5 Opus AAA Visual Analysis

Opus agent receives all render outputs and evaluates against:
- KCD2 / TW3 / RDR2 coastal reference quality bar
- Splatmap correctness (no material bleeding, correct zone transitions)
- Water believability (foam placement, tidemark, wet_rock wetness)
- Prop integration (scale, weathering coherence, scatter density)
- Silhouette readability (cliff edge, ruin shapes, rock stacks)

**Pass criteria:** All 5 dimensions score ≥ B+ before GitHub push confirmed.

---

## Success Criteria

1. All audit items resolved: test suite green, callable census zero, CodeQL alerts mapped
2. `GRADES_VERIFIED.csv` updated with Batch 14 grades
3. `FIX_ORDER_CODEX` has explicit FIXED/REFUTED/ACTIVE status on every item
4. Sunken Coastal Ruins node renders committed to GitHub with Opus AAA pass verdict
5. Visual proof of Hunyuan3D-2 props in `hunyuan_props_proof.png`

---

## Constraints

- Max 12 parallel Opus subagents per dispatch wave (sequential approach = 1 at a time per phase)
- No commits directly to `main` — all work on `codex/aaa-terrain-golden-semantics`
- No pytest in subagents — only primary session runs the test suite
- Blender 4.5 APIs only
- Hunyuan3D-2 requires 16–24 GB VRAM; VRAM guard must be checked before generation
- Do not commit/push while Codex is verifying (per `feedback_codex_commits.md`)
- All new findings merged into `GRADES_VERIFIED.csv` + master audit doc — no parallel SYNTHESIS files

---

## File Map

```
docs/aaa-audit/BATCH14_FINDINGS.md             ← Phase 1 output
docs/aaa-audit/REFUTED_2026_05_02.md           ← Phase 2 output
docs/aaa-audit/ACTIVE_ITEMS_FINAL_2026_05_02.json  ← Phase 2 output
docs/aaa-audit/FIX_ORDER_CODEX_2026_04_27.md   ← Phase 2 updates
docs/aaa-audit/GRADES_VERIFIED.csv             ← Phase 2 updates
output/aaa_sunken_coastal_ruins/               ← Phase 4 output
scripts/build_aaa_sunken_coastal_ruins.py      ← Phase 4 build script
```
