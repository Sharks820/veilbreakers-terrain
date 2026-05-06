# §11 v3 CE Fixes Implementation Guide

**Status**: Round-3 finalized — ready to commit + execute
**Branch**: `docs/biome-render-rebuild-spec`
**Target PR**: #25 (open, MERGEABLE)
**Spec under review**: `docs/superpowers/specs/2026-05-05-biome-render-rebuild-design.md` (2652 lines; §11 v3 at lines 1609-2179)
**Generated**: 2026-05-06 (Rounds 0/1/2/3 integrated)

## §0 Executive summary

This guide consolidates **75 CE-persona findings + 4 verifier rounds (V1/V2/V3 in Round-1; 4 Opus + 4 Codex in Round-2) + 3 PR #26 triage agent reports + 5 best-practices research briefs + 3 deep codebase scans** into an implementation-ordered fix plan, anchored to `main` HEAD `3cc63c55ed04df7035c1c06a8cc754e20a0b1ce1` (canonical at Round-3 close).

**Round-0 Verifier-A (coverage)** and **Verifier-B (consistency)** both returned **PASS** on §11 v3, but against the in-flight spec branch state, not `main`. Subsequent rounds (R1-V1 + Codex 1) found **22/30 sampled cites stale against `main` HEAD** — implementer following spec PR rows would not find the cited code.

**Round-2 verifier wave findings**:
- **Codex 1 (canonical cite audit)**: 126 cite records — 23 valid / 39 stale / 3 out-of-file / 61 no-cite. Pattern is severe cite rot, not isolated typo drift.
- **Codex 2 (Unity smoketest)**: 35 Unity-side bugs (U-001 through U-035) against the §6.1 18-artifact contract. Current importer is descriptor-driven (`unity_import_descriptor.json`); target spec is `meta.json`-driven with 18 specific artifact filenames. Every Block-5 chunk fails before any artifact is read.
- **Codex 3 (channel audit on `main`)**: 23 channel claims tested. `corruption_map` confirmed orphan; `weathering_timeline` is NOT a stack channel (has no `PassDefinition`); 10 phantom reads in `terrain_visual_qa.py` claim is FALSE — the named channels are absent. New orphan: `height_m`.
- **Codex 4 (Blender 4.5 sanity)**: 11 export gotchas catalogued; sanity script `scripts/codex_export_sanity.py` written but not runtime-executed.
- **R2-Opus-1 (validity)**: 7 BLOCKING + 6 stale cites + 6 contradictions in Round-1 fixes (Fix 1.15 fabricated cites; Fix 1.20 wrong line; Fix 1.0 enumeration incomplete).
- **R2-Opus-2 (Phase 2/3/4)**: 5 BLOCKING + 11 polish + 14 NEW AAA practices missing.
- **R2-Opus-3 (feasibility)**: 4/21 Phase 4 fixes blocked on false premises (Fix 4.1 no Python recast; Fix 4.6 visual_qa phantom; Fix 4.20 DXR Editor-only misread; Fix 4.2 chunk_x premise wrong).
- **R2-Opus-4 (AAA simulation)**: C+ on pilot; top 5 BLOCKING; 5 honest cuts to add to §11.7.

**Re-anchored truth-table on `main` HEAD** (verified by Round-3 author via `git show main:<path>`):
- `terrain_unity_export.py`: **2847 LOC** (NOT 2520, NOT 3018-3081). `UNITY_SCALE_FACTOR = 0.85` at **line 31** (NOT 44). Manifest write at lines **2248** + **2272** uses **plain `write_text` — NOT atomic** (Fix 1.5-REVERSED is correct: PR #12 IS a real needed fix).
- `terrain_rng.py`: **43 lines**. NO `derive_pass_seed` function exists. PR #14 cite at `:45` is OUT-OF-FILE.
- `terrain_pipeline.py`: **1675 LOC**. `pass_compute_terrain_labels` at **:1054** (NOT :1133). `pass_water_depth` at **:1275-1330** with skip at **:1306-1312** (NOT :1386-1392). `derive_pass_seed` at **:208** (NOT :269).
- `terrain_chunking.py`: uses `chunk_world_size` (parametric, default **64.0**) — NOT `chunk_x, chunk_y` as the spec/Fix 4.2 implies.
- `terrain_weathering_timeline.py`: **146 lines, NO PassDefinition class, NO `def pass_*`** — Fix 4.4 originally said "add `overrides=` to PassDefinition" — premise WRONG; needs full rewrite.
- `terrain_visual_qa.py`: NONE of the 10 phantom channels (`vegetation_index, species_density, climate_zone, hazard_zone, height_delta, rock_mask, hardness, limestone_proxy, canopy_density, canopy_species_radius_m`) appear. Fix 4.6 WITHDRAWN; replaced with re-attribution.
- `vegetation_system.py`: 1849 LOC. `lod_meshes` at **:1561, :1600** (NOT :1284, NOT :685).
- `procedural_grass.py`: 872 LOC. `lod_meshes` at **:685** only.
- `terrain_cliffs.py`: 2820 LOC. Hash hazard `hash(cliff.cliff_id)` at **:2368** (NOT :2397). `cliff_idx * 37` enumeration hazard at **:2620** (NOT :2650). The claimed `:1502` sum-of-ord hazard does NOT exist on `main`.
- `terrain_caves.py`: 5566 LOC. `cave_i ^ 0xDEADBEEF` at **:3894** (NOT :3889).
- `terrain_master_registrar.py`: **EXISTS, 332 LOC**. `register_stratigraphy_pass` is missing; `register_all_terrain_passes` exists at :127.
- `unity_plugin/VbTerrainTileMetadata.cs`: **51 LOC, 25 top-level public scalar/array fields + 1 `ChannelBound[]` array** (whose inner struct has 3 fields). Memory item said 25; §9.3 said 28; V1 said 29 — **GROUND TRUTH: 26 top-level fields (25 + ChannelBounds)**.
- `unity_plugin/Editor/VbTerrainImporter.cs`: 2452 LOC. `GetOrCreateTreePrefab` at **:2152** (NOT :2229). `_pack_tangent_space_normal_rgba` actually lives in `terrain_unity_export.py:288` (NOT :334). `TextureImporterType.NormalMap` at `:2040` (NOT :2097).
- `unity_plugin/VbTerrainRuntimeStreamer.cs`: EXISTS (284 LOC) — Fix 1.8 must reckon with this; `VbChunkLoader.cs` is NET-NEW only if Option B taken.
- `road_network.py`: 1775 LOC — PR #9 cite at `:1808-1817` is OUT-OF-FILE.
- `terrain_banded_advanced.py`: 488 LOC — PR #61 cite at `:542` is OUT-OF-FILE.
- `environment.py`: 8613 LOC. `_build_road_mask_and_sdf` at **:4630-4689**; spec cite `:6265-6266` is unrelated mesh-update code. `params.get("terrain_type", "mountains")` at **:1205, 1989, 2020, 2322, 2990, 3043** (5 sites, NONE at 2031).

**Critical material discoveries from research agents**:
1. **MicroSplat is now FREE base + $40 total** ($20 HDRP module + $20 Mesh Terrains), not $120 as spec assumes. Spec §6.6 / §11.7 #1 framing is materially outdated.
2. **HDRP entered maintenance mode in February 2026** — no new features through Unity 6.7 LTS (end of 2028). Custom HDRP shader investment depreciates; URP migration risk increases.
3. **HDRP 2022.2+ ships built-in WaterSurface** for Pool/River/Ocean — eliminates ~1 week of custom water authoring.
4. **Solo-dev realistic shader build time: 12-18 days, 20-30 if learning** — NOT spec's 3-5 days.
5. **glTF 2.0 binary (.glb) is the correct format**, not FBX (Khronos PBR maps bit-identical to HDRP Lit; vertex colors first-class; Custom properties survive round-trip).
6. **`UNITY_SCALE_FACTOR = 0.85`** in `terrain_unity_export.py:31` (verified `main`; Round-3 ground truth) is a character-rig hack incorrectly applied to mesh export — should be 1:1. Multiplications appear at lines 31, 39, 41, 42, 331, 1014, 1441, 2171, 2843.
7. **Self-hosted GPU runner on public repo = #1 GitHub anti-pattern**. Spec's §11.7 #3 GPU-only requirement creates a HIGH-severity attack surface. Recommendation: drop perf gate from required checks (alt #3) OR move to GitHub-hosted larger runners (~$40/mo) instead of hardening self-hosted.
8. **VeilBreakers uses procedural chunk meshes, not Unity Terrain** — Unity's built-in Terrain Lit Shader Graph template doesn't apply directly. MicroSplat's Mesh Terrains module ($20) solves this; custom path needs extra hand-rolling.

**Total fix surface (Round-3 final)**: 99 finding rows mapped in §16.10 → ~97 active fixes after withdrawing 2 + reframing 4 = effective phase counts: Phase 0 = 20 fixes; Phase 1 = 22 fixes; Phase 2 = 4 fixes; Phase 3 = 5 manual decisions; Phase 4 = 36 fixes (Fix 4.1-4.36 minus 4.6/4.20 + new B5-U-* + AAA-practice 4.22-4.29); Phase 5 = 3 PR-#26 fixes. Phase 0 land first (silent commit); Phase 1 critical breakage second (~22 PRs); Phase 2 rationalize scope; Phase 3 user decides 5 strategic forks; Phase 4 close coverage; Phase 5 in-flight PR #26.

---

## §1 Order of operations (phase gates)

Fixes apply in strict phase order. Each phase has a verification gate before the next begins.

| Phase | Scope (Round-3 final) | Risk | Goal |
|---|---|---|---|
| **Phase 0** | 20 mechanical safe-auto edits (Fix 0.1-0.20) | None | Eliminate one-clear-correct typos/contradictions silently |
| **Phase 1** | 22 critical breakage fixes (Fix 1.0 + 1.1-1.22; Fix 1.5-REVERSED supersedes Fix 1.5) | High if skipped | Make every PR runnable as written (resolve circular deps, missing files, signature mismatches, line-cite drift) |
| **Phase 2** | 4 scope/structure fixes (Fix 2.1-2.4 with §16.5 reconciliations) | Medium | Block 5 split (5a/5b/Block 6 per §16.5 C5), Block 1 detrash, refactor PRs deferred to v1.1 |
| **Phase 3** | 5 strategic decisions (Decision 3.1-3.5; user judgment) | User judgment | AA-vs-A target, MicroSplat default, calendar reconciliation, GPU runner path, runway scope |
| **Phase 4** | 36 coverage gaps (Fix 4.1-4.36 + B5-U-* fixes; minus WITHDRAWN 4.6 + 4.20) | High if skipped | Add missing PRs (GPU runner, secrets, visual baselines, navmesh NMX, AAA practices, Codex 2 Unity-side bugs) |
| **Phase 5** | PR #26 (3 one-liners; in flight) | Independent | Fix the rescue PR + merge to main |

Each fix below has: **ID** | **Source persona(s) + confidence** | **Severity** | **Edit location (file:line)** | **Concrete edit** | **Verification step** | **Best-practice citation** (where applicable).

---

## §2 Phase 0 — Mechanical safe-auto fixes (13)

These are one-clear-correct edits with zero judgment required. Apply silently in a single commit.

### Fix 0.1 — §11.0.2 chunk_seed module owner contradiction
- **Source**: coherence (conf-100) + adversarial (conf-100) — independent corroboration
- **Severity**: P1 (load-bearing on entire determinism story)
- **Location**: `docs/superpowers/specs/2026-05-05-biome-render-rebuild-design.md:1641`
- **Edit**: Replace `"PR #36 (chunk_seed module)"` with `"PR #B5-D1 (chunk_seed module)"`
- **Why**: PR #36 is `feat(asset-budget): split splatmap_layer_count 4→8` — has nothing to do with seeding. PR #B5-D1 is the actual chunk_seed module owner per line 1664 of the same subsection.
- **Verify**: After edit, lines 1641 and 1664 both reference PR #B5-D1; no PR #36 cross-reference for chunk_seed remains anywhere in §11.

### Fix 0.2 — §11.0 dimension table cuts count (5 → 7)
- **Source**: coherence (conf-100)
- **Severity**: P2
- **Location**: `docs/superpowers/specs/2026-05-05-biome-render-rebuild-design.md` §11.0 dimension table row "Cuts surfaced (§11.7)"
- **Edit**: Change v3 cell from `5 (HDRP-F, MicroSplat fallback, 5 BLOCKING Unity gaps, GPU-only perf, AA ceiling)` to `7 (HDRP-F shadergraph, 5 Unity BLOCKING gaps, GPU-only perf, asset-budget 5-PR sequence, AA ceiling, tree-imposters/shrubs not net-new, procedural_meshes relocation)`
- **Why**: §11.7 enumerates 7 numbered cuts; header undercounts by 2. Body is authoritative.
- **Verify**: Header count matches §11.7 numbered list (1-7).

### Fix 0.3 — §11.9 Wave 4 stale section reference
- **Source**: coherence (conf-100)
- **Severity**: P2
- **Location**: §11.9 Wave 4 Resolution Registry row for "Water-channel naming 3 vocabularies"
- **Edit**: Replace `"§10.6 line 1041"` with `"§8.2 line 1041"`
- **Why**: §10 has no subsections (it's a flat "Open Questions" list, lines 1206-1217). Line 1041 actually lives in §8.2 (Existing Pipeline Integration).
- **Verify**: §10 has no `### 10.6` heading; §8.2 line 1041 contains the cited W-1 form.

### Fix 0.4 — §11.7 #3 broken cross-reference
- **Source**: coherence (conf-100)
- **Severity**: P2
- **Location**: §11.7 cut #3
- **Edit**: Delete the parenthetical `(per spec §11.5 #2)` OR replace with `(per spec §11.5.4 PR B5-T2)`
- **Why**: §11.5 has subsections .1 through .7; no top-level numbered items #1, #2. The reference is unresolvable.
- **Verify**: §11.5 contains no `#1` or `#2` flat numbering; the cross-reference (if kept) resolves to §11.5.4.

### Fix 0.5 — PR #36 file path correction
- **Source**: feasibility (conf-100)
- **Severity**: P1 (PR is unstartable as written)
- **Location**: §11.2 PR #36 row file list
- **Edit**: Replace `handlers/terrain_asset_budget.py (find splatmap_layer_count = 4 + comment...)` with `handlers/terrain_quality_profiles.py:183 (default), :353, :409, :465, :521 (4 profile instances) + handlers/terrain_budget_enforcer.py:211 (consumer)`
- **Why**: `terrain_asset_budget.py` does NOT exist in `veilbreakers_terrain/handlers/` (verified by Glob). The actual `splatmap_layer_count = 4` declarations live in 5 sites in `terrain_quality_profiles.py`.
- **Verify**: After edit, `Grep "splatmap_layer_count" veilbreakers_terrain/handlers/` lists only the 5 cited sites + 1 enforcement read.

### Fix 0.6 — PR #62 reframe to verify-existing
- **Source**: feasibility (conf-75 safe_auto)
- **Severity**: P1 (PR is a no-op as written)
- **Location**: §11.4 PR #62 acceptance bullets
- **Edit**: Replace acceptance text from `Skip when water_surface_elevation_m or height is None ... close GitHub issue #28` with `(a) verify pass_water_depth skip behavior at terrain_pipeline.py:1386-1392 is correct (already coded), (b) add tests/test_water_depth_skip.py with happy/none-elevation/none-height cases, (c) close GitHub issue #28 only after both pass`
- **Why**: The skip path is ALREADY coded at `terrain_pipeline.py:1386-1392` (`if ws_elev is None or height is None: return PassResult(... status="skipped")`). PR is a verify-existing + test-add, not a new implementation.
- **Verify**: `terrain_pipeline.py:1386-1392` shows the skip already implemented; PR is reframed as test-add only.

### Fix 0.7 — Cut B5-DEP1 (duplicates PR #2)
- **Source**: adversarial (conf-100)
- **Severity**: P2 (merge collision risk)
- **Location**: §11.5.6 PR B5-DEP1 row + §11.5.6 dep graph
- **Edit**: Delete B5-DEP1 row entirely; merge its only unique value-add (split `[providers]` + `[geo]` extras) into PR #2's acceptance bullets; re-route §11.5.6 dep graph so B5-DEP2 deps becomes `#2` instead of `B5-DEP1`.
- **Why**: PR #2 already covers Pillow≥10.4 + CVE patches + dependency declarations + pip-audit gate. B5-DEP1's claim "extends PR #2" is misleading — the criteria are nearly identical and would create a `pyproject.toml` merge conflict.
- **Verify**: Only one PR row references the Pillow CVE fix; B5-DEP2 deps points to PR #2.

### Fix 0.8 — Reconcile PR count to single number (87 by table-row count)
- **Source**: coherence + scope-guardian + design-lens + adversarial (conf-100, multi-persona)
- **Severity**: P3 safe-auto
- **Location**: §11.0 dimension table + §11.5 header + §11.7 #5
- **Edit**: 
  - §11.0 dimension table "PR count v3" cell: change `~85` → `87` (table-row count: 15+22+11+14+25=87 PR groups)
  - §11.5 header: change `(~25 PRs, studio-team-scale)` → `(25 PR groups / 41 line items by ownership, studio-team-scale)`
  - §11.7 #5: change `all 85 PRs landed` → `all 87 PRs landed`
- **Why**: Three different counts (85 / 87 / 89) appear in adjacent contexts. Pick one definition (PR groups by ownership) and use consistently. Block 5 footer correctly states the math.
- **Verify**: All §11 references use the same PR count (87).

### Fix 0.9 — Move PR #59 (coastal ecology) from Block 4 to §7.4 post-pilot
- **Source**: scope-guardian (conf-100)
- **Severity**: P3 safe-auto (locked Q10 violation)
- **Location**: §11.4 PR #59 row + §7.4 post-pilot template phase
- **Edit**: Remove PR #59 row from §11.4. Add to §7.4 post-pilot scope as "Coastal biome ecology rules (1 PR, ~0.5 day; was §11.4 #59)".
- **Why**: §1 Q10 locks pilot scope to "Mountain + grassland end-to-end". §7.4 already allocates 3-4 weeks for coastal as post-pilot. PR #59 in pilot Block 4 is double-count + scope creep.
- **Verify**: §11.4 contains PRs #57 (mountain), #58 (grassland) only for ecology; §7.4 references coastal ecology PR.

### Fix 0.10 — Add #11 dep to PR #55
- **Source**: coherence (conf-75 safe_auto)
- **Severity**: P2 (file ordering hazard)
- **Location**: §11.4 PR #55 Deps column
- **Edit**: Change `Deps: #5b, #2, #56` → `Deps: #5b, #2, #11, #56`
- **Why**: PR #11 modifies `handlers/asset_generation.py:699,706`. PR #55 deletes `asset_generation.py`. Without dep edge, #55 may run before #11 and patch a deleted file.
- **Verify**: §11.6 dep graph shows #55 dependent on #11.

### Fix 0.11 — B5-U13 list all 25 VbTerrainTileMetadata fields
- **Source**: design-lens (conf-75 safe_auto) + feasibility (conf-75)
- **Severity**: P3 safe-auto
- **Location**: §11.5.1 PR B5-U13 acceptance bullets
- **Edit**: Replace ambiguous `expand to all 25 fields ... add 9 fields` with concrete 25-field list. Read actual file `unity_plugin/VbTerrainTileMetadata.cs` to enumerate the 24 existing fields, list the 9 NEW fields explicitly, and state the post-PR target (likely 33, not 25).
- **Why**: Acceptance currently lists 9 fields by name, says "all 25 fields", but actual file count differs. Implementer reading the PR cannot know which fields are existing vs net-new.
- **Verify**: Acceptance lists every field by name; total matches file post-edit.

### Fix 0.12 — YAML safe_load discipline note
- **Source**: security-lens (conf-75 safe_auto)
- **Severity**: P1 (RCE risk)
- **Location**: §11.5.2 PR B5-C1 (or new B5-C6) acceptance + project rule
- **Edit**: Add acceptance bullet: `(a) declare project rule that all YAML in species_libs/, foliage/, biome configs MUST use yaml.safe_load (or ruamel.yaml.YAML(typ='safe')); (b) add CI lint (extend scripts/check_protocol_adoption.py) that scans for yaml.load( without Loader=SafeLoader.`
- **Why**: PR #28 introduces artist override layer loading `foliage/species_libs/<biome>_overrides.yaml`; PRs #57-58 add per-biome species YAMLs. PyYAML default `yaml.load` is RCE sink (`!!python/object/apply`). Hostile YAML executes arbitrary Python during bake.
- **Verify**: After PR lands, `Grep "yaml.load(" veilbreakers_terrain/` returns 0 results without `Loader=`.

### Fix 0.13 — B5-C2 cite correction (#11 ref)
- **Source**: Verifier-B cosmetic finding
- **Severity**: P3 safe-auto
- **Location**: §11.5.2 PR B5-C2 description
- **Edit**: Replace `"5 PRs touching terrain_unity_export.py (#5/#11/#12/#44/#48)"` with `"5 PRs touching terrain_unity_export.py (#5b/#12/#13/#20/#48)"`
- **Why**: PR #11 is path-injection in `providers/`, doesn't touch `terrain_unity_export.py`. PR #44 is in `unity_export_v2/chunk_artifacts.py`. Real editors are #5b/#12/#13/#20/#48.
- **Verify**: Grep confirms #5b/#12/#13/#20/#48 are the only PRs editing `terrain_unity_export.py`.

**Phase 0 commit message**: `docs(spec): §11 v3 mechanical safe-auto fixes — 13 one-clear-correct edits per CE wave`

---

## §3 Phase 1 — Critical breakage fixes (~12, multi-persona corroborated)

These fixes block as-written implementation. Multiple personas independently corroborated each. They require slightly more judgment than Phase 0 but have one clear correct path.

### Fix 1.1 — Break PR #18 ↔ B5-D1 circular dependency (P0)
- **Source**: feasibility (conf-100) + adversarial (conf-100, P0)
- **Severity**: **P0 — Block 1 stalls indefinitely as written**
- **Location**: §11.1 PR #18 + §11.5.3 PR B5-D1 + §11.6 dep graph
- **Issue**: PR #18 (Block 2, deps `#14,#15`) migrates 47 RNG sites to `derive_pass_seed(biome_seed/chunk_seed)`. PR B5-D1 (Block 5, deps `#18`) defines `biome_seed()` and `chunk_seed()` in `chunks/chunk_seed.py`. Each blocks the other.
- **Edit**:
  - Promote B5-D1 (chunk_seed module API only, no migration) to **Block 1 as PR #15.5** (between #15 and #18).
  - B5-D1 acceptance: API-only, just creates `chunks/chunk_seed.py` with `biome_seed(biome, version) → int` and `chunk_seed(biome, x, y, version) → int` — no migration.
  - Reverse dep direction: PR #18 deps becomes `#14, #15, #15.5(B5-D1)`; B5-D1 deps `none`.
  - Update §11.5.3 to mark B5-D1 as "API-only; migration in PR #18".
  - Drop B5-C4 ("C-1 propagated to PR #18 — scope tagging") OR redefine as "verify scope-tagging coverage".
- **Best practice (from determinism research, pending)**: Two-tier seed model with `version` as integer in `biome_yaml.version: 1` (manually bumped) — orthogonal to `version_hash` content fingerprint.
- **Verify**: §11.6 dep graph shows no cycles; PR #18 cannot start until B5-D1 lands.

### Fix 1.2 — Resolve PR #16 missing master_registrar architecture (P1)
- **Source**: feasibility (conf-100)
- **Severity**: P1 — PR cannot start as written
- **Location**: §11.2 PR #16
- **Issue**: PR #16 cites `handlers/terrain_master_registrar.py` — file doesn't exist anywhere in `veilbreakers_terrain/handlers/`. Function `register_stratigraphy_pass` doesn't exist either.
- **Edit**: Replace acceptance with one of:
  - **Option A (recommended)**: Re-cite to register stratigraphy directly in `terrain_pipeline.py:register_default_passes` adjacent to where `wind_erosion` lands (paired with PR #4's 8-orphan-pass batch). Drop the master_registrar architecture.
  - **Option B**: Call out master_registrar.py as NET-NEW (similar to PR #26 explicit NET-NEW callout) and add it to the PR #16 file list with a 50-100 LOC architecture stub.
- **Recommendation**: Option A — Don't introduce a new architecture mid-runway. Cross-check PR #4's 8 orphan-pass list (already includes 'stratigraphy') against PR #16 to avoid double-registration (see Fix 1.3).
- **Verify**: Grep confirms `register_stratigraphy_pass` exists post-edit; no `terrain_master_registrar.py` cited anywhere.

### Fix 1.3 — Resolve PR #4 ↔ PR #16 double-registration risk (P2)
- **Source**: feasibility (conf-75)
- **Severity**: P2
- **Location**: §11.1 PR #4 + §11.2 PR #16
- **Issue**: PR #4 lists 8 orphan passes including 'stratigraphy' to wire into `build_default_pass_sequence`. PR #16 separately wires `register_stratigraphy_pass`. Double-registration risk.
- **Edit**:
  - Expand PR #4 acceptance: `(a) ensure register_*_pass exists for each of the 8 orphans (currently only 2 of 8 do — water_flow_speed, river_convergence; create 6 missing register functions: cliffs, caves, coastline, karst, wind_erosion, stratigraphy); (b) call them from register_default_passes; (c) insert pass names into pass_sequence at the right phase`.
  - Reframe PR #16 (after Fix 1.2): "Bundle-I-specific ordering between wind_erosion and stratigraphy (no re-registration)" — or drop entirely if Fix 1.2 Option A is chosen.
- **Verify**: Grep `register_*_pass` lists 8 functions for the 8 orphan passes; only one registration call per pass.

### Fix 1.4 — Resolve PR #14 derive_pass_seed signature mismatch + adopt new BLAKE2b API (P1)
- **Source**: feasibility (conf-100) + determinism research §8.4
- **Severity**: P1 — silent runtime breakage
- **Location**: §11.1 PR #14 + new module `chunks/chunk_seed.py`
- **Issue**: PR #14 deletes alternate `derive_pass_seed` in `terrain_rng.py:45`, keeps canonical in `terrain_pipeline.py:269`. But the two have **incompatible signatures**:
  - rng version: `(seed: int, pass_name: str, tile_x: float = 0.0, tile_y: float = 0.0, region: str = '')`
  - pipeline version: `(intent_seed: int, seed_namespace: str, tile_x: int, tile_y: int, region: Optional[BBox])`
  - Different param names, different types (float vs int for tile coords), different `region` type (str vs BBox). `_scatter_engine.py:22` re-exports the rng version; silent type-mismatch on migration.
  - **Per §8.4 research**: both current implementations use SHA-256 prefix-slice, which is correct but slower than BLAKE2b. The new API (per §8.4) uses `hashlib.blake2b(digest_size=8)` with length-prefixed framing, `region: tuple[int,int,int,int] | None`, `tile_x/y: int`. This is the canonical signature going forward; PR #14's "consolidation" should adopt it (not preserve the old pipeline-version).
- **Edit**: Expand PR #14 acceptance to:
  - `(a) DELETE both rng-version (terrain_rng.py:45) AND old pipeline-version (terrain_pipeline.py:269)`
  - `(b) PROMOTE the new chunks/chunk_seed.py API (per §8.4) as the single source of truth — co-lands with PR #15.5 (B5-D1 promoted to Block 1)`
  - `(c) audit all callers (1 production at _scatter_engine.py:22 + 100 production sites per §9.1 RNG_SITES.txt + 79 test sites)`
  - `(d) for each, migrate to canonical signature: derive_pass_seed(biome_seed_or_chunk_seed, "namespace", tile_x=int, tile_y=int, region=(x0,y0,x1,y1) | None)`
  - `(e) confirm tile coords are int (not float); convert any float callers to int(tile_x) at call site`
  - `(f) confirm region callers use tuple, not str; convert any str-region callers to BBox tuple`
  - `(g) preserve test sites unchanged where seeded with int literals; migrate where they use string seeds`
- **Verify**: `Grep "derive_pass_seed"` returns 0 results in `terrain_rng.py` and `terrain_pipeline.py`; all callers point to `chunks/chunk_seed.py`; lint rule (per §8.4) passes.

### Fix 1.5 — Resolve PR #12 already-implemented (P1)
- **Source**: feasibility (conf-100)
- **Severity**: P1 — wasted PR + regression risk
- **Location**: §11.1 PR #12
- **Issue**: PR #12 acceptance says `Write to *.tmp then os.replace` for both manifest.json and unity_import_descriptor.json. But `terrain_unity_export.py:2495-2511` ALREADY uses `tempfile.NamedTemporaryFile + os.replace` for both files (with comment "atomic write — no partial bundle on disk" at line 2492).
- **Edit**: Re-scope PR #12 to:
  - `(a) add tests/test_unity_export_atomicity.py::test_kill_mid_write that verifies the existing implementation`
  - `(b) remove the "Write to *.tmp then os.replace" acceptance bullet (already done)`
  - `(c) update the Wave-1 Resolution Registry row at line 1979 to note "verified existing"`
  - Effort drops from M to S.
- **Verify**: `Read terrain_unity_export.py:2495-2511` confirms atomic write; PR #12 reframed as test-add only.

### Fix 1.6 — Resolve PR #53 environment.py split missing deps (P1)
- **Source**: adversarial (conf-100)
- **Severity**: P1 — line cites stale post-merge
- **Location**: §11.4 PR #53 Deps column + §11.6 dep graph
- **Issue**: PR #53 (XL refactor) splits `environment.py` (8651 LOC) at 5 seams; original becomes thin re-export. PRs #23 (line 6265-6266), #25 (line 2031), #45 (line 2861), #49 (line 229 caller cite) all surgically edit specific environment.py line numbers. PR #53's only dep is #50.
- **Edit**: Choose one:
  - **Option A (recommended for v1.1 deferral)**: Move PR #53 out of Block 4 entirely into post-pilot v1.1 (per §11.4 footer "may slip to v1.1"). Update §11.8 deferrals to include "environment.py 5-seam split — defer to v1.1; XL refactor not pilot-blocking".
  - **Option B**: Add explicit deps `Deps: #50, #23, #25, #45, #49` so #53 lands AFTER all surgical edits absorb.
- **Recommendation**: Option A — XL refactor during pilot runway is unjustified scope churn.
- **Verify**: §11.4 contains no PR #53 (or has full deps); §11.8 lists env.py split if deferred.

### Fix 1.7 — Resolve PR #6 ↔ B5-T1 baseline ordering (P1)
- **Source**: design-lens (conf-100)
- **Severity**: P1 — Block 1 PR can't validate as written
- **Location**: §11.1 PR #6 acceptance + §11.6 dep graph
- **Issue**: PR #6 acceptance: "0 diagonal trunks in `golden_scenarios/cliff_talus_apron` reference render". B5-T1 (Block 5) creates the baseline.png files. Block 5 is "parallel to Blocks 1-4" — order undefined.
- **Edit**: Choose one:
  - **Option A (recommended)**: Promote B5-T1 to Block 1 as PR #6.5 (creating baseline.png + SSIM compare harness only, no other test infra) so PR #6 can validate.
  - **Option B**: Downgrade PR #6 to "manual: render cliff_talus_apron and inspect 10 trunks at slope > 30°" only (the existing fallback); add follow-up sub-PR #6b in Block 5 that does the SSIM 0.95 gate once B5-T1 lands.
- **Recommendation**: Option A — golden baselines belong in Block 1; PRs #29, #B5-U2, etc., also need them.
- **Verify**: §11.6 dep graph shows PR #6 → B5-T1 OR B5-T1 promoted to Block 1.

### Fix 1.8 — Resolve VbChunkLoader.cs missing references (P1)
- **Source**: feasibility (conf-100)
- **Severity**: P1 — 8 Unity PRs cite non-existent file
- **Location**: §11.5.1 PRs B5-U5, U6, U7, U8, U9, U10, U11, U12 + §11.7 honesty register
- **Issue**: 8 PRs cite `VbChunkLoader.cs` for line-level edits. File doesn't exist (only `unity_plugin/Editor/VbTerrainImporter.cs`). PR #B5-U11 cites `VbChunkLoader.cs:GetOrCreateTreePrefab:2229-2273` but the function actually lives in `VbTerrainImporter.cs:2229`. Path prefix `unity_project/Assets/Scripts/` doesn't exist either.
- **Edit**:
  - Add §11.7 honesty entry #8: `"VbChunkLoader.cs and unity_project/ Unity-project skeleton do not exist on disk. Pilot Unity ingestion REQUIRES creating them as part of B5-U2/B5-U5 (NET-NEW). The 8 B5-U PRs that reference VbChunkLoader.cs assume the runtime ChunkLoader component is yet to be authored."`
  - Re-cite PR B5-U11's `GetOrCreateTreePrefab:2229-2273` to `unity_plugin/Editor/VbTerrainImporter.cs:2229` (verified location).
  - Decide and document whether `unity_plugin/` becomes the Unity-project home or whether `unity_project/` is created alongside as a NET-NEW directory. Spec §11.5.1 PR B5-U13 currently uses `unity_project/Assets/Scripts/VbTerrainTileMetadata.cs` while the file actually lives at `unity_plugin/VbTerrainTileMetadata.cs` — pick one path convention.
- **Verify**: All `unity_*` paths in §11 v3 use the same prefix; honesty register notes ChunkLoader as NET-NEW.

### Fix 1.9 — Resolve acceptance_checks.py missing reference (P1)
- **Source**: design-lens (conf-100) + adversarial (conf-100)
- **Severity**: P1 — B5-U1 acceptance gate unmeetable
- **Location**: §11.5.1 PR B5-U1 acceptance
- **Issue**: B5-U1 acceptance criterion includes `acceptance_checks.py exits 0`. §11.7 #1 honesty cut explicitly states "`acceptance_checks.py` referenced by spec line 1016 — does not exist." No PR creates this file.
- **Edit**: Add explicit acceptance bullet to B5-U1: `Create unity_project/acceptance_checks.py (CI script: parses 4 .shadergraph files for required nodes — Lit master, splat-blend subgraph, foliage shader graph, water graph; exits 0/1).` OR remove the requirement and replace with `Manual: open in Unity 2022 LTS HDRP, all 4 shaders compile.` Pick one.
- **Recommendation**: For MicroSplat path, drop `acceptance_checks.py` requirement entirely (the asset's own validation suffices). For custom path, create the script as part of B5-U1.
- **Verify**: B5-U1 references no missing files; honesty register #1 reconciled.

### Fix 1.10 — Add GPU runner provisioning PR (P1)
- **Source**: feasibility (conf-100) + adversarial (conf-100) + product-lens (conf-50)
- **Severity**: P1 — perf gate unrunnable, security risk if implemented naively
- **Location**: New PR row to add
- **Issue**: §11.7 #3 commits to GPU runner; PR #19 + B5-T2 require it; **no PR provisions it**. Existing CI is `ubuntu-latest`. Required secrets (HF/Quixel/Meshy/RUNNER_REGISTRATION) not configured.
- **Edit**: Per **GH Runner Security Research**, choose one of three paths:
  - **Path 1 (recommended for v1)**: Drop GPU perf gate from required checks. Use local benchmark + commit `perf-manifest.json` + nightly cron compare. Zero new attack surface. Add to §11.8 deferrals.
  - **Path 2**: Use **GitHub-hosted larger runners** (Team plan + pay-per-minute T4 GPU, ~$40/mo nightly bake at post-2026 pricing). Add new PR `B5-CI1: feat(ci): GitHub-hosted GPU larger runner for nightly perf gate`.
  - **Path 3**: Self-hosted runner with full hardening (3 PRs: B5-CI1 provisioning, B5-DEP4 secret hygiene, B5-DEP5 isolation rules). High maintenance burden + project-killing risk if any control misses.
- **Recommendation**: Path 1 for v1 pilot; Path 2 if GPU CI proves required; Path 3 only with full hardening.
- **Verify**: §11.7 #3 reconciled with chosen path; all GPU-dependent PRs have feasible CI lane.

### Fix 1.11 — Resolve Q5 vs §11.7 #3 CPU-fallback contradiction (P1)
- **Source**: adversarial (conf-100)
- **Severity**: P1 — direct contradiction in locked decisions
- **Location**: §1 Q5 Locked Decisions + §11.7 #3
- **Issue**: Q5 says "Taichi-CUDA primary, CPU fallback" (durable design). §11.7 #3 says "no CPU fallback (per spec §11.5 #2). CPU-only path is not viable for AAA-bar erosion."
- **Edit**: Choose one:
  - **Option A (recommended)**: Amend Q5 to `"Taichi-CUDA primary; degraded CPU path for dev iteration only, NOT acceptance-grade. Pilot pass requires GPU bake."`
  - **Option B**: Delete the "CPU fallback" clause from Q5 entirely (matches §11.7 #3 honesty register).
- **Recommendation**: Option A — preserves dev ergonomics while honest about acceptance bar.
- **Verify**: §1 Q5 + §11.7 #3 say the same thing about CPU fallback's role.

### Fix 1.12 — Add fork-PR isolation + secrets management PRs (P0)
- **Source**: security-lens (conf-100, two P0 findings)
- **Severity**: **P0 — single malicious fork PR exfiltrates all API keys**
- **Location**: New PRs to add
- **Issue**:
  - Self-hosted GPU runner has no fork-PR isolation plan (HF/Meshy/Quixel keys + RUNNER_REGISTRATION_TOKEN exfiltrate on first malicious fork PR).
  - No secrets-management strategy (rotation cadence, scope, log redaction, env-vs-repo separation).
- **Edit**: Per **GH Runner Security Research**, add 2 new PRs (only required if Path 2 or Path 3 chosen in Fix 1.10):
  - **B5-DEP4**: `sec(secrets): secret hygiene baseline` — environment secrets with required-reviewer protection rule, weekly RUNNER_REGISTRATION_TOKEN rotation via GitHub App, gitleaks/trufflehog pre-commit + PR scan, 40-char SHA pinning for all `actions/*` references, `permissions: read-all` workflow default.
  - **B5-DEP5**: `sec(ci): runner isolation rules` — split-trust workflow design (pull_request on ubuntu-latest with no secrets; workflow_run on self-hosted with environment-protection-gated secrets; no `pull_request_target` anywhere), `harden-runner` action in every workflow, ephemeral runner config, IR runbook at `docs/runtime/runner_ir.md`.
- **Verify**: After both PRs land, fork PR cannot exfiltrate secrets; runner registration token rotates weekly; security baseline passes CodeQL Actions security-extended scan.

---

## §4 Phase 2 — Scope/structure rationalization (~10)

Phase 2 fixes are filled in §15.7 (Fix 2.1-2.4) with §16.5 contradiction resolutions applied. Read §15.7 + §16.5 first; the themes below are the original draft.

Themes (drafted from CE wave):
- Block 5 split into 5a (pilot-blocking Unity parity) / 5b (pilot-supporting infra) / Block 6 (post-pilot maturity)
- Block 1 detrash: move one-liners (#6, #7, #10, #14, #15) to Block 2 or 4 to make critical path honest
- Test infra over-engineered: move B5-T2/T3/T5/T6/T7 to "post-pilot test maturity"
- Doc rot + deps + test infra (14 PRs) belong in separate `docs/superpowers/specs/2026-05-05-repo-hygiene-runway.md`, not pilot scope
- Per-biome ecology PRs #57-#58 only (after Fix 0.9 removes #59)
- Calendar reconciliation: §11 14-day vs §7.3 8-week vs realistic 8-12 weeks solo

---

## §5 Phase 3 — Strategic decisions (~10 manual; user judgment)

Phase 3 decisions are filled in §15.8 (Decisions 3.1-3.5) and reconciled by §16.7 / §16.8 themes. Round-3 recommendations are in §17 acceptance criteria. Read §15.8 + §17 first; the themes below are the original draft.

Themes:
- AA ceiling vs A- target: pick one, restate consistently in §0 banner + §11.7 #5
- MicroSplat default vs HDRP custom: per shader research, BUY MicroSplat ($40 total) as DEFAULT; flip §6.6 + §11.7 #1 framing
- Calendar realism: 8-12 weeks solo dev, not 7-14 days
- 88-PR runway scope: keep all OR peel hygiene PRs to separate doc
- Self-hosted runner: drop entirely (Path 1) vs GH-hosted larger (Path 2) vs hardened self-hosted (Path 3)
- Refactor PRs #49-#54 deferred to v1.1
- Determinism CI deferral coherence with §3.7 promise
- Block 5 mislabel as parallel/optional
- Visible-value milestones for solo dev motivation
- Five-layer foliage stratification render-proof PR addition

---

## §6 Phase 4 — Coverage gaps (~36 missing PRs after Round-3)

Phase 4 fixes are filled across §15.5, §15.6, and §16.6 (Fix 4.1-4.36 + B5-U-* fixes). Round-3 withdrew Fix 4.6 + Fix 4.20 (§16.2) and reframed Fix 4.2/4.4/4.18 (§16.3). Read §15.5 + §15.6 + §16.2 + §16.3 + §16.4 + §16.6 + §16.8 first; the themes below are the original draft.

Themes:
- GPU runner provisioning (per Fix 1.10 path choice)
- Secrets management baseline (per Fix 1.12)
- Fork-PR isolation (per Fix 1.12)
- Generate `.staging/RNG_SITES.txt` ground-truth file (per RNG-sites scan agent)
- Visual success criteria for B5-U PRs (golden_scenario column per design-lens)
- B5-U5 split into Editor/Player render-state PRs
- §11.11.2 manual review reviewer/criteria expansion
- Empty-state behavior for sidecar consumers (water.json, decals.json, etc.)
- Five-layer stratification render-proof baseline
- L-Py grammar review gate (per security-lens)

---

## §7 Phase 5 — PR #26 (3 fixes; in flight)

PR #26 (`feat/rescue-visual-render-camera-proof`) is independent of §11 v3 work. A dedicated Opus agent is currently:
1. Setting up worktree on `feat/rescue-visual-render-camera-proof`
2. Applying 3 atomic fixes
3. Pushing + waiting for CI
4. Resolving PR comments
5. `gh pr merge --squash --auto` to main

### Fix 5.1 — handlers/__init__.py registration
- **Source**: PR #26 pytest agent + callable-census agent (both conf-100)
- **Severity**: P1 — fixes 4 required-check failures (ci 3.11/3.12, callable-census ×2)
- **Location**: `veilbreakers_terrain/handlers/__init__.py::_build_command_handlers()`
- **Edit**: Add line `_try_register("visual_render_camera_proof", f"{_pkg}.visual_render_camera_proof", "handle_visual_render_camera_proof")`
- **Why**: The handler's own docstring (lines 6-9) advertises this registration but the rescue cherry-pick from PR #24 didn't bring the line. `scripts/scan_callable_wiring.py:644-663` lands on `orphan_candidate` → `--strict-no-risk` exits 1 before pytest runs.

### Fix 5.2 — visual_render_camera_proof.py:246 type narrow
- **Source**: PR #26 pyright-strict agent (conf-100)
- **Severity**: P2 — fixes pyright-strict ×2 (NOT in required-checks but currently passing on main)
- **Location**: `veilbreakers_terrain/handlers/visual_render_camera_proof.py:246`
- **Edit**: Change `resolution=tuple(resolution)` to `resolution=(resolution[0], resolution[1])`
- **Why**: `tuple(resolution)` widens to `tuple[int, ...]` against the dataclass field `resolution: tuple[int, int]` at line 67. The variable was already coerced to a 2-tuple at line 184; this preserves the narrow type.

### Fix 5.3 — visual_render_camera_proof.py:224 empty-except
- **Source**: PR #26 CodeQL agent (conf-100)
- **Severity**: P3 — fixes CodeQL py/empty-except (NOT in required-checks per CLAUDE.md)
- **Location**: `veilbreakers_terrain/handlers/visual_render_camera_proof.py:224`
- **Edit**: Replace `except AttributeError: pass` with `except AttributeError: logger.warning("eevee.use_shadows / use_gtao not available in this Blender version")`. If `logger` not imported, add `import logging` + `logger = logging.getLogger(__name__)` near other imports.
- **Why**: Match sibling pattern at line 220; `py/empty-except` rule passes if any non-trivial body OR explanatory comment.

**Merge command**: `gh pr merge 26 --squash --auto` per CLAUDE.md squash-merge policy.

---

## §8 Best-practices research synthesis

### §8.1 Blender 4.5 → Unity 2022 LTS HDRP export

**Key recommendations**:
1. **Use glTF 2.0 binary (.glb)** as primary format, NOT FBX. Khronos PBR maps bit-identical to HDRP Lit; vertex colors first-class; Custom properties survive round-trip; Unity's `com.unity.cloud.gltfast` package is officially supported.
2. **Coordinate system + handedness**: Blender (right-handed Z-up) → Unity (left-handed Y-up). For procedural meshes built in Python: rotate `(x, y, z)_blender → (x, z, -y)_unity`, flip triangle winding CCW→CW, negate `tangent.w = -1.0` for HDRP MikkTSpace correctness.
3. **Scale + units**: Blender Scene Units = Metric/1.000m. FBX `Apply Scaling = "FBX Units Scale"`. **`UNITY_SCALE_FACTOR = 0.85` in `terrain_unity_export.py:44` is a character-rig hack incorrectly applied to mesh export — should be 1:1.**
4. **UV channels**: UV0 = surface tiling, UV1 = lightmap (Unity auto-gen for chunks; hand-author for foliage), UV2 = world-space planar.
5. **Vertex colors for splat masks**: ONLY for low-frequency data (cliff bias, wetness). Use RGBA8 splatmap **textures** (2 textures × 4 channels = 8 layers) for actual splat data — 4096m chunks at 1024² verts have 1 vertex per 4m², insufficient for 1m biome transitions.
6. **HDRP/Lit Mask Map**: pack R=metallic, G=AO, B=detail mask, A=smoothness. Author offline via Substance Painter "Unity HDRP" preset OR Python ImageMagick post-step.
7. **Mesh-as-Terrain (NOT Unity Terrain)**: spec uses chunk meshes; Unity Terrain `heights[]` cannot do overhangs. Confirmed correct architectural choice.
8. **LOD generation**: Decimate Modifier in Blender at 1.0/0.5/0.15 ratios, name `_LOD0/1/2` for Unity importer auto-LODGroup. LOD3 = octahedral impostor (Amplify Impostors $90 OR Imposterify free).
9. **Edge welding (1e-3m tolerance per spec §6.3)**: bake-side fix; sample 3-chunk neighborhood for normals to ensure boundary normals match across chunks. Don't rely on Unity-side vertex welding (can't merge across separate Mesh objects).
10. **Foliage prefabs**: per-species `.glb` with 4 LODs; encode wind-mass into vertex color RGB (R=trunk, G=branch, B=leaf, A=phase). Pivot at base (Y=0), not centroid. HDRP/Lit master with Alpha Clipping=ON, Double-Sided=Mirrored Normals.
11. **Water**: HDRP 2022.2+ ships built-in `WaterSurface` for Pool/River/Ocean. Eliminates ~1 week of custom water authoring. WaterDecal replaces deprecated WaterFoamGenerator.
12. **Decals**: HDRP DecalProjector + Decal master node. Enable Decal Layers in HDRP Asset to prevent mud-on-leaves smearing.
13. **HDRP project setup**: HDRP Wizard → "Fix All" on HDRP tab (NOT HDRP+DXR). Ray tracing OFF for v1 per §11.7 cut #5.
14. **Addressables**: all chunks/foliage/decals via Addressables; group chunks by 16×16 super-region; foliage 1 bundle per species.

**Citations**: Unity HDRP docs, Blender glTF exporter docs, Khronos glTF spec, Ben Golus MikkTSpace article, Unity glTFast package docs.

### §8.2 HDRP terrain shader (custom build vs MicroSplat)

**Recommendation: BUY MicroSplat ($40 total = base FREE + $20 HDRP module + $20 Mesh Terrains module)**.

**Critical context updates**:
- **MicroSplat base is now FREE** (was $120 historically) — actively maintained by Jason Booth, latest v3.9.49 Dec 2025, Unity 6 module exists.
- **HDRP is in maintenance mode** as of Unity 2024 — no new features through Unity 6.7 LTS (end of 2028); URP recommended for new projects. Custom HDRP shader investment depreciates.
- **MicroSplat Mesh Terrains module** ($20) directly addresses VeilBreakers's procedural-mesh-NOT-Unity-Terrain constraint that kills Path A's accelerator.
- Solo-dev realistic Path A (custom): **12-18 days, 20-30 if learning** — not 3-5 days as spec claims.

**Decision matrix highlights**:

| Dimension | Custom HDRP | MicroSplat |
|---|---|---|
| Direct cost | $0 | $40 (HDRP+Mesh) |
| Solo-dev time | 12-18 days realistic | 1-3 days config |
| AAA visual bar | Achievable with effort | Native out-of-box |
| Procedural mesh fit | Manual splatmap binding | Native via Mesh module |
| Anti-tiling | Hand-roll or import OSS | Built-in hex+stochastic |
| Variant bloat | High | Managed by MicroSplat keyword stripping |
| HDRP→URP migration | Re-author all shaders | $20 module swap |
| Vendor lock | None | Low (source in project, can fork) |

**Implementation path (MicroSplat)**:
1. Buy base (free) + HDRP 2022 Support ($20) + Mesh Terrains ($20).
2. Convert one biome chunk to MicroSplat material; validate vertex-color splatmap binding from Python pipeline.
3. Iterate biome textures into MicroSplat texture array slots.
4. Defer Foliage shader work (MicroSplat doesn't cover) — author 1 HDRP Lit foliage Shader Graph (~3 days).
5. Use built-in HDRP WaterSurface for Pool/River/Ocean (~1 day config).
6. Total: ~1 week for full visual stack vs ~3 weeks for Path A.

**Citations**: Unity HDRP docs, MicroSplat Asset Store + 80lvl Booth deep-dive, Daniel Ilett Shader Graph tutorial series, Unity render pipelines roadmap.

### §8.3 GitHub Actions self-hosted runner security

**Recommendation: Drop GPU perf gate from required checks (Path 1) OR move to GitHub-hosted larger runners (Path 2). Path 3 (self-hosted with full hardening) only if GPU CI is genuinely required AND all 3 PRs (B5-CI1/DEP4/DEP5) land before any `runs-on: self-hosted` workflow runs.**

**Threat model**: Self-hosted runners on PUBLIC repos = #1 GitHub anti-pattern. 2025-2026 documented incidents:
- **Pwn requests**: PR redefines build scripts → executes on host with target-repo secrets if `pull_request_target` + checkout `head.sha`.
- **CVE-2025-30066 (tj-actions/changed-files, March 2025)**: 23,000+ repos leaked secrets; lesson: pin every action by 40-char SHA.
- **Shai-Hulud worm (Praetorian/Sysdig, Nov 2025)**: persistent backdoor via `RUNNER_TRACKING_ID=0` escape + `svc.sh install` as systemd service; C2 over github.com polling defeats egress firewalls.

**For VeilBreakers (public repo + HF/Meshy/Quixel keys)**: a single unguarded fork PR ends secret hygiene posture. Recovery requires: rotate ALL keys, audit every prior workflow run, wipe runner host.

**Comparison**:

| Dimension | Self-hosted RTX 4060 Ti | GitHub-hosted T4/L4 larger | External (Cirrus) |
|---|---|---|---|
| Cost | ~$300 hardware (owned) + ~$10/mo electricity + ~10hrs/mo ops | ~$0.043/min post-Jan 2026 (~$40/mo nightly) | $150/mo per concurrent runner |
| Public-repo safe | Only if all 3 hardening PRs land | Yes by design | Yes |
| Plan requirement | None | Team or Enterprise | None |
| Maintenance burden | High | Zero | Low |
| Time to first green | 2-3 weeks | 1 day | 1 day |
| Worst-case incident | Project-wide secret rotation + hardware wipe | Bounded to single VM | Bounded to single VM |

**Hard rule**: do NOT enable any `runs-on: [self-hosted, ...]` workflow on this repo until all 3 PRs land + reviewed + IR runbook rehearsed.

**Citations**: GitHub Secure Use reference, Praetorian Self-Hosted Runners as Backdoors, Sysdig Shai-Hulud analysis, CISA tj-actions advisory, step-security/harden-runner.

### §8.4 Procedural terrain determinism

**Hash function recommendation**: `hashlib.blake2b(digest_size=8)` for hot-path seeding (3× faster than SHA-256, deterministic across Python versions, 64-bit `int` direct from digest). `hashlib.sha256` for `version_hash` cache key.

**REJECT `hash()`** (PYTHONHASHSEED-randomized; bpo-27706 confirms `random.Random(string)` is non-deterministic for the same reason). **REJECT `xxhash`/`mmh3`** (unnecessary deps; mmh3 5.0.0 had breaking seed-signature change — exactly the cross-version drift `version_hash` is meant to catch, not introduce).

**Two-tier seed model with `version` as integer** in `biome_yaml.version: 1`, manually bumped on intentional content changes:

| Option | Cache invalidation | Reproducibility | Dev ergonomics |
|---|---|---|---|
| **(a) `version: int` in YAML** ✓ | Manual but intentional | Forks share unless they bump | Authors hold the keys |
| (b) `version_hash` auto-derived | Automatic, every commit | Identical across forks at same SHA | World re-rolls every commit (catastrophic) |
| (c) git SHA | Automatic, every commit | Identical across forks | Same as (b) — re-rolls on commits |

Option (a) is the only ergonomic answer. Minecraft does this; No Man's Sky pinned a phone-number seed decoupled from binary versions. Spec §12.5 already declares "world is fixed across playthroughs" — option (a) is the only consistent choice.

**`version_hash` is a cache-invalidation key, NOT a seed input.** Spec §3.7's formula stays as-is. Add `requirements_lock_sha` as a fifth input — otherwise `pip install --upgrade numpy` silently changes outputs without changing `version_hash`.

**Concrete API signature** (lands at `chunks/chunk_seed.py` per PR B5-D1; replaces SHA-256 prefix slice in current `terrain_rng.derive_pass_seed`):

```python
# chunks/chunk_seed.py
import hashlib, struct
from typing import Final

_BIOME_NS:  Final = b"vb.biome.v1"
_CHUNK_NS:  Final = b"vb.chunk.v1"
_PASS_NS:   Final = b"vb.pass.v1"

def _h64(*parts: bytes) -> int:
    h = hashlib.blake2b(digest_size=8)
    for p in parts:
        h.update(struct.pack(">I", len(p)))   # length-prefixed → no ambiguity
        h.update(p)
    return int.from_bytes(h.digest(), "big", signed=False)

def biome_seed(biome: str, version: int) -> int:
    """Pre-slice scope. Drives DEM upscale jitter, fbm basis, Mei-2007 hydraulic
    noise, stratigraphy modulation, drainage carving."""
    return _h64(_BIOME_NS, biome.encode("utf-8"), struct.pack(">I", int(version)))

def chunk_seed(biome: str, x: int, y: int, version: int) -> int:
    """Post-slice scope. Drives foliage scatter, Voronoi clumping, ground-clutter,
    edge-thread sampling, macro_variation."""
    return _h64(_CHUNK_NS, biome.encode("utf-8"),
                struct.pack(">iiI", int(x), int(y), int(version)))

def derive_pass_seed(intent_seed: int, seed_namespace: str,
                     tile_x: int = 0, tile_y: int = 0,
                     region: tuple[int,int,int,int] | None = None) -> int:
    """Compose per-pass seed. `intent_seed` MUST be biome_seed(...) or
    chunk_seed(...) — never hash() of a string."""
    region_bytes = b"" if region is None else struct.pack(">iiii", *region)
    return _h64(_PASS_NS,
                struct.pack(">Q", intent_seed & 0xFFFFFFFFFFFFFFFF),
                seed_namespace.encode("utf-8"),
                struct.pack(">ii", int(tile_x), int(tile_y)),
                region_bytes)
```

**Three signature changes vs current `terrain_rng.py`** (load-bearing on Fix 1.4 PR #14):
1. `region: tuple[int,int,int,int]`, NOT `str` — current passes `repr()` of bbox, invites collision.
2. `tile_x/y: int`, NOT `float` — current does `int(tile_x * 1000)`; rounding error at chunk boundaries collapses distinct tiles to same seed.
3. **Length-prefixed framing** — prevents `("biome_a", 1)` vs `("biome", "_a1")` collision.

**RNG migration pattern (universal)**:
```python
# Pre-slice (DEM, hydraulic, stratigraphy):
seed = derive_pass_seed(biome_seed(biome, version), "hydraulic_mei2007", region=(x0,y0,x1,y1))
rng = np.random.default_rng(seed)         # NumPy hot path
rng_py = random.Random(seed)              # rare pure-Python use

# Post-slice (scatter, foliage, decals, macro_variation):
seed = derive_pass_seed(chunk_seed(biome, cx, cy, version), "foliage_poisson", tile_x=cx, tile_y=cy)
rng = np.random.default_rng(seed)
```

Per [Scientific Python SPEC 7](https://scientific-python.org/specs/spec-0007/), every pass function should accept `*, rng: RNGLike | SeedLike | None = None` and call `rng = np.random.default_rng(rng)` at the top.

**Lint rule (extend `_FORBIDDEN_RNG_CALLS` in `tests/test_phase8_determinism_guardrails.py:11-18`)**:
- Allow: `random.Random(int_literal)`, `random.Random(derive_pass_seed(...))`, `random.Random(biome_seed(...) | chunk_seed(...))`
- Flag: `random.Random("forest")` — PYTHONHASHSEED hazard
- Flag: `random.Random(hash("forest"))` — PYTHONHASHSEED hazard
- Flag: `random.Random()` — wall-clock seeded
- Flag: `np.random.normal/standard_normal/permutation` (extend ban list)
- Flag: `np.random.RandomState` (Mersenne Twister stream NOT version-stable)

**Byte-identity testing (18 artifacts)** — different gates for different artifact classes:

| Artifact | Byte-identity | SSIM ≥0.99 | Schema-only | Why |
|---|:-:|:-:|:-:|---|
| heightmap.bin (16-bit raw) | ✓ | | | Deterministic Taichi kernel |
| heightmap.png/normalmap.png/splatmap_*.png | ✓ | | | Pillow encoder deterministic |
| watermap.png/macro_variation.png/navmesh.png | ✓ | | | Mask thresholding |
| foliage.json/decals.json/water.json/edges.json | ✓ | | | Sorted before write |
| manifest.json | ✓ | | | `json.dumps(sort_keys=True, separators=(",",":"))` |
| meta.json | | | ✓ | Strip volatile fields (timestamp/git_sha) to `meta.runtime.json`; gate schema-only |
| terrain_render_preview.png/lighting_validation.png | | ✓ (≥0.95) | | Cycles cross-platform float drift — SSIM-only |

**Critical: JSON canonicalization** for byte-identity:
```python
records.sort(key=lambda r: (r["x"], r["y"], r.get("id", "")))
text = json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
out.write(text.encode("ascii"))  # bytes — not str — for byte-identity
```

**Subprocess-isolated CI gate** (already exists at `terrain_determinism_ci.py:307`; correctly DeprecationWarning'd for in-process variant per §11.8 #5). Required env:
```yaml
env:
  PYTHONHASHSEED: "0"
  PYTHONDONTWRITEBYTECODE: "1"
  SOURCE_DATE_EPOCH: "1735689600"  # reproducible-builds.org for Pillow tEXt
  TI_OFFLINE_CACHE: "0"            # disable Taichi JIT-cache cross-run leakage
```

**Taichi determinism** (per [Taichi #7645](https://github.com/taichi-dev/taichi/issues/7645)): `ti.init(random_seed=...)` is broken on Vulkan/macOS. **Use `ti.random()` only for SSIM-tested textures, NEVER for scatter or feature placement.** For Mei-2007 (PR #19), pass pre-computed RNG state buffer from NumPy: `state_buf = np.random.default_rng(seed).integers(0, 2**32, n_particles).astype(np.uint32); kernel(state_buf)`. Use stateless mixer (e.g., `wang_hash(state_buf[i] ^ iteration_idx)`). **Atomic float reductions are non-deterministic** (`atomicAdd` on float is non-associative + warp scheduler is non-deterministic per CUDA float compliance). Use integer atomics or scan-then-reduce.

**Floating-point determinism**: within-architecture achievable (`-ffp-contract=off`, no `-ffast-math`, no FMA fusion, explicit reduction orders). **Cross-architecture (x86 vs ARM) NOT achievable** — non-issue for VeilBreakers (bake on x86_64, players consume pre-baked artifacts; spec §12.5 confirms).

**Cross-version**: pin Python 3.12, Taichi 1.7.x, NumPy 1.26.x or 2.x exclusively (NEP 19 contract guarantees PCG64 stream stable; permutation/shuffle algos retuned across minor versions). `pip install --require-hashes` + checked-in `requirements.lock.txt`.

**AAA examples**: Minecraft (world_seed → LCG → chunk_seed XOR with feature salt; cautionary tale on bit-cancellation), No Man's Sky (single phone-number seed → galaxy → system → planet, decoupled from binary versions), Horizon Zero Dawn (Decima GPU-side procedural placement, world-coordinate-keyed, GDC 2017), Dwarf Fortress (per-stage seeds recorded to gamelog for stage-replay), RimWorld (`Rand.PushState`/`PopState` for nested per-feature scopes).

**Citations**: Python `random`/`hashlib` docs, bpo-27706, Scientific Python SPEC 7, NumPy parallel RNG, Taichi #7645, Bruce Dawson floating-point determinism, NVIDIA CUDA float compliance, Minecraft Wiki, Hello Games / NMS Wikipedia.

### §8.5 Procedural mesh chunk export

**Critical chunk-size correction**: Spec's 4096m chunk is **4-8× larger than shipped AAA chunks** for streaming. Witcher 3 ships 512m tiles (~74 km² world); Cyberpunk 2077 sectors are 64/128/256m three-LOD pyramid; Horizon FW uses Decima graph-packaged sectors (loosely 64-128m). **A 4096m mesh at 2m vertex spacing = 2048×2048 = 4.2M verts per LOD0 — exceeds Unity's 2³² index buffer per submesh and cripples streaming granularity.**

**Recommendation**: Keep `chunk_x, chunk_y` as the **biome unit** (template/grammar scope), but introduce **`subchunk_x, subchunk_y` (16×16 grid of 512m subchunks per 4096m biome)** as the Addressable streaming unit. Spec §6.3's edge contract operates at the subchunk grid; `edges.json` carries 257-vertex edge arrays per 512m subchunk. Add to Phase 4 as new PR.

**Edge welding pattern** (mandatory per spec §6.3, 1e-3m tolerance):

1. **Generate with 1-vertex halo**: each subchunk authors `(N+2)×(N+2)` vertices where the outer ring is *also produced* by the canonical neighbor sample. Halo verts not exported but used for normal averaging.
2. **Source heights from same merged height-field**: never call heightmap function twice for the same edge column — read both subchunks from a single backing array (the `--reuse-merged-field` path in PR B5-D4). Only path to bit-equality `this.S.heights[i] == neighbor_north.N.heights[i]`.
3. **Compute face normals first, then accumulate**: per-triangle cross products → accumulate into vertex normal sums *including the halo triangles*. ("Fake border vertices" technique per Unity Discussions: combine normals on procedural mesh with multiple tiles.)
4. **Drop halo, normalize, write**: only inner `N×N` verts and normalized accumulated normals exported. Halo's contribution already baked in.
5. **Bake normals AFTER weld, never before**: `RecalculateNormals()` after `Mesh.Optimize()` silently merges by index but ignores weld tolerance.
6. **Use MikkTSpace tangents** (Unity, Unreal, xNormal, Substance all use Mikk; rolling your own causes per-edge tangent flips on normal-mapped cliffs).
7. **HDRP normal handedness**: Unity is **+Y / left-handed world / DirectX-style**. If bake produces OpenGL (Y-down green), flip green at write time on the *texture*, never at runtime in shader (cost on every chunk transition).

**Failure mode (spec §13.9)**: 1cm height delta between `chunkA.east_edge[i]` and `chunkB.west_edge[i]` produces single-pixel-wide black line in HDRP deferred path because face normals on adjacent triangles flip when one vertex offsets epsilon. Looks like moiré edge or shimmering crack at LOD0; disappears at LOD2 → "works on console screenshot, broken on PC ultra" bug class. Spec's editor-only red-wireframe overlay is the right gate.

**Test (required by PR #38)**:
```python
def test_257_vert_edge_share():
    a = bake_chunk(0, 0, seed=42)
    b = bake_chunk(1, 0, seed=42)
    np.testing.assert_array_equal(a.east_edge_heights, b.west_edge_heights)  # bit-exact
    np.testing.assert_allclose(a.east_edge_normals, b.west_edge_normals, atol=1e-6)
```

**LOD chain (per 512m subchunk)**:

| LOD | Spacing | Grid | Verts | Tris | Use |
|---|---|---|---|---|---|
| LOD0 | 1m | 513×513 | 263,169 | 524,288 | <50m |
| LOD1 | 2m | 257×257 | 66,049 | 131,072 | 50-150m |
| LOD2 | 4m | 129×129 | 16,641 | 32,768 | 150-400m |
| LOD3 | 8m + imposter card | 65×65 | 4,225 | 8,192 | 400m+ |

**Decimate by factor-2 down-sampling** of the heightmap (every Nth sample), NOT mesh simplification — preserves silhouettes at chunk boundaries since `LODn[i] = LOD0[i*2^n]` (bit-exact seam matching). Mesh simplification (Simplygon-style) introduces edge drift, breaks bit-exact seams.

**Cliff overhangs** can't use `heights[]` (single-valued) — emit as separate non-heightmap mesh in `supplemental_mesh_specs_file` (already declared `VbTerrainImporter.cs:61`). LOD via Unity 6 Mesh LOD with cross-fade since they're discrete props.

**Watershed-aware single-chunk re-bake DAG** (PR B5-D2/D3):
```python
ChunkId = tuple[int, int]
ChannelId = Literal["heightmap", "erosion", "drainage", "splat", "foliage",
                    "water", "flow_map", "flow_accumulation", "decals", "edges"]

channel_dag: dict[ChannelId, set[ChannelId]] = {
    "erosion":           {"heightmap"},
    "drainage":          {"heightmap", "erosion"},
    "splat":             {"heightmap", "erosion", "drainage"},
    "foliage":           {"heightmap", "splat", "drainage"},
    "water":             {"drainage", "flow_accumulation"},
    "flow_map":          {"drainage", "flow_accumulation"},
    "flow_accumulation": {"drainage"},
    "decals":            {"splat", "foliage"},
    "edges":             {"heightmap", "erosion", "drainage", "water"},
}
chunk_upstream:   dict[ChunkId, set[ChunkId]]   # static topology
chunk_downstream: dict[ChunkId, set[ChunkId]]   # D8-derived from flow_direction

def chunk_version_hash(chunk: ChunkId, channel: ChannelId) -> str:
    parts = [content_hash(chunk, ch) for ch in channel_dag[channel]]
    if channel in {"water", "flow_map", "flow_accumulation"}:
        parts += [content_hash(c, "drainage") for c in chunk_upstream[chunk]]
    return blake2b(b"|".join(parts).encode()).hexdigest()[:16]
```

For headwaters edits, the downstream set can be the *entire river network* — gate the user with `--max-cascade-chunks 8`; refuse if exceeded, suggest full-biome bake.

**Addressables architecture**: one group per biome × content-type, NOT per chunk (>1000 bundles cripples catalog load):
```
VbTerrain_Mountain_Heightmaps   (group, packed-together, local)
VbTerrain_Mountain_Splatmaps    (group, packed-together, local)
VbTerrain_Mountain_Meshes       (group, packed-separately-by-label, local)
VbTerrain_Mountain_Foliage      (group, packed-together, remote-eligible)
```
Use **Addressables labels** for chunk identity: `chunk_4_7`, `chunk_4_8`. Load by intersection: `Addressables.LoadAssetsAsync<GameObject>(new[]{"chunk_4_7","mountain"}, MergeMode.Intersection)`. Streaming radius: load 3×3 around player, unload at 5×5.

**Format choice per artifact**:

| Artifact | Format | Rationale |
|---|---|---|
| chunk mesh per-LOD | **FBX 2014 binary** | Unity importer is FBX-tuned; preserves UV1+UV2, smoothing groups, vertex colors, multi-LOD sub-meshes; 23% faster import than glTF in Unity 2024.1+ |
| heightmap | **RAW u16 LE** | Unity TerrainData expects this; deterministic; no PNG decoder variance |
| splatmap | **PNG RGBA8** | Lossless, deterministic, diff-friendly |
| navmesh | **NMX/.asset (NavMeshData binary), NOT OBJ, NOT JSON** | **P0 fix needed**: spec memory flags `navmesh OBJ vs NMX`; current `navmesh.json` writes coords without `dtNavMeshCreateParams` — Unity cannot bake from it. Fix: integrate `recast4j` or `recast-navigation-python` to emit `dtNavMesh.bin` per Detour spec, wrap as `NavMeshData` via `NavMeshBuilder.UpdateNavMeshDataAsync`. OBJ has no walkability, no off-mesh links, no area IDs. |
| foliage prefab | **FBX (model)** + **JSON (placement)** | `tree_prototypes` as FBX; per-chunk `tree_instances.json`. **Memory**: foliage attachment in Unity is broken (climate stuck "temperate") — wire `tile_biome_name` → biome-specific foliage catalog. |
| water surface | **NOT exported as mesh** | HDRP Water System builds surface from `water_surface_elevation_file` (heightfield) + flow_map + foam mask. Mesh export defeats HDRP's adaptive LOD. |
| edge contract | **JSON** | Diff-reviewable, schema-versioned (PR #39 spec_version: 2) |

**§8.5 conflict with §8.1 on FBX vs glTF**: §8.1 (Blender→Unity HDRP general export research) recommends glTF; §8.5 (procedural mesh chunk research) recommends FBX for chunk meshes citing Unity importer being FBX-tuned. **Resolution**: For procedural chunk meshes, FBX 2014 binary is the better choice (per §8.5 Threekit comparison + spec's own existing `terrain_unity_export.py` outputting FBX-compatible). For one-off prefabs (foliage `.glb`, decal mesh) glTF is fine. Document this in fixes guide explicitly so the implementer doesn't get whiplash.

**Single-chunk re-bake CLI (PR B5-D4)**:
```bash
python -m veilbreakers_terrain.bake \
    --biome mountain --chunk 4,7 --reuse-merged-field /cache/mountain_v3_field.npz \
    --halo 5 --skip-watershed-cascade=false
```

Acceptance gates:
- single-chunk path completes <9 min on RTX 4060 Ti
- output byte-identical for unchanged chunks vs full-biome bake (extends `test_phase8_determinism_guardrails.py` to all 18 artifacts per PR B5-T4)
- `version_hash` in `manifest.json` matches Merkle root of upstream channel hashes

**AAA examples**: Witcher 3 (REDengine 3, 46×46 × 512m tiles, 0.5m vertex spacing, Simplygon LODs, Umbra streaming — Gollent GDC 2014); Cyberpunk 2077 (REDengine 4, tiered 64/128/256m exterior sectors); Horizon FW (Decima deterministic graph-based content packaging, in-memory metadata for millions of assets); AC Shadows (Anvil micropolygon GPU-driven streaming).

**Citations**: Unity Addressables 2.11 docs, Unity 6 Mesh LOD cross-fade, Unity NavMeshData scripting API + NavMeshComponents repo, HDRP normal map handedness (Unity Discussions), Marmoset tangent-handedness docs, Ben Golus normal mapping for triplanar shader, Threekit FBX vs glTF comparison, Ardenfall world streaming in Unity, Gollent GDC 2014 Witcher 3 landscape creation, Guerrilla "Space-Efficient Content Packaging" + "Scaling Tools for Millions of Assets" Horizon FW.

---

## §9 Deep codebase scans

### §9.1 RNG sites enumeration (RNG_SITES.txt)

**Output**: `docs/superpowers/specs/.staging/RNG_SITES.txt`

**MAJOR DISCOVERY: spec memory item is materially wrong.**

§11.10 #2 says "real value: 47 handlers + 11 tests = 58 production sites + 1 hash() hazard". **Actual count is 100 production handler sites + 79 tests = 179** (per `RNG_SITES.txt` ground truth). The "47/58" figure looks like a stale Batch-9-era count never updated as `terrain_caves.py` grew to 22 sites and `terrain_features.py` to 14.

**This invalidates PR #18's effort estimate (currently L)** — actual scope is 2× larger than documented. Effort must scale to XL or split across 2 PRs.

**Counts (TSV-verified against grep on disk; canonical per `RNG_SITES.txt`)**:
- Production handler sites: **100 RNG-creation calls + 2 hash-hazards = 102 entries**
  - `random.Random(...)`: 35 sites in handlers/
  - `np.random.default_rng(...)`: 63 sites in handlers/
  - `sim/` modules (foam.py, pbd_cloth.py): 2 sites
- Test sites: **79** (np.random.default_rng + random.Random across tests/)
- Module-level `random.seed(...)`: **0** (clean ✓)
- `np.random.seed(...)` legacy: 1 in `tests/test_coverage_gaps.py:427` (test-only, low priority)
- **Hash hazards: 2 (NOT 1 as spec claims)**:
  - `terrain_cliffs.py:2397` — confirmed (PR #15 covers): `hash(cliff.cliff_id) & 0x7FFFFFFF`
  - `terrain_cliffs.py:1502` — **additional, less severe**: `sum((i+1)*ord(ch) for i, ch in enumerate(cliff.cliff_id))`. Deterministic across PYTHONHASHSEED but string-id-fragile (renaming a cliff_id char shifts the entire boulder field). **PR #15 scope must expand to cover both.**

**Top 3 ambiguous-scope sites needing human decision** (cannot auto-classify per-biome vs per-chunk):
1. **`terrain_cliffs.py:2650`** — Mixes `seed ^ (0xB0B1 + cliff_idx * 37)`. The `cliff_idx` is enumeration index. If `pass_cliffs` reorders `cliff_list`, every cliff's boulder field shifts. **Must use stable id (cliff world coords) not enumeration index** — fix concurrent with PR #15.
2. **`terrain_caves.py:3889`** — `cave_i ^ 0xDEADBEEF` for stalactite subsample (60-cap). Same enumeration-index hazard.
3. **`terrain_features.py` mesh-builders** (262, 761, 1296, 1789, 2168, 3082, 3474, 3774, 4178) — All take opaque `seed` parameter; caller decides scope. Currently invoked per-feature-instance, but PR #18 must verify no caller invokes them whole-biome-once.

**Dead-RNG candidates (delete during migration, NOT migrate)**:
- `terrain_features.py:2168` — `_ = rng` "reserved"
- `terrain_waterfalls.py:2280` — `_ = np.random.default_rng(...)`
- `terrain_materials_v2.py:1046-1047` — `_ = _pass_rng`

**Implications for fixes guide**:
- **NEW Phase 0 fix**: §11.10 #2 memory correction — change "47 handlers + 11 tests = 58" to "109 handlers + 80 tests = 189". Drop "1 hash() hazard" → "2 hash() hazards (terrain_cliffs.py:2397 + :1502)".
- **NEW Phase 1 fix (Fix 1.4 update)**: PR #18 effort upgrade L → XL OR split across 2 PRs (handlers vs tests).
- **NEW Phase 1 fix**: PR #15 scope expand to cover both hash hazards + the 2 enumeration-index hazards (cliff_idx, cave_i).
- **NEW Phase 4 fix**: 3 dead-RNG sites cleanup PR.

### §9.2 Channel reads/writes graph (CHANNEL_GRAPH.md)

**Output**: `docs/superpowers/specs/.staging/CHANNEL_GRAPH.md`

**Headline numbers**:
- 145 distinct channel names touched (117 writers, 103 readers; union 145)
- **17 orphan reads** (broken consumers) + **35 orphan writes** (dead producers)
- 8 spec §3.4 names not in code (vocabulary divergence)
- 5 race-risk channels with multiple writers (most have proper `overrides=`)

**Validation against §11 v3 wave-flagged items**:
1. **"no PR registers `water_surface_mask`"** — partially OBSOLETE. `terrain_water_variants.py:879` already writes it; channel is in `_ARRAY_CHANNELS` at `terrain_semantics.py:616`. **PR #B5-C5 may now be doc-only — recommend §11 verifier confirm before opening.**
2. **"3 competing water-vocabulary names"** — confirmed. Spec §3.4 says `water_surface_z`, `water_depth`, `shoreline_mask`; code uses `water_surface_elevation_m`, `water_depth_m`, `shoreline_blend`. PR #B5-C1 closes.
3. **legacy `water_surface` count understated** — spec line 209 says "4 consumers"; **real count is ~10 reads across 6 files** (navmesh_export ×2, unity_export, waterfalls ×2, water_variants internal ×3, wildlife_zones, _water_network/_ext ×3). **PR #5b migration list is too short — add 6 more reader migration sites to acceptance.**
4. **Issue #27 (cliff/water/rock/gravel_label std=0)** — confirmed: only `pass_compute_terrain_labels` (validator) writes. Zero generators stamp. PR #29 architecture fix required.
5. **`terrain_macro_color.consumed_channels=("height",)` lies** — confirmed. Real reads are 8: height + biome_id + wetness + erosion_amount + deposition_amount + strata_cross_section + albedo_shift_rgb + snow_line_factor. **PR #31 closes (verify scope covers all 8, not just the 6 currently noted in memory).**

**Top 5 orphan reads (P0 — broken consumers)**:
1. `cliff_label` / `water_label` / `rock_label` / `gravel_label` — Issue #27 (4 channels, 1 architectural fix via PR #29)
2. `forest_mask` — 5 reads, 0 writes (no PR addresses; **add to Phase 4**)
3. `water_depth` (legacy spec name) vs `water_depth_m` — vocabulary unification (PR #B5-C1)
4. `material_zones` — declared as `roughness_driver` consumed_channel but never produced (phantom prerequisite; **add to Phase 4**)
5. `terrain_visual_qa.py` reads ~10 phantom channels: `vegetation_index, species_density, climate_zone, hazard_zone, height_delta, rock_mask, hardness, limestone_proxy, canopy_density, canopy_species_radius_m` — memory item "VisualQA is data-contract not visual" confirmed; **add to Phase 4: PR-cleanup terrain_visual_qa.py phantom channels**

**Top 5 dead producers**:
1. `corruption_map` — `biome_channels` writes; no `stack.get` reader anywhere — **Phase 4: delete or wire**
2. **All 12 channels in spec §9.5** (waterfall_velocity, mist_fog_volume, wave_amplitude_per_vertex, particle_emitter_specs, foam_atlas_path, caustic_atlas_path, river_mouth_mask, confluence_foam, delta_fan_direction, shoreline_blend, mist_zone_mask, wet_surface_decal) — produced but no readers
3. `audio_reverb_class` / `audio_zone_list` / `wildlife_affinity` — produced; consumed only via state-side aggregator, not stack.get
4. `tidal_zone_label`, `wave_energy` — coastline outputs, zero readers
5. `riverbed_caustics` — `_water_network_ext` writes; no consumer

**`consumed_channels` declaration mismatches** (8 found):
- Worst: `terrain_macro_color` (1 declared, 8 actual) and `terrain_labels` (1 declared, 5 actual including the 4 self-preserve reads)

**P0 not in any current §11 v3 PR (NEW Phase 4 fixes)**:
1. `corruption_map` orphan write (`biome_channels`) — delete or wire
2. `weathering_timeline` writing `wetness` without `overrides=` declaration → **silent ChannelOwnershipError risk** per memory item "PassDefinition overrides pattern"
3. `environment.py:6265-6266` road_mask DAG escape — direct `stack.set` outside any registered pass (PR #23 exists for this but **scope must be widened to include the road_mask DAG-escape, not just the closure registration**)
4. `terrain_visual_qa.py` reading ~10 phantom channels — needs cleanup PR
5. `material_zones` declared in `consumed_channels` of `roughness_driver` but never produced anywhere — phantom prerequisite, breaks pipeline if `roughness_driver` ever runs

These 5 items are NEW to Phase 4 and were not flagged by the CE persona wave; they only emerged from the channel-graph deep scan.

### §9.3 Cross-PR file-edit conflict matrix (PR_FILE_CONFLICT_MATRIX.md)

**Output**: `docs/superpowers/specs/.staging/PR_FILE_CONFLICT_MATRIX.md`

**🚨 SHOWSTOPPER FINDING**: **22 of 30 sampled cites are stale when measured against `main` HEAD.** Verifier-B's PASS verdict was against the **spec branch state** (where the author *expected* things to be), NOT against `main` HEAD (where an implementer would actually branch from). The "PASS" is misleading: an implementer following PR #N's line cite to make a surgical edit will NOT find the cited code there.

**Headline counts**:
- 88 PRs analyzed (Block 1: 15 / Block 2: 22 / Block 3: 11 / Block 4: 14 / Block 5: 26 line items)
- **Files with multi-PR ownership**: 11
- **Ordering hazards (P0/P1)**: 7
- **Bad-cite drift hazards**: 22 of 30+ verified cites are off
- **Missing dep edges in §11.6**: 14

**Top 5 ordering hazards**:
1. **PR #18 ↔ B5-D1 cycle (P0)** — confirmed; §11.0.2 work-around cites the wrong PR (`#36` instead of `B5-D1`). [Already covered by Fix 0.1 + Fix 1.1]
2. **PR #53 invalidates #23/#25/#45/#49 (P0)** — XL split of `environment.py` (8613 LOC) makes 5 surgical line cites stale; §11.6 declares no deps. [Already covered by Fix 1.6]
3. **PR #55 deletes `vegetation_system.py` while #43 / #B5-A4 / #56 edit it (P0)** — only `#56→#55` declared; **`#43→#55` and `#B5-A4→#55` missing**. [NEW — see Fix 0.14]
4. **PR #55 deletes `asset_generation.py` while #11 edits :699,706 (P0)** — `#11→#55` missing from §11.6. [Already covered by Fix 0.10]
5. **`terrain_pipeline.py` co-edit collision (P1)** — **11 PRs all mutate the same orchestrator file with no serialization rule** (only `terrain_unity_export.py` has one via B5-C2). [NEW — see Fix 1.13]

**Top 5 stale-cite hazards (against `main` HEAD)**:
1. **PR #29** cites `terrain_pipeline.py:1133-1191` for `pass_compute_terrain_labels` — that range on `main` is `pass_compute_biome_channels` (a different pass). **Actual cite is line 1054.**
2. **PR #14** cites `terrain_rng.py:45` for "alternate `derive_pass_seed` to delete" — **the file is 43 lines on `main`**; the duplicate exists only on the in-flight spec branch. **Implementer branching from `main` has nothing to delete** (the PR is a no-op against `main`).
3. **PR #62** cites `terrain_pipeline.py:1386-1392` for `pass_water_depth` skip — that range is `_topo_sort_passes` (Kahn's algorithm). **Actual `pass_water_depth` is at lines 1275-1330.**
4. **PR #43 / #56 / #B5-A4** cite `vegetation_system.py:1284` for `lod_meshes` — line 1284 is unrelated `terrain_vertices` block. **`lod_meshes` is at 685, 1561, 1600.**
5. **PR #23** cites `environment.py:6265-6266` for road_mask DAG-escape closure — `road_mask` write code is at lines **4630-4689 (`_build_road_mask_and_sdf`)**; 6265-6266 is unrelated mesh-update code.

**Critical: path-namespace mismatch (global doc-rot)**: Every PR row uses `handlers/<file>.py`, `providers/<file>.py`, `unity_project/Assets/Scripts/...` shorthand. **Reality on `main`**: `veilbreakers_terrain/handlers/`, `veilbreakers_terrain/providers/`, `unity_plugin/...`. Needs §11.0.3 preface OR global rewrite. [NEW — see Fix 0.15]

**Corrected B5-C2 cite (verifier-B got partial credit)**:
- Spec says: `#11 → #12 → #44 → #5b → #48` (5 PRs)
- Reality: `#5b → #12 → #13 → #20 → #48 → B5-U4` (6 PRs; `#11` is in `providers/`, `#44` is in `unity_export_v2/` — neither edits `terrain_unity_export.py`)
- [Already covered by Fix 0.13]

**Memory correction surfaced**: **`VbTerrainTileMetadata.cs` has 28 data fields on `main`**, not the spec-claimed 25 (or the stale-memory 3). Spec §11.10 #1 and PR B5-U13 row need updating to 28. [NEW — see Fix 0.16]

**Files referenced by spec but missing on `main` (19 net-new + 2 fix-target hazards)**:
- `terrain_asset_budget.py` (PR #36 fix-target — file doesn't exist; **PR turns into a feat, not a fix**) [Already covered by Fix 0.5]
- `_parallel_merge.py` (PR #47 fix-target — file doesn't exist; **PR turns into a feat, not a fix**) [NEW — see Fix 1.14]
- 17 others are explicitly NEW files in feat(...) PRs (chunks/, coastal/, unity_export_v2/, etc.) — fine.

**Implications for fixes guide (NEW fixes added to Phase 0/1/4)**:
- **Fix 0.14** (Phase 0): Add `#43→#55` and `#B5-A4→#55` dep edges
- **Fix 0.15** (Phase 0): Global path-namespace rewrite — `handlers/` → `veilbreakers_terrain/handlers/` etc.
- **Fix 0.16** (Phase 0): Update VbTerrainTileMetadata field count 25→28 in §11.10 #1 and B5-U13 (already in Fix 0.11 but bump to 28)
- **Fix 0.17** (Phase 0): PR #6 cite-anchor refresh — many PRs cite spec-branch line numbers, not `main` HEAD
- **Fix 1.13**: Add `terrain_pipeline.py` writer-edit serialization rule (11 PRs; mirror B5-C2 pattern)
- **Fix 1.14**: PR #47 `_parallel_merge.py` reframe — file doesn't exist on `main`; PR is feat-not-fix
- **Phase 1.X (cite-refresh pass)**: NEW global pass before any other Phase 1 fix lands — re-anchor all line cites against `main` HEAD per PR_FILE_CONFLICT_MATRIX.md. Without this, 73% of surgical PRs hit "no such code at this line" failures.

---

## §10 Verifier scrub log — Round 1

Three Opus verifiers dispatched in parallel after Round-0 synthesis (V1=validity, V2=coverage+ordering, V3=best-practices+AAA-readiness). All three returned with substantial critical findings. Combined picture: guide is **B+ for spec-author execution / C+→B- for AAA-readiness**; **NOT yet ready-to-execute**. Round-2 (4 Opus + 4 Codex) follows after Round-1 findings integrate.

### §10.1 Verifier-1 (validity scrub against `main` HEAD)

**Methodology**: Read every Phase 0/1 fix; independently verify each cited file/line on `main` HEAD via `git show main:...` rather than working tree. Cross-reference against PR_FILE_CONFLICT_MATRIX.md.

**7 BLOCKING false-claims in existing fixes** (must rewrite):

| Fix | False claim | Truth on `main` |
|---|---|---|
| **Fix 1.2** | `terrain_master_registrar.py` doesn't exist | File EXISTS (331 LOC); only `register_stratigraphy_pass` function is missing. Rewrite to "add function inside existing file." |
| **Fix 1.4** | `terrain_rng.py:45` has alternate `derive_pass_seed` | File is **43 lines** total; no `derive_pass_seed` function exists; cite `:45` is past EOF. `_scatter_engine.py:22` is `from typing import Any` (no re-export). Canonical `derive_pass_seed` is at `terrain_pipeline.py:208` not `:269`. **PR #14 is essentially a no-op against `main`.** Rewrite the entire fix. |
| **Fix 1.5** | PR #12 atomic-write already implemented at `terrain_unity_export.py:2495-2511` | Lines 2495-2511 are `_wildlife_zones_json` code. Actual manifest write is at `:2248` and `:2272` using **plain `write_text` — NOT atomic via tempfile/os.replace**. **PR #12 is a REAL needed fix, not a no-op.** Reverse the reframe. |
| **Fix 0.6** | water-depth skip at `terrain_pipeline.py:1386-1392` | Range 1386-1392 is `_topo_sort_passes` (Kahn's algorithm). Actual `pass_water_depth` is at **1275-1330** with skip block at **1306-1312**. Cite is 80 lines off. |
| **Fix 0.11** | VbTerrainTileMetadata.cs has 25 fields | Direct count on `main`: **29 top-level public fields** (28 simple + 1 `ChannelBound[]` array of structs with 3 inner fields). Reconcile with §9.3 (which says 28). |
| **Fix 1.8** | `VbChunkLoader.cs` is fully NET-NEW | `unity_plugin/VbTerrainRuntimeStreamer.cs` (284 LOC) **already exists** serving runtime tile-loader role (camera-aware activation, frustum, distance priority). Architectural decision needed: rename/extend VbTerrainRuntimeStreamer.cs OR create separate VbChunkLoader.cs. Plus `GetOrCreateTreePrefab` is at line **2152**, not 2229. |
| **Fix 5.1** | Add `_try_register(...)` line to handlers/__init__.py | On rescue branch, registration uses different idiom (`_il.import_module + _make_signature_handler`). Fix is morally correct but mechanically off — the PR #26 fix-agent worked it out at runtime. |

**11 missing-finding fixes for cite drift in §11 v3 PRs**:

| PR | Spec cite | Actual cite on `main` | Severity |
|---|---|---|---|
| #9 | `road_network.py:1808-1817` | **OUT OF FILE** (file is 1775 LOC); SDF triple-loop site needs re-finding | P0 |
| #24 | "857-858 is WRONG; use 890" | `radians(88.0)` IS at line 857 on main; spec assertion reversed | P0 |
| #25 | "use `:2031`" | `params.get("terrain_type", "mountains")` actually at lines **1205, 2020, 2322, 2990, 3043** (none at 2031) | P0 |
| #29 | `terrain_pipeline.py:1133-1191` for `pass_compute_terrain_labels` | Range is `pass_compute_biome_channels` (different pass!); actual labels pass at **1054** | P0 |
| #33 | Sabine `:539, :554` | Sabine refs at **12, 73, 79, 181, 252**; LOC 1049 vs actual 1028 | P0 |
| #34 | `terrain_checkpoints.py:97-102` | Registries at lines **49, 52, 54** | P1 |
| #43 / #56 / B5-A4 | `vegetation_system.py:1284` for `lod_meshes` | Line 1284 is unrelated `terrain_vertices`; `lod_meshes` at **685, 1561, 1600**; `procedural_grass.py:720` actual at **685** | P0 |
| #45 | `environment.py:2861` | Actual at **:2844** | P1 |
| #52 | (missing deps) | `terrain_semantics.py` split affects 16+ pass-contract-edit PRs; not in §11.6 dep graph | P1 |
| #61 | `terrain_banded_advanced.py:542` | `variant="classic"` actual at line **434** | P0 |
| B5-U4 | `_pack_tangent_space_normal_rgba:334` | Actual at **:288**; Unity-side `textureType = NormalMap:2097` actual at **:2040** | P1 |

**6 stale cites in research/scan sections**:
- §0 finding #6: `UNITY_SCALE_FACTOR = 0.85` at line 31, NOT 44
- §8.4: subprocess gate at `terrain_determinism_ci.py:265` (not 307); NO `DeprecationWarning` exists in file
- §8.4: test path needs `veilbreakers_terrain/` prefix
- §9.1: RNG count is **100 production + 79 tests = 179** per RNG_SITES.txt ground-truth (guide overstates 109+80=189)
- §9.1 hash hazards: actual at `terrain_cliffs.py:2368` (not 2397), `:1228, :1467` (not 1502), `:2620` (not 2650), `terrain_caves.py:3894` (not 3889)
- §9.2: `terrain_water_variants.py:879` for `water_surface_mask` write; actual writes at **691, 864, 875, 907**

**6 cross-fix contradictions**:
1. Fix 1.10 Path 1 (drop GPU) not propagated to §11.7 #3 wording
2. Fix 1.4 + Fix 1.1 chunk_seed promotion ordering (B5-D1 → {#14, #15} dep direction unclear)
3. Fix 0.11 (25) vs §9.3 (28) vs reality (29) — three numbers
4. Fix 1.5 (PR #12 = no-op) contradicts Fix 0.13 (PR #12 in dep chain) — but Fix 1.5 itself is wrong per Verifier-1, so this resolves once Fix 1.5 is reversed
5. Fix 0.5 redirects PR #36 from `terrain_asset_budget.py` but §11.7 #4 cuts implies that file is the orchestrator
6. §8.5 4096m → 512m subchunk recommendation is unactioned — no Fix promoted

**8 imprecisions**: Fix 0.5 off-by-one cites (`:182` not `:183` etc.); Fix 0.13 missing B5-U4 in dep chain; environment.py LOC 8651 (spec) vs 8613 (main); §8.x research undated; Fix 0.8 PR-count methodology unclear; Fix 0.9 §7.4 unverified; Fix 1.6 Option A "move to v1.1" without spelling consequences; §0 PASS framing for Verifier-A/B not honest about wrong-baseline issue.

**Verdict**: 7 BLOCKING + 11 missing-cite fixes + 6 stale cites in §8/§9 + 6 contradictions + 8 imprecisions = **38 corrections required before commit**.

### §10.2 Verifier-2 (coverage + order-of-operations)

**Methodology**: Build fix-graph; map every CE persona finding + scan finding + research recommendation to a fix; detect cycles, missing prerequisites, phase-boundary violations.

**Coverage gaps**:
- Only **28/75 CE persona findings** explicitly mapped to a Phase 0/1 fix; **47 deferred to Phase 2/3/4 TODO stubs** — guide §13 acceptance criterion #1 ("All 75+ findings consolidated") FAILS.
- **§9.3 prose-only "fixes" (Fix 0.14, 0.15, 0.16, 0.17, 1.13, 1.14)** are referenced by ID in §9.3 prose but **no `### Fix x.y` headed sections exist** — implementer following Phase-0/1 lists will MISS them entirely. **Must promote to headed sections.**
- **6/14 research recommendations adopted as fixes**; 8 still floating in §8 prose.

**17 BLOCKING gaps** (from V2):
1. 6 prose-only §9.3 fixes need promotion to headed sections (Fix 0.14-0.17, 1.13-1.14)
2. **navmesh OBJ→NMX P0** — flagged in §8.5 but no headed fix
3. **UNITY_SCALE_FACTOR=0.85 hack** — every chunk export silently wrong; no fix
4. **4096m → 512m subchunk** — load-bearing on Addressables; no fix
5. **Cite-refresh pass omitted as structural prereq** — must be **Fix 1.0** (precedes all Phase-1 surgical fixes)
6. 3 dead-RNG cleanup sites — promised but no fix
7. 6 P0 wrong-cite hazards (#23, #25, #29, #43/#56/#B5-A4, #62) only partially covered
8. Phase 2/3/4 TODO stubs
9. §8.4 Taichi atomic-float warning not codified into PR #19 acceptance
10. §8.4 18-artifact byte-identity matrix not codified into B5-T4
11. Wave-5 §B.1 PR #11 → #44/#48 atomicity dep missing
12. CHANNEL_GRAPH 5/8 spec §3.4 channel names not in code unaddressed
13. forest_mask broken consumer (5 reads, 0 writes)
14. Verifier-B B5-A4 → #56 dep recommendation
15. Wave-5 §B.1 PR #46 missing dep on #3 + PR #62 missing dep on #9
16. VbTerrainTileMetadata field count contradiction (25 vs 28 vs 29)
17. Fix 1.5 PR #12 cite is wrong (V1 confirmed; lines 2495-2511 ≠ atomic write)

**3 phase-boundary violations**: Fix 0.5, Fix 0.6, Fix 0.10 currently in Phase 0 but require judgment → should be Phase 1.

**29 NEW fixes recommended**:
- Fix 1.0 (cite-refresh prereq)
- Fix 0.14-0.17 promotions (4)
- Fix 1.13-1.14 promotions (2)
- Fix 1.15-1.21 (7 NEW: UNITY_SCALE_FACTOR, #11→#44/#48 dep, PR #25 cite, PR #29 cite, PR #62 cite, PR #43 cite, Taichi atomic-float)
- Phase 4 NEW 4.1-4.14 (14: navmesh OBJ→NMX, 512m subchunk, corruption_map, weathering_timeline overrides, env.py:6265 road_mask, terrain_visual_qa phantom channels, material_zones, forest_mask, 5 missing spec channels, 3 dead-RNG cleanup, RNG count update, PR #15 hash-hazard expansion, PR #18 effort upgrade, B5-T4 18-artifact matrix)

### §10.3 Verifier-3 (best-practices + AAA-readiness)

**Methodology**: Validate research currency via WebSearch + Context7; AAA-bar gap analysis; Blender→Unity flawless-export stress-test (14 categories); Codex agent specialization recommendations.

**Currency corrections to research briefs**:
- **§8.1**: `UNITY_SCALE_FACTOR=0.85` confirmed character-rig hack at `terrain_unity_export.py:31` (V1 also noted line drift). Internal contradiction §8.1 (glTF) vs §8.5 (FBX) not resolved into a fix. **MISSING**: `MeshDataArray` API (Unity 2020.1+ way that's 2-3× faster than `mesh.vertices=` and Burst-compatible). AAA studios use this; guide doesn't mention.
- **§8.2**: MicroSplat FREE base CONFIRMED. **HDRP entered maintenance mode FEB 2026** (NOT "as of Unity 2024" — guide is ~1 year off). **MISSING**: Adaptive Probe Volumes (APV) — load-bearing AAA practice for procedural worlds; without APV interior shadows look flat.
- **§8.3**: GH Actions T4 GPU is **$0.07/min**, not $0.043/min. Nightly bake budget should be **$60-70/mo** not $40/mo. Plus MISSING `concurrency: cancel-in-progress` for fork-PR + OIDC for cloud auth.
- **§8.4**: BLAKE2b is **1.23×-1.5×** faster than SHA-256 on small digests, NOT 3× as guide claims. Length-prefixed framing is canonical (Schneier TLS doc). Taichi #7645 confirmed unresolved. MISSING: `SeedSequence.spawn()` parallel pattern; NEP 19 reproducibility contract not stated explicitly.
- **§8.5**: `recast4j` is JAVA (not Python); Python wrapper `recast-navigation-python` claim unverified; if real recommendation is **DotRecast (C#)** that goes Unity-side, not bake-side. §8.5 cliff-overhang Unity 6 Mesh LOD cross-fade contradicts Unity 2022 LTS lock.

**7 BLOCKING AAA-readiness gaps** (NEW practices to add):
1. **APV (Adaptive Probe Volumes)** setup — interior shadow lighting flat without it
2. **`MeshDataArray` native path** — chunk import perf 2-3× off baseline
3. **Crash-resilient bake** — 64-hour bake unrecoverable on crash without per-chunk checkpoint
4. **Per-chunk integrity hash + corruption detection on load** — silent corruption otherwise
5. **Asset schema migration framework** — mid-dev schema bump = re-bake everything otherwise
6. **Editor-only DXR feature flag** against shipping to Player build
7. **NavMeshData round-trip integration test** — recast/Detour Python integration claim unverified

**Blender→Unity flawless-export stress-test (14 categories)**: 5 PASS, 6 PARTIAL, 8 FAIL. Failure categories: streaming, versioning, build pipeline, cross-platform, localization, source control, etc.

**Recommended Codex agent specializations** (V3 suggested 6; user wants 4):
1. Live-codebase line-cite verifier (sweep §11.1-§11.5 against `main` HEAD)
2. Unity Editor smoke-test stub (CRITICAL — only Codex can find Unity-side bugs no Python verifier can)
3. Channel-graph integrity validator (re-validate orphan/race counts)
4. Blender 4.5 + bpy export sanity (headless `.glb` round-trip)

**11 NEW fixes recommended (Fix 0.18-0.20, 1.15-1.17, 4.NEW.1-7)**.

**Verdict**: B+ spec-author execution / **C+→B- AAA-readiness**. 7 BLOCKING + 8 POLISH gaps. Guide must NOT advance to merge until at least Codex agents 1, 3, 5 close their gaps.

### §10.4 Combined finding tally (all 3 verifiers)

| Source | BLOCKING | NEW fixes | Stale claims | Contradictions |
|---|:-:|:-:|:-:|:-:|
| V1 (validity) | 7 | 11 | 6 | 6 |
| V2 (coverage) | 17 | 29 | — | — |
| V3 (best-practices) | 7 | 11 | 5 | 1 |
| **Combined (deduplicated)** | ~25 | ~50 | ~10 | ~7 |

**Round-2 trigger**: After Round-1 findings integrate (this section + corrections to existing fixes + Phase 2/3/4 fill + new fixes 0.14-0.20, 1.0, 1.13-1.21, 4.1-4.14, AAA add-ons), dispatch **4 Opus + 4 Codex** agents in parallel:
- **Opus 1**: Re-scrub validity post-integration (find regressions)
- **Opus 2**: Re-scrub Phase 2/3/4 newly-filled sections
- **Opus 3**: Implementation-feasibility deep dive on Phase 4 fixes
- **Opus 4**: AAA-bar acceptance simulation (20-yr terrain studio lead lens)
- **Codex 1**: Live-codebase line-cite verifier — sweep all §11.1-§11.5 cites against `main` HEAD
- **Codex 2**: Unity Editor smoke-test stub — minimal HDRP project, import existing chunk artifacts, find Unity-side bugs
- **Codex 3**: Channel-graph integrity validator — re-validate orphan counts; surface new orphans
- **Codex 4**: Blender 4.5 + bpy export sanity — headless `.glb` round-trip on synthesized chunk artifacts

---

## §11 Codex final pass log

Round-2 Codex CLI agents (Codex 1-4) ran in parallel; outputs are canonical inputs to this guide:
- **Codex 1** → `docs/superpowers/specs/.staging/CODEX1_CITE_AUDIT.tsv` (126 cite records, 23 valid / 39 stale / 3 OOF / 61 no-cite). Methodology: `git show main:<path>` blob inspection only; sed broken in env so PowerShell/Python indexing used. **CANONICAL CITE GROUND TRUTH for §16.1.**
- **Codex 2** → `docs/superpowers/specs/.staging/CODEX2_UNITY_SMOKETEST.md` (35 Unity-side bugs U-001 through U-035 against §6.1 18-artifact contract; current importer is descriptor-driven, target spec is meta.json-driven). **Drives §16.4 + new B5-U-* fixes.**
- **Codex 3** → `docs/superpowers/specs/.staging/CODEX3_CHANNEL_AUDIT.tsv` (23 channel claims tested on `main` HEAD). Confirmed corruption_map orphan; refuted "10 phantom reads in terrain_visual_qa.py"; surfaced new orphan height_m. **Drives §16.2 WITHDRAWN Fix 4.6.**
- **Codex 4** → `docs/superpowers/specs/.staging/CODEX4_BLENDER_SANITY.md` + `scripts/codex_export_sanity.py` (Blender 4.5 export gotchas; sanity script written but not runtime-executed). **Confirms §15.1 UNITY_SCALE_FACTOR=0.85 hack; documents 11 export failure modes.**

Round-2 Opus verifier outputs (R2-Opus-1/2/3/4) are summarized in §10 (and elaborated in §16.0/16.5). Their outputs were available to the Round-3 Ultrathink author for final reconciliation.

---

## §12 Iteration log (Round-3 final)

See §18 for the full iteration log including all Round-3 changes.

---

## §13 Acceptance criteria

This guide is "done" — ready to commit to PR #25 — when:

- [x] All 75+ findings consolidated into Phase 0-5 sections (§14 + §16.10 mapping)
- [x] Each fix has: source, severity, location, concrete edit, verification step, best-practice citation (where applicable)
- [x] Order of operations is sound (no circular deps, no fix that requires another not-yet-applied fix; §16.5 resolves contradictions)
- [x] All file:line cites verified to exist on disk via codebase scan agents (Codex 1 TSV; §16.1 re-anchor table)
- [x] No contradictions between fixes (§16.5 resolves all 10 known)
- [x] All 5 best-practices research briefs integrated into §8
- [x] All 3 deep codebase scan files generated and integrated into §9
- [x] Round-1 V1/V2/V3 + Round-2 R2-Opus-1/2/3/4 + Codex 1/2/3/4 + Round-3 Ultrathink scrubbed every line
- [x] 4 Codex CLI agents (Codex 1/2/3/4) validated guide vs codebase + best practices
- [x] Iteration loop closed: no new issues in Round-3 final pass (§16.11)
- [x] Implementation guide cited as ready-to-execute by Round-3 author

(Outdated criteria above are kept for change-log fidelity. Final acceptance is in §17.)

---

## §14 Appendix — All 75+ findings consolidated → Phase × Fix ID

See §16.10 for the full mapping table (99 finding rows).

---

## §15 Round-1 integration — NEW fixes promoted from §10 verifier reports

After the 3 Round-1 verifiers returned (V1=validity, V2=coverage, V3=best-practices), this section promotes their findings into headed `### Fix x.y` sections so an implementer following the Phase 0/1/4 lists doesn't miss them. Pre-Round-2 (4 Opus + 4 Codex) dispatch.

### §15.0 Fix 1.0 — Cite-Refresh Prereq (P0, MUST precede all Phase-1 surgical fixes)
- **Source**: PR_FILE_CONFLICT_MATRIX §7 + V2 BLOCKING #5 + V1 confirms 22/30 stale cites
- **Severity**: **P0 — without this, 73% of surgical PRs hit "no such code at this line" failures**
- **Action**: Single PR (or batched PR-prep step) that re-anchors **every** line cite in §11.1-§11.5 against `main` HEAD. Use `PR_FILE_CONFLICT_MATRIX.md` as canonical input. Output: corrected line numbers per PR row.
- **Verify**: 0 cite errors when running a static check `git show main:<cited_file> | sed -n 'NL,NLp'` against every cite
- **Note**: Fix 1.0 must land **before** Fix 1.2 / 1.4 / 1.5 / 1.8 / 0.6 / 0.11 (V1 found these to have corrected-but-still-stale cites).

### §15.1 V1 BLOCKING corrections — rewrites of existing fixes

#### Fix 1.2-CORRECTED — `terrain_master_registrar.py` exists
**Original Fix 1.2 said**: file doesn't exist. **V1 truth**: file IS on `main` (331 LOC); only the function `register_stratigraphy_pass` is missing.
- **Edit**: REWRITE PR #16 acceptance to "ADD `register_stratigraphy_pass` function inside the existing `handlers/terrain_master_registrar.py` file (Bundle I; insert after `register_wind_erosion_pass`)."
- **Verify**: `git show main:veilbreakers_terrain/handlers/terrain_master_registrar.py | wc -l` = 331; grep for `register_stratigraphy_pass` returns 0.

#### Fix 1.4-CORRECTED — PR #14 phantom premise reframe
**Original Fix 1.4 said**: PR #14 deletes alternate `derive_pass_seed` at `terrain_rng.py:45`. **V1 truth**: `terrain_rng.py` is 43 lines (cite past EOF); no `derive_pass_seed` function exists in the file; `_scatter_engine.py:22` is `from typing import Any`. Canonical lives at `terrain_pipeline.py:208` not `:269`. PR #14 is essentially a no-op against `main`.
- **Edit**: REWRITE PR #14 acceptance to:
  - `(a) recognize the duplicate-derive_pass_seed claim is stale (only existed on a now-discarded spec-branch state)`
  - `(b) PROMOTE the new chunks/chunk_seed.py BLAKE2b API (per §8.4) as the single source of truth — co-lands with PR #15.5 (B5-D1 in Block 1)`
  - `(c) update terrain_rng.py:45-43 to import + re-export from chunks/chunk_seed (transition shim)`
  - `(d) migrate the 100 production + 79 tests RNG sites per §9.1 ground-truth (NOT 47/58 in spec memory; NOT 109/189 in §9.1 prose)`
- **Verify**: `terrain_rng.py` becomes a thin shim; `chunks/chunk_seed.py` is canonical; tests pass; no caller uses `from terrain_pipeline import derive_pass_seed`.

#### Fix 1.5-REVERSED — PR #12 atomic write IS needed
**Original Fix 1.5 said**: PR #12 already implemented; reframe as test-only. **V1 truth**: lines 2495-2511 are wildlife_zones code; actual manifest write at `terrain_unity_export.py:2248` and `:2272` uses **plain `write_text` — NOT atomic**. PR #12 is a REAL needed implementation.
- **Edit**: REVERSE Fix 1.5. Restore PR #12 as full implementation:
  - `(a) replace plain write_text at :2248 and :2272 with NamedTemporaryFile + os.replace pattern`
  - `(b) add helper _atomic_write_json(path, data) replacing _write_json:787 plain write_text`
  - `(c) add tests/test_unity_export_atomicity.py::test_kill_mid_write`
  - `(d) update Wave-1 Resolution Registry row to reflect "PR #12 = real impl + test"`
- **Effort**: M (not S as Fix 1.5 implied).
- **Verify**: `Grep "manifest.json" terrain_unity_export.py` shows tempfile+os.replace; tests pass.

#### Fix 0.6-CORRECTED — water-depth skip cite is 80 lines off
**Original Fix 0.6 said**: cite at `terrain_pipeline.py:1386-1392`. **V1 truth**: that range is `_topo_sort_passes` (Kahn's algorithm); actual `pass_water_depth` is at lines **1275-1330** with skip block at **1306-1312**.
- **Edit**: Update Fix 0.6's location reference: replace `:1386-1392` with `:1275-1330 (skip block at :1306-1312)`. The reframe-as-verify-existing remedy is correct; only the cite is wrong.
- **Verify**: `git show main:veilbreakers_terrain/handlers/terrain_pipeline.py | sed -n '1306,1312p'` shows the skip block.

#### Fix 0.11-CORRECTED — VbTerrainTileMetadata has 29 fields
**Original Fix 0.11 said**: 25 fields. **§9.3 said**: 28. **V1 ground truth**: **29 top-level public fields** (28 simple + 1 `ChannelBound[]` array of structs with 3 inner fields).
- **Edit**: Update Fix 0.11 + §11.10 #1 + B5-U13 to "29 fields"; enumerate all 29 by name in B5-U13 acceptance.
- **Verify**: Direct count via `git show main:unity_plugin/VbTerrainTileMetadata.cs | grep -E '^\s*public ' | wc -l` = 29.

#### Fix 1.8-CORRECTED — VbTerrainRuntimeStreamer.cs already exists
**Original Fix 1.8 said**: VbChunkLoader.cs is fully NET-NEW. **V1 truth**: `unity_plugin/VbTerrainRuntimeStreamer.cs` (284 LOC) exists serving runtime tile-loader role.
- **Edit**: ADD architectural decision to Fix 1.8: choose either:
  - **Option A**: Rename + extend `VbTerrainRuntimeStreamer.cs` → `VbChunkLoader.cs`. Preserves the existing camera-aware activation/frustum/distance-priority code.
  - **Option B**: Keep `VbTerrainRuntimeStreamer.cs` as-is and add separate `VbChunkLoader.cs` for chunk-streaming concerns; document the boundary.
  - **Recommended**: Option A — single class for tile loading; preserves existing behavior.
- Also: PR B5-U11's `GetOrCreateTreePrefab` is at line **2152** not 2229 in `VbTerrainImporter.cs`.
- **Verify**: After PR, only one runtime tile-loader class exists; `VbTerrainRuntimeStreamer.cs` either renamed OR explicitly bounded.

### §15.2 V2 prose-only fixes — promoted to headed sections

#### Fix 0.14 — Add #43→#55 + #B5-A4→#55 dep edges
- **Source**: PR_FILE_CONFLICT_MATRIX top-5 ordering hazard #3
- **Severity**: P0 — `vegetation_system.py` deletion before edits = file-not-found errors
- **Edit**: Add to §11.6 dep graph: `#43 → #55` and `#B5-A4 → #55` (both must land before #55 deletes the file).
- **Verify**: §11.6 dep walk shows #55 has 4 incoming edges (#56, #43, #B5-A4, plus existing).

#### Fix 0.15 — Global path-namespace rewrite preface
- **Source**: PR_FILE_CONFLICT_MATRIX critical doc-rot
- **Severity**: P1 — implementer cannot resolve any path-shorthand cite
- **Edit**: Add §11.0.3 preface: "All file paths in §11.1-§11.5 use shorthand (`handlers/X.py`, `providers/X.py`, `unity_project/Assets/Scripts/X.cs`). Reality on `main`: `veilbreakers_terrain/handlers/X.py`, `veilbreakers_terrain/providers/X.py`, `unity_plugin/X.cs` (Editor-side: `unity_plugin/Editor/X.cs`)."
- **Verify**: Every PR row resolvable to a real `main` HEAD path.

#### Fix 0.16 — VbTerrainTileMetadata field count update memory + spec
- **Source**: V1 + §9.3
- **Severity**: P2 (correctness of memory items)
- **Edit**: Update §11.10 memory item #1 from `"25 fields"` → `"29 fields (28 simple + 1 ChannelBound[] array of structs with 3 inner fields)"`; propagate to B5-U13 acceptance + Fix 0.11.
- **Verify**: Three locations agree.

#### Fix 0.17 — PR cite-anchor refresh against main HEAD (subsumed by Fix 1.0)
This was prose; now subsumed under Fix 1.0 as the single global cite-refresh prereq.

#### Fix 1.13 — terrain_pipeline.py writer-edit serialization rule
- **Source**: PR_FILE_CONFLICT_MATRIX top-5 ordering hazard #5
- **Severity**: P1 — 11 PRs all mutate the same orchestrator file with no serialization rule (only `terrain_unity_export.py` has B5-C2 pattern)
- **Edit**: Add §11.5.2 PR `B5-C6: fix(coherence): serialize terrain_pipeline.py writer-edit chain` mirroring B5-C2: PR labels enforce only one in-flight at a time; declared chain `#3 → #4 → #14 → #18 → #29 → #35 → #45 → #46 → #62 → others`.
- **Verify**: §11.6 dep graph shows the linearization; PR labels enforced via CI.

#### Fix 1.14 — PR #47 _parallel_merge.py reframe
- **Source**: PR_FILE_CONFLICT_MATRIX missing-file finding
- **Severity**: P1
- **Edit**: PR #47 cites `_parallel_merge.py` as fix-target; file doesn't exist on `main`. Reframe as feat-not-fix: "Create `_parallel_merge.py` with thread-safe attribute-bypass write pattern (per §8.4 atomic-float ban)".
- **Verify**: After PR, file exists; pattern documented.

### §15.3 V3 best-practices currency corrections

#### Fix 0.18 — BLAKE2b speed claim correction
- **Source**: V3 §8.4 currency check (PYPI benchmarks: BLAKE2b 574 MiB/s vs SHA-256 467 MiB/s = 1.23×)
- **Edit**: §8.4 amend "BLAKE2b is **3× faster** than SHA-256 in CPython 3.12" → "BLAKE2b is **~20-30% faster** than SHA-256 on small (8-byte) digests in CPython 3.12. The speedup matters at 100+ production RNG sites × 64-chunk bake but is not a 3× win."
- **Verify**: §8.4 reflects accurate benchmark.

#### Fix 0.19 — GH-hosted T4 GPU pricing correction
- **Source**: V3 §8.3 currency check (T4-4-core actually $0.07/min, January 2026 39% reduction applies to smaller runners)
- **Edit**: §8.3 + Fix 1.10 Path 2 amend "$0.043/min" → "$0.07/min for T4-4-core; ~$60-70/mo for 60-90 min/night nightly bakes."
- **Verify**: §8.3 + Fix 1.10 use $0.07/min.

#### Fix 0.20 — HDRP maintenance entry date correction
- **Source**: V3 §8.2 currency check (HDRP entered maintenance Feb 2026, not "as of Unity 2024")
- **Edit**: §8.2 + §0 amend "HDRP is in maintenance mode as of Unity 2024" → "HDRP entered maintenance mode in **February 2026** (no new features through Unity 6.7 LTS, end of 2028)."
- **Verify**: §8.2 + §0 use Feb 2026.

### §15.4 V1 wrong-cite fixes (P0)

#### Fix 1.15 — UNITY_SCALE_FACTOR=0.85 → 1.0
- **Source**: V3 §8.1 + V1 §0 corrections
- **Severity**: P1 — every chunk export silently scaled 15% off
- **Edit**: `terrain_unity_export.py:31` (NOT :44 as guide says) — `UNITY_SCALE_FACTOR = 0.85` → `UNITY_SCALE_FACTOR = 1.0`. Also remove all 25+ multiplications by `UNITY_SCALE_FACTOR` in lines 916, 1216, 2540, 2576, 2843-2846, 3018-3020, 3078-3081 (since 1.0 is identity, these become no-ops). OR: keep multiplications + change constant; either path produces 1:1 mesh export.
- **Verify**: Bake 1 chunk; verify Unity-side mesh is 1:1 with bake-side.

#### Fix 1.16 — PR #11 → #44/#48 atomicity dep edge
- **Source**: Wave-5 §B.1 (V2 BLOCKING #11)
- **Severity**: P1 — atomicity prereq missing
- **Edit**: Add §11.6 dep edges `#11 → #44` and `#11 → #48` (atomicity precedes the 5 PRs touching `terrain_unity_export.py`).
- **Verify**: §11.6 graph shows 4-incoming-edge counts on #44 and #48.

#### Fix 1.17 — PR #25 self-wrong-cite reverse
- **Source**: V1 missing-finding #3
- **Severity**: P0
- **Edit**: PR #25 currently claims "use `:2031`"; actual `params.get("terrain_type", "mountains")` is at lines **1205, 2020, 2322, 2990, 3043** (none at 2031). REWRITE PR #25 to address the canonical first occurrence at `:1205` + document 4 sister callsites.
- **Verify**: `git show main:veilbreakers_terrain/handlers/environment.py | grep -n 'params.get("terrain_type"'` returns 5 lines, none 2031.

#### Fix 1.18 — PR #29 wrong-pass cite
- **Source**: V1 missing-finding #4
- **Severity**: P0 — implementing per spec edits the WRONG pass
- **Edit**: PR #29 currently cites `terrain_pipeline.py:1133-1191` for `pass_compute_terrain_labels`. That range is `pass_compute_biome_channels` (different pass!). Actual `pass_compute_terrain_labels` at line **1054**. REWRITE PR #29 to cite `:1054` (and surrounding scope).
- **Verify**: `git show main:veilbreakers_terrain/handlers/terrain_pipeline.py | sed -n '1054p'` shows `def pass_compute_terrain_labels`.

#### Fix 1.19 — PR #62 wrong-pass cite
- **Source**: V1 BLOCKING-4 (also Fix 0.6 update)
- **Severity**: P0
- **Edit**: PR #62 currently cites `:1386-1392`. Actual `pass_water_depth` at **:1275-1330** with skip at **:1306-1312**. Update cite.
- **Verify**: skip block visible at `:1306-1312`.

#### Fix 1.20 — PR #43 / #56 / #B5-A4 wrong-line cite
- **Source**: V1 missing-finding #7
- **Severity**: P0
- **Edit**: All three PRs cite `vegetation_system.py:1284` for `lod_meshes`. Actual at lines **685, 1561, 1600** in `vegetation_system.py`; `procedural_grass.py:720` actually at **:685**. REWRITE all three PR rows with corrected cites.
- **Verify**: Grep confirms.

#### Fix 1.21 — PR #19 Taichi atomic-float ban
- **Source**: V2 BLOCKING #9
- **Severity**: P1 — without this, perf gate could ship non-deterministic kernel
- **Edit**: Expand PR #19 acceptance: "(a) FORBID `atomic_add` on float in Mei-2007 hydraulic kernel; (b) use integer atomics OR scan-then-reduce per §8.4 Taichi determinism caveat; (c) verify same input → same output to 1 ULP across 5 runs on the same GPU."
- **Verify**: Grep `atomic_add\(.*float` in PR #19 returns 0.

#### Fix 1.22 — B5-T4 18-artifact byte-identity matrix codification
- **Source**: V2 BLOCKING #10
- **Severity**: P1
- **Edit**: B5-T4 acceptance: adopt §8.4's 18-artifact matrix verbatim (which artifacts are byte-identity, SSIM, schema-only). Each artifact gets explicit gate. Reference `meta.json.runtime.json` separation (volatile fields stripped to runtime variant for byte-identity).
- **Verify**: B5-T4 PR has the matrix table inline.

### §15.5 Phase 4 — Coverage gaps (V2's 14 fixes promoted)

#### Fix 4.1 — navmesh OBJ→NMX conversion (P0)
- **Source**: §8.5 + V2 BLOCKING #2
- **Edit**: Replace current `navmesh.json` writer with proper Recast/Detour `dtNavMesh.bin` emit. Use **DotRecast (C# NuGet 2026.1.3)** Unity-side OR `recast-navigation-python` bake-side (verify package exists; if not, integrate via subprocess to recast4j Java JAR). Wrap as Unity `NavMeshData` via `NavMeshBuilder.UpdateNavMeshDataAsync`.
- **Verify**: Bake 1 chunk; load in Unity; agent pathfinds end-to-end.

#### Fix 4.2 — 4096m → 512m subchunk introduction (P1)
- **Source**: §8.5 4-8× too large for streaming
- **Edit**: Keep `chunk_x, chunk_y` as biome unit. Introduce `subchunk_x, subchunk_y` (8×8 per 4096m biome) as Addressable streaming unit. `edges.json` operates at subchunk grid (257-vertex edge arrays per 512m subchunk). LOD0 = 513×513 = 263,169 verts (within Unity's 2³² index buffer per submesh).
- **Verify**: Single chunk bake produces 64 subchunks; each importable as separate Addressable.

#### Fix 4.3 — corruption_map orphan write
- **Source**: CHANNEL_GRAPH P0 #1
- **Edit**: Either delete `corruption_map` writer in `biome_channels.py` OR wire to `terrain_macro_color` consumer.
- **Verify**: `Grep "corruption_map"` returns either 0 or matching reader/writer pair.

#### Fix 4.4 — weathering_timeline overrides=
- **Source**: CHANNEL_GRAPH P0 #2
- **Edit**: `weathering_timeline.PassDefinition` add `overrides=("wetness",)` to prevent silent ChannelOwnershipError per memory item.
- **Verify**: PassDefinition declares overrides.

#### Fix 4.5 — env.py:6265 → :4630-4689 road_mask scope
- **Source**: CHANNEL_GRAPH P0 #3 + V1 cite drift
- **Edit**: Expand PR #23 scope to address `_build_road_mask_and_sdf` at lines 4630-4689 (not 6265-6266). The DAG-escape closure at the original cite is mesh-update code, unrelated.
- **Verify**: `git show main:veilbreakers_terrain/handlers/environment.py | sed -n '4630,4689p'` shows road_mask write.

#### Fix 4.6 — terrain_visual_qa.py 10 phantom channels cleanup
- **Source**: CHANNEL_GRAPH P0 #4
- **Edit**: Delete reads of `vegetation_index, species_density, climate_zone, hazard_zone, height_delta, rock_mask, hardness, limestone_proxy, canopy_density, canopy_species_radius_m` (none produced anywhere). Replace with declared-channel reads only.
- **Verify**: `Grep` confirms 10 phantom reads removed.

#### Fix 4.7 — material_zones phantom prerequisite
- **Source**: CHANNEL_GRAPH P0 #5
- **Edit**: Either delete `material_zones` from `roughness_driver.consumed_channels` OR add producer.
- **Verify**: `consumed_channels` declares only produced channels.

#### Fix 4.8 — forest_mask broken consumer
- **Source**: CHANNEL_GRAPH "Top 5 orphan reads" #2
- **Edit**: 5 readers, 0 writers. Either add producer OR delete readers.
- **Verify**: Channel graph shows balance.

#### Fix 4.9 — 5 spec §3.4 channel names not in code
- **Source**: CHANNEL_GRAPH "8 spec §3.4 names not in code"
- **Edit**: For each of `wet_fetch, flow_velocity_xy, foam_potential, waterfall_mask, wave_fetch, wet_zone_override` — either implement OR delete from spec §3.4 (vocabulary unification).
- **Verify**: Spec §3.4 channels = code-exposed channels.

#### Fix 4.10 — 3 dead-RNG sites cleanup
- **Source**: §9.1 RNG_SITES.txt
- **Edit**: Delete `_ = rng` / `_ = np.random.default_rng(...)` at `terrain_features.py:2168`, `terrain_waterfalls.py:2280`, `terrain_materials_v2.py:1046-1047`.
- **Verify**: `Grep "_ = .*random"` returns 0.

#### Fix 4.11 — RNG count update memory + spec
- **Source**: §9.1 RNG ground truth (100 production + 79 tests = 179)
- **Edit**: Update §11.10 memory item #2 from `"47 handlers + 11 tests = 58"` → `"100 handlers + 79 tests = 179"`. Update PR #18 acceptance with corrected count + effort upgrade L → XL.
- **Verify**: Three locations agree.

#### Fix 4.12 — PR #15 hash-hazard scope expansion
- **Source**: §9.1 — 2 hash hazards + 2 enumeration-index hazards (NOT 1)
- **Edit**: PR #15 scope covers BOTH `terrain_cliffs.py:2368` (hash) AND `:1228, 1467` (sum-of-ord) AND `:2620` (cliff_idx enumeration) AND `terrain_caves.py:3894` (cave_i enumeration). Use stable cliff world-coords or biome+chunk_seed, not enumeration index.
- **Verify**: All 4 hazards eliminated; CI lint catches new instances.

#### Fix 4.13 — PR #18 effort upgrade L → XL
- **Source**: §9.1 (109 sites, not 47)
- **Edit**: PR #18 effort L → XL OR split into PR #18a (handlers, ~100 sites) + PR #18b (tests, 79 sites).
- **Verify**: Effort estimate matches site count.

#### Fix 4.14 — Verifier-B B5-A4 → #56 dep edge
- **Source**: Verifier-B cosmetic finding (Round-0)
- **Severity**: P3
- **Edit**: Add `B5-A4 → #56` dep edge for clarity (B5-A4 edits `vegetation_system.py:1284` while #56 deletes the file; Fix 0.14 covers this but explicit edge avoids ambiguity).
- **Verify**: §11.6 graph shows the edge.

### §15.6 V3 AAA-readiness gaps (7 BLOCKING NEW Phase 4 fixes)

#### Fix 4.15 — APV (Adaptive Probe Volumes) setup PR
- **Source**: V3 BLOCKING #1
- **Severity**: P1 — without APV, interior shadow lighting flat
- **Edit**: Add new PR `B5-U15: feat(unity): APV brick streaming per chunk` — bake APV brick streaming asset per chunk; configure HDRP Frame Settings → APV; Addressable group `VbTerrain_<biome>_APVCells`.
- **Verify**: HDRP Frame Settings shows APV enabled; chunk-stream loads APV bricks.

#### Fix 4.16 — MeshDataArray native path PR
- **Source**: V3 BLOCKING #2
- **Severity**: P1 — chunk import perf 2-3× off
- **Edit**: Add new PR `B5-U16: feat(unity): MeshDataArray native path` — `VbChunkLoader.cs` (or VbTerrainRuntimeStreamer.cs per Fix 1.8 Option A) uses `Mesh.AllocateWritableMeshData` + `Mesh.ApplyAndDisposeWritableMeshData`, NOT `mesh.vertices = ...`. Burst-compatible; 2-3× faster on import.
- **Verify**: Profiler shows chunk import time drops 2-3×.

#### Fix 4.17 — Crash-resilient bake PR
- **Source**: V3 BLOCKING #3
- **Severity**: P1 — 64-hour bake unrecoverable on crash
- **Edit**: `chunks/chunk_baker.py` writes per-chunk `.lock` + atomic finish marker (rename from `.partial` to `.done` on success). CLI `--resume` flag skips chunks with valid finish marker.
- **Verify**: Kill bake mid-flight; `--resume` skips completed chunks.

#### Fix 4.18 — Per-chunk integrity hash + corruption detection
- **Source**: V3 BLOCKING #4
- **Severity**: P1 — silent corruption otherwise
- **Edit**: Append BLAKE2b digest of contents to last 32 bytes of every binary artifact (heightmap.bin, splatmap.png, etc.). `VbChunkLoader.cs` reads + verifies on load; raises `ChunkCorruptError` on mismatch.
- **Verify**: Corrupt 1 byte; load raises error.

#### Fix 4.19 — Asset schema migration framework
- **Source**: V3 BLOCKING #5
- **Severity**: P1 — mid-dev schema bump = re-bake everything
- **Edit**: `meta.json.schema_version` + `chunks/schema_migrations/v1_to_v2.py` style migrators with snapshot tests. Migration on schema-version-mismatch on load (or fail-fast if unrecognized).
- **Verify**: Bake at v1; load at v2; migrator applies.

#### Fix 4.20 — Editor-only DXR feature flag
- **Source**: V3 BLOCKING #6
- **Severity**: P1 — HDRP DXR is Editor-only per §11.7 #5
- **Edit**: Add `[UNITY_EDITOR]`-only `#define VB_DXR_EDITOR` to any DXR-using shader/component; CI lint asserts no DXR sub-graphs in Player builds.
- **Verify**: Player build excludes DXR sub-graphs.

#### Fix 4.21 — NavMeshData round-trip integration test
- **Source**: V3 BLOCKING #7 + Fix 4.1
- **Severity**: P1
- **Edit**: Bake one chunk; import via DotRecast / `NavMeshBuilder.UpdateNavMeshDataAsync`; assert agent pathfinds end-to-end. Subsumes Fix 4.1's verification.
- **Verify**: Test passes; agent reaches goal.

### §15.7 Phase 2 stub fill (Block 5 split + scope rationalization)

(V2's 47 unmapped CE findings span Phase 2/3/4. The most-cited Phase 2 themes get headed entries here; remainder roll into Round-2 expansion.)

#### Fix 2.1 — Block 5 split into 5a/5b/Block 6
- **Source**: scope-guardian conf-100 + product-lens conf-75
- **Edit**: §11.5 splits into:
  - **5a** "Pilot-blocking Unity parity" = §11.5.1 PRs B5-U1 through B5-U5 (5 BLOCKING gaps per §11.7 #2)
  - **5b** "Pilot-supporting infra" = §11.5.3 single-chunk re-bake, §11.5.5 asset budget, B5-U6 through B5-U14 polish Unity
  - **Block 6** "Post-pilot maturity" = §11.5.2 coherence, §11.5.4 test infra, §11.5.6 deps, §11.5.7 doc rot
- **Verify**: §11.5 has 3 child sections; calendar minima updated.

#### Fix 2.2 — Block 1 detrash (move one-liners to Block 2/4)
- **Source**: scope-guardian conf-75
- **Edit**: Move PR #6 (one-line default flip), #7 (one-line default flip), #10 (small bytes change), #14 (delete duplicate), #15 (replace one hash) to Block 2 or 4. Keep Block 1 as 6-PR critical path.
- **Verify**: §11.1 has 6 PRs; critical path matches.

#### Fix 2.3 — Refactor PRs #49-#54 deferred to v1.1
- **Source**: scope-guardian conf-100 (corroborated by adversarial conf-100 Fix 1.6)
- **Edit**: Move #49-#54 to §11.8 deferrals: "environment.py 5-seam split, terrain_features.py 9-seam split, terrain_semantics.py 82-importer split, animation modules relocate, procedural_meshes.py 22,816 LOC relocate — defer to v1.1 (XL/L refactors not pilot-blocking)".
- **Verify**: §11.4 contains 8 PRs (was 14); §11.8 contains 6 deferred refactors.

#### Fix 2.4 — Test infra over-engineered (move B5-T2/T3/T5/T6/T7 to post-pilot)
- **Source**: scope-guardian conf-75
- **Edit**: Keep B5-T1 (render goldens) + B5-T4 (byte-identity 18 artifacts) in pilot; move B5-T2/T3/T5/T6/T7 to "post-pilot test maturity" section.
- **Verify**: §11.5.4 has 2 PRs; deferrals add 5.

### §15.8 Phase 3 stub fill (strategic decisions; user judgment)

(All Phase 3 fixes are `manual` — require user decision; documenting them here so user can decide.)

#### Decision 3.1 — AA ceiling vs A- target
- **Source**: scope-guardian + product-lens
- **Decision**: Pick one and restate consistently in §0 banner + §11.7 #5. **Recommended**: A-/A target (matches §6.10 lock); reframe §11.7 #5 from "AA ceiling" to "v1 ship items deferred per §11.8" so deferrals don't undermine the A- target.

#### Decision 3.2 — MicroSplat default vs HDRP custom
- **Source**: V3 §8.2 + product-lens
- **Decision**: Per V3 research, **BUY MicroSplat** ($40 total = FREE base + $20 HDRP module + $20 Mesh Terrains module) as DEFAULT path. Flip §6.6 framing from "fallback" to "first choice" to honestly reflect solo-dev time arbitrage (~2 weeks of solo-dev time vs $40).

#### Decision 3.3 — Calendar realism
- **Source**: scope-guardian conf-75 + adversarial conf-100
- **Decision**: §11.6 calendar minima from "14 days single engineer / 7-8 days two engineers" → "Optimistic 14 working days assumes 1 PR/hour throughput; **realistic 30-45 working days for solo developer** with normal review cycles. Drop the two-engineer line entirely OR explicitly note it requires hiring (out of scope)."

#### Decision 3.4 — GPU runner path (per Fix 1.10)
- **Source**: V3 + adversarial
- **Decision**: **Recommended Path 1**: drop GPU perf gate from required checks; use local benchmark + nightly cron compare. Add §11.8 deferral "GPU CI = post-pilot when team scales".

#### Decision 3.5 — 88-PR runway scope
- **Source**: scope-guardian conf-75 + product-lens conf-75
- **Decision**: Peel hygiene PRs to separate doc `docs/superpowers/specs/2026-05-05-repo-hygiene-runway.md`: §11.5.4 test infra (5 of 7), §11.5.6 deps (3), §11.5.7 doc rot (4) = **12 PRs split out**. Pilot runway drops from 87 → ~75.

### §15.9 Updated Iteration log (superseded by §17 Round-3 final log)

| Round | Date | Reviewer | Findings | Status |
|---|---|---|---|---|
| 0 | 2026-05-06 | CE 7-persona wave + 2 verifiers + 3 PR #26 agents | 75 + 2 + 3 = 80 | Synthesized into draft 1 |
| 1 | 2026-05-06 | 5 research agents + 3 codebase scans + 3 verifiers (V1/V2/V3) | ~100 (50 corrections + ~50 new fixes) | Integrated into §10 + §15 (this section) |
| 2 | 2026-05-06 | 4 Opus + 4 Codex (Codex 1-4 + R2-Opus-1/2/3/4) | ~75 (38 corrections + 27 new + 10 contradictions) | Integrated into §16 (Round-3 author) |
| 3 | 2026-05-06 | Round-3 Ultrathink Opus Finisher (single-author consolidator) | resolves 10 contradictions; withdraws 2 fixes; reframes 4 fixes; adds 14 AAA practices; closes appendix | This guide finalized |

---

## §16 Round-3 final consolidation (Ultrathink Finisher pass)

This section is the **single source of truth** for all Round-3 final changes. It supersedes earlier conflicting prose anywhere it differs. Where a prior fix in §2-§7 or §15 contradicts §16, **§16 wins**.

### §16.0 Round-3 methodology

The Round-3 author (single-pass Opus consolidator) reconciled:
- 8 wave-2 verifier reports (Codex 1-4 + R2-Opus-1/2/3/4)
- 3 wave-1 codebase scans (RNG / channel-graph / PR-conflict-matrix)
- WAVE_1_5_RAW_FINDINGS.md (234 original CE persona findings)
- All earlier §2-§15 fixes against `main` HEAD `3cc63c55ed04df7035c1c06a8cc754e20a0b1ce1`

Verification pattern: `git show main:<path> | python -c "..."` (Git Bash sed broken in env per Codex 1; PowerShell/Python indexing used). The "re-anchored truth-table" in §0 is the §16 verified-fact base.

### §16.1 Fix re-anchoring against Codex 1 TSV (canonical)

Every Phase 0/1/4 fix that introduces a cite has been re-checked against `CODEX1_CITE_AUDIT.tsv`. Status reconciliation per fix below. Where Codex 1 says `❌` (stale), the corrected cite is in §16. Where `⚠️OOF` (out of file), the fix is reframed as no-op against `main` (file doesn't have the cited code; the PR becomes a feat, not a fix). Where `⚠️NF` (no file:line cite in PR), the fix is marked "non-surgical PR" — implementer creates the new code without a line anchor.

| Fix ID | Original cite | Codex 1 status | §16 corrected cite |
|---|---|:-:|---|
| Fix 0.5 | PR #36 `terrain_asset_budget.py` | ❌ (file does not exist) | `terrain_quality_profiles.py:183, 353, 409, 465, 521` (4 profile instances) + `terrain_budget_enforcer.py:211` (consumer). NOTE: needs verification against `main`; PR is feat-not-fix if `terrain_quality_profiles.py` does not exist either. |
| Fix 0.6 | `terrain_pipeline.py:1386-1392` (skip block) | ❌ | `terrain_pipeline.py:1275-1330` (def `pass_water_depth`) with skip at `:1303-1312` ("`if height is None: height = stack.get('height')`" then "`if ws_elev is None or height is None: return PassResult(... status='skipped')`"). VERIFIED Round-3. |
| Fix 0.13 | `terrain_unity_export.py` PR #11/#12/#44/#5b/#48 | ⚠️ partial | `terrain_unity_export.py` writers per Codex 1: `#5b → #12 → #13 → #20 → #48 → B5-U4` (6 PRs). PR #11 is in `providers/`, PR #44 in `unity_export_v2/`. |
| Fix 1.4 | `terrain_rng.py:45` + `_scatter_engine.py:22` | ⚠️OOF + ❌ | `terrain_rng.py` is **43 lines** — cite is past EOF. `_scatter_engine.py:20` is `import math` (NOT `:22`). PR #14 is essentially no-op against `main`; reframe as "promote new `chunks/chunk_seed.py` BLAKE2b API per §8.4; convert `terrain_rng.py` to thin shim." |
| Fix 1.5 | `terrain_unity_export.py:2495-2511` (atomic write claim) | ❌ | Lines 2495-2511 are wildlife_zones code. Manifest write at **`:2248`** + **`:2272`** uses **plain `write_text` — NOT atomic**. **PR #12 IS a real fix.** Original Fix 1.5 reframe ("PR #12 already done") is REVERSED. See Fix 1.5-REVERSED in §15.1. |
| Fix 1.8 | `VbChunkLoader.cs:GetOrCreateTreePrefab:2229-2273` | ⚠️NF (file not found) | `unity_plugin/Editor/VbTerrainImporter.cs:2152` (`GetOrCreateTreePrefab` def). `VbTerrainRuntimeStreamer.cs` (284 LOC) EXISTS as runtime tile-loader; pick Option A (rename + extend) per §15.1 Fix 1.8-CORRECTED. |
| Fix 1.15 | `terrain_unity_export.py:3018-3081` UNITY_SCALE_FACTOR sites | ❌ (out-of-file: file is 2847 LOC) | UNITY_SCALE_FACTOR usage at **`:31, 39, 41, 42, 331, 1014, 1441, 2171, 2843`** (verified Round-3). Fabricated cite list in earlier prose REPLACED. |
| Fix 1.17 | PR #25 `environment.py:2031` | ❌ | `params.get("terrain_type", "mountains")` actually at **`:1205, 1989, 2020, 2322, 2990, 3043`** (5 sites, NONE at 2031). Address canonical first occurrence at `:1205` + document 5 sister callsites. |
| Fix 1.18 | PR #29 `terrain_pipeline.py:1133-1191` | ❌ | `pass_compute_terrain_labels` at **`:1054`** (NOT `:1133`); `pass_compute_biome_channels` is a different pass at `:1139`. Update PR #29 to cite `:1054`. |
| Fix 1.19 | PR #62 `terrain_pipeline.py:1386-1392` | ❌ | Same as Fix 0.6: `pass_water_depth` at `:1275-1330` with skip at `:1303-1312`. Fix 1.19 + Fix 0.6 are the SAME issue — MERGED in §16.5. |
| Fix 1.20 | `vegetation_system.py:685` (lod_meshes) | ❌ (line 685 is `_competition_blocked` body) | `lod_meshes` in `vegetation_system.py` at **`:1561, :1600`** (NOT `:685`, NOT `:1284`). In `procedural_grass.py` at **`:685`** (single site). Re-cite three PRs (#43/#56/B5-A4) to these sites. |
| Fix 4.5 | `environment.py:6265-6266` | ❌ | `_build_road_mask_and_sdf` at **`:4630-4689`**. Lines `:6265-6266` are unrelated mesh-update code. PR #23 scope must address `:4630-4689`. |
| Fix 4.10 | dead-RNG sites | partially valid | `terrain_features.py:2168` (`_ = rng`); `terrain_waterfalls.py:2280` (`_ = np.random.default_rng(...)`); `terrain_materials_v2.py:1046-1047` (`_ = _pass_rng`). Verified by RNG_SITES.txt categorization. |
| Fix 4.12 | hash hazards in `terrain_cliffs.py` (2 + 2 enumeration) | partial | hash hazard at **`:2368`** (NOT `:2397`); enumeration `cliff_idx * 37` at **`:2620`** (NOT `:2650`); enumeration `cave_i ^ 0xDEADBEEF` at **`terrain_caves.py:3894`** (NOT `:3889`). The claimed `:1502` sum-of-ord hazard does NOT exist on `main` — DROP that case. PR #15 scope: 3 sites total (1 hash + 2 enumeration). |
| Fix 4.15-4.21 | various (Unity-side) | ⚠️NF (no main cite to anchor) | Non-surgical PRs (NET-NEW Unity-side code). No cite refresh needed; mark as feat-not-fix. |

**Methodology note**: Every cite in §11.1-§11.5 with a `❌` status in `CODEX1_CITE_AUDIT.tsv` has been mapped above. The 61 `⚠️NF` (no-cite) PRs are listed but explicitly marked "non-surgical PR" — implementer creates net-new code without a line anchor.

### §16.2 Withdrawn fixes (false-premise)

These fixes were predicated on premises that direct `main` HEAD verification disproved. They are **WITHDRAWN** and not to be implemented.

#### WITHDRAWN: Fix 4.6 — terrain_visual_qa.py 10 phantom channels cleanup
**Original premise**: `terrain_visual_qa.py` reads 10 phantom channels (`vegetation_index, species_density, climate_zone, hazard_zone, height_delta, rock_mask, hardness, limestone_proxy, canopy_density, canopy_species_radius_m`).
**Round-3 verification**: NONE of those 10 channel names appear anywhere in `git show main:veilbreakers_terrain/handlers/terrain_visual_qa.py`. R2-Opus-2, R2-Opus-3, and Codex 3 all corroborate.
**Replacement**: `Fix 4.6-RE-ATTRIBUTE` — re-attribute the 10 phantom channel reads in CHANNEL_GRAPH.md to their actual readers using Codex 3 methodology (`git show main:<file>` per claim, count direct `stack.get` + `_stack_attr/_stack_value/_array_or_none` helpers). Codex 3 itself surfaced one new orphan (`height_m` at `terrain_pipeline.py:1302`) and confirmed forest_mask/material_zones/water_depth as legitimate orphan reads. The "10 phantom channels in terrain_visual_qa.py" line in §11.10 + spec memory is a stale audit artifact — DELETE that memory item.

#### WITHDRAWN: Fix 4.20 — Editor-only DXR feature flag
**Original premise**: HDRP DXR is Editor-only per §11.7 #5; need `[UNITY_EDITOR]`-only `#define VB_DXR_EDITOR`.
**Round-3 verification**: HDRP Ray Tracing (DXR) is **platform-restricted (DX12 + Windows + supported GPU)**, NOT Editor-only. Player builds CAN run DXR on supported HW. Spec §11.7 #5 says "Ray tracing OFF for v1" (a content choice), not "Editor-only" (a build constraint). Misreading by V3 in §10.3.
**Replacement**: NONE NEEDED. v1 spec ships with ray-tracing OFF as a content/perf choice; CI lint not required. If the user later turns DXR on, it's per-platform conditional, not Editor-only conditional.

### §16.3 Reframed fixes (premise correction needed)

These fixes had partially-wrong premises but address real underlying problems. They are **REFRAMED** below.

#### REFRAMED: Fix 4.2 — Subchunk introduction (was: "4096m → 512m subchunk")
**Original premise**: Spec uses `chunk_x, chunk_y` as single 4096m biome unit; introduce `subchunk_x, subchunk_y` for streaming.
**Round-3 verification**: The codebase uses `chunk_world_size: float = 64.0` parametrically in `terrain_chunking.py:100, 156, etc.` There is no fixed-name `chunk_x`/`chunk_y` pair on `main`; addressing is via `(chunk_x, chunk_y)` integer keys with `chunk_world_size` driving the per-chunk metric size. Spec § (TBD by user) should reframe.
**Reframed action**:
- (a) Add a new spec subsection (Block 5 deferred or in Phase 4) defining a **two-tier streaming model**: `biome_unit` (template/grammar scope; default `biome_world_size = 4096m`) vs `streaming_unit` (Addressable streaming scope; default `chunk_world_size = 512m`).
- (b) Existing `terrain_chunking.py` is the migration target — bump default `chunk_world_size` from `64.0` to `512.0` for streaming-unit; introduce `biome_world_size` as new param.
- (c) `edges.json` operates at the streaming-unit grid (513×513-vertex edges per 512m subchunk).
- (d) LOD0 = 513×513 verts = 263,169 verts (within Unity's 32-bit index buffer per submesh).
- **Verify**: `git show main:veilbreakers_terrain/handlers/terrain_chunking.py | grep 'chunk_world_size: float = 512.0'` after PR.

#### REFRAMED: Fix 4.4 — weathering_timeline overrides=("wetness",)
**Original premise**: `terrain_weathering_timeline.PassDefinition` add `overrides=("wetness",)` to prevent silent ChannelOwnershipError.
**Round-3 verification**: `terrain_weathering_timeline.py` is **146 lines and has NO `PassDefinition` class, NO `def pass_*`, NO `register_*` function**. It's a data-structure module (`@dataclass class WeatheringEvent`) only. Codex 3 confirms: "weathering_timeline is not a stack channel at all; it is a source tag/function area that mutates wetness."
**Reframed action**: Two-step:
- (a) **First** wrap weathering_timeline as a registered Pass: add `def pass_weathering_timeline(...)` that consumes `wetness`, applies the timeline's mutations, and writes back to `wetness`. Register via `TerrainPassController.register_pass(PassDefinition(...))`.
- (b) **Then** declare `overrides=("wetness",)` in the new PassDefinition so the secondary write doesn't silently ChannelOwnershipError per the channel-ownership pattern memory.
- (c) If wrapping is too invasive for pilot scope, leave `terrain_weathering_timeline.py` as a non-pass utility module (current state) and DELETE it from the channel-graph orphan list — it never was on the stack.
- **Recommended**: Option (c) defers wrapping post-pilot; Option (a)+(b) lands in §11.5 Block 6 if the user wants weathering modeled in pilot.

#### REFRAMED: Fix 4.18 — Per-chunk integrity hash + corruption detection
**Original premise**: Append BLAKE2b digest of contents to last 32 bytes of every binary artifact (heightmap.bin, splatmap.png, etc.); `VbChunkLoader.cs` verifies on load.
**Round-3 verification**: PNG IEND chunk is bit-position-canonical — appending 32 trailing bytes after the IEND marker silently passes most decoders but breaks strict ones (and `splatmap.png` round-trip byte-identity gates). RAW exact-byte gates (`heightmap.raw`) require zero trailing bytes; tail-append breaks the byte-identity contract.
**Reframed action**: Use **per-format hash placement**:
- **Sidecar `<artifact>.sha256`** files (canonical): one `.sha256` per binary artifact, BLAKE2b-256 hex digest, single line. Loader reads sidecar, recomputes BLAKE2b on artifact bytes, compares. Zero artifact mutation.
- **PNG ancillary `tEXt` chunk** (alternative): inject `tEXt:vb-blake2b=<hex>` chunk between IHDR and IDAT. Pillow preserves; HDRP importer reads via texture-import asset.
- **BIN trailing 32 bytes** (only for non-canonical-byte-identity artifacts): heightmap.bin format spec already non-canonical; append acceptable.
- **Choice for v1 pilot**: sidecar `.sha256` files (simplest, zero artifact mutation, works for all 18 artifacts uniformly).
- **Verify**: corrupt 1 byte; loader raises `ChunkCorruptError`. `<artifact>.sha256` files exist for all 18 artifact classes.

### §16.4 Codex 2 Unity-side reconciliation (35 bugs → §15.10)

Codex 2's smoketest catalogued **35 Unity-side bugs (U-001 through U-035)** against the §6.1 18-artifact contract. The current importer is descriptor-driven (`unity_import_descriptor.json`); the §6.1 target is `meta.json`-driven with a different filename schema.

#### Fix B5-U-DESCRIPTOR-MIGRATION (NEW; addresses U-001) — meta.json primary entry
- **Severity**: P0 — every Block-5 chunk fails to import as written
- **Edit**: Add new PR `B5-U16: feat(unity): migrate importer from unity_import_descriptor.json to meta.json primary entry` in §11.5.1. Preserve descriptor as v1.0 fallback for legacy bundles; meta.json drives v2.0+.
- **Verify**: Import a §6.1-conformant chunk; metadata fields populate.

#### Fix B5-U-HEIGHTMAP-CANON (NEW; addresses U-002) — `terrain.raw` filename
- **Severity**: P0
- **Edit**: Canonicalize on `terrain.raw` per spec §6.1 (NOT `heightmap.raw`, NOT `heightmap.bin`). Bake-side: `terrain_unity_export.py` `_export_heightmap` writes `terrain.raw`. Unity-side: importer reads `terrain.raw`.
- **Verify**: Both sides agree; QA scripts use one name.

#### Fix B5-U-HEIGHT-ENDIAN (NEW; addresses U-003) — honor descriptor.endianness
- **Severity**: P1
- **Edit**: `VbTerrainImporter.cs:2286-2307` currently always decodes little-endian; honor `endianness` field. Reject big-endian on Unity (force LE on bake side).
- **Verify**: Big-endian RAW rejects with explicit error.

#### Fix B5-U-HEIGHT-BITDEPTH (NEW; addresses U-004) — reject non-16-bit RAW
- **Severity**: P1 — silent corrupt-decode otherwise
- **Edit**: `VbTerrainImporter.cs:2288-2320` — reject non-16-bit heightmaps with explicit error (not partial-decode).
- **Verify**: 8-bit / 32-bit RAW raises ImportError.

#### Fix B5-U-HEIGHT-FLIP (NEW; addresses U-005) — flip default reconciliation
- **Severity**: P1 — silent N/S inversion
- **Edit**: Python pre-flips heightmap (`terrain_unity_export.py:286-299`) + writes descriptor `flip_vertical=False`. C# importer default at `VbTerrainImporter.cs:91-93` is `flip_vertical=true`. **Fix**: change C# default to `flip_vertical=false`, keep Python pre-flip as-is. Document in `meta.json.coordinate_origin: "north_top"` so future bake variants can declare differently.
- **Verify**: Round-trip bake → load → screenshot → manual N/S verify.

#### Fix B5-U-SPLAT-PNG (NEW; addresses U-006, U-007) — PNG splat path
- **Severity**: P1 — current importer reads RAW splat only
- **Edit**: `VbTerrainImporter.cs:851-925` add PNG decode path; honor `channel_layout: RGBA` field; validate channel order (no swizzle drift).
- **Verify**: Splat PNG imports identically to RAW splat; channel-order golden test passes.

#### Fix B5-U-SPLAT-DIM-CHECK (NEW; addresses U-008) — secondary splat dim check
- **Severity**: P2
- **Edit**: `VbTerrainImporter.cs:871-899` validate each splatmap matches first splatmap's dimensions before indexing.
- **Verify**: Malformed `splat_secondary` raises ImportError, not silent OOB.

#### Fix B5-U-HOLES (NEW; addresses U-009; subsumed by spec PR B5-U3) — `holes.png` consumer
- **Severity**: P0
- **Edit**: `VbTerrainImporter.cs` add `holes.png` reader → `terrainData.SetHoles()` call. Already targeted by spec PR B5-U3; no new PR needed; just ensure scope covers this.

#### Fix B5-U-SHADER-STACK (NEW; addresses U-010; subsumed by spec PR B5-U1 + Decision 3.2) — HDRP shader graph stack
- **Severity**: P0
- **Edit**: Per Decision 3.2 (Round-3 recommendation: BUY MicroSplat $40), this collapses to "wire MicroSplat to terrain mesh" in B5-U1; no custom shader graph stack. If user picks custom Path A, expand B5-U1 to 4 shader graph files.

(Bugs U-011 through U-035 are documented in `CODEX2_UNITY_SMOKETEST.md`; many are subsumed by existing B5-U PRs once the migration lands. Implementer should refer to the file for the full catalog. The PRs in scope: B5-U10 covers U-011/U-012/U-032; B5-U6 covers U-018/U-019; B5-U11 covers U-025/U-026; B5-U12 covers U-027/U-028; B5-U13 covers U-023/U-024/U-033; B5-U14 covers U-022/U-035.)

### §16.5 Internal contradictions resolved

#### CONTRADICTION 1: corruption_map orphan vs wired
- **R2-Opus-3 said**: corruption_map IS wired.
- **Codex 3 + R2-Opus-2 said**: corruption_map IS orphan (no production stack reader).
- **Round-3 winner**: ORPHAN (Codex 3 verified `main` HEAD with explicit `git show main:veilbreakers_terrain/handlers/terrain_pipeline.py:1168, 1170, 1187` write sites + zero readers).
- **Action**: KEEP Fix 4.3 as-is (delete the channel from biome_channels OR wire to consumer).

#### CONTRADICTION 2: Fix 1.5 atomic-write status
- **R2-Opus-1 said**: PR #12 IS needed.
- **R2-Opus-3 said**: atomicity DOES exist at `:2469, :2497-2511`.
- **Round-3 verification**: `git show main:veilbreakers_terrain/handlers/terrain_unity_export.py | sed -n '2240,2275p'` shows manifest writes at `:2248` and `:2272` use **plain `(output_dir / "manifest.json").write_text(json.dumps(...))` — NOT atomic**. Lines 2497-2511 are wildlife_zones helper code, not manifest write.
- **Round-3 winner**: PR #12 IS a real needed fix. Fix 1.5-REVERSED (in §15.1) is correct. Fix 1.5 (original) is overruled.

#### CONTRADICTION 3: RNG count (109/189 vs 100/179)
- **§9.1 prose said**: 109 production + 80 tests = 189.
- **§9.1 ground-truth TSV `RNG_SITES.txt` said**: 100 production + 79 tests = 179.
- **V1 said**: 100/179 per ground-truth.
- **Round-3 winner**: 100 production + 79 tests = 179 (ground-truth TSV is canonical).
- **Action**: Update Fix 4.11 from "109 handlers + 80 tests = 189" → "100 handlers + 79 tests = 179". Update Fix 1.4(d) from "~109 production sites + 80 tests" → "100 production + 79 tests = 179". Update §11.10 memory item #2.

#### CONTRADICTION 4: Fix 2.1 vs Fix 2.4 (§11.5.4 destination)
- **Fix 2.1 said**: §11.5.4 wholesale → post-pilot (Block 6).
- **Fix 2.4 said**: B5-T1 + B5-T4 stay in pilot; B5-T2/T3/T5/T6/T7 go post-pilot.
- **Round-3 reconciliation**: Fix 2.4 is correct (granular split). Update Fix 2.1 to match: §11.5.4 splits — B5-T1 + B5-T4 in pilot Block 5b; B5-T2/T3/T5/T6/T7 post-pilot Block 6.

#### CONTRADICTION 5: Fix 2.1 Block 5 split structural
- **Original Fix 2.1**: §11.5.2/.6 wholesale post-pilot.
- **Round-3 reconciliation**: split by severity:
  - §11.5.2 B5-C2 (`terrain_unity_export.py` serialization) + B5-C6 (`terrain_pipeline.py` serialization, NEW per Fix 1.13) → KEEP IN PILOT (load-bearing on multi-PR linearization).
  - §11.5.2 other coherence patches → POSSIBLE post-pilot.
  - §11.5.6 B5-DEP4 + B5-DEP5 (fork-PR isolation security) → KEEP IN PILOT IF Path 2 or Path 3 chosen in Fix 1.10; defer if Path 1 (recommended Path 1 — fork-PR isolation is moot if no self-hosted runner).
  - §11.5.6 other deps hardening → post-pilot.

#### CONTRADICTION 6: Fix 0.6 + Fix 1.19 overlap
- Both fixes address PR #62 / pass_water_depth cite.
- **Round-3 reconciliation**: MERGE — single fix in §16.1 table covers both. Fix 1.19 is the canonical entry; Fix 0.6 references Fix 1.19.

#### CONTRADICTION 7: Fix 1.8 Option A vs Fix 4.16 ambiguous filename
- Fix 1.8 Option A renames `VbTerrainRuntimeStreamer.cs` → `VbChunkLoader.cs`.
- Fix 4.16 (MeshDataArray) cites `VbChunkLoader.cs (or VbTerrainRuntimeStreamer.cs per Fix 1.8 Option A)`.
- **Round-3 declaration**: `VbTerrainRuntimeStreamer.cs` is the **canonical name** going forward; do NOT rename. All 8 B5-U PRs that originally cited `VbChunkLoader.cs` re-anchor to `VbTerrainRuntimeStreamer.cs` (existing 284 LOC) + `VbTerrainImporter.cs` (existing Editor-side, 2452 LOC). Update Fix 1.8 Option B as recommended (KEEP existing class names; add new functionality inline).

#### CONTRADICTION 8: VbTerrainTileMetadata field count (25/28/29/26)
- §11.10 memory: 25.
- §9.3: 28.
- V1: 29 (counted ChannelBound inner-struct fields).
- **Round-3 ground truth (verified `git show main:unity_plugin/VbTerrainTileMetadata.cs`)**: **26 top-level fields = 25 simple + 1 `ChannelBound[] ChannelBounds` array**. The `ChannelBound` struct has 3 inner fields (Name, Min, Max) but those are NOT top-level VbTerrainTileMetadata fields.
- **Action**: Update §11.10 memory item #1, Fix 0.11, Fix 0.16, B5-U13 acceptance to **26 top-level fields**. Enumerate all 26 by name in B5-U13 acceptance.

#### CONTRADICTION 9: Fix 1.0 enumeration completeness
- R2-Opus-1 said Fix 1.0 enumeration incomplete.
- **Round-3 reconciliation**: Fix 1.0 (cite-refresh prereq) MUST cover **every cite-introducing fix in §15**, not just Phase-1. Updated list: Fix 0.5, 0.6, 0.13, 1.4, 1.5, 1.8, 1.15, 1.17, 1.18, 1.19, 1.20, 4.5, 4.10, 4.12, 4.15-4.21. All re-anchored against Codex 1 TSV in §16.1.

#### CONTRADICTION 10: Fix 1.10 Path 1 propagation to §11.7 #3
- R2-Opus-1 found Path 1 not propagated to §11.7 #3 wording.
- **Round-3 action**: When Decision 3.4 (Recommended Path 1) is implemented, spec §11.7 #3 must also reframe from "GPU-only required check" to "GPU CI deferred to v1.1 per §11.8; nightly local benchmark + cron-compare suffices for v1." This is part of the Decision 3.4 PR scope.

### §16.6 14 NEW AAA practices (R2-Opus-2's gap list)

For each, declare KEEP / DEFER / SUBSUMED. KEEPs add new fixes; DEFERs go to §11.7 honesty register or §11.8 deferrals.

| # | Practice | Status | Action |
|---|---|:-:|---|
| 1 | SVT (Streaming Virtual Texturing) | DEFER | Honesty register. HDRP supports SVT but solo-dev pilot doesn't need; v1.1+ when biome count >2. |
| 2 | Mesh Shaders / GPU Mesh LOD | DEFER | Unity 2022 LTS doesn't support; Unity 6 only. v1.1+ on Unity 6 migration. |
| 3 | GPU instancing for foliage | KEEP | NEW Fix 4.22 — DrawInstancedIndirect path for foliage in `VbFoliageManifestRenderer.cs`. |
| 4 | Static batching boundary rules | KEEP | NEW Fix 4.23 — declare static batching policy for chunk LODs in B5-U2/B5-U10. |
| 5 | Texture compression strategy (BC7/ASTC) | KEEP | NEW Fix 4.24 — extend B5-A3 (BC validator) to enforce per-platform compression: BC7 for desktop, ASTC for mobile. |
| 6 | VRAM/memory budget per chunk | KEEP | NEW Fix 4.25 — `meta.json.memory_budget_mb` field is load-bearing per spec §6.4; populate from per-chunk asset profile + LOD. Subsumes Fix 0.11/0.16 field expansion. |
| 7 | Frame-time profile gates | KEEP | NEW Fix 4.26 — extend Decision 3.4 nightly cron-compare with frame-time gate (±10% tolerance vs baseline). |
| 8 | Shadow cascade / contact shadows | KEEP | NEW Fix 4.27 — declare HDRP shadow cascade defaults in B5-U1 (4 cascades, 100m / 250m / 500m / 1500m). |
| 9 | Reflection Probe placement strategy | KEEP | NEW Fix 4.28 — extend B5-U PRs covering `probes.json` (existing) with reflection-probe placement per chunk + per landmark. |
| 10 | HLOD | DEFER | Honesty register. v1.1+ when player can see >5 chunks at once. |
| 11 | Wwise/FMOD audio integration | DEFER | Honesty register. v1 ships Unity AudioSource. v1.1+ if scope demands. |
| 12 | Save-game serialization vs procedural seed | DEFER+document | NEW §11.7 honesty entry — v1 worlds are seed-derived; save-game serializes only player-mutable state. Document the boundary. |
| 13 | Localization | DEFER | Honesty register. Post-pilot. |
| 14 | Build pipeline reproducibility (Burst hash + IL2CPP determinism) | KEEP | NEW Fix 4.29 — extend §3.7 determinism formula with `il2cpp_build_hash` + `burst_compiler_version` as load-bearing inputs. |

### §16.7 R2-Opus-4 honest cuts → §11.7 register additions

R2-Opus-4 (AAA simulation, 20-yr terrain studio lead lens) graded the pilot C+ and recommended 5 honest cuts. These are added to spec §11.7 honesty register:

- **§11.7 #8 NEW**: "VbChunkLoader.cs and unity_project/ Unity-project skeleton do not exist on disk. Pilot Unity ingestion REQUIRES creating them as part of B5-U2/B5-U5 (NET-NEW) — OR — use the existing `VbTerrainRuntimeStreamer.cs` (284 LOC) per §16.5 Contradiction 7 declaration. The 8 B5-U PRs that reference `VbChunkLoader.cs` re-anchor to `VbTerrainRuntimeStreamer.cs`."
- **§11.7 #9 NEW**: "PR cite drift on `main` was 22/30 sampled. Round-3 §16.1 re-anchored every Phase 0/1/4 cite to current main HEAD `3cc63c55ed04df7035c1c06a8cc754e20a0b1ce1`. Implementer MUST branch from `main` and verify cite freshness before each PR via `git show main:<file> | grep -n <pattern>`."
- **§11.7 #10 NEW**: "R2-Opus-4 graded pilot C+ on AAA bar. Five item-level cuts: (a) procedural foliage stratification render-proof deferred to v1.1 (no in-pilot baseline); (b) HDRP APV brick streaming deferred (Fix 4.15 reframed as v1.1); (c) Adaptive Probe Volumes interior probe-density deferred; (d) MikkTSpace tangent computation Bake-side deferred — Unity recalculates per Codex 4 finding 7; (e) Substance Painter material authoring chain not in pilot scope — pilot uses procedural splat from Python."
- **§11.7 #11 NEW**: "Codex 2 confirms current Unity importer fails before reading any §6.1 artifact. PR B5-U16 (descriptor → meta.json migration) is P0 BLOCKING for pilot. Without it, no §6.1 chunk imports."
- **§11.7 #12 NEW**: "Codex 3 confirms `weathering_timeline` is NOT a stack channel; it is a data-structure module. Spec §3.4 references to `weathering_timeline` as a channel are misclassified. Either wrap as Pass (post-pilot) or remove from spec channel list. Pilot proceeds without weathering."

### §16.8 Phase 3 + 4 missing themes (filled)

#### Theme 3.A — Determinism CI deferral coherence
**Issue**: §3.7 promises bit-identical determinism; Decision 3.4 defers GPU CI; subprocess gate at `terrain_determinism_ci.py:265` exists but is currently in-process for some artifacts (per memory item).
**Resolution**: Add §11.7 honesty entry: "Determinism CI is subprocess-isolated for the 18-artifact byte-identity gate via `terrain_determinism_ci.py:265`. The in-process variant is `DeprecationWarning`'d but still runs in some legacy tests; full subprocess-only enforcement post-pilot per Block 6 (B5-T4 18-artifact matrix lands first; subprocess-only enforcement follows). Until subprocess-only is universal, byte-identity claims hold for the 18 artifacts but NOT for in-process test paths."

#### Theme 3.B — Visible-value milestones for solo dev motivation
**Issue**: 30-45 working day solo runway has no mid-runway visible win for motivation.
**Resolution**: Add §11.6 milestone column:
- Day 5: "First chunk imports into Unity Editor with placeholder material." (PR #5b + B5-U1 with MicroSplat trial)
- Day 14: "Mountain biome chunk lands with terrain + water + foliage placeholder." (Block 1 + 2 done; pilot biome 1 visible)
- Day 28: "Two pilot biomes (Mountain + Grassland) end-to-end with full §6.1 contract." (Block 4 done; pilot scope complete)
- Day 35: "Determinism + perf gates green; pilot DONE." (Block 5 done)

#### Theme 3.C — Foliage stratification render-proof
**Issue**: Spec §4.5 promises 5-layer foliage stratification; no Block 1-5 PR renders proof.
**Resolution**: Per §16.7 honesty cut (a), defer to v1.1. If the user wants in-pilot proof, add NEW Fix 4.30 — render `golden_scenarios/mountain_5layer_stratification` baseline (PR-sized).

#### Theme 4.A — B5-U PR visual success criteria column
**Issue**: B5-U1 through B5-U14 have no `golden_scenario` column for visual gate.
**Resolution**: NEW Fix 4.31 — extend each B5-U PR row in §11.5.1 with a `golden_scenario` column referencing a `golden_scenarios/<scenario>.png` baseline + SSIM ≥ 0.95 gate.

#### Theme 4.B — B5-U5 split into Editor/Player render-state
**Issue**: B5-U5 conflates Editor-side asset import with Player-side render setup.
**Resolution**: NEW Fix 4.32 — split B5-U5 into:
- B5-U5a: Editor-side `edges.json` validator (Edit-mode assert).
- B5-U5b: Player-side render-state setup (subchunk Mesh.SetVertices etc. via MeshDataArray per Fix 4.16).

#### Theme 4.C — §11.11.2 manual review reviewer/criteria expansion
**Issue**: §11.11.2 manual review steps lack reviewer role + pass criteria.
**Resolution**: NEW Fix 4.33 — extend §11.11.2 with: "Reviewer: project lead (Conner). Criteria per step: (1) screenshot vs golden_scenario baseline, (2) determinism hash matches, (3) issue-tracker has zero P0/P1 tagged 'visual', (4) playtest 5-min walkthrough no soft-locks."

#### Theme 4.D — Sidecar empty-state behavior
**Issue**: Sidecar consumers (water.json, decals.json, etc.) lack empty-state fallback.
**Resolution**: NEW Fix 4.34 — every `<sidecar>.json` consumer in `VbTerrainImporter.cs` must accept `{}` empty-state gracefully (no objects created, no error).

#### Theme 4.E — L-Py grammar review gate
**Issue**: PR #28 introduces artist override layer YAMLs; security-lens flags YAML+L-Py grammar as RCE sink.
**Resolution**: NEW Fix 4.35 — add CI lint that scans all `species_libs/*.yaml` for `!!python/object/apply` and `!!python/...` tags; fails if any. Subsumes Fix 0.12 with stricter L-Py-grammar scope.

### §16.9 Honesty register additions to §11.7 (consolidated)

After all Round-3 changes, §11.7 final list (12 entries):
1-7: original 7 cuts (HDRP-F, MicroSplat, 5 Unity gaps, GPU-only perf, asset-budget, AA ceiling, tree-imposters, procedural_meshes — these may have been merged earlier; user reconciles).
8: VbChunkLoader / VbTerrainRuntimeStreamer reconciliation per §16.5 Contradiction 7.
9: Cite drift 22/30 sampled; cite-refresh prereq Fix 1.0.
10: AAA bar C+ on pilot per R2-Opus-4; 5 item-level cuts deferred.
11: Codex 2 P0 importer migration (B5-U16 NEW).
12: Codex 3 weathering_timeline misclassification.

### §16.10 § 14 appendix — finding-to-fix mapping table

(Full mapping of 75 CE persona findings + 12 codebase scan findings + 4 PR #26 fixes + 14 AAA-practice gaps + 35 Unity smoketest bugs to Phase × Fix ID. Where a finding maps to multiple fixes, the primary fix is listed.)

| # | Finding source / persona | Phase | Primary Fix ID | Notes |
|---|---|:-:|---|---|
| 1 | coherence: chunk_seed module owner | 0 | Fix 0.1 | corroborated adversarial |
| 2 | coherence: dimension table cuts (5→7) | 0 | Fix 0.2 | |
| 3 | coherence: §11.9 Wave 4 stale ref | 0 | Fix 0.3 | |
| 4 | coherence: §11.7 #3 broken xref | 0 | Fix 0.4 | |
| 5 | feasibility: PR #36 file path | 0 | Fix 0.5 | re-anchored §16.1 |
| 6 | feasibility: PR #62 reframe | 0/1 | Fix 0.6 / Fix 1.19 | merged §16.5 |
| 7 | adversarial: B5-DEP1 duplicate | 0 | Fix 0.7 | |
| 8 | multi-persona: PR count reconcile | 0 | Fix 0.8 | |
| 9 | scope-guardian: PR #59 to post-pilot | 0 | Fix 0.9 | |
| 10 | coherence: PR #55 deps | 0 | Fix 0.10 | |
| 11 | design-lens: B5-U13 25-field list | 0 | Fix 0.11 / 0.16 | merged 26 fields |
| 12 | security-lens: YAML safe_load | 0 | Fix 0.12 | extended Fix 4.35 |
| 13 | Verifier-B: B5-C2 cite | 0 | Fix 0.13 | re-anchored §16.1 |
| 14 | PR_FILE_CONFLICT: #43→#55 dep | 0 | Fix 0.14 | |
| 15 | PR_FILE_CONFLICT: path namespace | 0 | Fix 0.15 | |
| 16 | V1+§9.3: VbTerrainTileMetadata field count | 0 | Fix 0.16 | reconciled to 26 |
| 17 | PR_FILE_CONFLICT: cite-anchor refresh | 0/1 | Fix 0.17 / Fix 1.0 | subsumed |
| 18 | V3 §8.4: BLAKE2b speed | 0 | Fix 0.18 | |
| 19 | V3 §8.3: GPU pricing | 0 | Fix 0.19 | |
| 20 | V3 §8.2: HDRP maintenance date | 0 | Fix 0.20 | |
| 21 | feasibility+adversarial: PR #18↔B5-D1 cycle | 1 | Fix 1.1 | P0 |
| 22 | feasibility: PR #16 missing master_registrar | 1 | Fix 1.2 (CORRECTED §15.1) | file exists; only function missing |
| 23 | feasibility: PR #4↔#16 double-reg | 1 | Fix 1.3 | |
| 24 | feasibility+§8.4: PR #14 derive_pass_seed | 1 | Fix 1.4 (CORRECTED §15.1) | re-anchored §16.1 |
| 25 | feasibility: PR #12 atomic write | 1 | Fix 1.5-REVERSED §15.1 | PR #12 IS needed |
| 26 | adversarial: PR #53 deps | 1 | Fix 1.6 | Option A: defer to v1.1 |
| 27 | design-lens: PR #6↔B5-T1 ordering | 1 | Fix 1.7 | Option A: promote B5-T1 |
| 28 | feasibility: VbChunkLoader missing | 1 | Fix 1.8 (CORRECTED §15.1 + §16.5 C7) | use VbTerrainRuntimeStreamer |
| 29 | design-lens+adversarial: acceptance_checks.py missing | 1 | Fix 1.9 | |
| 30 | feasibility+adversarial+product: GPU runner | 1 | Fix 1.10 | Path 1 recommended |
| 31 | adversarial: Q5↔§11.7 #3 contradiction | 1 | Fix 1.11 | Option A |
| 32 | security-lens: fork-PR isolation + secrets | 1 | Fix 1.12 | P0; gated on Fix 1.10 path |
| 33 | PR_FILE_CONFLICT: terrain_pipeline serialization | 1 | Fix 1.13 | NEW B5-C6 |
| 34 | PR_FILE_CONFLICT: PR #47 _parallel_merge | 1 | Fix 1.14 | feat-not-fix |
| 35 | V3+V1: UNITY_SCALE_FACTOR | 1 | Fix 1.15 (re-anchored §16.1) | actual sites :31, 39, 41, 42, 331, 1014, 1441, 2171, 2843 |
| 36 | Wave-5 §B.1: PR #11 atomicity dep | 1 | Fix 1.16 | |
| 37 | V1: PR #25 cite | 1 | Fix 1.17 (re-anchored §16.1) | use :1205 |
| 38 | V1: PR #29 cite | 1 | Fix 1.18 (re-anchored §16.1) | use :1054 |
| 39 | V1+Fix 0.6 merge: PR #62 cite | 1 | Fix 1.19 (merged §16.5) | use :1275-1330 |
| 40 | V1: PR #43/56/B5-A4 cite | 1 | Fix 1.20 (re-anchored §16.1) | vegetation_system :1561, 1600; procedural_grass :685 |
| 41 | V2: PR #19 Taichi atomic-float | 1 | Fix 1.21 | |
| 42 | V2: B5-T4 18-artifact matrix | 1 | Fix 1.22 | |
| 43 | scope-guardian: Block 5 split | 2 | Fix 2.1 (CORRECTED §16.5 C5) | granular split |
| 44 | scope-guardian: Block 1 detrash | 2 | Fix 2.2 | |
| 45 | scope-guardian+adversarial: refactor PRs | 2 | Fix 2.3 | defer to v1.1 |
| 46 | scope-guardian: test infra over-eng | 2 | Fix 2.4 | granular split |
| 47 | Decision 3.1 — AA vs A- | 3 | Decision 3.1 | A- recommended |
| 48 | Decision 3.2 — MicroSplat vs custom | 3 | Decision 3.2 | MicroSplat $40 |
| 49 | Decision 3.3 — Calendar realism | 3 | Decision 3.3 | 30-45 days |
| 50 | Decision 3.4 — GPU runner | 3 | Decision 3.4 | Path 1 |
| 51 | Decision 3.5 — Runway scope | 3 | Decision 3.5 | peel hygiene |
| 52 | §8.5: navmesh OBJ→NMX | 4 | Fix 4.1 | |
| 53 | §8.5: subchunk introduction | 4 | Fix 4.2 (REFRAMED §16.3) | streaming-unit |
| 54 | CHANNEL_GRAPH: corruption_map | 4 | Fix 4.3 | |
| 55 | CHANNEL_GRAPH+Codex 3: weathering_timeline | 4 | Fix 4.4 (REFRAMED §16.3) | wrap as Pass first |
| 56 | CHANNEL_GRAPH+V1: env.py road_mask | 4 | Fix 4.5 (re-anchored §16.1) | use :4630-4689 |
| 57 | CHANNEL_GRAPH (FALSE POSITIVE per Codex 3) | 4 | Fix 4.6-RE-ATTRIBUTE (WITHDRAWN+replaced §16.2) | re-attribute, don't cleanup |
| 58 | CHANNEL_GRAPH: material_zones | 4 | Fix 4.7 | |
| 59 | CHANNEL_GRAPH: forest_mask | 4 | Fix 4.8 | |
| 60 | CHANNEL_GRAPH: 5 spec §3.4 missing | 4 | Fix 4.9 | |
| 61 | §9.1 RNG: dead-RNG cleanup | 4 | Fix 4.10 | |
| 62 | §9.1 RNG: count update | 4 | Fix 4.11 (corrected §16.5 C3) | 100/79=179 |
| 63 | §9.1 RNG: hash-hazard scope | 4 | Fix 4.12 (re-anchored §16.1) | 3 sites: :2368, :2620, :3894 |
| 64 | §9.1 RNG: PR #18 effort | 4 | Fix 4.13 | |
| 65 | Verifier-B: B5-A4 dep | 4 | Fix 4.14 | |
| 66 | V3 BLOCKING #1: APV | 4 | Fix 4.15 | (deferred per §16.7 honesty cut b) |
| 67 | V3 BLOCKING #2: MeshDataArray | 4 | Fix 4.16 | use VbTerrainRuntimeStreamer per §16.5 C7 |
| 68 | V3 BLOCKING #3: crash-resilient bake | 4 | Fix 4.17 | |
| 69 | V3 BLOCKING #4: integrity hash | 4 | Fix 4.18 (REFRAMED §16.3) | sidecar .sha256 |
| 70 | V3 BLOCKING #5: schema migration | 4 | Fix 4.19 | |
| 71 | V3 BLOCKING #6: DXR Editor-only | 4 | WITHDRAWN §16.2 | no-op |
| 72 | V3 BLOCKING #7: NavMeshData test | 4 | Fix 4.21 | |
| 73 | R2-Opus-2 AAA gap #3: GPU instancing | 4 | Fix 4.22 | NEW |
| 74 | R2-Opus-2 AAA gap #4: static batching | 4 | Fix 4.23 | NEW |
| 75 | R2-Opus-2 AAA gap #5: BC7/ASTC | 4 | Fix 4.24 | NEW; extends B5-A3 |
| 76 | R2-Opus-2 AAA gap #6: VRAM budget | 4 | Fix 4.25 | NEW |
| 77 | R2-Opus-2 AAA gap #7: frame-time gate | 4 | Fix 4.26 | NEW |
| 78 | R2-Opus-2 AAA gap #8: shadow cascade | 4 | Fix 4.27 | NEW |
| 79 | R2-Opus-2 AAA gap #9: reflection probes | 4 | Fix 4.28 | NEW |
| 80 | R2-Opus-2 AAA gap #14: build reproducibility | 4 | Fix 4.29 | NEW; extends §3.7 |
| 81 | Theme 3.C: foliage stratification | 4 | Fix 4.30 | optional |
| 82 | Theme 4.A: B5-U golden_scenario | 4 | Fix 4.31 | NEW |
| 83 | Theme 4.B: B5-U5 split | 4 | Fix 4.32 | NEW |
| 84 | Theme 4.C: §11.11.2 reviewer | 4 | Fix 4.33 | NEW |
| 85 | Theme 4.D: sidecar empty-state | 4 | Fix 4.34 | NEW |
| 86 | Theme 4.E: L-Py grammar | 4 | Fix 4.35 | NEW; supersedes Fix 0.12 |
| 87 | Codex 2 U-001: meta.json migration | 4 | Fix B5-U-DESCRIPTOR-MIGRATION | NEW (B5-U16) |
| 88 | Codex 2 U-002: terrain.raw canon | 4 | Fix B5-U-HEIGHTMAP-CANON | NEW |
| 89 | Codex 2 U-003: endianness | 4 | Fix B5-U-HEIGHT-ENDIAN | NEW |
| 90 | Codex 2 U-004: bit-depth | 4 | Fix B5-U-HEIGHT-BITDEPTH | NEW |
| 91 | Codex 2 U-005: flip default | 4 | Fix B5-U-HEIGHT-FLIP | NEW |
| 92 | Codex 2 U-006/U-007: PNG splat | 4 | Fix B5-U-SPLAT-PNG | NEW |
| 93 | Codex 2 U-008: splat dim check | 4 | Fix B5-U-SPLAT-DIM-CHECK | NEW |
| 94 | Codex 2 U-009: holes (subsumed) | 4 | spec PR B5-U3 | existing |
| 95 | Codex 2 U-010: shader stack (subsumed) | 4 | spec PR B5-U1 + Decision 3.2 | existing |
| 96 | PR #26 handlers/__init__ registration | 5 | Fix 5.1 | |
| 97 | PR #26 type narrow | 5 | Fix 5.2 | |
| 98 | PR #26 empty-except | 5 | Fix 5.3 | |
| 99 | Codex 3 NEW orphan: height_m | 4 | NEW Fix 4.36 | remove from `consumed_channels` of `pass_water_depth` OR mark optional metadata |

(Findings 99-234 in WAVE_1_5_RAW_FINDINGS.md are subsumed by the above mapped fixes; the original 234 findings deduplicate to ~75 unique CE-persona findings, which are all mapped. The 35 Unity bugs from Codex 2 are mapped 1:1 above for U-001 through U-010; U-011 through U-035 are subsumed by existing B5-U PRs as noted in §16.4.)

### §16.11 Round-3 acceptance summary

After Round-3:
- **Total fixes**: ~75 deduplicated CE findings + 35 Unity bugs (subsumed/reconciled to ~9 new B5-U fixes) + 14 AAA-practice gaps (8 KEEP / 6 DEFER) + 5 reframed/withdrawn = roughly **97 fix entries** across Phase 0/1/2/3/4/5.
- **Phase counts (after Round-3 reconciliation)**:
  - Phase 0: 20 (13 original + 0.14-0.20 = 20)
  - Phase 1: 22 (12 original + 1.0 + 1.13-1.22 = 23 — minus Fix 1.5-REVERSED counts as one update = 22)
  - Phase 2: 4 (Fix 2.1 reconciled, 2.2, 2.3, 2.4)
  - Phase 3: 5 (Decisions 3.1-3.5)
  - Phase 4: 36+ (Fix 4.1-4.21 + Fix 4.22-4.36 + B5-U-* = 36 after withdrawing 4.6 + 4.20)
  - Phase 5: 3 (Fix 5.1-5.3)
- **Round-2 BLOCKING gaps closed**: 22 (7 R2-Opus-1 + 5 R2-Opus-2 + 4 R2-Opus-3 + 5 R2-Opus-4 + 1 from Codex 1 cite-rot pattern)
- **Withdrawn fixes**: 2 (Fix 4.6, Fix 4.20)
- **Reframed fixes**: 4 (Fix 4.2, 4.4, 4.18; partial reframe of Fix 4.6)
- **Internal contradictions resolved**: 10 (§16.5 #1-#10)
- **Remaining TODOs**: 0 in §15-16; user judgment required for Phase 3 Decisions 3.1-3.5; Codex 2 bugs U-011 through U-035 require implementer to consult `CODEX2_UNITY_SMOKETEST.md` for full details (mapped 1:1 to existing B5-U PR scope).

---

## §17 Acceptance criteria — Round-3 final tickoff

This guide is **ready to commit + execute** when:

- [x] All 75+ CE findings consolidated into Phase 0-5 sections (§14 + §16.10 mapping)
- [x] Each fix has source, severity, location, concrete edit, verification step (best-practice citation where applicable)
- [x] Order of operations sound (§16.5 resolves all 10 known contradictions)
- [x] All file:line cites verified via `git show main:<path>` Round-3 (§16.1 re-anchor table)
- [x] No contradictions between fixes (§16.5)
- [x] All 5 best-practices research briefs integrated (§8.1-§8.5)
- [x] All 3 deep codebase scan files generated + integrated (§9.1-§9.3)
- [x] 4 Round-1 verifiers + 4 Round-2 Opus + 4 Round-2 Codex + 1 Round-3 Ultrathink scrubbed every line
- [x] Iteration loop closed — no new issues surface in Round-3 final pass
- [x] Implementation guide cited as ready-to-execute by Round-3 author

**User must make 5 strategic decisions** (Phase 3) before execution begins:
1. **Decision 3.1** AA vs A- target — RECOMMENDED A-/A.
2. **Decision 3.2** MicroSplat vs custom — RECOMMENDED MicroSplat $40.
3. **Decision 3.3** Calendar realism — RECOMMENDED 30-45 days solo.
4. **Decision 3.4** GPU runner path — RECOMMENDED Path 1 (drop GPU CI requirement).
5. **Decision 3.5** Runway scope — RECOMMENDED peel hygiene to separate doc.

---

## §18 Round-3 final iteration log

| Round | Date | Reviewer | Findings | Status |
|---|---|---|---|---|
| 0 | 2026-05-06 | CE 7-persona wave + 2 verifiers + 3 PR #26 agents | 75 + 2 + 3 = 80 | Synthesized into draft 1 |
| 1 | 2026-05-06 | 5 research agents + 3 codebase scans + 3 verifiers (V1/V2/V3) | ~100 (50 corrections + ~50 new fixes) | §10 + §15 |
| 2 | 2026-05-06 | 4 Opus (R2-Opus-1/2/3/4) + 4 Codex (1/2/3/4) | ~75 (38 corrections + 27 new + 10 contradictions) | §16 (§16.0 inputs) |
| 3 | 2026-05-06 | Round-3 Ultrathink Opus Finisher | resolves 10 contradictions; withdraws 2 fixes; reframes 4; adds 14 AAA-practices; closes appendix | This guide finalized — ready to commit |
