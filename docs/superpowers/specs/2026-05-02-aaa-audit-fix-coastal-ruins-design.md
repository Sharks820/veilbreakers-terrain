# AAA Terrain Audit-Fix + Sunken Coastal Ruins Node — Design Spec

**Date:** 2026-05-02  
**Branch:** `codex/aaa-terrain-golden-semantics`  
**Author:** Claude (Sonnet 4.6) + Conner  
**Approach:** Sequential (Approach A) — each phase fully verified before next starts  
**Rev:** 2 (post spec-review — all 4 BLOCKERs + 5 IMPORTANT issues resolved)

---

## Context

- 429 confirmed audit items across Batches 0–13 in `FIX_ORDER_CODEX_2026_04_27.md`
- 629 GitHub CodeQL alerts: 27 error / 161 warning / 441 note; Batch 11 maps 15 active fixes.
  All 629 alerts will be individually adjudicated in Phase 2 (each gets a FIX entry or explicit REFUTED with cited evidence).
- Test suite: 3,667 passed / 0 failed as of 2026-04-29
- Existing nodes: Ashen Caldera v1/v2, Mountain Pass v1
- **New node:** Sunken Coastal Ruins (storm-carved sea cliffs, tide pools, eroded rock stacks, submerged ruin foundations)

---

## Execution Phases

### Phase 1 — Batch 14 Deep Scan

Sequential domain-by-domain scan of the live codebase for new bugs not yet in the codex:

| Domain | Scan targets |
|---|---|
| Water / coastline | Orphaned channel writes, never-flushed labels, double-wired semantics |
| **Coastline / tidal zones** | `detect_tidal_zones()` 5-zone completeness (spray zone present?), `pass_coastline` registration, cliff-face splatmap coverage, JONSWAP wave energy wiring |
| Erosion / geology | Dead pass registrations, wrong units, silent skips, delta never applied |
| Materials / splatmap | Orphaned layer configs, missing `stack.set()`, dead template slots |
| Scatter / foliage | Duplicate wiring paths, missing collision exclusion, dead spec fields |
| Unity export / C# | Importer gaps, attribute mismatch, off-mesh JSON orphans |
| Procedural meshes | Never-called generators, dead UV / vertex-color slots |
| Roads / navmesh | Unregistered passes, incomplete A* cost tables |
| Atmospheric / VFX | `pz=0.0` descendants, orphaned volume configs |
| Tests / guardrails | Test-only callables with no runtime callers, mock leaks |
| CodeQL 629-alert audit | Map every one of the 629 alerts to a FIX entry (active or completed) OR a written REFUTED entry with cited evidence |
| Hunyuan3D-2 provider | Verify HF Space provider wiring, `gradio_client` import guard, `/generation_all` texture path, HF token env var |
| Visual pipeline / renders | Script wiring, output manifest, Blender 4.5 API compat, GPU probe present |

Output: `docs/aaa-audit/BATCH14_FINDINGS.md` with structured findings in format:
`[{id, file, line, severity, finding, codeql_alert_ref?}]`

**Gate:** Scan complete, findings documented.

---

### Phase 2 — Opus Consolidation + Open-Item Verification

Single Opus agent reads live code for every active item in Batches 0–13 plus all Batch 14 findings.

For each item:
- `FIXED` — code already corrects it → skip
- `ACTIVE` — still present → include in implementation
- `REFUTED` — evidence contradicts finding → mark and remove with cited line evidence

For the 629 CodeQL alerts specifically: every alert is adjudicated. Each alert must have either:
- A mapped FIX entry (active or already fixed), OR
- An explicit REFUTED entry citing the specific reason (false positive, test noise, already handled by another fix, etc.)

Outputs:
- Updated `FIX_ORDER_CODEX_2026_04_27.md` with Batch 14 appended
- `docs/aaa-audit/REFUTED_2026_05_02.md` for removed items with evidence
- `docs/aaa-audit/ACTIVE_ITEMS_FINAL_2026_05_02.json` as implementation work list  
  Schema: `[{"fix_id": "FIX-X-Y", "batch": N, "status": "ACTIVE", "file": "...", "line": N, "description": "..."}]`
- `docs/aaa-audit/GRADES_VERIFIED.csv` updated for any grade changes

**Gate:** All items classified. All 629 CodeQL alerts individually adjudicated (each has FIX entry OR REFUTED entry). Codex updated with accurate batch contents and fix counts.

---

### Phase 3 — Implementation (Sequential batches, Sonnet agents)

Strict order matching `FIX_ORDER_CODEX` dependency chain.

**Test ownership:** Opus checkpoints verify code changes match codex spec via static reading only. The primary session (not subagents) runs `pytest` + `python scripts/callable_census_gate.py --strict-zero` after each batch. Opus does NOT invoke pytest directly.

| Step | Batch | Content | Opus checkpoint | Primary tests |
|---|---|---|---|---|
| 3.0 | Batch 0 | 7 critical-path single-line fixes (slope units, water threshold, erodibility, NaN export, road_mask, pool_delta, +1) | Verify 7 files changed, each fix matches codex spec | Full test suite + callable census |
| 3.1 | Batch 1 | Pipeline wiring — pass appends, `stack.set()` calls (12 fixes) | Verify all `stack.set()` inserts and pass registrations match codex | Test slice + callable census |
| 3.2 | Batch 2 | Export contracts — binary channels, splatmap, Unity (10 fixes) | Verify Unity importer + export handler changes match codex | Unity manifest validation |
| 3.3 | Batch 3 | Math / algorithm correctness — wrong formulas, wrong units (18 fixes) | Verify each formula change matches cited reference (Olsen 2004, Leopold-Maddock, etc.) | Test suite + golden diff |
| 3.4 | Batch 4 | Simulation completeness — stubs replaced with real algorithms (14 fixes) | Verify stub→real replacements are non-trivial implementations | Extended test suite |
| 3.5 | Batch 5 | Orphan system wiring — complete code, zero callers (10 fixes) | Verify caller-side wiring added, not just stub fixes | Callable census zero |
| 3.6 | Batch 6 | Quality / density floors — below-AAA output floors (12 fixes) | Verify output quality parameters match AAA references cited in codex | Full suite |
| 3.7 | Batches 7–9 | S22 sweep — triplanar UV, deepcopy OOM, parallel merge setattr, Rule-1 gate, navmesh OBJ, decal_density crash, 12 phantom channels (67 fixes) | Verify S22 sweep items by file:line against committed code | Full suite + callable census |
| 3.8a | Batch 10 | Opus deep-scan P0/AAA-gap findings (23 active): waterfall drop/Q orphan, saliency vantage_weights, JONSWAP fetch_norm, DEM valid_mask wiring, billboard/impostor config, AASHTO grade limits, animation timing orphans, etc. | Verify each algorithmic fix matches codex spec; these are pipeline bugs, not static-analysis items | Full suite |
| 3.8b | Batch 11 | CodeQL 629-alert active fixes (15 active): phantom exports, cyclic imports, empty-except sites, resource/CI security, dead code, orphaned wiring | Verify CodeQL alert IDs explicitly resolved; re-scan confirms alerts closed | CodeQL re-scan green |
| 3.9 | Batches 12–13 | Deep scan — inert erosion passes, water physics, Unity import orphans, pool_deepening_delta double-apply, 8 biome grammar features never called, foliage never attached (66 fixes) | Verify double-apply fixes and grammar feature wiring | Full suite + callable census |
| 3.10 | Batch 14 | New findings from Phase 1 scan | Verify each new finding resolved | Full suite + callable census zero |

After **every step**: Opus verifies static code changes match codex. Primary session runs tests. Both must pass before next step.

**Gate:** All batches complete, test suite green, callable census zero, CodeQL alerts resolved.

---

### Phase 4 — Sunken Coastal Ruins Terrain Node

#### 4.1 Visual Reference Research

Web-search + fetch for reference imagery:
- Real-world: Tintagel cliffs (Cornwall), Dunluce Castle cliffs (Ireland), Étretat sea arches (Normandy), Makapuu tidepools (Hawaii), Dunnottar Castle (Scotland)
- AAA game: God of War (2018) coastal zones, AC Odyssey sea-cliff shores, Horizon Forbidden West shoreline vignettes
- Select 3–5 hero reference images; save to `output/aaa_sunken_coastal_ruins/references/`
- Emulation target: storm-carved escarpment 50–120m, eroded sea stacks, submerged limestone ruin bases, deep tide pools, spume-streaked lower cliffs

#### 4.2 Node Architecture

**Heightmap formula skeleton** (standalone Python node, same pattern as Ashen Caldera v2):
```python
# 1. Base shelf: Heaviside-smoothed escarpment
#    cliff_edge at x=0, land side +1 normalized, sea side tapers to -0.3
#    profile = 0.5 * (1 + tanh(k * (x - cliff_edge))) where k = 8.0
# 2. Cliff face displacement: domain-warped multi-octave noise
#    3 octaves, base freq = 0.004, domain warp amplitude = 80m
# 3. Sea floor bathymetry: linear ramp from 0m at waterline to -30m at tile edge
#    with pit-fill depressions for tide pools (Gaussian bowls r=8-20m, depth=-2 to -6m)
# 4. Ruin footprints: rectangular flat pads at tidal-shelf elevation ± 0.5m
#    partially submerged: 40% of pads sit 0.5–2m below waterline
# 5. Sea stacks: isolated Gaussian spires at splash/intertidal boundary
#    r=8-25m, height=20-60m above waterline, 3-7 stacks per tile
```

**Coastline pipeline integration** — call existing handlers rather than reimplementing:
- `pass_coastline()` from `coastline.py` for 5-zone tidal classification
- `detect_tidal_zones()` must produce all 5 zones: subtidal / intertidal / splash / spray / supralittoral
  (verify spray zone exists after Batch 14 scan; add if missing)
- `apply_coastal_erosion()` for cliff-face drainage gully generation
- `compute_wave_energy()` (JONSWAP) for foam + wet_rock placement

**LOD chain** — reference `lod_pipeline.py` for terrain; Blender decimate modifier for props:

| Level | Terrain resolution | Prop poly budget | Transition distance |
|---|---|---|---|
| LOD 0 | 1025 × 1025 | ≤ 8,000 tris | < 50 m |
| LOD 1 | 513 × 513 | ≤ 2,500 tris | < 150 m |
| LOD 2 | 257 × 257 | ≤ 800 tris | < 400 m |
| LOD 3 | 129 × 129 | Billboard impostor | > 400 m |

```
HeightmapGen (standalone Python, Caldera v2 pattern)
  ├─ Cliff escarpment + domain-warp noise + sea stacks + ruin pads
  ├─ pass_coastline() → 5-zone tidal classification
  ├─ apply_coastal_erosion() → drainage gullies on cliff face
  ├─ Hydraulic erosion (cliff-face gullies, 10k+ iterations)
  ├─ Water system (tide pools + surge channel + JONSWAP wave foam)
  ├─ Scatter
  │   ├─ Driftwood logs × 40–80 instances (intertidal + splash zones)
  │   ├─ Wave-worn boulders × 60–120 instances (all tidal zones)
  │   ├─ Eroded rock stacks × 15–25 instances (splash / spray zones)
  │   ├─ Ruin column fragments × 20–40 instances (subtidal + intertidal)
  │   ├─ Kelp / seaweed clumps × 100–200 instances (subtidal + intertidal)
  │   └─ Barnacle clusters × 200–400 instances (intertidal micro-scatter)
  ├─ Atmospheric volumes (sea mist at cliff base, spume at splash, fog in sea cave)
  └─ Unity export (HDRP channels + LOD 0–3 per table above + navmesh + foliage manifest)
```

#### 4.3 Hunyuan3D-2 Props

**Provider path:** HuggingFace Space `tencent/Hunyuan3D-2` via `gradio_client` (free, ~90s/asset queue). Local mode is explicitly blocked by the provider — no VRAM guard needed. Requires `HUGGINGFACE_TOKEN` env var for private spaces. Build script must include `pip install gradio_client` guard.

Use `/generation_all` endpoint for shape + PBR texture in one call. The built-in texture output (Hunyuan3D-2's native PBR) is the primary texture source — no separate CC0 bake step unless the Hunyuan texture quality is rejected during Opus visual review. If CC0 baking is needed as a fallback, use `ambientcg.com/api/v2?id=<material>&method=GET&format=PNG-VAR1` to download matching PBR PNG set, then bake onto UV-unwrapped mesh in Blender headless.

| Prop | Variants | Hunyuan prompt guidance |
|---|---|---|
| `dead_tree_coastal` | 3 | "bleached salt-weathered dead tree, coastal, no leaves, twisted branches, smooth grey bark" |
| `boulder_wave_worn` | 5 | "wave-worn coastal boulder, wet basalt, barnacle patches, tidemark staining, smooth rounded surfaces" |
| `log_driftwood` | 4 | "driftwood log, grey-bleached, waterlogged, coastal beach, kelp draped" |
| `rock_stack_eroded` | 6 | "eroded sea stack, layered sedimentary rock strata, spray-wet, coastal" |
| `ruin_column_fragment` | 3 | "ancient ruin column fragment, worn limestone, algae-stained, half-submerged in water" |
| `kelp_clump` | 4 | "kelp seaweed clump, dark olive green, translucent edges, wet sheen, coastal" |

Each prop: Hunyuan3D-2 `/generation_all` → Blender UV unwrap → LOD chain (decimate modifier: 0.3→ LOD1, 0.1→ LOD2, billboard→ LOD3) → Unity HDRP export.

#### 4.4 Visual Proof Deliverables

**Render safety requirements** (per `2026-05-01-aaa-visual-pipeline-v2-design.md`):
- Build script must implement `_gpu_cycles_available()` with EEVEE NEXT fallback
- Orbit renders: 4 frames max (not 8) at EEVEE NEXT, 16 TAA samples
- Hero/featured renders: 48 spp Cycles OR EEVEE NEXT if GPU unavailable
- Particle / grass count ≤ 3,500 per instance collection
- Implement `_push_renders_to_github()` for artifact delivery (do not rely on CI artifact upload)

All committed to `output/aaa_sunken_coastal_ruins/` and pushed to GitHub:

| File | Content |
|---|---|
| `render_hero.png` | Cliff face with ruins, tide pools, sea mist |
| `render_waterline.png` | Water surface + foam + wet_rock material |
| `render_cave_entrance.png` | Sea cave with atmospheric fog volumes |
| `orbit/orbit_00..03.png` | 4-direction orbit renders (N/E/S/W) |
| `hunyuan_props_proof.png` | Mosaic of all generated props with textures applied |
| `CROSS_SECTIONS.png` | Heightmap + splatmap + water channel visualization |
| `BUILD_SUMMARY.json` | Node metadata, pass results, quality metrics |
| `references/ref_*.png` | 3–5 reference images used for emulation |

#### 4.5 Opus AAA Visual Analysis

Opus agent receives all render outputs and evaluates against:
- KCD2 / TW3 / God of War coastal reference quality bar
- Splatmap correctness (5-zone tidal transitions, no material bleeding)
- Water believability (foam placement, tidemark, wet_rock wetness, JONSWAP wave energy visible)
- Prop integration (scale, weathering coherence, scatter density matches real coastal imagery)
- Silhouette readability (cliff edge, ruin shapes, sea stacks readable against sky)

**Pass criteria:** All 5 dimensions score ≥ B+ before GitHub push is confirmed.

**Re-render fallback:** If any dimension scores below B+, Opus identifies the specific visual failure and the build script is patched to fix it. One re-render iteration is attempted. If the second render still fails, the issue is escalated as a blocking hold for manual review. Maximum 2 re-render iterations before escalation.

---

## Success Criteria

1. All audit items resolved: test suite green, callable census zero
2. All 629 CodeQL alerts adjudicated: each has a FIX entry or an explicit REFUTED with cited evidence
3. `GRADES_VERIFIED.csv` updated with Batch 14 grades
4. `FIX_ORDER_CODEX` has explicit FIXED/REFUTED/ACTIVE status on every item
5. Sunken Coastal Ruins node renders committed to GitHub with Opus AAA pass verdict (≥ B+ on all 5 dimensions)
6. Visual proof of Hunyuan3D-2 props in `hunyuan_props_proof.png`

---

## Constraints

- Sequential Approach A: one phase fully verified before the next starts
- No commits directly to `main` — all work on `codex/aaa-terrain-golden-semantics`
- No pytest in subagents — only primary session runs the test suite and callable census
- Blender 4.5 APIs only
- Hunyuan3D-2 uses HF Space via `gradio_client` (no local server, no VRAM guard). Requires `HUGGINGFACE_TOKEN` env var. `pip install gradio_client` guard in build script.
- Do not commit/push while Codex is verifying (per `feedback_codex_commits.md`)
- All new findings merged into `GRADES_VERIFIED.csv` + master audit doc — no parallel SYNTHESIS files
- Opus checkpoints are static code reviews only — they do not run tests or mutations

---

## File Map

```
docs/aaa-audit/BATCH14_FINDINGS.md                 ← Phase 1 output
docs/aaa-audit/REFUTED_2026_05_02.md               ← Phase 2 output
docs/aaa-audit/ACTIVE_ITEMS_FINAL_2026_05_02.json  ← Phase 2 output
docs/aaa-audit/FIX_ORDER_CODEX_2026_04_27.md       ← Phase 2 updates (Batch 14 appended)
docs/aaa-audit/GRADES_VERIFIED.csv                 ← Phase 2 updates
output/aaa_sunken_coastal_ruins/                   ← Phase 4 output
output/aaa_sunken_coastal_ruins/references/        ← Visual reference images
scripts/build_aaa_sunken_coastal_ruins.py          ← Phase 4 build script
```
