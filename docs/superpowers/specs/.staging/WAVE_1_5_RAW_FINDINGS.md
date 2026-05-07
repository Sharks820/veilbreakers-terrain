# Wave 1-5 Raw Findings — Final Consolidated Reference

**Purpose:** Single-source-of-truth for the §11 v3 author + verifiers + Codex CLI final pass. Every claim has a file:line cite or a "VERIFIED-FALSE" annotation when prior wave was wrong.

**Reading order:** §A truth-foundation (Verifier-3 + Verifier-4) → §B wave-5 scans → §C surgical edits → §D new PRs → §E memory updates → §F output requirements.

---

## §A. Truth foundation (Verifier-3 forensic + Verifier-4 referee)

### A.1 Disputed-item ground truth (V3 forensic line-cite reads)

| # | Claim | Truth | Source |
|---|-------|-------|--------|
| 1 | 7-8 orphan passes in `terrain_pipeline.py:169-261` | **REAL**: cliffs, caves, coastline, karst, wind_erosion, stratigraphy, pass_water_flow_speed, pass_river_convergence absent. **ALREADY in v2 §11.1 PR #4** | V3 forensic |
| 2 | `_toposort_passes` cycle | **REAL** at `terrain_pipeline.py:1449` (no `overrides=` check). **ALREADY in v2 §11.1 PR #3** | V3 forensic |
| 3 | PYTHONHASHSEED hazard at `terrain_cliffs.py:2397` | **REAL** (`hash(cliff.cliff_id) & 0x7FFFFFFF`). **ALREADY in v2 §11.2 PR #15** | V3 forensic |
| 4 | 127 random.Random sites | **INFLATED — REAL = 47 handlers + 11 tests = 58 (or 68 with scripts).** 127 only by counting 65 doc-prose mentions | V3 forensic |
| 5 | Overhang threshold cite `terrain_cliffs.py:857-858` | **WRONG cite.** Real threshold = `radians(88.0)` at `terrain_cliffs.py:890` (60°/80° appear only in comments) | V3 forensic |
| 6 | Biome collapse cite `_terrain_world.py:861-869` | **WRONG cite.** Lines 861-869 are seed/needs_generate. Real collapse at `_terrain_world.py:2031` (`params.get("terrain_type", "mountains")`) | V3 forensic |
| 7 | Manifest atomicity cite `terrain_unity_export.py:1612, 1629` | **WRONG cite.** Cited lines are dict-key string assignments. Real fix needs the actual write site (Grep for `json.dump.*manifest`) | V3 forensic |
| 8 | `terrain_macro_color.consumed_channels=("height",)` at line 230, but reads 6 more (`biome_id`, `wetness`, `erosion_amount`, `deposition_amount`, `albedo_shift_rgb`, `snow_line_factor` + strata) | **REAL** | V3 forensic |
| 9 | `DARK_FANTASY_PALETTE` covers IDs 0-7 only | **REAL** (8 entries at lines 28-37). Biomes 8-13 fall through `pal.get(bid, default_rgb)` to biome-0 umber `(0.32, 0.30, 0.24)`, NOT grey | V3 forensic |
| 10 | Foam alpha INVERTED at `terrain_waterfalls.py:115` | **REAL — BOTH factors wrong.** `prox_ratio = 1.0 - saturate(obstacle_proximity / max(foam_radius, 1e-9))` (should be `saturate(...)`); `speed_ratio = 1.0 - flow_speed / max(max_foam_speed, 1e-9)` (should be `flow_speed / max_foam_speed`). Doc-comment at line 100-101 shows correct formula | V3 forensic |
| 11 | `terrain_audio_zones.py` 989 lines | **WRONG count — 1049 lines.** Sabine claim verified (line 539 cave/2s; line 554 open-field/0.1-0.3s) | V3 forensic |
| 12 | `pass_hydrology` cite `environment.py:2017-2019` | **WRONG cite.** Real insert at `environment.py:2861` (`requested_passes[3:3] = ["pass_hydrology", "erosion"]` — pre-erosion confirmed) | V3 forensic |
| 13 | `id()`-keyed checkpoint registries at `terrain_checkpoints.py:97-102` | **REAL.** `_LABEL_REGISTRY: Dict[int, ...]`, `_AUTOSAVE_CONTROLLERS: Dict[int, bool]`, `_ORIGINAL_RUN_PASS: Dict[int, ...]` all keyed by `id(controller)` | V3 forensic |
| 14 | Issue #27 — terrain_labels std=0 | **CONFIRMED OPEN.** `pass_compute_terrain_labels` at `terrain_pipeline.py:1133-1191` zero-fills 4 channels. **ZERO production callsites** stamp `cliff_label/water_label/rock_label/gravel_label` (only `terrain_pipeline.py:1174-1177` zero-fill + 6 test stamps). Existing docstring at `terrain_pipeline.py:1140-1143` says "feature generators stamp; this pass only guarantees presence." Architectural intent is generator-stamping; current state has zero generators stamping. | V3 + PR #24 audit |
| 15 | Issue #28 — pass_water_depth skips | `pass_water_depth` at `terrain_pipeline.py:1355-1421`; skips when `water_surface_elevation_m` or `height` is None. Producers exist at `terrain_water_variants.py:880` (water_variants writer) and `:1463` (bathymetry). Skip is correct when biome has no water; harness ran pass standalone | V3 + PR #24 audit |
| 16 | Spec C-1 contradiction (line 124 vs 237) | **REAL ambiguity** — same word "seed" used for two scopes. Line 124 = per-chunk; line 237 = per-biome merged-field. Resolution: `biome_seed = hash(biome, version)` for pre-slice; `chunk_seed = hash(biome, chunk_x, chunk_y, version)` for post-slice | V3 + V4 |
| 17 | All 6 V2-claimed v2 duplicates verified | PR #3 (line 1633), PR #4 (line 1635), PR #15 (line 1648), §11.5 #5 (line 1685 Heitz), §11.5 #1+#3 (lines 1681, 1683 three-interpreter) — all literally in v2 spec | V3 forensic |
| 18 | Issue #27 fix architecture | **V1 wrong** ("synthesize from slope_deg>60°" alone is regression — slope insufficient, can't distinguish cliff/scree/rock/water). **V2 correct on architecture** (each generator stamps own label, terrain_labels = validator). **Current state**: zero generators stamp. Real fix = wire generators + keep validator | V4 |
| 19 | Rescue PR C — `landform_zones.py` / `shoreline_sdf.py` | **Files do NOT exist** on disk (only stale `.pyc` artifacts). Spec §3.5 line 211 has per-biome zone IDs as **grid-binary masks**; landform_zones provides Bezier-SDF **smooth shorelines** (sub-cell resolution). Genuine value-add for coastal pilot, NOT replaced by chunk zone masks | V3 + V4 |
| 20 | AAA-vs-AA gap | **2 net-new items**: parent-child scatter rules + artist override layer. Tree imposters already in spec §4.8 LOD3 (line 366); midground shrubs already in spec §4.4 Layer 4 (line 320). V1 claim of 4 net-new was severity-inflated | V4 |

### A.2 Verifier-4 final judgment

**v3 draft was 78% correct.** Recommend **OPTION C** (surgical trim, not revert) → BUT user chose **OPTION 1** (revert + clean rewrite). Apply all V4 surgical guidance to the clean rewrite.

---

## §B. Wave-5 scan results (10 reports, all completed)

### B.1 Cross-PR coherence (25 issues, 9 severe)

**Highest-severity:**
- **Water-channel naming has 3 competing vocabularies** in spec itself: §3.4 line 192 (`water_surface_z`/`water_depth`), §3.4 line 209 (`water_surface_mask`/`water_surface_elevation_m`/`water_depth_m`), §10.6 line 1041 (W-1 form). PR #5 implements one; PR #37 reads another.
- **`terrain_unity_export.py` touched by 5 PRs** (#5/#11/#12/#44/#48) with inconsistent dep chains. Need explicit serialization.
- **#56 ↔ #55 cycle**: #55 deletes `vegetation_system.py`, #56 edits it. Order undefined.
- **C-1 amendment not propagated to PR #9**: 127-site migration can't route to right scope.
- **No PR registers `water_surface_mask` channel**: PR #37 reads it, but no PR creates it.
- **PR #36 (8-channel splat)** missing dep on #40 (splat seam re-normalize).
- **PR #46 (Rule-1 gate)** missing dep on #3 (toposort).
- **PR #62 (close #28)** missing dep on #9 (subprocess determinism harness).
- **PR #44 + #48** edit `terrain_unity_export.py` but neither lists #11 (atomicity) as dep.

**Recommended re-ordering**: #56 before #55; #11 before #44/#48; add deps #36→#40, #3→#46, #9→#62.

### B.2 CI pipeline impact (8 changes, +60-100% wall-clock)

**Existing CI inventory:**
- `python-package.yml`: matrix `ci (3.11)` + `ci (3.12)` on ubuntu-latest, 45min, ruff + 6 guardrails + pytest with `--cov-fail-under=72` (memory said 40 — STALE, real is 72 already)
- `type-check.yml`: pyright + pyright-strict ratchet
- `callable_census.yml`: callable-census + scan + protocol adoption
- `codeql.yml`: `Analyze (python)` + `Analyze (actions)`, weekly cron, `security-and-quality` query suite (memory said default-only — STALE)
- `visual_testing_readiness.yml`: blender + libegl1, artifact-shape only

**Required new lanes:**

| PR | Lane | Tooling | Runtime | Cost |
|----|------|---------|---------|------|
| (Block 1) | bake-venv (ubuntu) | conda 3.10 + Taichi-CUDA + rasterio + Pillow≥10.4 + numpy 1.26 | 12-18min cold, 3-5min cached | HIGH (first GPU need) |
| (Block 1) | blender lane | bundled 3.11.x running scene-read smoke | 6-10min | MED |
| (Block 1) | Taichi-CUDA perf gate | self-hosted GPU runner (RTX 4060 Ti) | ~5min after warmup | HIGH (no CPU fallback) |
| (Block 1) | subprocess determinism | adds `PYTHONHASHSEED=0` env | +2min | LOW |
| (Block 4) | CodeQL custom queries + mutmut | extends codeql.yml | +15-25min nightly | MED |
| (Block 1) | pytest-xdist | extends python-package.yml | -4-6min (NEGATIVE cost) | NEG |
| (Block 4) | chunk-render-proof.yml | Blender headless render validation | 10-25min/chunk | MED |
| (Block 4) | coverage ratchet 70% | already at 72 — gate change only | 0min | LOW |

**Required secrets**: `HUGGINGFACE_TOKEN`, `QUIXEL_API_KEY`, `MESHY_API_KEY`, `RUNNER_REGISTRATION_TOKEN`. None currently configured.

**Branch protection**: Currently `protected=true`, `enforce_admins=true`, `required_linear_history=true`, `allow_force_pushes=false`. 6 required checks live (memory said `protected=false` — STALE). `required_approving_review_count=0` is a gap if user wants belt-and-suspenders.

### B.3 HDRP shader graph inventory — **F (~10%)**

**Zero shader graph assets exist on disk:**
- 0× `.shadergraph`, 0× `.hlsl`, 0× `.shader`, 0× `.shadersubgraph`, 0× `.mat`
- **No Unity project**: no `Assets/`, no `Packages/manifest.json`
- All 4 promised variants (`VbTerrainLitTriplanar`, `AntiTile`, `DistanceNormal`, `OverlayDynamic`) + master + 2 subgraphs are absent
- Only HLSL artifact: `terrain_stochastic_shader.py:51-265` embedded as Python f-string, **tagged URP not HDRP** (line 73, 263)
- `acceptance_checks.py` referenced by spec line 1016 — **does not exist**

**42-item contract status:** ~9/42 SHIPPED, ~22/42 TODO, ~4/42 WRONG, ~7/42 AMBIGUOUS. Honest grade **F**.

### B.4 Unity-side parity — 14 gaps, **5 BLOCKING**

**5 BLOCKING (Block 5 separate workstream):**
1. **Zero HDRP shader graph assets** — `Shader.Find` cascade `HDRP/TerrainLit → HDRP/Lit → URP/Lit → Standard → Diffuse` falls to magenta default if HDRP package missing
2. **Water surfaces stubbed out** — `VbTerrainImporter.cs:1150-1153` `CreateWaterSurfaces` explicitly logs "raster-backed water mesh creation disabled" + skips. HDRP WaterSurface never instantiated
3. **`holes.png` never read** — no `terrainData.SetHoles` call. Mandatory contract item 13 fails
4. **Tangent-space normal handedness mismatch** — bake emits OpenGL-Y (`_pack_tangent_space_normal_rgba` at `terrain_unity_export.py:334` — no flip); Unity importer's `ImportTextureAsset:2097` sets `textureType = NormalMap` but never inverts G channel. Wrong-handed shading on slopes
5. **`edges.json` edge-stitch contract entirely absent** both bake AND Unity sides. Only `seam_contract.world_id` string copied. Cross-chunk seam pop guaranteed

**9 polish gaps:**
6. `vertex_ao.bin` not consumed (vertex color AO)
7. `decals.json` attached as JSON sidecar only — no `DecalProjector` instantiated
8. `flow_map.png` attached as sidecar — never bound to water shader
9. `caves/*.fbx` not imported
10. Layer height/detail PNGs ignored (TerrainLayer only gets diffuse/normal/mask)
11. Tree prefab is a Capsule primitive (`GetOrCreateTreePrefab:2229-2273`) — placeholder
12. No UV2 (lightmap), UV3 (Pivot Painter wind), or vertex colors on supplemental/foliage meshes
13. `meta.json` keys missing in `VbTerrainTileMetadata`: `version_hash`, `character_spawn_safe_pos`, `addressable_deps`, `neighbor_prefetch_hints`, `memory_budget_mb`, `audio_zones`, `navmesh_hints`, `seed`, foliage `is_landmark`, water `basin_id/segment_id`
14. Unknown-key warning only fires on descriptor — raw manifest sidecars (audio/decals/water JSON) blob-attached without schema validation

**Memory correction**: `VbTerrainTileMetadata` declares **28 atomic public fields + 1 `ChannelBound[]` array field = 29 declared MonoBehaviour members** (`unity_plugin/VbTerrainTileMetadata.cs:11-49`), NOT a 3-field stub. Use this canonical phrasing wherever the count is referenced — see also §E.1 below.

### B.5 End-to-end determinism — **CLOSE** (4 PRs to byte-identical)

- **47 `random.Random()` sites** in `handlers/`, all explicitly seeded. **0 bare**.
- 0 `np.random.seed()`, 0 bare `np.random` in production
- Architecture sound: `derive_pass_seed` centralized in `TerrainPassController._run_pass` at `terrain_pipeline.py:269,668`; SHA-256 over JSON tuple
- **1 active hash() hazard** at `terrain_cliffs.py:2397` (already in v2 PR #15)
- **3 minor leaks**:
  - BLAS thread-count not pinned (`OMP_NUM_THREADS=1` not set anywhere)
  - **2 `derive_pass_seed` definitions**: canonical at `terrain_pipeline.py:269`, alternate at `terrain_rng.py:45` (never imported by handlers — drift hazard)
  - `terrain_quixel_ingest.py:874` unsorted inner `iterdir()` — multi-JSON-sidecar dir order-dependent

**Verdict**: byte-identical bakes achievable in **~4 small PRs**. Spec PR #9's "127 sites" is massively overscoped.

### B.6 Asset budget enforcement — 1 enforced, 6 paper

- `enforce_budget()` at `terrain_budget_enforcer.py:574` is a complete A-graded function
- Called only from `terrain_bundle_n.py:286` inside `run_bundle_n_post_pipeline_hooks()`, fired by `TerrainPassController.run_pipeline()` at `terrain_pipeline.py:983-991`
- **`build_terrain_aaa_node_v6.py` BYPASSES the controller** for the live 1024² stack (`run_production_passes` at lines 187-287) — directly invokes `pass_cliffs`, `pass_waterfalls`, `pass_materials`. The 32×32 stub through controller is theatre (writes `validation_full_present: true` to BUILD_SUMMARY.json)

**Specific gaps:**
- **Splat layer count hard-coded to 4** with comment `# Unity max; same for all profiles` — **WRONG, Unity 2022+ HDRP supports 8**. `default_dark_fantasy_rules` produces 5 channels; v6 lines 597-605 silently drops channel 4+ to RGBA
- **Zero BC6H/BC7/BC5 compression** anywhere. Splatmap baked as **OpenEXR** (spec §6.1 specifies PNG)
- **Missing emitters**: `splat_secondary.png`, `holes.png`, `flow_map.png` (RG16), `triplanar_mask.png`, `vertex_ao.bin`, per-layer `albedo/normal/mask/height/detail.png`
- **`lod_meshes = []` accepted as default** at `vegetation_system.py:1284` and `procedural_grass.py:720`. No validator. P0 unfixed
- **Streaming budget paper-only**: §6.5 mandates 2GB chunk-artifact cap + per-chunk file-count cap — neither emitted nor enforced
- **`except Exception: log.error(...)` swallow** at `terrain_pipeline.py:992-999` silently absorbs hard budget violations (must demote to fail)

### B.7 Single-chunk re-bake — DEGRADED but achievable

- 8 of 18 artifacts cleanly per-chunk; 6 require full-watershed; 4 partial
- **6 missing modules** (none in v3 PRs): `chunks/chunk_baker.py`, `chunks/edge_contract.py`, `chunks/cache_invalidator.py`, `chunks/chunk_seed.py`, single-chunk CLI, watershed-downstream invalidator
- Architecture is "bake before slice" — sound for content edits (foliage seed bump, decals, render): ~9 min/chunk achievable
- Heightmap/biome_id edits force full biome re-bake (~30-45s erosion floor unavoidable, then re-slice 64 chunks)
- `chunk_seed` not yet implemented anywhere

### B.8 Test infrastructure — 1,315 tests, **7 gaps**

- **1,315 tests** across 163 files (memory's "3,667 passed" was parametrize expansions)
- **Coverage at 72%** (memory said 40% — STALE)
- 19 skipped, 0 stale (all environmental/dependency-based)
- **ZERO render-baseline PNGs** — `compare_render_to_golden` SSIM 0.95 handler at `terrain_visual_qa.py:706` is unreachable
- 1 byte-identity test (`test_phase8_determinism_guardrails.py:53`) covers **only 3 of 18 artifacts**
- **ZERO** `pytest-benchmark`, `hypothesis`, `mutmut`, `pytest-rerunfailures`
- Protocol enforcement at **28% (21/74 passes)**; `check_protocol_adoption.py` gates only 11 critical
- 8 ad-hoc `elapsed < N` asserts in 8 files (will flake on shared CI)
- One CI lane runs full suite (no fast/nightly split)

**Memory correction**: determinism CI in-process theatre note is partially STALE — there IS one subprocess byte-identity test for the CLI; weakness is 3/18 coverage.

### B.9 Doc rot — **HIGH** severity

- 220 markdown files, 0 truly old (>60d) but **superseded authoritative claims still cited**
- **04-27 master implementation guide** has 5+ P0 blockers listed as active that Batch15 (2026-05-04) marks ✅ FIXED:
  - W-1 dual-semantics (partially fixed at `_water_network.py:907-929`, `procedural_grass.py:350-352`, `coastline.py:1242`)
  - E-1 erodibility 1000× (fixed at `_terrain_erosion.py:318`)
  - E-2 stratigraphy delta (fixed at `terrain_stratigraphy.py:1069`)
  - M-3 `TerrainTextureLayerStack` "doesn't exist" — exists at `terrain_texture_layer_stack.py:38`
  - CL-2 cliff/talus/strata masks "never rasterized" — fixed at `terrain_cliffs.py:2704-2706`
- Grade table predicts **5/11 grades wrong**: Water D+→C+, Visual QA F→fixed, AI assets D→live, etc.
- **Spec lines 7 + 27** cite 3 build scripts that DON'T EXIST: `coastal_build_v3d_vegetation_v2.py`, `mountain_build_v1_full.py`, `grassland_full_build.py`
- 14 superseded docs to archive: 4× `MASTER_AUDIT_V*_2026_04_19.md` siblings, deep_dive_2026_04_20 trio, GLM_IMPLEMENTATION_PLAN, scratch reconstruct files

### B.10 Dependency CVE + supply chain — **8 hardening items**

| Issue | Action |
|-------|--------|
| Pillow `>=10.0` | bump to `>=10.4` (CVE-2023-50447 + CVE-2024-28219) |
| `taichi`, `rasterio`, `PyYAML`, `gradio_client`, `requests`, `huggingface_hub` undeclared | add to pyproject.toml; split into `[providers]` + `[geo]` extras |
| No `uv.lock` / `requirements-lock.txt` | generate; switch CI to `pip install --require-hashes` |
| No `bake-env.yml` (conda) | create; pin NumPy 1.24.x to match Blender 4.5 |
| No `.github/dependabot.yml` | create; weekly cadence for pip + github-actions |
| Actions tag-pinned (not SHA) | SHA-pin all actions/* refs |
| HF Space (Hunyuan3D-2) not SHA-pinned | add `revision=` capture in `hunyuan3d2_provider.py` |
| CodeQL `security-and-quality` only | upgrade to `security-extended` + custom CWE-918 SSRF rules for `requests`/`gradio_client` paths |

---

## §C. Surgical edits to existing v2 §11 PRs

These PRs are already in v2 §11.1-§11.5 (commit `6cee216`). Author should reference, NOT duplicate. Apply these edits when constructing the Resolution Registry §11.9 and PR tables.

| PR # (v2) | Edit |
|-----------|------|
| #3 (toposort overrides=) | Reframe as v2-existing; note acceptance: `terrain_pipeline.py:1449-1510` patched to consume `overrides=` |
| #4 (orphan passes) | Reframe as v2-existing; carry C-1 amendment (resolve line 124 vs 237 with `biome_seed`/`chunk_seed` split) |
| #6 (three-interpreter) | Reframe as v2-existing decision crystallized to PR (`§11.5 #1+#3` → measurable acceptance: 3 CI lanes green) |
| #9 (determinism) | **Amend count**: "127 sites" → **"~58 production sites (47 handlers + 11 tests) + 1 hash() hazard + PYTHONHASHSEED gate"** |
| #11 (manifest atomicity) | **Fix cite**: `terrain_unity_export.py:1612,1629` → real manifest write site (Grep `json.dump.*manifest` first) |
| #12 (NaN/Inf sanitization) | Reframe as `fix(data-quality)` not `fix(security)` |
| #15 (PYTHONHASHSEED) | Already correct (`terrain_cliffs.py:2397`). Mark as v2-existing |
| #16 (tree imposters) | **CUT** — already in spec §4.8 LOD3 line 366. Demote to "verify §4.8 LOD3 imposter pipeline completes" |
| #17 (midground shrubs) | **CUT** — already in spec §4.4 Layer 4 line 320. Demote to "verify scatter pass wires §4.4 Layer 4 shrubs" |
| #20/#21/#22 (per-biome ecology) | **DEMOTE** to Block 4 post-pilot. Dark-fantasy game, P3 polish severity |
| #24 (overhang threshold) | **Fix cite**: `terrain_cliffs.py:857-858` → **`terrain_cliffs.py:890`** (real `radians(88.0)` value; make threshold configurable to 80°/90°) |
| #25 (biome archetypes) | **Fix cite**: `_terrain_world.py:861-869` → **`_terrain_world.py:2031`** (`params.get("terrain_type", "mountains")`) |
| #37 (Issue #27 terrain_labels) | **REWRITE acceptance**: drop "synthesize from `slope_deg>60°`" (regression). Restore generator-stamping per existing docstring contract at `terrain_pipeline.py:1140-1143`. Each generator stamps owned label; `pass_compute_terrain_labels` becomes validator/clamp. Issue #27 closes when std>0 in 100% chunks via stamping |
| #45 (pass_hydrology) | **Fix cite**: env.py "2017-2019" → **`environment.py:2861`** (`requested_passes[3:3] = ["pass_hydrology", "erosion"]`) |
| #52 (Rescue PR C) | KEEP. landform_zones.py + shoreline_sdf.py files don't exist (confirmed); Bezier-SDF smooth shorelines genuine value-add over grid zone masks |
| #62 (close Issue #28) | **GATE**: explicit prereq "after PR #5 W-1 atomic migration lands AND `test_water_depth_skip.py` confirms skip path under new `water_surface_elevation_m` semantics" |

---

## §D. NEW PRs from wave-5 (Block 5 + cross-cutting additions)

### D.1 Cross-PR coherence patches (5 PRs)

1. **Unify water-channel naming** — single registry `water_surface_mask` (binary), `water_surface_elevation_m` (z), `water_depth_m` (delta). Remove §3.4 line 192 alternate names. Split PR #5 into 5a (drop legacy write) + 5b (register canonical channels).
2. **Serialize `terrain_unity_export.py` writer edits** — explicit dep chain #11 → #44 → #48 → #5 to prevent merge collisions.
3. **Fix #56 ↔ #55 cycle** — either #55 removes `vegetation_system.py` from delete list (defaults fix needed first), or #56 lands before #55 with explicit dep.
4. **Propagate C-1 to PR #9** — 127-site (corrected to ~58) migration must distinguish `biome_seed` vs `chunk_seed` per scope. Add scope tagging to migration helper.
5. **Register `water_surface_mask` channel** — PR #37 reads it; no PR creates it. Add to PR #5b explicitly.

### D.2 Block 5 — Unity-side parity (5 PRs, **studio-team-scale workstream**)

This is a separate workstream from bake-side PRs. Requires Unity project setup + HDRP shader graph development. Either commits to the work OR triggers MicroSplat $120 fallback per spec §6.6.

1. **HDRP shader graph stack** — create 4 .shadergraph files (`VbTerrainLitTriplanar`, `AntiTile`, `DistanceNormal`, `OverlayDynamic`) + master `VbTerrainLit` + 2 subgraphs (`subgraph_triplanar`, `subgraph_antitile_stochastic`). Validate via `acceptance_checks.py` (also missing). OR trigger MicroSplat fallback.
2. **HDRP WaterSurface instantiation** — replace `VbTerrainImporter.cs:1150-1153` skip stub with actual WaterSurface creation from `water.json` ocean/river/lake interfaces.
3. **`holes.png` consumer** — `terrainData.SetHoles(holes_array)` in `VbTerrainImporter.cs`.
4. **Tangent-space normal Y-flip on import** — invert G channel in `ImportTextureAsset:2097` when `textureType = NormalMap`.
5. **`edges.json` edge-stitch contract** — both bake-side emitter AND Unity-side validator. 1e-3m height tolerance per §6.3. Fail-fast on mismatch.

### D.3 Asset budget hardening (4 PRs, beyond existing #36)

1. **Splatmap layer count 4→8** — fix all profiles (`splatmap_layer_count = 8`); fix `default_dark_fantasy_rules` 5-channel emit; fix v6 lines 597-605 silent truncate.
2. **BC6H/BC7/BC5 compression enforcement** — `TextureFormat` selector: BC6H for HDR, BC7 for albedo, BC5 for tangent-space normals. Hard validator in Bundle N.
3. **Missing emitters** — `splat_secondary.png` (layers 4-7), `holes.png`, `flow_map.png` (RG16), `triplanar_mask.png`, `vertex_ao.bin`, per-layer `albedo/normal/mask/height/detail.png`.
4. **`lod_meshes` validator + except-swallow fix** — block manifest emission when `lod_meshes == []`; demote `except Exception: log.error` at `terrain_pipeline.py:992-999` to hard fail.

### D.4 Single-chunk re-bake architecture (4 PRs)

1. **`chunks/chunk_seed.py`** — implement `chunk_seed(biome, x, y, version)` (4-arg) and `biome_seed(biome, version)` (2-arg). Wire into existing 47 RNG sites via PR #9 single-pass migration.
2. **`chunks/cache_invalidator.py`** — chunk-grid-aware content-hash + dependency graph (heightmap → erosion → drainage → splat → foliage). Reads `terrain_dirty_tracking.DirtyRegion`.
3. **Watershed-downstream invalidator** — when heightmap edited at chunk (i,j), compute D8 downstream chunk set from cached `flow_direction`; invalidate `water.json` + `flow_map.png` on those.
4. **`chunks/chunk_baker.py` + single-chunk CLI** — halo-aware re-bake; CLI: `python -m veilbreakers_terrain.bake --biome mountain --chunk 4,4 --reuse-merged-field`.

### D.5 Test infrastructure (7 PRs)

1. **Render-baseline PNGs** — commit 4 baseline PNGs for `golden_scenarios/{cave_entrance, cliff_talus_apron, deep_lake_basin, waterfall_plunge_pool}`. Wire `compare_render_to_golden` SSIM 0.95 into CI.
2. **`pytest-benchmark` + nightly perf cron** — install; convert 8 ad-hoc `elapsed < N` asserts to `@pytest.mark.benchmark`; add nightly perf workflow with regression history.
3. **`hypothesis` property tests** — install; add channel-invariant tests (NaN-free, shape-stable, range-bounded across N seeds).
4. **Extend byte-identity test to all 18 manifest artifacts** — `test_phase8_determinism_guardrails.py:53` currently checks 3.
5. **Protocol enforcement 21/74 → ≥60/74** — extend `check_protocol_adoption.py` registry + decorate handlers.
6. **`pytest-rerunfailures` + flaky-hunter nightly** — install; tag known-flaky; nightly job that rebuilds confidence intervals.
7. **CI fast-lane vs nightly-full split** — fast PR lane <5min (lint + smoke); nightly full suite.

### D.6 Dependency hardening (3 PRs)

1. **CVE patch + missing deps** — Pillow `>=10.4`; declare `taichi`, `rasterio`, `PyYAML`, `gradio_client`, `requests`, `huggingface_hub`; split `[providers]` + `[geo]` extras.
2. **Lockfile + bake-env.yml** — generate `uv.lock`; `pip install --require-hashes`; create `bake-env.yml` (Blender 4.5 NumPy 1.24.x compat).
3. **Supply chain hardening** — `.github/dependabot.yml`; SHA-pin all GitHub Actions; pin Hunyuan3D-2 HF Space SHA in `hunyuan3d2_provider.py`; CodeQL `security-extended` + CWE-918 custom rules.

### D.7 Doc rot cleanup (4 PRs)

1. **Archive 14 superseded docs** — 4× `MASTER_AUDIT_V*_2026_04_19.md`, deep_dive_2026_04_20 trio, GLM_IMPLEMENTATION_PLAN, scratch reconstruct files. Move to `docs/_archive/2026-04/`.
2. **Patch 04-27 guide** — grade table + P0 list with Batch15 ✅ FIXED status; SUPERSEDED-BY banner pointing to BATCH15.
3. **Fix spec lines 7 + 27** — remove references to 3 nonexistent build scripts; refresh `CODEBASE_STRUCTURE.md` post-providers/, post-Batch14 export-wiring, post-`terrain_texture_layer_stack.py`.
4. **Refresh dirty-tree docs** — `BLENDER_AGENT_USAGE_GUIDE.md` + `TERRAIN_CALLABLE_USAGE_GUARDRAIL.md` (currently dirty in tree per `git status`).

---

## §E. Memory updates (5 stale items)

1. `VbTerrainTileMetadata 3-field stub` → **28 atomic public fields + 1 `ChannelBound[]` array field = 29 declared MonoBehaviour members** (`unity_plugin/VbTerrainTileMetadata.cs:11-49`). Matches §B.4 above; supersedes earlier "25-field" / "26-field" claims that reflected partial counts at intermediate states.
2. `127 random.Random sites` → **47 handlers + 11 tests = 58 production**
3. `coverage floor 40%` → **72%** (`.github/workflows/python-package.yml:83`)
4. `branch protection protected=false` → **protected=true** (live API check)
5. `CodeQL default config only` → **security-and-quality** + Python+Actions languages (`.github/codeql/codeql-config.yml`)

Plus the 04-27 implementation guide pin needs **SUPERSEDED-BY** banner pointing to `MASTER_AUDIT_BATCH15.md` (W-1, E-1, E-2, M-3, CL-2 all fixed).

---

## §F. Output requirements for §11 v3 author

**Target file**: `docs/superpowers/specs/2026-05-05-biome-render-rebuild-design.md`

**Replace**: existing §11 (currently v2 from commit `6cee216`, lines ~1600-end-of-§11). Use Read first to find exact start/end line numbers.

**New §11 structure (5 blocks instead of 4):**

```text
§11.0    Preface — v3 vs v2 deltas, cumulative wave 1-5 verification table (276 reported, 263 verified open, 234 unique mapped to PRs)
§11.0.1  Source-of-truth pin (this file at .staging/WAVE_1_5_RAW_FINDINGS.md)
§11.0.2  C-1 contradiction resolution (biome_seed vs chunk_seed)
§11.1    Block 1 — Immediate blockers (~3 days). Pipeline-can-run + perf gate + security baseline. ~15 PRs
§11.2    Block 2 — AAA-parity + ecology promoted from B1 + long-tail. ~22 PRs
§11.3    Block 3 — Tile-seam + concurrency + DEM. ~11 PRs
§11.4    Block 4 — Polish + rescue + infra + ecology demoted. ~14 PRs
§11.5    Block 5 — NEW — Unity-side workstream + cross-PR coherence + asset budget hardening + single-chunk re-bake + test infra + deps + doc rot. ~25 PRs
§11.6    Cross-PR dependency graph (DOT or table)
§11.7    AAA-parity cuts (explicit honesty register)
§11.8    Open deferrals (post-pilot v2 work)
§11.9    Resolution Registry — every wave 1-5 finding ID → closing PR or §11.7/§11.8 deferral
§11.10   Memory updates (5 items + 04-27 SUPERSEDED-BY)
§11.11   Verification protocol — how each PR's acceptance is checked (test command, render proof, manual review)
```

**Each PR row must have:**
- `PR #N — <conventional commit title under 70 chars>`
- `Files: file:line[, file:line, ...]` (cite must be VERIFIED — use V3 forensic table A.1 as ground truth)
- `Acceptance: 3-5 bullet criteria, each measurable`
- `Validation: test command OR render proof OR manual review path`
- `Effort: S / M / L / XL`
- `Block + dependencies (PR #X, #Y after)`

**Total PR count target: ~85** across 5 blocks.

**Forbidden patterns:**
- DO NOT duplicate v2 §11 PRs (#1-#27 in commit `6cee216`). Reference as "from v2 §11.X".
- DO NOT use the 4 wrong line cites (857-858 / 861-869 / 1612-1629 / 2017-2019). Use the V3-corrected cites (890 / 2031 / Grep-found / 2861).
- DO NOT claim 127 random.Random sites. Use ~58 production.
- DO NOT propose Issue #27 fix as "synthesize from slope alone." Use generator-stamping + validator architecture.
- DO NOT propose `landform_zones.py` resurrection as duplicate. It's net-new (files don't exist).

**Required honesty markers:**
- §11.7 must explicitly state: HDRP shader graph stack is **F (~10%)** — 0 .shadergraph files exist. Block 5 commits to either building them OR triggering MicroSplat $120 fallback.
- §11.7 must state: Unity-side has **5 BLOCKING gaps** that bake-side PRs do not fix.
- §11.7 must state: Pipeline `<60min/chunk` target requires Taichi-CUDA + GPU runner; no CPU fallback.
- §11.10 must update the 5 stale memory items.

**Approval gate**: After author writes new §11, two Opus verifiers run in parallel (coverage + consistency), then Codex CLI does final pass with `gpt-5.5` model. User commits only after all 4 approvals.
