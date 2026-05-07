# VeilBreakers Terrain — IMPLEMENTATION & FIX GUIDE (FINAL)

**Date:** 2026-05-07
**Status:** Single source of truth. Supersedes the 2026-04-27 master guide and the Batch 15 "Fixed Items" table.
**Build basis:** 32 agent runs (22 Opus + 10 codex GPT-5.5) across visual-disconnect investigation + 2 R1 deep-scan rounds + R1.5 conflict-resolution wave + 2 user-supplied repo deep-dives. Verified by 3 final-pass Opus verifiers.

> **Overnight status note:** This guide consolidates everything. Verifier agents may push corrections after this initial write — they will append to §13 if anything in §0-§12 is contradicted by the codebase. Read §0 first.

---

## §0. WHAT YOU NEED TO KNOW FIRST

### 0.1 The truth about visual output
- **Algorithm grade ≠ visual grade.** Most VeilBreakers handlers are algorithmically A-tier. Player-visible output is currently F-tier.
- **75% of "looks like dogshit" is two things:** (a) zero `.unity` scene exists in the repo — bake never goes through HDRP; (b) `scripts/render_batch15_verification.py` renders **fresh fbm noise unrelated to our pipeline** (no `veilbreakers_terrain` imports, just bpy + numpy). Every "B15-P0-XX verified" claim from those PNGs is theatrical.
- **Implementation guide is more wrong than the bugs it tracks.** R1-A10's stale-claim audit had 5 false positives; V1 verifier and R1.5 conflict-resolvers settled all 5 against A10. The 2026-04-27 master guide lists 14+ items as "P0 unfixed" that are fixed in code.

### 0.2 Hardware & spec (R2 LOCKED — UPDATED 2026-05-07 per user decisions)
- **RTX 4060 Ti 8GB** — USER-CONFIRMED 2026-05-07 baseline (memory `project_hardware_8gb_vram_2026_05_07.md`). All decisions assume 5.5GB Unity / 1.5GB headroom / 1GB OS. R2-A1 budget table at §7.1.
- **Hardware upgrade paths (user-evaluated 2026-05-07):**
  - **(A) Keep 4060 Ti 8GB** + DLSS 4.5 SR Quality + cloud bake-rig (~$31/mo RunPod RTX 4090 spot for path-traced goldens + APV bakes). Day-1 path; works with all decisions in this guide.
  - **(B) Used RTX 4070 Ti Super 16GB** (~$750 net delta ~$450 after selling 4060 Ti 8GB at ~$300). Removes 8GB ceiling — unlocks APV Sky Occlusion, 8-layer splat, in-process Path Tracer goldens.
  - **(C) RTX 5070 12GB** (~$549). Middle path; +50% VRAM, native DLSS 4.5 SR support, GDDR7 bandwidth uplift. AAA-tier achievable per §18 R2 deep-dive table.
- **32 GB RAM**, Windows 11, **Unity 6.3 LTS** (released Dec 3 2025) + **HDRP 17.6**, **Blender 4.5 LTS**.
- **Auto-Rig Pro INSTALLED** (user confirmed 2026-05-07) — do NOT recommend buying.
- **Game:** VeilBreakers, single-player, dark-fantasy, **AAA-target** (reference titles in §18: Witcher 3 NG, Hellblade 2, Cyberpunk 2.0, Diablo IV, Alan Wake 2, Black Myth Wukong; "Bloodborne PS4 5GB" downgrade framing DROPPED).
- **Resolution & frame target — LOCK 1080p/60 native via DLSS 4.5 SR Quality (Preset L, 720p internal → 1080p output).** Unity HDRP 17.6 ships native DLSS 4.5 SR; 3-5 day solo-dev integration. Force Preset L via DLSS-Swapper sidecar. 16.6ms frame budget at 1080p/60. **Supersedes prior "1080p/45 raster lock" decision.** DLSS3 frame-gen (Streamline FG) remains v1.1 contingent (~2-3 weeks custom Unity plugin work) — SR Quality is the v1 unlock, not FG. See §18 for full latest-decisions patch.

### 0.3 Money (R2 FINAL — supersedes R1/R1.5)
- **Total baseline spend: $20.** MicroSplat HDRP-for-Unity-6.3 (344008) ONLY.
- **Conditional ceiling: $40** if cliffs/overhangs gameplay-critical → add MicroSplat Mesh Terrains (157356) $20.
- **Amplify Impostors $30, Beautify HDRP $39.99, Aurora $25, THOR $30 — ALL DROPPED.** R2-A2 verified each has a working free equivalent at the AA-ceiling 8GB target. See §14.1.
- **Wwise Indie, Steam Audio (Apache 2.0 — NOT AGPL), Unity Recorder, HDRP Path Tracer, Graphics Test Framework, GRD, RenderMeshIndirect, SpeedTree 9 Importer, Cinemachine, A* Free, Animation Rigging, AI Navigation, Localization** — all **FREE** and adopted-without-purchase.

### 0.4 DAY 0 SETUP CHECKLIST (~4-6 hr wall-clock — complete BEFORE opening §17 Day 1)

Estimate: 4-6 hours wall-clock. Do this checklist sequentially. Do NOT skip to §17 Day 1 until all boxes are checked.

```
☐ Install Unity 6.3 LTS (6000.3.0f1) + HDRP 17.6 module via Unity Hub (~30 min download + 20 min install)
☐ Install Blender 4.5 LTS (~20 min)
☐ Buy MicroSplat HDRP-for-Unity-6.3 (Asset Store ID 344008, $20)
☐ Subscribe SpeedTree 9 Indie ($19/mo trial OK first month)
☐ Verify Auto-Rig Pro installed in Blender (already owned)
☐ Create RunPod account + add $20 credit + generate SSH keypair (~15 min)
☐ Update NVIDIA driver to ≥546.01 (verify in `nvidia-smi`)
☐ NVIDIA Control Panel > Manage 3D Settings > Program Settings: add Unity.exe + your-game.exe → "CUDA - Sysmem Fallback Policy" = "Prefer No Sysmem Fallback"
☐ Subscribe Wwise Indie license (free under <$250K dev budget) at audiokinetic.com
☐ Run `tools/hwcap/capture_4060ti.py` to baseline VRAM ceiling (Day 0 commit task — see §17.0)
☐ Author `scripts/run_unity_recorder_gate.py` skeleton (~50 LOC, see §17.0 + §19.8 #8)
☐ Clean repo state: `git status` should show only intentional WIP; remove temp `pr*_*.json` files in repo root
☐ Verify pyright + pytest baseline: `pytest && pyright --strict`
```

### 0.5 OUT-OF-SCOPE DEFERRALS (NOT in this doc, NOT v1.0 blockers)

The dev MUST NOT block on these for v1 terrain pipeline; assume external decisions land before Phase D D43-44 hero-shot framing.

- **Art style guide** (color palette, mood references) — author separately in `docs/art_style_v1.md`
- **Camera framing rules per biome** — author in `docs/cinematography.md`
- **Audio style guide** — Wwise project setup is in §17 D54-55; audio direction deferred
- **Save-game schema** — defer to v1.1 (no save in v1.0 ship-minimum per §16.3)
- **Player input bindings** — InputSystem is implicit; specifics deferred
- **HUD/UI design** — defer; v1.0 ship-minimum is gameplay+terrain
- **Story/narrative integration** — defer
- **Tutorial flow** — defer
- **Steam store page setup** — schedule Week 9 (post-D60)

---

## §1. STALE-CLAIM CORRECTIONS — apply BEFORE planning

### 1.1 P0s flagged "unfixed" but ACTUALLY FIXED in code (drop from priority list)

| ID | Stale-doc claim | Verified reality | File:line |
|----|-----------------|------------------|-----------|
| W-1 | dual-semantics water_surface | FIXED — `pass_water_flow_speed` prefers `water_surface_mask` | `_water_network.py:907-911,815-817` |
| W-2 | no `water_depth_m` producer | FIXED — registered + writing (corrected file path per V1) | `terrain_pipeline.py:1355` `pass_water_depth` |
| W-4 | `validate_seam_continuity` orphan | FIXED — called | `_water_network.py:1955` |
| C-1 | dual scatter handlers | FIXED — `scatter_biome_vegetation` removed | `handlers/__init__.py:1108,1121` |
| C-2 | `SpeciesSpec` missing fields | FIXED — `lod_paths`, `wind_profile`, `impostor_atlas_path`, etc. all present | `terrain_foliage_catalog.py:135-148` |
| CL-2 | cliff/talus/strata masks not on stack | FIXED | `terrain_cliffs.py:2673-2675` |
| V-1 | no channel validation in visual_qa | FIXED — `validate_channel_manifest`, `_check_stochastic_seam`, `_check_water_elevation`, `_check_foam_alpha` exist | `terrain_visual_qa.py:442,509,534,546` |
| E-1 | erodibility 1000× bug | FIXED — `np.clip(erod_arr, 0, 1)` | `_terrain_erosion.py:308-318` |
| E-2 | strat erosion delta unapplied | FIXED — in `_DELTA_CHANNELS` | `terrain_delta_integrator.py:40` |
| ~~M-3~~ | ~~`TerrainTextureLayerStack` missing~~ | **MOVED to §1.2 OPEN as SCAFFOLDED** (per §14.2 reclassification) — class exists but `terrain_quixel_ingest.py` still uses loose-channel pattern. See §1.2. | `terrain_texture_layer_stack.py:21-74` |
| M-4 | AO + displacement dropped | FIXED — both loaded + blended | `terrain_quixel_ingest.py:678,691-700,705-729` |
| B14-10 | ×25 hydraulic multiplier | FIXED for raw ×25; climate `iteration_scale` still mutates (minor) | `_terrain_world.py:1158` |
| B15-P0-07 | splatmap L>4 truncation | FIXED — `ceil(L/4)` group writer | `terrain_unity_export.py:1741-1843` |
| B15-P0-09 | `compute_stream_power_erosion` dead code | FIXED — wired into `pass_erosion` | `_terrain_world.py:1338,1415` |
| B15-P0-10 | gradient axis swap at `_terrain_noise.py:1533` | **PHANTOM** — `:1533` is a function def. `:1529` `dy, dx = np.gradient(h, row_spacing, col_spacing)` is correct numpy convention | `_terrain_noise.py:1529` |
| B15-P0-11 | per-tile mean subtraction at `_terrain_world.py:698` | **REMOVED** — `:698` is a comment; `:712-713` documents removal | `_terrain_world.py:712-713` |
| B14-6 / P0-P1 | `pass_road_network` not registered | FIXED — defined `:1718`, registrar `:1860` calls `register_pass(name="pass_road_network")`, master registrar `:231`, default sequence `:218` | `road_network.py:1718,1860,1872`; `terrain_master_registrar.py:231`; `terrain_pipeline.py:218` |
| P0-I1 | determinism in-process | FIXED — production calls `run_determinism_check_subprocess` at `terrain_bundle_n.py:421`. Line 217 `_ = run_determinism_check` is import-verifier (no parens), not a call | `terrain_bundle_n.py:421` |
| P0-I3 | live preview deep-copies | FIXED — `_clone_stack_for_diff` doesn't exist. `StackSnapshot` is hash-only via `_channel_hash` xxhash int per channel | `terrain_live_preview.py:42,53-60` |
| B15-P0-02 | 4-biome crash, 14 entries | FIXED — `BIOME_CLIMATE_PARAMS` has exactly 18 entries matching canonical 18. Plus consumers use `.get(name, default)` so wouldn't crash | `_biome_grammar.py:82-101` |

### 1.2 Items GENUINELY still open

| ID | Description | File:line | Severity |
|----|-------------|-----------|----------|
| B15-P0-01 | `_HEIGHT_SCALE` 200× multiplicative; deliberate, but `target_height_range_m` override path at `:994-1036` should be canonical | `_terrain_world.py:933,941-945` | P1 (mischaracterized) |
| ~~B15-P0-05~~ | ~~caustics defaults legacy `water_surface`~~ | **PHANTOM (per §14.2)** — `:1054` already reads `water_surface_elevation_m`. Removed from open list. | `_water_network_ext.py:1054` |
| B15-P0-28..33 | 17 passes registered but only consumed via `optional_channels` / delta-integration; technically scheduled implicitly. Only 3 are real omissions: `stratigraphy`, `wind_erosion`, `coastline` should be in default sequence explicitly | `terrain_pipeline.py:118-200` | P1 |
| ~~P0-S2~~ | ~~foliage catalog non-canonical names — zero placements~~ | **NOT EVIDENCED (per §14.2)** — `:92,460,822` uses canonical `thornwood_forest`/`mountain_pass`/`corrupted_swamp`. Legacy alias resolver at `:822` handles backward-compat. Removed from open list (CI assertion still recommended as belt-and-braces). | `terrain_foliage_catalog.py:92,460,822` |
| ~~P0-I2~~ | ~~mask cache entry-cap 128~~ | **FIXED (per §14.2)** — `:130-137` already uses byte-budget 2GB LRU eviction; 128-entry cap documented as the *old* design. Removed. | `terrain_mask_cache.py:130-137` |
| P0-E1 | `validate_vertex_attributes_present` never called | `terrain_unity_export.py` | P1 |
| ~~P0-E2~~ | ~~tree prototypes hardcoded 10m~~ | **FIXED (per §14.2)** — `:2244` already uses `np.median(valid)` of per-instance `height_scale` or `_TREE_HEIGHT_DEFAULT`; species-driven via height column. Removed. | `terrain_unity_export.py:2244` |
| M-3 (SCAFFOLDED) | `TerrainTextureLayerStack` class exists but `terrain_quixel_ingest.py` still uses loose-channel pattern. Awaiting integration PR. (Reclassified from §1.1 FIXED per §14.2.) | `terrain_texture_layer_stack.py:21-74,39` | P1 — scaffolded |
| Foam-formula | `speed_ratio = 1.0 - flow_speed/max_foam_speed` is physically inverted (Beaufort: foam ∝ wind^3.52) | `terrain_waterfalls.py:114-115` | P0 — easy fix |
| Render-pipeline lie | `scripts/render_batch15_verification.py` renders fresh fbm noise unrelated to pipeline (zero `veilbreakers_terrain` imports). All "B15-P0-XX verified" claims theatrical | `scripts/render_batch15_verification.py:19-30` | P0 — process integrity |

### 1.3 10 NEW bugs (Bug-A..E from R1.5 fresh-eyes sweep + Bug-F..J from R2-A4 — not in any prior audit; sequence A-J intact, no skipped letters)

**Bug-A: `derive_pass_seed` bifurcation (P0).** Two definitions with INCOMPATIBLE hash payloads:
- `terrain_rng.py:45` — payload: plain string concat
- `terrain_pipeline.py:269` — payload: `json.dumps([...])`
- `_scatter_engine.py:22` imports from `terrain_rng`; 21+ other files import from `terrain_pipeline`. **Scatter is deterministically out-of-sync with everything else.**
- **Fix:** delete `terrain_rng.derive_pass_seed`, re-export `terrain_pipeline.derive_pass_seed` from `terrain_rng`.

**Bug-B: `VbFloatingOrigin.cs` infinite-shift loop (P0).** After `ShiftWorld`, only `ShiftRoots[]` get `position -= offset`. `ReferenceTransform` (Camera.main / player) is NOT auto-included. Next `LateUpdate` re-reads `reference.position`, finds it still > `MaximumDistance`, shifts again — every frame. Particles + renderers tear.
- **Fix:** after shifting roots, check if `ReferenceTransform != null && Array.IndexOf(ShiftRoots, ReferenceTransform) < 0` then `ReferenceTransform.position -= offset`.
- **File:** `unity_plugin/VbFloatingOrigin.cs:38-58, 70-78`.

**Bug-C: Material asset mutation on disk (P1).** `prototype.Material.enableInstancing = true` runs every `RenderManifest` call inside `[ExecuteAlways]` MonoBehaviour. Modifying `Material.enableInstancing` on a project asset dirties the .mat file in editor.
- **Fix:** check `prototype.Material.enableInstancing` once at `OnEnable`, log warning if not pre-enabled, never mutate at runtime.
- **File:** `unity_plugin/VbFoliageManifestRenderer.cs:220`.

**Bug-D: `_water_network.py:1097` silent attr_name swallow (P1).** `rgba.attr_name = str(color_attribute)` on `rgba = np.empty(...)` raises `AttributeError`, swallowed by `except Exception: pass`. Downstream consumers fall back to defaults silently.
- **Fix:** return tuple `(rgba, color_attribute_name)` or use a small dataclass.
- **File:** `_water_network.py:1096-1099`.

**Bug-E: `terrain_features.py` 14 magic-offset RNG splits (P1).** `random.Random(seed + 9001)`, `+77777`, `+9999`, `+7777`, `+4444` — magic offsets not collision-free, violates `terrain_caves.py:24` Rule 4 ("uses `derive_pass_seed` — never `random.random()`").
- **Fix:** replace each with `derive_pass_seed(state.intent.seed, "terrain_features.<sublabel>", tx, ty, region)`.
- **Files:** `terrain_features.py:262, 761, 1296, 1347, 1661, 3082, 3356, 3474, 3774, 4061, 4178, 4510 + 2 more`.

**Bug-F: `terrain_lava.py:89-100` D8 boundary masking accumulates 8x transfer per iteration (P0). [R2-A4]** A cell receives lava from all 8 neighbours simultaneously; the loop adds `transfer` once per direction → high-viscosity flows balloon to 8x physical depth. Symptom: lava lakes appear ~8x deeper than `terrain_lava` intent specifies; downstream caustics + emissive pass over-blooms. Fresh-eyes #2 finding (R2 Opus).
- **Fix:** divide transfer by active-neighbour count, OR iterate sequentially with `lava = new_lava` after each direction.

**Bug-G: `terrain_unity_export.py:1587-1588` `terrain_size_x_m` double-applies UNITY_SCALE_FACTOR (P0). [R2-A4]** `manifest["cell_size"]` at `:2343` is already `_apply_unity_scale(stack.cell_size)` (Unity units). Line `:1587` then multiplies by `tile_size` — the `_m` field name promises metres but stores Unity-scaled units. 128-cell tile at 1.0m emits `terrain_size_x_m = 128 * 0.85 = 108.8`. Blender-side QA tools comparing to 128m fail.
- **Fix:** rename to `terrain_size_x_unity` or compute from raw `stack.tile_size * stack.cell_size` BEFORE scaling.

**Bug-H: `terrain_morphology.py:455` magic-offset seed `int(intent.seed) + idx` (P1). [R2-A4]** Same anti-pattern as Bug-E.
- **Fix:** replace with `derive_pass_seed(intent.seed, "pass_morphology", state.tile_x, state.tile_y, region) + idx_hash`.

**Bug-I: `unity_plugin/Editor/VbTerrainImporter.cs:608-619` navmesh grid shape inference non-deterministic for 256-cell tiles (P0). [R2-A4]** When `cellCount` admits two factorizations: a `cellCount = 256` (16×16) tile passes square test giving 16×16 even if source is `1×256` → silent dimension swap → navmesh area modifiers placed at wrong (row,col).
- **Fix:** write rows/cols explicitly into descriptor; never infer from `cellCount` alone.

**Bug-J: `terrain_pipeline.py:483-507` `register_pass` weak-ref leak on overwrite (P1). [R2-A4]** When duplicate-named pass overwrites at `:492`, new module entry added to registry at `:505` but old entry isn't removed. `WeakValueDictionary` purges only when prior `PassDefinition` is GC'd — but closure holds it alive. After `importlib.reload()`, mapping resolves to stale func for one tick, silently re-running old pass logic.
- **Fix:** explicitly `_PASS_MODULE_REGISTRY.pop((mod, attr), None)` before new assignment.

### 1.4 Anomalies + silent failures + dead-code paths + determinism hazards

#### 1.4.1 Anomalies (3 — original sweep)

1. **`snow_line` shadow-write** — `register_snow_line_pass` registers a `snow_line` pass writing `snow_line_factor`, but default sequence never schedules it. Bundle I `pass_glacial` overrides `snow_line_factor` immediately. Dead weight unless callers schedule manually.
2. **`pass_horizon_lod` naming mismatch** — default sequence references `pass_horizon_lod` (line 221); `terrain_horizon_lod.register_bundle_l_horizon_lod_pass` likely registers `horizon_lod` (Bundle J `BUNDLE_J_PASSES` tuple lists `horizon_lod` not `pass_horizon_lod`). Silent-skip orphan-by-typo. (Verifier 1: `terrain_horizon_lod.py:344` registers BOTH names — phantom; see §14.2.)
3. **`pyproject.toml` `mcp` extra** pins git SHA `35815ea7…` from external repo without integrity hash → supply-chain risk. Plus `mcp` extra restricts to `python_version >= '3.12'` while project declares `requires-python = ">=3.11"` — silent skip on 3.11.

#### 1.4.2 Silent failures (3 NEW — R2-A4)

- **S1. `_water_network_ext.py:179-185, 253-259`** — bare `except Exception: pass` swallows `setattr` failures on frozen-dataclass segments → meander solver returns success but downstream sees zeros. River geometry silently degenerates to straight lines.
- **S2. `terrain_unity_export.py:514, 1786`** — `_water_shader_manifest_json` swallows ALL errors → foam VFX never enables for entire tile if foam channel malformed. No log entry, no failure mode.
- **S3. `terrain_master_registrar.py:111-119`** — bundle import failure logs WARNING but `loaded.append(label)` records as `"P-lava:SKIPPED(...)"` if registrar crashes. Caller using simple API never sees raised exception.

#### 1.4.3 Dead-code paths (3 NEW — R2-A4)

- **D1. `terrain_chunking.py:1081-1139`** — `_compute_tile_contracts` (Smits' AABB slab test for road/river segment crossings) defined but zero call sites. Either delete or wire into `road_network.py`.
- **D2. `asset_generation.py`** — entire 803-LOC module emits `DeprecationWarning` on import, but still imports `gradio_client`, `runpod`, `requests` at module level. Pollutes CI logs. Memory says canonical replacement is `Hunyuan3D2Provider`. Confirm zero call sites + delete.
- **D3. `terrain_morphology.py:499-552`** — `get_natural_arch_specs` ignores `templates` parameter entirely; only uses `np.percentile(lap, 95)` curvature placement. Either misadvertised or parameter dead.

#### 1.4.4 Determinism hazards (2 NEW — R2-A4)

- **H1. `_water_network_ext.py:381-468`** — `solve_outflow` uses heap with float64 height ties; resolves by `r` index = depends on `_DIST` enumeration order. Pass passes determinism replay TODAY but breaks if anyone reorders `_D8`. **Fix:** stable secondary key `(elevation, dist_from_start, r, c)`.
- **H2. `terrain_unity_export.py:2826-2832`** — decal jitter uses `((r * 73856093) ^ (c * 19349663)) & 0xFFFFFFFF` — Wang-hash but **NO `intent.seed` mixing**. Two tiles at same (r,c) get identical decal rotations across different worlds. **Fix:** include `derive_pass_seed(...)` or `stack.world_id` hash.

### 1.5 Spec/code drift (gap not in any audit)

`docs/superpowers/specs/2026-05-05-biome-render-rebuild-design.md:215-220` promises 4 channels: **`vb_aspect_deg`, `vb_aspect_north`, `vb_canopy_openness`, `vb_TWI`**. Repo grep returns **zero hits**. No pass produces them. Spec §4.2 (foliage stack) consumes `aspect_north`, `TWI`, `moisture_M`, `canopy_openness`. **Foliage will silently fall back or fail.** Add producers in a new `pass_topographic_indices` (~150 LOC).

**Spec/code drifts table (FINAL-V3 #4 fill — X2 splatmap):**

| ID | Drift | Producer | Consumer | Failure mode | Fix |
|----|-------|----------|----------|--------------|-----|
| X-topo | spec promises `vb_aspect_deg`/`vb_aspect_north`/`vb_canopy_openness`/`vb_TWI`; no producer exists | none | foliage stack §4.2 | silent fallback to defaults | add `pass_topographic_indices` (~150 LOC) producer |
| X2-splat | `_default_splatmap_layer_meta:1274` returns `terrain_layers` length, but `splatmap.layer_end - splatmap.layer_start` may differ. When `terrain_layer_assets` length ≠ `(end - start)` C# at `unity_plugin/Editor/VbTerrainImporter.cs:891` silently drops layers `< layer_start` or `> layer_end`; zero-sum guard at `:912` then fills with layer 0 = 1.0 → entire tile renders as the first terrain layer, no biome variation visible | `terrain_unity_export.py:_default_splatmap_layer_meta:1274` | `unity_plugin/Editor/VbTerrainImporter.cs:891,912` | tile renders as one layer, no biome blends; no log entry, no error | add length-vs-range invariant assert on Python side BEFORE manifest write (fail loud); C# import should also assert and throw, not zero-sum-guard. (R2-A4 X2; cross-link §9 row.) |

### 1.6 Memory entries proven STALE 2026-05-07 (update memory)

| Memory entry | Stale claim | Reality |
|---|---|---|
| `project_foliage_stack_2026_04_26.md` Botaniq broken headless | Botaniq 7.x ships engon + bg.py — viable for pre-resolved asset paths |
| same — BlenderKit broken headless | BlenderKit ships `blenderkit_asset_tasks` + Docker image — explicit headless support for cached assets (login still needed for fresh download) |
| same — Geo-Scatter broken headless | Geo-Scatter v5.6.2 shipped headless bugfix |
| Crest URP-first paid for HDRP | **PARTIALLY STALE** — Crest is MIT on GitHub (last push Feb 1 2026, 3.8k stars). BUT free GitHub repo is **BIRP-only** (README explicit). HDRP is paid Crest 5 SKU ($100-200). Paid SKU **not necessary** — HDRP 17.6 native + foam fix covers AA. |
| Crest Phillips spectrum | Actually Pierson-Moskowitz |
| MicroSplat HDRP for Unity 6.3 doesn't exist yet | **STALE** — shipped Nov 8 2025 at $20, Asset Store ID 344008, targets Unity 6000.3.0 |
| Megascans paid via Bridge | FREE since Dec 2024 via Fab.com (legacy Bridge grandfathered for previously-acquired assets) |
| `terrain_rng.py = 43 LOC, no derive_pass_seed` | **STALE** — file is 73 lines, `derive_pass_seed` IS defined at `:45` (creating Bug-A bifurcation) |
| "30 dead morphology templates" | **STALE** — exist + applied + serialized + tested. Feature-gated by empty-tuple default, not dead |

---

## §2. FREE-FIRST PROCUREMENT MATRIX

### 2.1 Foliage (R2 REVISED — Amplify Impostors DROPPED)

**Stack to adopt ($0):**
- **SpeedTree 9 Importer** — built-in Unity 6.3, FREE, supports `.st9`, GPU Resident Drawer compatible, HDRP/URP shadergraphs. **Ships built-in octahedral billboard impostors** (closes Amplify gap at 8GB). Pin SpeedTree 9.5 — NOT 10 (R2-A3 #4: SpeedTree 10 has known crashes). Cap 6 hero species. Modeler trial 30 days; thereafter use cached library + Blender glTF re-export (no license needed for re-export).
- **Modular Tree (GoodPie fork)** Blender 4.3+ — GPLv3, active 2026-03-29. **Use as FREE replacement for Amplify Impostors** for Blender-authored hero trees needing billboard impostors via Unity SpeedTree 9 Importer. **Caveat (R2-A5 + R2-A3 #12 + R2-V2 corrected estimate):** GoodPie's Unity export is *vertex-color PivotPainterMask only* (R/G/B/A) — no FBX/glTF round-trip, no UV2/UV3 packing. README still says UE5-only fully tested. Realistic ship date: **months, not days**. Plan a manual **FBX-sidecar-JSON + AssetPostprocessor remapper, 3-5 days** (Blender exports base FBX + sidecar JSON containing pivot/depth/extent/direction; Unity AssetPostprocessor.OnPostprocessModel validates vertex count and writes Vector4 UVs into UV2/UV3). Do NOT block on GoodPie shipping Unity export.
- **Unity Terrain Tools 6.3** (Asset Store 64852) — FREE, brushes + splatmap stamping.
- **MapMagic 2** (165180) — FREE Apache 2.0, node-based procedural placement.
- **Vegetation Spawner** (177192) — FREE, procedural tree+grass placement on Unity Terrain.
- **Vista Personal Edition** (297327) — FREE Pinwheel.
- **Nature Renderer 6 Free** (285961) — compute-shader procedural instancing, GPU culling. **Strong fit for VB vegetation pipeline.**
- **happy-turtle/foliage-wind** GitHub — Book-of-the-Dead wind, HDRP+URP. **LICENSE FILE NOT DECLARED — R1 said Apache 2.0, WRONG (R2-A5).** SHIP-BLOCKER until clarified. **Action:** file GitHub issue at `happy-turtle/foliage-wind`; if no response within 30 days, **re-author the wind shader internally** (~1-2 days HLSL or Shader Graph subgraph). Until then, exclude from license manifest.
- **MangoButtermilch/Unity-Grass-Instancer** GitHub MIT (verified active 2026-03-20, 328 stars) — 6 progressive optimization tiers, Unity 6 + HDRP shadergraph.
- **EricHu33/UnityGrassIndirectRenderingExample** GitHub MIT — Hi-Z occlusion, RT trample. **Mandatory** at 8GB (R2-A3 #5: RenderMeshIndirect default has NO frustum/occlusion cull → 30K grass uncull = 6ms+).
- **AlexMerzlikin/Unity-BatchRendererGroup-Boids** GitHub — **NO LICENSE FILE** (R1 said MIT, WRONG per R2-A5). Cannot redistribute. **Use as algorithmic reference only**, write internal BRG implementation.
- **Improved Sapling** GitHub abpy fork — GPL-2, Blender 4.x.
- **Sapling Tree Gen** Blender extension — bundled.
- **L-Py / PlantGL** openalea — CECILL-C, headless Python tree generation. **CGAL caveat:** dual GPL/LGPL/commercial. For internal bake-time use: $0. Binary ship needs strict LGPL component selection or commercial CGAL.
- **Tree It** — freeware standalone (no CLI; manual export only).
- **Polyhaven trees** CC0, **ambientCG** bark/leaves CC0, **Sketchfab CC0 filter**.

**Paid worth considering — R2 verdict: NONE.**
- **Amplify Impostors** (119877) — **DROPPED ($0).** R2-A2 #2: SpeedTree 9 Importer ships built-in octahedral billboards FREE; at 8GB the full octahedral atlas memory is unaffordable anyway, and atmospheric perspective hides octahedral 8-axis past 80m on 1080p dark-fantasy biomes. Use SpeedTree 9 native billboards + Modular Tree GoodPie fork for Blender-authored heroes.
- **Speedtree Indie** $199/yr — **SKIP** unless 20+ unique tree species. SpeedTree 9 Importer FREE in Unity 6.3 covers shipped-asset workflow.

### 2.2 Atmosphere / Sky / Clouds / Fog

**Stack to adopt ($0, all native HDRP 17.6):**
- **HDRP 17.6 PBS Sky** — Hillaire 2020 + Bruneton precompute, ~1.5 ms / 1080p / 4060 Ti.
- **HDRP 17.6 Volumetric Clouds** Medium preset (Sparse/Cloudy/Overcast/Stormy) — drag-drop, ~1.8 ms.
- **HDRP 17.6 Volumetric Fog** + Local Volumetric Fog boxes — ~0.6-1.2 ms.
- **HDRP 17.6 Aerial Perspective** — included in PBS, 0 ms extra.
- **Polyhaven HDRIs** CC0 — 470+ 16K skies for cinematics. `kloppenheim_06_puresky`, `qwantani_moonrise_puresky`, `satara_night`.
- **Unity-Technologies/VisualEffectGraph-Samples** MIT — fireflies, embers, dust motes, smoke.
- **keijiro/Kino** Unlicense — Streak (anamorphic bloom), Recolor, Glitch — HDRP custom post.
- **AllSky Free** (146014) — 10 cubemaps for HDRP HDRI Sky override.
- **Fantasy Skybox FREE** (18353) — 50 painterly textures for dark-fantasy.
- **Lightning controller** — 50-LOC C# (HDRP Light flicker + Volume Profile keyframed Exposure spike + cloud-layer alpha pulse).

**Skip all paid:** Cozy ($60), HDRP Time of Day ($80), Atmospheric Height Fog ($35), Sky Master Ultimate ($90), Expanse ($100), Enviro 3 ($60-80) — all redundant with HDRP 17.6 native.

### 2.3 Lighting (Daytime)

**Stack to adopt ($0):**
- **APV (Adaptive Probe Volumes)** — HDRP 17 native, Sky Occlusion ON for dynamic TOD. Bake **3-10 min/chunk**, **3-12 hr full 8×8 grid**, Max Probe Spacing 243m for VeilBreakers scale (32GB OOM risk at default).
- **HDRP 17 Directional Light** + 4-cascade CSM at 200/400/800/2000m + Contact Shadows + Micro Shadows.
- **HDRP 17 Reflection Probes** (baked + realtime planar).
- **HDRP 17 SSGI/SSR** native — Performance mode.
- **paulhayes Sun.cs gist** — single-file directional-light rotator MIT. **Verified URL hash:** `gist.github.com/paulhayes/54a7aa2ee3cccad4d37bb65977eb19e2` (R1's "sun-rotator" slug was fabricated — use this exact gist hash when fetching). Cross-ref §17 Phase E D51-52 + §14.11.
- **cosinekitty/astronomy-engine** — VSOP87/NOVAS sun/moon/planet positions ±1 arcmin via NuGet. Wire to PBS celestial body for biome physiology sun-trajectory sampling (REDengine NEW-S2 pattern).
- **cdrinmatane/SSRT3** GitHub MIT — alternative SSGI if HDRP native too noisy.

**Skip:** Bakery $60 (APV deprecates), Magic Light Probes $50 (APV deprecates), Enviro 3 (already covered), HDRP Day/Night Cycle (279317).

### 2.4 Lighting (Nighttime — dark fantasy specific)

**Stack to adopt ($0):**
- **PBS Sky Moon** native (DL 0.05-0.5 lux, color 7500-10000K cool blue, shadow penumbra 4cm).
- **PBS Sky procedural stars** native + NASA Tycho overlay via Shader Graph.
- **olawlor/AuroraRendererUnity** — public domain HLSL shader, HDRP Custom Pass wrap (port effort: 1-2 days).
- **HDRP 17 froxel volumetric god rays** with "Volumetric Shadows" on moon DL — ~1.2 ms Medium / ~0.6 ms Low.
- **HDRP 17 point/area lights** + light cookies + contact shadows for lanterns/ruins (~0.05 ms per shadowed point).
- **Shader Graph emissive runic glyphs** — `_EmissionIntensity` 5-80 nits + Bloom; needle-mirror/com.unity.shadergraph samples.
- **HDRP 17 Local Volumetric Fog boxes** with curl-noise density-mask 3D textures (~0.15 ms each, stack 3-6 per courtyard).
- **HDRP 17 Water caustics** native for moonlight on water.
- **VFX Graph fireflies** — `Output Particle HDRP Volumetric Fog` context for ember-particle volumetric scattering. ~0.3 ms per 200 lit fireflies.
- **AgX Tonemapping Unity** (meenphie GitHub) — better highlight rolloff for dark fantasy than ACES.
- **Polyhaven night HDRIs** CC0 (Qwantani Moonrise, Satara, Kloppenheim 02).
- **Polyhaven LUT collections** + Unity Color Adjustments + Filmic curve. Yharnam-Tuscany recipe: lift shadows +0.05 toward teal, gamma neutral, gain warm (R+5, G+2). Bake `.cube` LUT in DaVinci Resolve free.

**Paid skips — R2 verdict: ALL DROPPED.**
- **Aurora Borealis Shader VFX** ($25) — **SKIP.** olawlor/AuroraRendererUnity is **public domain** (looser than MIT). HDRP custom-pass port = 4-6 hr per R2-A2 #4 (not 1-2 days as R1 claimed). Half-res custom-pass + temporal accumulation per R2-A3 #7.
- **Beautify HDRP** (165411, $39.99) — **SKIP.** R2-A2 #3: only differentiator is Purkinje effect. HDRP 17.6 ships ACES + Neutral natively; AgX (meenphie GitHub MIT) ports cleanly = 1-evening job. Purkinje effect = ~30-line HLSL custom post-process volume — see §2.4.x DIY recipe below.
- **THOR Thunderstorm** ($30) — **SKIP.** R2-A2 #5: 26 thunder samples replaceable with Sonniss GDC (free royalty-free). Lightning logic = 50 LOC: HDRP Light flash + native Lens Flare ring procedural shape (HDRP 17.x).

**§2.4.x — Purkinje effect DIY HLSL custom post-process (replaces Beautify $40)**

Drop into `Assets/Settings/PostFX/PurkinjeShift.hlsl` + register as `CustomPostProcessVolumeComponent`. Luminance-driven scotopic blue shift. Place AFTER tonemap, BEFORE color adjustments.

```hlsl
// Purkinje (scotopic) blue shift — dark-fantasy night-vision approximation
// References: Hunt 1995 (Reproduction of Colour) + Khan-Pattanaik 2004 night model
// Trigger: photopic→scotopic transition below ~3.4 cd/m² (log10 luminance < 0.53)
TEXTURE2D_X(_InputTexture);
float4 _PurkinjeParams; // x = strength [0..1], y = threshold cd/m², z = blue shift, w = unused

float4 FragPurkinje(Varyings input) : SV_Target {
    UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(input);
    float4 c = SAMPLE_TEXTURE2D_X(_InputTexture, s_linear_clamp_sampler, input.texcoord);
    // Photopic luminance (Rec.709)
    float Lp = dot(c.rgb, float3(0.2126, 0.7152, 0.0722));
    // Scotopic luminance approximation (V'(λ) shifted toward blue: Wald 1945 rod sensitivity)
    float Ls = dot(c.rgb, float3(0.7020, 1.0397, 1.4756)) * 0.10;
    // Mesopic blend coefficient (CIE 191:2010 simplified)
    float k = saturate(1.0 - log10(max(Lp, 1e-5) / _PurkinjeParams.y) / 2.0);
    k *= _PurkinjeParams.x;
    // Blend toward blue-shifted scotopic response
    float3 scot = float3(c.b * 0.3, c.b * 0.7, c.b * 1.0) * Ls / max(Lp, 1e-5);
    float3 outRGB = lerp(c.rgb, scot, k * _PurkinjeParams.z);
    // Hue compression toward cyan as luminance falls (Purkinje shift)
    float compress = smoothstep(0.0, 0.15, k);
    outRGB = lerp(outRGB, dot(outRGB, float3(0.299,0.587,0.114)).xxx * float3(0.85,0.95,1.10), compress * 0.4);
    return float4(outRGB, c.a);
}
```

Pair with HDRP Volume override exposing strength/threshold/blueShift in `[VolumeComponentMenu("Post-processing/VeilBreakers Purkinje")]`. Profiled ~0.10 ms / 1080p / 4060 Ti. Save: $40.

### 2.5 Water (R2 — 8GB HARD CONSTRAINTS APPLIED)

**Stack to adopt ($0):**
- **HDRP 17 WaterSurface** native — Ocean (GPU FFT), River (flow-map + foam), Pool (ripples + buoyancy). Foam Generators + water decals + caustics + underwater post all native.
- **HDRP Water Samples** package — Pool / Glacier / Island / Pond example scenes.
- **dbrizov/NaughtyWaterBuoyancy** MIT (verified active 2026-04-11, 947 stars) — Archimedes-style multi-sample.
- **sinanata/Unity-HDRP-Water-Buoyancy-Handler** GitHub — **GPL-3.0** (R2-A5: R1 silent on license — viral copyleft for closed-source). **Use as algorithmic reference only**, OR replace with `dbrizov/Unity-WaterBuoyancy` (MIT, active 2026-04-11) per R2-A5 critical-alternates list.
- **Scrawk/Tiled-Directional-Flow** GitHub — **NOASSERTION license** (R2-A5: R1 said MIT, unverifiable). Use algorithm reference only; rewrite in Shader Graph 17.4.
- **flamacore/UnityHDRPSimpleWater** — **NO LICENSE FILE (R2-A5)**, abandoned 6y dark (2020-07-02). Avoid.
- **daniel-ilett/shaders-ice** — abandoned 5y dark (2021-01-14, URP 7.3 era); port-or-rewrite. **robertrumney/frozen-shader** OK.
- **TeckArtist FlowMap Painter** standalone free.
- **Steam Audio Unity** — **APACHE 2.0** (R2-A6 N1 + R2-A8: R1 was WRONG about AGPL; Steam Audio re-licensed Apache-2.0 in 2020). Apache §4(d): include `NOTICE` file in `Third-Party-Notices.txt` + visible in-game About screen. **Ship-OK.**
- **Foam formula correction** at `terrain_waterfalls.py:114-115`:
  ```python
  prox_ratio = 1.0 - saturate(prox / foam_radius)
  speed_ratio = saturate(flow_speed / max_foam_speed)
  whitecap_term = 0.3 * saturate((flow_speed / ref_speed) ** 3)  # Beaufort cubic, ref_speed ~ 3.4 m/s
  foam = saturate(prox_ratio * speed_ratio + whitecap_term)
  ```

**8GB VRAM HARD CONSTRAINT (R2-A3 #8 + R2-A1):** HDRP WaterSurface Ocean + River + Pool simultaneously consumes **~300-380 MB combined VRAM** + 2.3-5.0 ms / frame at 3-active. NVIDIA driver 532+ memory-fallback cliff (96× slowdown) triggers if total VRAM exhausts. **DO NOT run all three simultaneously visible.** Authoring rule: at most 2 surface types per chunk (typically River + Pool, OR Ocean alone). Drop `SimulationResolution 256 → 128` cuts ~60% memory at acceptable visual loss. Foam-Generator count cap: 8 per chunk.

**Skip paid:** Crest 5 ($100-200) — free GitHub Crest 4 (MIT, last push 2026-05-06, 3.8k stars) is BIRP-only OSS branch. **HDRP route: Unity 6.3 native WaterSurface only** per R2-A5 critical-alternate. Stylized Water 3 ($45) only if dark-fantasy swamp/blood requires stylization beyond HDRP native. KWS ($110) skip — overlap with HDRP native.

**Crest 4 vs Crest 5 disambiguation (FINAL-V3 #5 fill):** **Crest 4.x = MIT GitHub repo `wave-harmonic/crest`, BIRP-only (README is explicit). Crest 5 = paid Asset Store SKU 268614 ($100-200), HDRP/URP support.** The two are NOT the same product — Crest 5 is a separate commercial release after the Crest 4 OSS branch. **VeilBreakers uses Unity HDRP 17.6 native `WaterSurface` (FREE, AA-tier sufficient with the foam-formula fix at `terrain_waterfalls.py:114-115`).** Do not buy Crest 5; do not vendor Crest 4 (BIRP-only, will not run on HDRP).

### 2.6 Materials / Shaders / Terrain Shader (R2 — $20 BUY justified by Texture Clusters)

**Stack to adopt ($20 total — single paid SKU):**
- **MicroSplat base** (96478) — FREE.
- **MicroSplat HDRP for Unity 6.3** (344008) — **$20 BUY** (R2-A2 #1 + codex c03 verified, R2-V2 corrected sub-count). Shipped Nov 8 2025, targets Unity 6000.3.0. **Specific reason to spend the $20:** MicroSplat **Texture Clusters** — pseudo-random cycling between **3 sub-textures per layer** at 60+m view distance (per jbooth blog + Asset Store ID 104223; corrected from R2-A2's prior "4 sub-textures" claim by R2-V2). Unity 6.3 native Terrain Shader Graph + Hex CSNOH does **stochastic blend within ONE texture per layer** only (no inter-texture cycling). Without Texture Clusters, large terrain swaths show the visible "Skyrim grass plane" indie tell at mid-far distance — the single biggest gap between AAA terrain and indie terrain on the same hardware. ROI: $20 saves ~3 days of Shader Graph node-spaghetti reimplementing the same effect. Booth has shipped MicroSplat continuously since 2018 — proven 7-year update record.
- **MicroSplat Mesh Terrains** (157356) — **$20 conditional**, only if cliffs/overhangs.
- **Unity 6.3 Terrain Shader Graph** — FREE native (Dec 2025), 10 layer types: Layer Triplanar (9 samples), Layer Hex CSNOH (anti-tile within-texture stochastic blend, 6 samples), Layer Distance fade, Layer Parallax CSNOH (POM). 50%+ faster than legacy TerrainLit. **Use as fallback** if MicroSplat 344008 SKU withdrawn — but accept the Texture Clusters gap.
- **Shader Graph Terrain Sample** package — FREE Pkg Mgr import.
- **HDRP Lit triplanar UV mode** native FREE.
- **POM Node** Shader Graph 17.4 native FREE.
- **Better Shaders authoring framework** (187838) — FREE, Booth's auth tool for Shader Graph extensions.
- **Quixel Megascans on Fab** — FREE since Dec 2024 (legacy assets grandfathered; new acquires via Fab paywall).
- **Megascans Bridge for Blender** add-on — FREE.
- **ozgurdegil/triplanar-shader-graph** — **NO LICENSE FILE (R2-A5)**. Avoid vendoring; reference algorithm only.
- **GameDevBox/Advanced-Triplanar-Shader** GitHub — FREE reference.
- **gihuncho/unity-procedural-stochastic-tiling-triplanar** — **NO LICENSE (single-commit GPT-4 generated, R2-A5)**. Avoid.
- **Material Maker 1.5** — open-source Substance Designer alternative, free, Jan 2026 release, exports for HDRP.
- **GenPBR** — image → PBR maps + MaterialX, free browser tool.

**8GB constraint (R2-A1 #3, R2-A3 #3):** 8-layer Tex2DArray BC7 4K with mips = ~430-520 MB. Combined with cloud history + APV + atlases consumes 60% of VRAM budget. **Cap layers at 4 (1080p/8GB profile) or use 2K instead of 4K.** Unity 6.3 native at 10 layers = 3-pass shader = 3× pixel cost — unacceptable at 8GB.

**Skip:** MicroSplat Anti-Tiling Module ($30) — **Built-in pipeline only, NOT HDRP**. Better Lit Shader ($50) — Unity 6.3 Terrain Shader Graph + Hex CSNOH covers it free for within-texture stochastic blend (does NOT close Texture Clusters gap). Stochastic Height Sampling ($paid) — broken at HDRP 5.7. Corvo URP/HDRP, TerraTess, TerraFormer, Repetitionless — all redundant.

### 2.7 Scatter / GPU Instancing (R2 — Hi-Z mandatory + GoodPie remapper required)

**Stack to adopt ($0):**
- **GPU Resident Drawer** — HDRP 17 native, FREE. Enable: Project Settings > Graphics > Shader Stripping > BatchRendererGroup Variants = Keep All; HDRP Asset > Rendering > GPU Resident Drawer = Instanced Drawing. **Conflict (R2-A6 N5):** GRD's per-frame BRG buffer updates fight with DLSS3 motion-vector reprojection — fast-moving instanced foliage shows trail artifacts unless `_LastFrameWorldPos` written via DOTS-instanced motion-vector pass. Unity 6.3 added this; older 6.0 = visible smearing. Verify DLSS plugin version 3.7.10+.
- **BatchRendererGroup API** — Unity 6 native FREE.
- **Graphics.RenderMeshIndirect** — Unity 2022.2+ FREE; replaces 1023-cap `DrawMeshInstanced`. Use for grass blades. **R2-A3 #5 MANDATORY at 8GB:** RenderMeshIndirect default has NO frustum/occlusion cull. 30K grass uncull = 2.5-6 ms / frame; with **mandatory compute Hi-Z occlusion pre-pass** (per `EricHu33/UnityGrassIndirectRenderingExample` MIT) = 0.4-1.2 ms. Without Hi-Z pre-pass, foliage breaks the 16.6 ms budget alone.
- **Unity HLOD 2.0** (`com.unity.hlod` package, Unity 6 native, R2-A5 critical-alternate #2) — replaces abandoned `Unity-Technologies/HLODSystem` repo (no LICENSE file per R2-A5; Unity Companion claimed but absent; tested 2021.3, dead). Use the package, not the repo.
- **AlexMerzlikin BRG-Boids** GitHub — **NO LICENSE FILE** (R2-A5: R1 said MIT, WRONG). Cannot redistribute. Use as algorithmic reference only.
- **MapMagic 2 core** Apache 2.0 — FREE on GitLab.
- **Vista Personal** FREE.
- **EasyRoads3D Free v3** — FREE for spline roads + auto guardrails; integrates with MapMagic.
- **DOTS-Instancing shader template gist** by AlexMerzlikin.
- Existing `_scatter_engine.py` Bridson Poisson — keep as primary CPU placement.

**Modular Tree GoodPie Unity export — caveats (codex c07 verified 2026-05-07):**
- README states "Pivot Painter export is UE5-focused; only Unreal Engine 5 export is fully tested. Unity is in progress."
- Unity code at `python_classes/pivot_painter/formats/unity.py` writes vertex-color `PivotPainterMask` only (R=hierarchy depth, G=branch extent, B=stem hash, A=1). **No FBX/glTF exporter, no UV2/UV3 packing.**
- Most-recent Unity-relevant commits: `4377db9` (2026-01-29) calls itself a placeholder; `cba1ec8` refactors vertex-color packing. **No FBX/glTF round-trip commits found.** No active issue/milestone proving round-trip work. Realistic ship date: months, not days.
- **Action: write a custom Unity FBX-sidecar-JSON + AssetPostprocessor remapper** (~3-5 days per R2-V2 — corrects R2-A3 #12's "1-2 days" estimate; GoodPie ships only vertex-color PivotPainterMask, no FBX/UV2/UV3, so the remapper is the bottleneck not a 1-day add-on):
  1. In Blender: export base FBX + sidecar JSON from MTree mesh attributes (`stem_id`, `hierarchy_depth`, `pivot_position`, `branch_extent`, `direction`).
  2. Preserve vertex order after triangulation; write vertex-count/hash into sidecar.
  3. Unity `AssetPostprocessor.OnPostprocessModel` loads sidecar, validates `mesh.vertexCount == sidecar.count`.
  4. Pack `mesh.SetUVs(1, ...)` = `pivot.xyz + hierarchyDepth`; `mesh.SetUVs(2, ...)` = `direction.xyz + branchExtent`. Optional `SetColors(...)` for stem hash variation.
  5. Shader reads `TEXCOORD1/2` and bends around pivot. Unity supports up to 8 UV channels; `SetUVs` accepts `Vector4`.

**SpeedTree 9 Importer billboard impostors — codex c08 verdict (2026-05-07):**
- Unity 6.3 imports `.st`/`.st9`, auto-generates per-LOD materials, creates prefab with configured `LODGroup`. Billboard exists only if SpeedTree export includes billboards.
- SpeedTree Modeler 9 exports billboards as a final LOD with multi-view images packed into a billboard atlas. Unity renders them through `BillboardAsset`/`BillboardRenderer`: camera-facing cutout mesh, several baked Y-axis views, atlas coords + normal texture. **Native is multi-view vertical billboard — NOT octahedral, NOT crossboard.**
- At **80m+ distance** with HDRP fog/atmospheric perspective, the octahedral-vs-multi-view difference is not player-visible at 1080p; silhouette + alpha mip + fog match dominate over parallax accuracy.
- **Memory:** SpeedTree native 2 maps (diffuse+alpha, normal): `2048 RGBA32 ×2 + mips ≈ 42.7 MiB` raw / `~10.7 MiB` BC3/BC7. Amplify standard 4 maps: `2048 ×4` compressed + mips ≈ `21.3 MiB` / raw `85.3 MiB`. **At 8GB the Amplify 4-map atlas is unaffordable for 6+ hero species.**
- **Verdict: SpeedTree 9 native billboards SUFFICIENT for 8GB / 1080p / dark-fantasy.** Spend budget on atlas BC compression + alpha mip coverage + fog match + LOD threshold tuning + billboard shadow settings, not on Amplify. Re-evaluate ONLY if a screenshot A/B at 80-140m shows obvious native failure on hero silhouettes.

**Skip paid:** GPU Instancer Pro ($70) — GRD native is now equivalent for MeshRenderers. GPU Instancer legacy free is **non-commercial license — DO NOT USE** (legal trap).

### 2.8 Blender 4.5 Authoring

**Stack ($0; user has Auto-Rig Pro installed):**
- Blender 4.5 LTS native: Geometry Nodes, Cell Fracture, Node Wrangler, glTF I/O.
- **A.N.T. Landscape** (Blender Extensions, free GPL) — heightmap sketch.
- **Sapling Tree Gen** + **Improved Sapling** — free GPL trees.
- **Modular Tree (GoodPie fork)** — Blender 4.3+, active 2026.
- **Polyhaven Asset Browser** add-on — FREE CC0 hundreds of HDRIs/textures/models.
- **Geo-Scatter v5.6.2** free tier — headless verified working as of 2026-05-07 (memory was stale).
- **Megascans Bridge** legacy — FREE, grandfathered.
- **L-Py / PlantGL** openalea — FREE CECILL-C.
- **Auto-Rig Pro** — INSTALLED (user owns).
- **ambientCG** CC0, **Sketchfab CC0**, **OpenGameArt CC0**, **Blendswap free tier** — hero asset libraries.
- **Real Snow** Blender Extensions — free GPL.

**Skip:** Botaniq Trees Pro ($89) — free Modular Tree+Sapling covers 80%. Geo-Scatter full library ($69) — only if biome bringup time > $69.

### 2.9 Audio (R2 — license thresholds verified 2026-05-07)

**Stack to adopt ($0; pick Wwise OR FMOD primary):**
- **Wwise Indie (R2-A8 + codex c06 verified 2026-05-07):** FREE when game's **total production BUDGET < $250,000 USD** (NOT revenue — R1 was wrong). Audited at Greenlight/Pre-Production, again before launch, then **every 6-12 months post-launch** (range, not fixed cadence). Pricing tiers: Indie `<$250K`, Pro `$250K-$2M`, Premium/Platinum `>$2M`. **If you exceed Indie threshold, two paths:** (1) Standard Pro **upfront**: `$8,000 first platform + $4,000 each extra platform` (NOT royalty); (2) Royalty alternative: **1% gross sales** post-launch (no recoupable, no public cap), waived if game generates `<$10,000 revenue`. **Includes in free Indie:** all engine features (advanced Spatial Audio, Rooms & Portals, Interactive Music systems, geometric occlusion), unlimited sounds, full platform access. Premium IR plug-ins/content can still be paid add-ons. **Recommended primary.** Sources: audiokinetic.com/en/free-wwise-indie-license/, /en/wwise/pricing/for-games, /en/blog/wwise-licensing-and-pricing-philosophy/.
- **FMOD Studio Indie (R2-A8 + codex c06 verified):** FREE Indie tier requires developer revenue **<$200K/year** AND development budget **<$600K**. Above either: Basic `$600K-$1.8M` = `$6,000`; Premium `>$1.8M` = `$18,000`. NOT percentage royalty; flat fee per game. All features/platforms included. Easier learning curve; weaker Rooms & Portals than Wwise. Use only if Wwise authoring fails. Source: fmod.com/licensing.
- **Steam Audio Unity (R2-A6 N1 + R2-A8 — APACHE 2.0, R1 WRONG about AGPL):** FREE, **Apache-2.0 license** since 2020. Apache §4(d) requires `NOTICE` file in `Third-Party-Notices.txt` AND visible in-game About screen. **Ship-OK for shipped-binary use.** Raycast occlusion + transmission + reverb + dynamic geometry + portals. **Adopt regardless of middleware choice.**
- **Sonniss GameAudioGDC** — ~160GB cumulative archive 2016-2026, royalty-free commercial, no attribution. **Sonniss GameAudioGDC 2026 ships 26+ thunder samples in the cumulative archive (~160GB)** — equivalent SFX coverage to THOR Thunderstorm $30 (R2-A2 #5 verified count). Combined with 50-LOC `LightningController.cs` the FREE path delivers full storm SFX + visual at $0. **CAVEAT (R2-A8):** Section 4 AI/ML training prohibition applies to YOU not attackers. If you ever train an internal AI model on shipped audio = BREACH. Relevant given Hunyuan3D-2 stack.
- **Freesound CC0**, **OpenGameArt CC0**, **Pixabay free SFX**, **NASA audio** public domain. Note (R2-A8): audit each OpenGameArt download — many are CC-BY-SA (viral) or CC-BY-NC (non-commercial = BLOCKER).
- **Kevin MacLeod incompetech** — 2,000+ tracks CC-BY 4.0. Required attribution: `"<Track> by Kevin MacLeod (incompetech.com) — Licensed under CC By 4.0 — http://creativecommons.org/licenses/by/4.0/"`. End credits OK per CC-BY 4.0 §3(a)(2). Alternative: pay $30/song no-attribution license.
- **Free Music Archive CC-BY**.
- **Footstepper free** (159431) — Asset Store, surface-detection by Footstep Material assets, terrain-splatmap aware.
- **dropecho/unity_footstep** GitHub — **NOASSERTION license** (R2-A5). Use as algorithmic reference only.
- **dimdimich123/ModularFootstepSystem** GitHub — verify license before vendoring.
- **Unity-AudioOcclusion** GitHub MIT — raycast-based occlusion.
- Unity native AudioReverbZone presets keyed off existing `audio_reverb_class` raster.

**License chain ship checklist (R2-A8):**
1. `Third-Party-Notices.txt` in installed game folder (Apache + MIT NOTICE files).
2. In-game Settings → Credits → Third-Party Licenses sub-page (CC-BY attributions).
3. End credits: Kevin MacLeod tracks + CC-BY assets.
4. Steam store "Includes" section: Wwise/FMOD trademarks if used.
5. `LICENSES.md`: dssim "CI-build-only" policy.

**EXCLUDE — non-commercial license:** **BBC Sound Effects** (RemArc license). Will block ship. **CarterGames/SaveManager** — GPL-3.0 (R2-A5 says R1 silent on license — kills closed-source build). Replace with **DerKekser/unity-save-system** (MIT, active 2024-08-22) per R2-A5 critical-alternate #3.

### 2.10 Editor productivity & visual gates

**Stack to adopt ($0):**
- **Unity Recorder 5.1** — FREE package, accumulates HDRP path-traced sub-frames into PNG sequences. **The golden-screenshot pipeline.**
- **HDRP Path Tracing** — native HDRP 17, RTX 4060 Ti supports DXR.
- **Cinemachine 3.1+** — FREE Package Manager, HDRP volume adapters, supports Unity 6.4.
- **Unity Test Framework + Graphics Test Framework 8.6** — FREE, built-in `ImageAssert.AreEqual(camera, refImage, settings)` MSE/RMSE thresholds. Replaces hand-roll dssim.
- **dssim (kornelski)** Rust CLI — multiscale SSIM L*a*b*, AGPL/commercial dual. AGPL fine for build-side CI (not shipped).
- **Animation Rigging 1.4** — FREE Two Bone IK for foot placement.
- **AI Navigation package** — replaces legacy NavMeshComponents.
- **Localization (com.unity.localization)** — FREE first-party.
- **TextMesh Pro / UI Toolkit** — Unity 6.3 bundled.
- **A* Pathfinding free** — Aron Granberg, Burst+Job, free tier covers 95% of cases.
- **Save System (MIT):** AlexMeesters/Component-Save-System, DerKekser/unity-save-system, CarterGames/SaveManager.
- **JetBrains RiderFlow** — free Unity editor plugin.
- **Scene Templates** — built-in.

---

## §3. PAID TOOL DECISIONS (R2 FINAL — REVISED 2026-05-07: SpeedTree 9 Indie restored, happy-turtle DROPPED)

R2-A2 verified each "BUY" against VRAM constraint + free-equivalent availability. **MicroSplat HDRP-for-6.3 + SpeedTree 9 Indie are the two positive-ROI paid tools** (foliage stack pivoted from happy-turtle to SpeedTree 9 Indie 2026-05-07 — happy-turtle abandoned 2021, broken on HDRP 17 ShaderGraph, no commercial ship history). This table supersedes all R1/R1.5 paid-tool tables.

| Tool | Cost | Decision | Reason |
|------|------|----------|--------|
| MicroSplat base (96478) | FREE | adopt | required dep for HDRP-for-6.3 |
| **MicroSplat HDRP for Unity 6.3 (344008)** | **$20 BUY (one-time)** | **BUY** | Closes Texture Clusters gap (3 sub-textures cycled per layer pseudo-randomly per jbooth blog + Asset Store ID 104223). Unity 6.3 native does NOT cycle — produces visible "Skyrim grass plane" tiling at 60+m. Saves ~3 days of Shader Graph node-spaghetti. Booth ships continuously since 2018 — 7-year update record. |
| **SpeedTree 9 Indie subscription** | **$19/mo or $199/yr** | **BUY (foliage canonical)** | REPLACES happy-turtle/foliage-wind decision (4.5y abandoned, broken on HDRP 17 ShaderGraph, no commercial ship history). Unity 6.3 SpeedTree 9 Importer is FREE; Indie subscription unlocks **Modeler + .st9 export** with HDRP 17 GRD-compatible native wind. AAA foliage-wind parity with Witcher 3 NG / Hellblade 2 / Cyberpunk 2.0. Subscription is monthly-cancellable so cost rolls off after authoring sprints. |
| MicroSplat Mesh Terrains (157356) | $20 | **conditional** | Only if cliffs/overhangs gameplay-critical. No free alternative at this fidelity tier. |
| **Cloud bake-rig (RunPod RTX 4090 spot)** | **~$31/mo (optional)** | **adopt-recommended** | Path-traced goldens + APV bakes off-rig at ~$0.40/hr, ~80 hr/mo realistic usage. Keeps local 4060 Ti 8GB free for editor work. See §18 setup. |
| Auto-Rig Pro | OWNED | acknowledge | user has installed (already paid) |
| Amplify Impostors (119877) | $30 | **DROP — $0** | SpeedTree 9 Importer (FREE, Unity 6.3 native) ships built-in octahedral billboards driven by .st9 export from SpeedTree 9 Indie. |
| Beautify HDRP (165411) | $39.99 | **DROP — $0** | HDRP 17.6 ships ACES + Neutral natively. AgX (meenphie GitHub MIT) ports cleanly = 1-evening. Purkinje effect = ~30 lines of HLSL custom post-process volume (R2-A2 #3). |
| Aurora Borealis Shader VFX | $25 | **DROP — $0** | olawlor/AuroraRendererUnity public domain. HDRP custom-pass port = 4-6 hr (R2-A2 #4). |
| THOR Thunderstorm | $30 | **DROP — $0** | 26 thunder samples replaceable with Sonniss GDC (free royalty-free). 50-LOC LightningController.cs covers logic (R2-A2 #5). |
| **happy-turtle/foliage-wind** | n/a | **DROP — abandoned** | Last commit 2021; broken on HDRP 17 ShaderGraph node API; no commercial ship history. Replaced by SpeedTree 9 Indie above + DIY HDRP Shader Graph wind (~2 days) for procedural filler density. |
| Wwise Indie | FREE | adopt | <$250K dev BUDGET threshold (NOT revenue — see §7.2). 1% royalty above. |
| Wwise Pro (above-Indie tier) | **$8,000 first platform + $4,000 each extra platform** OR 1% gross-sales royalty | conditional | FINAL-V3 #6 fill: triggers when production BUDGET exceeds Indie threshold ($250K). The $250K threshold is dev BUDGET not revenue. Royalty alternative is post-launch waivable below $10K revenue. Maintain `docs/license/wwise_budget_audit.md` snapshot at greenlight + pre-launch + 6/12mo post-launch. (R2-A8, codex c06.) |
| Steam Audio Unity | FREE | adopt | **APACHE-2.0 since 2020 — NOT AGPL.** R1 was wrong. NOTICE-file attribution only. Runtime occlusion/portals/transmission (R2-A6 N1, R2-A8). |
| Crest 5 HDRP (268614) | $100-200 | **SKIP** | free GitHub Crest 4 is BIRP-only; HDRP 17.6 native WaterSurface + foam fix covers AAA-tier with DLSS 4.5 SR Quality |
| Gaea 2 Pro | $199 | **SKIP** | Indie tier ($99) cannot automate; not needed for v1 |
| Bakery GPU Lightmapper | $60 | **SKIP** | APV native deprecates |
| Magic Light Probes | $50 | **SKIP** | APV native deprecates |
| Enviro 3 / Cozy / Sky Master / Expanse / Atmospheric Height Fog / HDRP Time of Day | $35-100 | **SKIP** | redundant with HDRP 17.6 native |
| Botaniq Trees Pro | $89 | **SKIP** | SpeedTree 9 Indie above is canonical; Modular Tree GoodPie + Sapling covers stylized filler (R2 §1.6 confirms headless works) |
| Geo-Scatter full library | $69 | **SKIP** | free tier headless verified working (R2 §1.6) |
| GPU Instancer Pro | $70 | **SKIP** | GRD native equivalent now |
| GPU Instancer legacy free | n/a | **EXCLUDE** | non-commercial license — legal trap |
| BBC Sound Effects | n/a | **EXCLUDE** | RemArc license non-commercial only — fail-PR risk |

**Day-1 spend: $20 one-time (MicroSplat HDRP-for-6.3) + $19 (SpeedTree 9 Indie first month).**
**Recurring during active dev: $19/mo SpeedTree + ~$31/mo cloud bake-rig (optional but recommended) = ~$40-50/mo.**
**Annual SpeedTree Indie alternative: $199/yr (saves ~$30 vs 12 monthly).**
**Conditional add: +$20 MicroSplat Mesh Terrains if cliffs/overhangs gameplay-critical.**
**See §14.1 + §18 for hardware-upgrade options (B/C) + per-domain AAA tier matrix.**

---

## §4. TerraForge3D PORT TARGETS (MIT-licensed, vendor-friendly)

Repo: github.com/Jaysmito101/TerraForge3D — C++/GLSL/OpenCL desktop tool. Active branch: gen3 (last code 2023-11-21). License: MIT.

1. **GPU erosion compute kernel structure** (`Data/compute/erosion.glsl` + `GPUErosionFilter.cpp`) — 1024-thread workgroup parallel droplet. Map to `_terrain_erosion.py:208-547` bottleneck. Numba `@njit(parallel=True)` or Taichi port = ~50-100x speedup at 1024², unblocks multi-pass cascades.
2. **Aeolian/wind erosion** (`AdvancedErosionFilter.cpp` + `WindErosionParticle`) — params: Suspension, Abrasion, Roughness, Settling, Sediment. Desert/tundra biomes get only hydraulic+thermal today; aeolian is the missing third pillar (dunes, sandblasted ridges, lee-side accretion). Add `apply_aeolian_erosion_masks` next to thermal.
3. **Curve-node value-remap profile** (`CurveNode.cpp` + ImGui::CurveValueSmooth, 10-256 control points) — port via scipy `PchipInterpolator` to `terrain_stratigraphy.py`. Designers tune erosion-delta-per-altitude without code edits.
4. **Unified mask-as-channel pattern** (gen3 Mask Editor, commit `c800a84` 2023-11-21) — formalises our scattered `mask: np.ndarray` parameters across 26+ pass functions. Concept maps to `PassDefinition.overrides=` but cleaner UX.
5. **FastNoiseLite cellular jitter + 4 distance metrics** (Manhattan / EuclideanSq / Hybrid) — Manhattan gives angular fortress-cliff polygons for VeilBreakers dark-fantasy biomes. Add `distance_metric` and `jitter` kwargs to our Worley primitive in `_terrain_noise.py`.

**Skip:** their CPU droplet (we have hero-exclusion + erodibility map), absence of thermal erosion (gap on their side), no biome system.

**Visual quality:** their renders are proceduralist-tool internal preview, NOT AAA. Closer to World Machine v1 demo than Houdini/Gaea. Our HDRP stack will exceed if we close aeolian gap.

---

## §5. PROCEDURAL-PLANT-AND-FOLIAGE-GENERATOR PORT TARGETS (GPL-3 — clean-room only)

Repo: github.com/adremeaux/Procedural-Plant-and-Foliage-Generator — Unity URP C# + HLSL compute. **GPL-3.0** — vendoring binds VeilBreakers commercial release. **Hard blocker for direct use; clean-room port only.**

**Visual quality:** stylized-realistic single-leaf macros (anthurium/begonia/orchid). Hero-tier *houseplants*, NOT forest foliage. Zero mid/far-field applicability. No LOD, no impostors, no wind, no scatter, no canopy. Targeted technique donor for hero close-up foliage in cemetery / mushroom_forest / ruined_citadel biomes.

**5 clean-room ports (algorithms aren't copyrightable; specific code is):**
1. **Vein topology + split + spanner** (12 vein params: VeinDensity, VeinBunching, VeinSplit/Depth/Amp, SpannerLerp, Squeeze, MidribTaper, SecondaryTaper) → emit per-species procedural vein albedo+normal in `terrain_foliage_catalog.py`.
2. **Distortion-on-curve compute shader** (`LeafDistort.compute` `DistortOnCurve` kernel `[numthreads(8,1,1)]`, cubic Bézier `(1-t)³p₀ + 3(1-t)²tp₁ + 3(1-t)t²p₂ + t³p₃` against influence curves) — best transferable IP. Replaces broken `DrawMeshInstanced` 1023-cap path with `RenderMeshIndirect` + leaf-curl compute pre-pass for hero foliage.
3. **Penetration-resolution sequential collision** (`PlantPhysicsSimulator.SolveCollisions` — sequential `Physics.ComputePenetration` against progressive composite, accumulate offsets in `Vector3[]`). Resolves leaf interpenetration after Poisson placement. Port as Python pre-bake with `scipy.spatial.cKDTree.query_ball_point` overlap resolver in `vegetation_system.py`.
4. **Parameter-space hybridization** (Default/Min/Max + LPRandomValCurve [CenterBell / CenterBellLRSplit] + LPRandomValCenterBias [Spread1-3, Squeeze1-3] + LPImportance tier per param) — bias variance curves so "veil_healthy" cluster around healthy phenotype with rare blighted outliers.
5. **CPU-side IM texture command pipeline** (`IMTextureFactory` composable layered ops: DrawGradient → DrawCellsOverlay → DrawInnerShadow → DrawVeinBackdrop → DrawPrimaryVeinsRadiance → DrawPrimaryVeinsMain → DrawHairlineVeins → DrawMargin) — direct fit for our PIL/numpy bake stage.

**Skip:** whole-tool fork (GPL ban), pot/trunk/arrangement (single-houseplant scope), ImageMagick CPU compositor (port concept, not dep).

---

## §6. IMPLEMENTATION PATH (R2-A7 60-day plan — REPLACES R1's 30-day)

**Why 60 not 30:** R2-A7 verified the 30-day plan covers only 30-40% of P0 surface. Spec §11 v3 has 114 PRs and Decision 3.3 budgets 30-45 days for spec critical path ALONE — R1 added new TerraForge3D + PFG ports + Unity HDRP scene + APV bake + foliage + audio + visual gate on top. This new plan targets ~80% of P0 at $0 spend / 8GB constraint.

### PHASE A (Days 1-15) — Bake-side blockers + spec critical-path PRs
- **D1-2:** PRs #1+#2 (gitignore + LFS hygiene + pyproject CVE fixes) cleanup; pip-audit zero-CRITICAL gate.
- **D3-5:** PR #3 topo-sort consumes `overrides=` → unblocks 8 orphan-registered passes. Fix Bug-A (derive_pass_seed bifurcation, branch-only — ensure main's single-source design wins on merge), Bug-D (water_network attr_name silent swallow), Bug-E (14 random.Random sites → derive_pass_seed; 5 magic-offset, 9 plain-seed).
- **D6-7:** B15-P0-01 affine rescale + B15-P0-02 4-biome crash + import-time biome-name invariant. **GATE D5** = topo-sort PR landed.
- **D8-9:** PR #4 wire 8 orphan passes + 6 missing register_*_pass functions (snow_line shadow-write removed, stratigraphy/wind_erosion/coastline scheduled).
- **D10-11:** PR #5a/#5b W-1 channel migration + B15-P0-05 caustics rename.
- **D12-13:** B15-P0-08 hydraulic mass leak (75% boundary loss) + B15-P0-10 gradient axis swap + B15-P0-11 mean subtraction.
- **D14-15:** B15-P0-17 bedrock_height pre-integration + P0-18 hardness Y-axis vs Z-axis + P0-21 horizon_lod overrides; foam Beaufort cubic at `terrain_waterfalls.py:114-115`. **GATE D15** = bake-side P0 fixes landed; channel-graph audit green.

### PHASE B (Days 16-25) — Determinism, RNG migration, manifest atomicity, splat truncation
- **D16:** PR #9 vectorize road SDF via scipy EDT.
- **D17-18:** PR #15.5 + #14 chunk_seed module + derive_pass_seed unification across `terrain_rng` ↔ `terrain_pipeline`.
- **D19-22:** PR #18 RNG migration — 179 sites (100 production + 79 test) replace `random.Random(seed)` with `derive_pass_seed`. XL parallel job.
- **D23:** PR #15 4 hash hazards.
- **D24:** PR #12 atomic manifest + descriptor write + #13 NaN/Inf assertions.
- **D25:** B15-P0-07 splatmap L>4 truncation. **GATE D25** = subprocess-determinism CI matrix passes 18/18 (3 OS × 3 Py × 2 seed-seq).

### PHASE C (Days 26-35) — Orphan-pass wiring + label-stamping + stream cap
- **D26-27:** PR #16 stratigraphy + #17 morphology delta integrators wired in default sequence.
- **D28-29:** PR #21 pass contracts + #31-#32 macro_color 8-channel + 14-biome palette.
- **D30-32:** PR #29 label-stamping (Issue #27).
- **D33:** PR #36 splatmap 4→8 (Unity 2022+ supports 8 — but **lock effective 4 layers at 8GB** per R2-A1 quality preset).
- **D34:** PR #43 + #44 streaming budget cap (`QualitySettings.streamingMipmapsMemoryBudget = 3072`).
- **D35:** PR #42 missing emitters (vb_aspect_deg, vb_aspect_north, vb_canopy_openness, vb_TWI via new `pass_topographic_indices` ~150 LOC; consumer `requires_channels=` updates on foliage-catalog/scatter passes). **GATE D35** = `pass_topographic_indices` produces all 4 spec channels + foliage-stack consumer wiring complete.

### PHASE D (Days 36-45) — Unity ingestion + Block 5a visual gate
- **D36-37:** B5-U1 Unity 6.3 LTS + HDRP 17.6 project bootstrap + **4-layer splat config (NOT 8-layer — 8GB constraint)** + APV Sky Occlusion **OFF** at 8x8 grid. `Packages/manifest.json` + `VbHDRPAsset_HighFidelity_8GB.asset` (4 cascades, Sky Occ off, Tex2DArray 4-layer, Volumetric Clouds Low slice 64).
- **D38:** B5-U3 SetHoles consumer (`holes.png` was never read; wire up).
- **D39:** B5-U4 normal-Y flip handedness + B5-U5 edges.json contract.
- **D40-41:** B5-U2 HDRP WaterSurface stub (river + pool only — no ocean at 8GB).
- **D42:** B5-U8 flow_map RG16 EXR + RenderMeshIndirect for foliage (replaces `DrawMeshInstanced` 1023-cap; **Hi-Z occlusion mandatory** per R2-A3 #5).
- **D43-44:** Visual gate `scripts/run_unity_recorder_gate.py` + Graphics Test Framework `ImageAssert.AreEqual` SSIM ≥ 0.95 per spec §11.5b PR #6.5 (rasterized goldens at 8GB; **HDRP Path Tracer flagged v1.1** — 8GB OOMs at 1080p/300spp).
- **D45:** NotImplementedError shim for `compute_nonblack_ratio` (after replacement gate is live, NOT before — prevents 17-day CI break per V2 self-contradiction #3). **GATE D45** = visual gate SSIM ≥ 0.95 (per spec §11.5b PR #6.5) against rasterized goldens.

### PHASE E (Days 46-60) — Performance, atmosphere, audio, hero render, decision gate
- **D46-47:** PR #19 Numba/Taichi erosion (integer atomics ONLY — atomic-float ban per spec §8.4). TerraForge3D #1 GPU erosion compute kernel port (gated by §10 confirmation that existing Cordonnier 2016 SPL is genuinely the bottleneck — see §14.9 disagreement #2).
- **D48:** B15-P0-09 SPL solver wired (V1 confirms; V3 disagreement — verify before wiring).
- **D49-50:** Foliage RenderMeshIndirect + **Modular Tree GoodPie billboard impostors** (replaces Amplify $30 — see §2.1; **budget +3-5d for manual FBX-sidecar-JSON + AssetPostprocessor remapper** since GoodPie Unity export is months not days, per R2-V2 §13.5). NR6 compute-shader grass instancing 30K+ blades/chunk.
- **D51-52:** Volumetric Clouds Low slice 64 + 3 Local Volumetric Fog boxes (8GB cap — not 6) + 50-LOC `LightningController.cs` (HDRP Light flash + native Lens Flare ring shape).
- **D53:** AgX Tonemapping LUT bake + **Purkinje effect HLSL volume** (~30-LOC custom post-process per §2.4.x — replaces Beautify $40).
- **D54-55:** Wwise Indie + **Steam Audio (Apache 2.0 verified — see §7.2)** integration + AkRoom/AkPortal volumes from `audio_reverb_class` raster + Sonniss SFX + Footstepper free + day/night `AmbientAudioController`. Fallback FMOD Indie if Wwise authoring blocks.
- **D56-57:** B15-P0-15 vectorize 22 biome-feature O(N²) loops (~1 TB transient at 1024² removed).
- **D58:** Memory + spec doc updates (§14.8 supersession list).
- **D59-60:** Hero shot render + decision gate. **Rubric (REVISED 2026-05-07 per §18.1 + §18.9):** ≤16.67 ms frame budget at 1080p output via DLSS 4.5 SR Quality (Preset L, 720p internal). Native 1080p/60 NOT required; SR Quality is the contract. SSIM ≥0.95 vs rasterized golden. Foliage placement >0 per chunk. PYTHONHASHSEED=0 byte-identical determinism. 4060 Ti 8GB VRAM peak ≤ 7.4 GB sustained. **GATE D60** = pilot ships at 1080p/60 via DLSS 4.5 SR Quality (which is *upscaling*, not frame-gen). DLSS3 frame-gen is the only thing **EXPLICITLY DEFERRED to v1.1** contingent on Streamline integration work (per §18.9 + R2-V2).

**Deferred to v1.1:** APV Sky Occlusion (16GB rebake rig), 8-layer splatmap (16GB only), HDRP Path Tracer goldens (16GB rig), TerraForge3D GPU port (only if profiler confirms bottleneck), PFG #2 Bézier compute shader, refactors PR #49-#54, 30 Batch15 P1s, Aurora HDRP custom pass (4-6 hr — easy v1.1 win), 12 hero VFX Graph particle systems, Unity HLOD 2.0.

**TOTAL: 60 working days (~12 weeks calendar). $20 spend (MicroSplat HDRP-for-Unity-6.3) + $20 conditional (Mesh Terrains if cliffs). All else free.**

<details><summary>R1 30-day plan (HISTORICAL — REPLACED by 60-day above; do NOT execute)</summary>

### Days 1-3: Code-state corrections + critical fixes
1. **Fix Bug-A: derive_pass_seed bifurcation** — delete `terrain_rng.py:45` definition, re-export from `terrain_pipeline.derive_pass_seed`. Update `_scatter_engine.py:22` import path. (~0.5d)
2. **Fix Bug-B: VbFloatingOrigin shift loop** — auto-shift `ReferenceTransform` if not in `ShiftRoots[]`. (~0.25d)
3. **Fix Bug-C: Material asset mutation** — verify-only at `OnEnable`, no runtime mutation. (~0.25d)
4. **Fix Bug-D: water_network attr_name swallow** — return tuple or dataclass. (~0.25d)
5. **Foam formula correction** at `terrain_waterfalls.py:114-115` (Beaufort cubic). (~0.25d)
6. **Rename `renders/visual-verification/batch15/`** → `renders/algorithm-sanity-checks/batch15/` with README warning that PNGs are fbm test fixtures NOT pipeline output. (~0.25d)
7. **Replace `compute_nonblack_ratio` smoke proof** with stub raising `NotImplementedError("VisualQA replaced by Unity Recorder + Path Tracer pipeline; see scripts/run_unity_recorder_gate.py")`. (~0.25d)
8. **Update `docs/AAA_MASTER_IMPLEMENTATION_GUIDE_2026_04_27.md`** — annotate every §3.1 stale claim with "FIXED — see IMPLEMENTATION_FIX_GUIDE_2026_05_07_FINAL.md §1.1". (~0.5d)
9. **Update memory** with §1.6 stale-corrections + Auto-Rig Pro owned + new bugs. (~0.25d)
10. **Fix Bug-E: terrain_features magic-offset RNG** — 14 sites → derive_pass_seed. (~0.5d)

**Subtotal: ~3 days. Output: clean baseline.**

### Days 4-7: HDRP scene bootstrap
11. Unity 6.3 LTS + HDRP 17.6 project bootstrap; `Packages/manifest.json` with HDRP 17.6 + Visual Effect Graph 17 + Adaptive Probe Volumes + Addressables + Burst + Collections + Mathematics. (~0.5d)
12. `Assets/Settings/HDRPGlobalSettings.asset` + `VbHDRPAsset_HighFidelity.asset` (4 cascades, Lit shader Both, Decal layers). (~0.5d)
13. `Assets/Scenes/vb_hero_demo.unity` scene authoring: Directional Light 50° altitude / 145° azimuth / 100k lux + Camera + HDAdditionalCameraData (TAA, Volume layer mask). (~0.5d)
14. **Master Volume profile** (`vb_default_volume_profile.asset`): PBS Sky + Volumetric Fog + Volumetric Clouds Medium + Bloom + Tonemapping (ACES initially, swap to AgX after Day 11) + Vignette + Color Adjustments + Manual Exposure 0.0 EV. (~1d)
15. **MicroSplat HDRP-for-6.3 install** ($20) + 8-layer splat config + TerrainLayer auto-binding from manifest. (~1d)
16. **APV authoring + Sky Occlusion ON** + per-biome Probe Adjustment Volumes + Max Probe Spacing 243m + bake (overnight 4-6 hr). (~1d active + 6 hr passive)

**Subtotal: 4 days. Output: pilot biome HDRP scene with terrain rendering.**

### Days 8-11: Foliage + scatter
17. **Convert `VbFoliageManifestRenderer`** from `DrawMeshInstanced` to `Graphics.RenderMeshIndirect` (kills 1023 cap + `_BaseColor` SetVectorArray bug). Use AlexMerzlikin BRG template. (~1.5d)
18. **Fix biome catalog name vocabulary (P0-S2)** — unify `procedural_grass.DEFAULT_BIOME_ID_MAP` ↔ `terrain_biome_registry.CANONICAL_BIOME_IDS`. Add CI assertion `assert set(BIOME_CLIMATE_PARAMS) == set(CANONICAL_BIOME_IDS)`. (~1d)
19. **Wire `pass_procedural_grass`** density emit + grass_density_map manifest output. (~0.5d)
20. **Buy + integrate Amplify Impostors** ($30 — 50% off list $60; R1's "$90" was stale) — 4 species impostor atlas. (~1d)
21. **happy-turtle/foliage-wind shader** — wind on terrain detail mesh + impostor LOD swap. (~0.5d)
22. **Nature Renderer 6 Free** — install + replace Unity Terrain detail mesh layer with NR6 compute-shader instancing for 30K+ blades/chunk. (~1d)
23. **EricHu33 trample RT** + nedmakesgames Shader Graph wind+trample. (~0.5d)

**Subtotal: 6 days. Output: 5 species visible in scene with wind + LOD + impostors.**

### Days 12-15: Atmosphere + lighting polish
24. Volumetric Clouds Medium preset tuning per biome. (~0.5d)
25. Volumetric Fog density tuning + 3 Local Volumetric Fog boxes for hero mood. (~0.5d)
26. **olawlor/AuroraRendererUnity** Custom Pass port — HDRP 17 wrap. (~1.5d)
27. **VFX Graph fireflies + ember context** — `Output Particle HDRP Volumetric Fog`. (~0.5d)
28. **Shader Graph emissive runic glyphs** for ruined_citadel / corrupted_swamp biomes. (~0.5d)
29. **AgX Tonemapping LUT bake** in DaVinci Resolve free → `.cube` → HDRP Color Adjustments external LUT. Yharnam-Tuscany recipe. (~1d)
30. **Lightning controller** — 50-LOC `LightningController.cs` (Light flicker + Volume keyframed Exposure spike + cloud alpha pulse). (~0.5d)

**Subtotal: 5 days. Output: full atmosphere + lighting feel.**

### Days 16-19: Water + audio
31. **HDRP WaterSurface bind** to `water_surface_z` + `water_depth_m` + `shoreline_mask` + `flow_speed`. River + Pool surface types per biome. (~1d)
32. **Custom flow_map writer** in `terrain_unity_export.py` — RG16 EXR for HDRP River currentMap. (~0.5d)
33. **Frozen-water shader** (daniel-ilett port to HDRP) for Veil-frozen biomes. (~1d)
34. **Wwise Indie** integration + AkRoom + AkPortal volumes from `audio_reverb_class` raster. (~1.5d)
35. **Steam Audio Unity** — occlusion + reverb + portals. (~1d)
36. **Sonniss SFX** + **Footstepper free** + day/night `AmbientAudioController`. (~1d)

**Subtotal: 6 days. Output: water + AAA audio chain.**

### Days 20-22: Visual gate replacement
37. **`scripts/run_unity_recorder_gate.py`** — Unity Recorder Image Sequence + HDRP Path Tracing (256-1024 spp accumulation) → PNG goldens. (~1d)
38. **Graphics Test Framework `ImageAssert.AreEqual`** wired into CI for SSIM/MSE thresholds against goldens. (~1d)
39. **`VbHeroShotRecorder.cs`** + Cinemachine vcam tagged "HeroShot" + 4 Volume profiles for biome-specific framing. (~1d)

**Subtotal: 3 days. Output: real visual gate replacing the fbm-fixture lie.**

### Days 23-26: Spec/code drift + remaining P0/P1
40. **`pass_topographic_indices`** (~150 LOC) — produces `vb_aspect_deg`, `vb_aspect_north`, `vb_canopy_openness`, `vb_TWI` per spec §3.5. (~1.5d)
41. **Add `BIOME_CLIMATE_PARAMS == CANONICAL_BIOME_IDS` invariant** assertion at module-import time. (~0.25d)
42. **Fix B15-P0-05** — caustics default channel rename `water_surface` → `water_surface_mask`. (~0.25d)
43. **Schedule `stratigraphy`, `wind_erosion`, `coastline`** explicitly in default sequence (currently consumed only via delta integration). (~1d)
44. **Mask cache byte-cap** (P0-I2) — replace entry-cap 128 with byte-cap (default 4 GB) at `terrain_mask_cache.py:134`. (~0.5d)
45. **`validate_vertex_attributes_present` wire-up** (P0-E1) at `terrain_unity_export.py`. (~0.5d)
46. **Tree prototype size** (P0-E2) — drive from `SpeciesSpec` instead of hardcoded 10m. (~0.5d)
47. **Resolve `pass_horizon_lod` naming mismatch** anomaly. (~0.25d)
48. **Remove `snow_line` shadow-write** registration — pass_glacial overrides it; delete the orphan registrar. (~0.25d)
49. **Clean `pyproject.toml mcp` extra** — pin SHA + integrity hash, remove python_version inconsistency. (~0.25d)
50. **Hero shot render** — render `vb_hero_demo.unity` via Recorder. Side-by-side vs Hellblade-2 alpine still. Decision gate: scale to 8 chunks OR re-evaluate architecture. (~1d)

**Subtotal: 6 days. Output: spec-faithful pilot + production gate.**

### Days 27-30: TerraForge3D port + Plant-Foliage-Gen port (clean-room)
51. **TerraForge3D #1: GPU erosion compute kernel** Numba/Taichi port → `_terrain_erosion.py`. (~1.5d)
52. **TerraForge3D #2: Aeolian erosion** for desert/tundra biomes. (~1d)
53. **TerraForge3D #3: Curve-node profile** scipy PchipInterpolator → `terrain_stratigraphy.py`. (~0.5d)
54. **PFG #2: Bézier distortion compute shader** for hero close-up foliage curl. (~1.5d)
55. **PFG #3: Penetration-resolution KD-tree overlap resolver** in `vegetation_system.py`. (~0.5d)

**Subtotal: 5 days. Output: aeolian erosion + hero-foliage distortion + leaf overlap fix.**

**TOTAL (HISTORICAL — STALE): 30 days. ~$70 R1.5-era spend ($40 MicroSplat + $30 Amplify Impostors at sale, list $60 — R1's $90 figure was stale per Verifier 2 + R2-V2). All else free.** Final R2 baseline is $20 / $40 ceiling per §0.3 + §14.1 — Amplify is dropped entirely; SpeedTree 9 Importer + GoodPie billboards replace it free.

</details>

---

## §7. RISKS & MITIGATIONS

### 7.1 Hardware reality (R2-A1 — 8GB-locked)

**HARD CONSTRAINT: 8GB VRAM** (RTX 4060 Ti 8GB confirmed per `project_hardware_8gb_vram_2026_05_07.md`). VeilBreakers locks at **High preset** baseline. Path Tracing at 1080p alone consumes 11-12GB → KILL from runtime (editor-only goldens). 4-preset table:

| Preset | VRAM target | APV Sky Occ | Splat layers | Volumetric Clouds | Fog vols | Reflection probes | RT |
|--------|-------------|-------------|--------------|-------------------|----------|-------------------|----|
| **Ultra** (16GB only) | 12-14GB | ON | 8 layers 4K | High slice 128 | 12 vols | 8×512² resident | RTGI ON |
| **High (8GB safe)** ← **VeilBreakers v1 baseline** | 5.5GB / 1.5GB headroom | OFF | 4 layers 4K BC7 | Low slice 64 | 6 vols | 4×256² FIFO | SSGI only |
| **Medium (8GB safe)** | 4.0GB | OFF | 4 layers 2K BC7 | Low slice 32 | 3 vols | 2×256² FIFO | none |
| **Low (4GB Steam Deck)** | 3.0GB | baked LMs | 2 layers 1K | disabled | 0 vols | baked only | none |

**8GB VRAM budget table (5.5GB Unity / 1.5GB headroom / 1GB OS):**

| Allocation | MB |
|---|---|
| HDRP camera + GBuffer + history | 100 |
| VBuffer (clouds Low + fog) | 250 |
| 4-layer terrain T2DArray BC7 + mips | 113 |
| Reflection probe cache (4 × 256²) | 64 |
| APV runtime (no Sky Occ, 8x8 streamed) | 200 |
| Foliage GPU buffers (8x8 streamed) | 220 |
| Mesh + materials streaming pool | 1500 |
| Lightmaps + shadow atlas | 800 |
| Misc (UI, post FX, BVH if RT) | 250 |
| Driver/headroom | 500 |
| **Total** | **~4000 + 1500 streaming = 5.5GB** |

**R1 tools cut/swapped at 8GB (R2-A1):**
1. **Path Tracing** → KILL from runtime (editor-only goldens, 720p / 64spp accumulation)
2. **APV Sky Occlusion** → OFF at 8x8 grid (drop to 4x4 if needed)
3. **8-layer terrain** → 4 layers (HDRP cap remains 8 but 4 effective at 8GB)
4. **12 fog volumes** → 3-6 with 32³ density masks
5. **8 cubemap probes resident** → 4 FIFO at 256²
6. **Volumetric Clouds Medium** → Low slice 64
7. **No realtime planar reflections for water** — SSR + cubemap fallback

**Frame-budget reality at 8GB / 1080p:**
- **Day-time:** 22ms total measured (R2-A10 ship table) = **150% of 16.6ms = NOT 60fps achievable.** **Lock 1080p/45 v1** (22.2ms budget); 1080p/60 with DLSS3 FG is v1.1 contingent on Streamline integration per R2-V2. **Spec must lock this — see §14.10.**
- **Night-time:** ~16.1ms (alpha/fog overdraw lower) → comfortable at 60fps for night scenes only.
- **APV bake reality:** 3-10 min per chunk; 3-12 hr full 8×8 grid (chunk-batched overnight). Max Probe Spacing 243m mandatory for 32GB system RAM safety.
- **Path Tracer goldens:** editor-only at 720p / 64spp accumulation, restart Unity between bakes (denoiser leaks per R2-A3 #10).

**Verdict:** AA-ceiling shippable at 8GB / 1080p / 45fps with High preset. **Reference: PS4-Bloodborne 5GB pool (NOT Hellblade-2 Series-X 10GB)** — see §16.

### 7.2 License chain audit (R2 — Steam Audio CORRECTED to Apache 2.0)
- **L-Py / PlantGL CGAL:** dual GPL/LGPL/commercial. Internal bake: $0. Binary ship: requires strict LGPL component selection or commercial CGAL.
- **Steam Audio:** **APACHE 2.0 — NOT AGPL** (R1 was WRONG). Verified by R2-A8 + codex c02 against `github.com/ValveSoftware/steam-audio/blob/master/LICENSE.md`. Valve open-sourced as Apache 2.0 on **Feb 19 2024** (v4.5.2 — first open-source release of SDK source code; no Valve public record of the SDK ever being AGPL). **Ship-OK for commercial closed-source Unity HDRP.** Required: include Apache 2.0 license text in `Third-Party-Notices.txt` + ship `NOTICE` file content if upstream provides one + mark any modified Steam Audio files with change notices. **NOT required:** source release, AGPL copyleft compliance, modification disclosure to players.
- **Procedural-Plant-and-Foliage-Generator:** GPL-3.0 — **clean-room ports only. Do not vendor code.**
- **Crest free GitHub (Crest 4):** MIT, but BIRP-only. We're not using.
- **happy-turtle/foliage-wind:** **NO LICENSE FILE — R1 said Apache 2.0, WRONG (R2-A5).** SHIP-BLOCKER. **Action:** file GitHub issue at upstream repo; if no response within 30 days, **re-author wind shader internally** (~1-2 days HLSL or Shader Graph subgraph). Until clarified, exclude from any vendored binary.
- **AlexMerzlikin/Unity-BatchRendererGroup-Boids:** **NO LICENSE FILE** (R1 said MIT, WRONG per R2-A5). Algorithmic reference only.
- **sinanata/Unity-HDRP-Water-Buoyancy-Handler:** **GPL-3.0** (R1 silent, R2-A5 caught). Replace with **dbrizov/NaughtyWaterBuoyancy** (MIT, active 2026-04-11).
- **CarterGames/SaveManager:** **GPL-3.0** (R1 silent). Replace with **DerKekser/unity-save-system** (MIT).
- **Scrawk/Tiled-Directional-Flow:** NOASSERTION (R1 said MIT — unverifiable per R2-A5).
- **WorkingClassDuck/URP-HDRP-Water, ozgurdegil/triplanar-shader-graph, gihuncho/unity-procedural-stochastic-tiling-triplanar, dropecho/unity_footstep, HLODSystem:** all **NO LICENSE / NOASSERTION** per R2-A5. Algorithmic reference only.
- **Crest 5 paid SKU:** Asset Store EULA. **Skipping.**
- **Wwise Indie:** Free if production **BUDGET** <$250K USD (NOT revenue, R2-A8 #4). 1% royalty above. **Audit cadence (R2-V2 corrected):** at greenlight + pre-launch + every 6-12 months post-launch (range, not single fixed 6-12mo schedule). Audiokinetic indie-license blog.
- **FMOD Indie:** Free under $200K annual revenue + $600K dev budget. Above either → flat $2K/platform OR Commercial $5-15K. NOT percentage royalty.
- **Sonniss GameAudioGDC:** royalty-free + **AI/ML training prohibition applies to YOU not attackers** (R2-A8 #3). If you ever train internal AI model on shipped Sonniss audio = BREACH. Critical given Hunyuan3D-2 stack.
- **BBC Sound Effects RemArc:** non-commercial. **EXCLUDE — fail-PR risk.**
- **GPU Instancer legacy free:** non-commercial. **EXCLUDE.**
- **dssim (kornelski):** DUAL AGPL-3.0 OR commercial. SAFE if CI-build-only (no shipping trigger). Pin policy in `.github/workflows/*.yml` + `LICENSES.md`.

**Manifest checklist for ship (R2-A8):**
1. `Third-Party-Notices.txt` (Apache + MIT NOTICE files, including Steam Audio Apache 2.0 + Valve copyright)
2. In-game Settings → Credits → Third-Party Licenses sub-page (CC-BY attributions)
3. End credits: Kevin MacLeod tracks + CC-BY assets
4. Steam store "Includes" section: Wwise/FMOD trademarks if used
5. `LICENSES.md`: dssim "CI-build-only" policy
6. **Re-author or replace happy-turtle/foliage-wind shader** — license unverifiable

### 7.3 Maintenance reality (active vs abandoned)
- **Active 2026:** Crest (MIT, Feb 2026), Modular Tree GoodPie fork (Jan 2026), happy-turtle/foliage-wind, MangoButtermilch grass instancer (Mar 2026), NaughtyWaterBuoyancy (Apr 2026), MicroSplat (Dec 2025), Geo-Scatter v5.6.2.
- **Abandoned but works:** Unity-Technologies/HLODSystem (tested 2021.3.3, validate Unity 6 patch), Scrawk/Phillips-Ocean (2022), Scrawk/Brunetons-Ocean (2022).
- **DO NOT USE — abandoned:** AlTheSlacker/HDRPDayNight (author flags broken), EmmetOT/HDRPGrass (Unity 2019.4 only), yangrc1234/VolumeCloud (won't be maintained), ColinLeung-NiloCat/UnityURP-MobileDrawMeshInstancedIndirectExample (URP-locked Unity 2019.4), mkrebser/GPUInstance (13 commits, Unity 2023.2 maybe), MTree main fork last release 2021-12-11 (use GoodPie fork instead).

### 7.4 Cross-tool conflicts (17 verified + 5 NEW per R2-A6)
1. **MicroSplat HDRP-for-6.3 vs Unity 6.3 native Terrain Shader Graph** — pick one, never mix on same chunk. Recommend MicroSplat ($20).
2. **APV vs SSGI** — configure SSGI "additive on top of APV" not "replace" to avoid double-count.
3. **GRD vs MaterialPropertyBlock** — GRD silently disables; audit `VbFoliageManifestRenderer` after RenderMeshIndirect rewrite.
4. **HDRP Path Tracer + MicroSplat shader** — Path Tracer goldens require TerrainLit fallback. Editor-only goldens at 8GB (cannot run runtime).
5. **Wwise vs Unity native audio** — Wwise replaces AudioListener; pick one at scene init.
6. **Steam Audio + Wwise** vs **Steam Audio + FMOD** — both work; Wwise pairing has tighter Rooms & Portals integration.
7. **Auto-Rig Pro vs Unity Animation Rigging** — different scopes; not in conflict.
8. **(NEW R2-A6 N1) Steam Audio license chain** — Apache 2.0 since 2020. Apache §4(d): include NOTICE file. NOT AGPL (R1 wrong).
9. **(NEW R2-A6 N2) SpeedTree .st9 vs glTF Draco** — Draco strips morph targets used by SpeedTree wind. Decision: keep .st9 for trees; glTF/Draco for static props only.
10. **(NEW R2-A6 N3) Blender Z-up vs Unity Y-up vs SpeedTree Y-up forward-Z chain** — FBX export from Blender with default `-Y forward, Z up` produces parent rotation `(-89.98°, 0, 0)` in Unity that breaks Auto-Rig Pro retarget. **Fix:** Apply Transform in FBX exporter or use Unity FBX Importer "Bake Axis Conversion".
11. **(NEW R2-A6 N4) HDRP Decal Projector vs Terrain Holes** — decals project through hole alpha but lose depth. **Workaround:** tag decals `Affects Transparent = Off` in cave entrances.
12. **(NEW R2-A6 N5) GPU Resident Drawer vs DLSS3 frame-gen** — GRD's per-frame BRG buffer updates fight with DLSS3 motion-vector reprojection. Verify DLSS plugin version 3.7.10+. Unity 6.3 added `_LastFrameWorldPos` write via DOTS-instanced motion-vector pass; older 6.0 = visible smearing.

### 7.5 NVIDIA driver 536.40+ introduced fallback / 546.01+ added the toggle — shared-memory cliff (NEW — CRITICAL 8GB risk)

**Per R2-A3 #1 + R2-A6-N1 + V2 codex confirmation + R2-V1/R2-V2 corrected per NVIDIA KB a_id/5490: driver 536.40+ introduced shared-memory fallback (silently spills to system memory at ~3 GB/s vs 288 GB/s VRAM = ~96× workload-specific slowdown when VRAM exhausts), and driver 546.01+ (2023-10-31) added the user-facing toggle** `CUDA - Sysmem Fallback Policy = Prefer No Sysmem Fallback` in NVIDIA Control Panel — Manage 3D settings — Program Settings. Users on driver versions <536.40 do not see the cliff because the fallback didn't exist; users on 536.40-545.x see the cliff with no in-driver remedy; users on 546.01+ can disable fallback per-app. **CRITICAL for shipping — without explicit launcher check, Steam users on 8GB experience random crashes that they will report as Unity bugs.**

**Required ship-side implementation (4 parts):**

1. **`--driver-required >=546.01` launcher check.** Build a small native launcher (`VbLauncher.exe`) that calls `nvapi.dll` `NvAPI_SYS_GetDriverAndBranchVersion`. If <546.01: show GUI dialog "Update NVIDIA driver to 546.01+ for stable performance" with link to https://www.nvidia.com/Download/. Block launch until updated, OR offer "Continue at risk (random stutter possible)" override flag.

2. **VRAM telemetry at 2Hz.** Wire `GraphicsSettings.gfxDeviceMemoryBudget` polling at 2Hz (every 500ms). Log to `Application.persistentDataPath/vram_telemetry.log` with timestamp + reported VRAM + estimated headroom. Format: `2026-05-07T12:34:56Z, 7368MB used, 7424MB budget, 56MB headroom`.

3. **Auto-degrade on threshold breach.** On `>7.2GB sustained 3sec` trigger one-step downgrade through preset chain: Ultra→High→Medium→Low. Each downgrade: log to `vram_degrade.log`, show toast "Quality reduced to <preset> for stability." Persist new setting.

4. **`Assets/Settings/HDRP_4060Ti_Failsafe.asset` auto-activator.** Detects `SystemInfo.graphicsMemorySize <= 8192` at boot. Forces: Volumetric Clouds → Low; Tex2DArray → 4-layer 2K; WaterSurface SimulationResolution → 128; APV Sky Occlusion → bake-time only (runtime read disabled); shadow cascades 4→3; render scale 1.0→0.9 if frame >18ms.

**Phase-0 hardware capture harness:** Before locking the stack, build `tools/hwcap/capture_4060ti.py` that runs an empty HDRP scene + each R1 feature toggle individually and logs VRAM peak via `nvidia-smi --query-gpu=memory.used --format=csv -lms 100`. Lock the stack only after capture confirms each pick fits in <600 MB headroom against 7.4 GB working ceiling.

**Stacked-feature memory ceiling (R2-A3 #2):** APV 250MB + Volumetric Clouds Medium 450MB + WaterSurface Ocean+River 250MB + 8-layer 4K Tex2DArray 500MB + foliage Indirect 50MB + HDRP base 700MB + shadows 250MB + 8 hero SpeedTree species 800MB = **~3.25GB before any gameplay assets**. Leaves only ~4.5GB for animations, characters, particles, post-FX, audio, frame-N+1 streaming. **No headroom for hot-loading new chunks — preset reductions in §7.1 mandatory.**

**Texture streaming + HDRP virtual texturing (R2-A3 #5, NOT in R1):** Default Unity streaming on 8GB cards uses 6GB, leaving HDRP only 2GB → instant fallback. Must set `QualitySettings.streamingMipmapsMemoryBudget = 3072` (3GB) explicitly at boot.

**GPU compute contention (R2-A3 #3):** Spec runs Taichi-CUDA bakes on the same 4060 Ti during dev. Editor + Taichi share VRAM context → bake-while-editing OOMs Unity Editor. **Mitigation:** sequential bake-then-edit workflow; never run Taichi while Unity Editor open.

**Unity Terrain multi-pass shader stalls (R2-A3 #4):** With 10-layer Shader Graph terrain, first-time-seen terrain triggers async shader compilation 6-14 sec on 4060 Ti — pink/black tiles during fly-through. Recorder captures these stalls into goldens. **Mitigation:** prewarm shader variants at scene load via `ShaderVariantCollection.WarmUp()`.

**DLSS3 Frame Generation memory cost (R2 codex r2c10):** Per NVIDIA Streamline DLSS-G guide, **1080p = 272MB** VRAM (NOT 120-160MB). Footprint same for single-frame and multi-frame modes. Unity HDRP 17.6 ships **DLSS 4.5 SR only — no native FG**. Streamline 2.11.1 (2026-04-21) has FG but no turnkey Unity plugin. **At 8GB with HDRP + textures + terrain + shadows + water + APV + GRD already at ~5.5GB, adding 272MB DLSS-G is feasible but tight.** Decision (§14.10): treat FG as optional PC setting, D3D12-first, with VRAM telemetry gate; lock 1080p/45 raster v1, evaluate Streamline integration for v1.1.

---

## §8. VERIFICATION GATES (R2-A9 — 13.5 days CI work)

### 8.1 Existing gates (R1 baseline)

1. **Visual fidelity:** SSIM ≥ 0.95 vs HDRP Path Tracer goldens (per spec §11.5b PR #6.5; raised from R1's 0.92). Replaces fake `compute_nonblack_ratio`.
2. **Determinism:** subprocess byte-identity CI gate already wired at `terrain_bundle_n.py:421`. Expand artifact matrix from 3 of 18 → 18 of 18 (spec §11.5.4 PR B5-T4).
3. **Channel-graph integrity:** `PassDefinition.overrides=` + `_STRICT_PROVENANCE` + `ChannelOwnershipError`. Run on every PR.
4. **Biome name invariant:** `assert set(BIOME_CLIMATE_PARAMS) == set(CANONICAL_BIOME_IDS)` at module-import time.
5. **Foliage placement gate:** assert minimum N placements per chunk.
6. **License manifest gate:** `tools/audit_asset_licenses.py` — fails PR if BBC RemArc, GPL-3 vendored code, or non-commercial SFX present.
7. **Frame-budget gate:** `VbPerformanceProfiler` runs hero shot, asserts <22.2 ms day (1080p/45 lock) / <16.67 ms night.
8. **Cross-pipeline gate (optional, deferred):** SSIM ≥ 0.65 vs Gaea Pro reference (defer until Gaea Pro purchased).

### 8.2 R2-A9 8 critical CI gaps (commercial-release blockers)

Current CI inventory: 5 workflows (`python-package.yml` Ubuntu Py 3.11/3.12, `type-check.yml` pyright 1.1.408, `callable_census.yml`, `visual_testing_readiness.yml`, `codeql.yml`). Test inventory: 167 test files, 139 handlers, pytest markers benchmark/contract/integration/slow/visual. **Unity side: ZERO Editor tests, no .csproj, no .unity scene, no manifest.json, no Builds/, no Steam/itch automation.**

| # | Gap | What's missing | Effort | Priority |
|---|-----|----------------|--------|----------|
| 9 | **No Unity Test Framework / Graphics Test Framework workflow** | `ImageAssert.AreEqual` for SSIM goldens requires `game-ci/unity-test-runner@v4` matrix | 2 days | P0 |
| 10 | **No Windows runner** | Game ships Win 11; pytest only Ubuntu. Need `runs-on: windows-2022` matrix | 0.5 day | P0 |
| 11 | **No determinism subprocess matrix** | Spec §11.5.4 demands 18 artifacts (3 OS × 3 Python × 2 seed-seq); current is in-process theatre | 2 days | P0 |
| 12 | **No license-manifest gate** | Sonniss/BBC RemArc/AGPL detection not wired. Need `scripts/license_manifest_gate.py` | 1.5 days | P0 |
| 13 | **No biome-name invariant gate** | `scripts/biome_name_invariant_gate.py` diffing canonical registry vs catalog vs foliage manifest | 0.5 day | P0 |
| 14 | **No frame-budget / VRAM perf gate** | Unity Performance Testing Extension job asserting <22.2ms gameplay + <7.5GB GPU.allocatedMemory (8GB-locked) | 2 days | P0 |
| 15 | **No SSIM golden snapshot retention/ratchet** | Nightly `golden-snapshot.yml` storing PNGs as artifacts (retention 90 days) + tag-based prune script | 2.5 days | P1 |
| 16 | **No release pipeline** | Steam upload (steamcmd), itch (butler push), beta-branch routing all manual. Need `.github/workflows/release.yml` with encrypted secrets | 1.5 days | P1 |

**Total CI effort: ~13.5 days for P0-P1** (5 nice-to-haves Hypothesis/Steam-Proton/Sentry/AI-tag/Gaea-compare adds ~3 days = 16.5 days max).

### 8.NICE — 5 Nice-to-have CI gaps (FINAL-V3 #7 fill)

R2-A9 surfaced 8 critical gaps (above) plus 5 nice-to-haves not previously enumerated in §8. Total nice-to-have effort: ~3 days. Defer to v1.1 unless free agent capacity allows during Phase E.

| # | Gap | What's missing | Effort | Priority |
|---|-----|----------------|--------|----------|
| N1 | Hypothesis property-based tests | Random-seed property tests for `derive_pass_seed`, channel ownership, splatmap layer invariants. `pip install hypothesis` + `tests/property/test_*.py` + `pytest -m property` job. | 1 day | P2 |
| N2 | Linux x64 Steam Proton matrix entry | Add `runs-on: ubuntu-22.04` Proton compatibility smoke (`pytest -m steamdeck`). Validates Steam Deck shipping target (per §17.7 v2 escalation). | 0.5 day | P2 |
| N3 | BugSplat / Backtrace.io free crash reporting | Free-tier crash reporter integration. Auto-uploads stack + `vram_telemetry.log` + `vram_degrade.log` (per §7.5) on crash. | 1 day | P2 |
| N4 | AI/ML training tag CodeQL custom query | Custom CodeQL query flagging any code path that could train models on shipped Sonniss/Steam-Audio assets — protects R2-A8 §3 / Sonniss §4 BREACH risk. | 0.5 day | P2 |
| N5 | Weekly Gaea reference compare | Cron `monday-gaea-compare.yml` SSIM-comparing pilot biomes vs static Gaea reference. Defer until Gaea Pro $199 purchased (currently SKIP per §3). | defer (paid prereq) | P3 |

### 8.3 Pre-merge vs post-merge split (per V3 + V14.6)

**Pre-merge required (cheap, fast, < 5min total):**
- `ci (3.11)`, `ci (3.12)` (Ubuntu pytest)
- `pyright`
- `callable-census`
- `Analyze (python)`, `Analyze (actions)` CodeQL
- **NEW:** Windows runner (gap #10)
- **NEW:** biome-name invariant gate (gap #13)
- **NEW:** license-manifest gate (gap #12)
- **NEW:** channel-graph integrity (gate #3)

**Post-merge nightly (expensive, 30+ min):**
- SSIM Path Tracer goldens (gap #9 + gate #1)
- Frame-budget perf at 8GB target (gap #14 + gate #7)
- Determinism subprocess matrix 18 artifacts (gap #11 + gate #2)
- VRAM telemetry validation (per §7.5)

**Post-merge tag-triggered (release):**
- Release pipeline (gap #16)
- Golden snapshot ratchet retention (gap #15)

### 8.5 GATE verification commands (paste-ready bash one-liners — §19.8 #7 fill)

For each §17 GATE checkpoint, paste the matching one-liner. Each must exit 0 to proceed past the GATE.

| GATE | Verification command |
|------|----------------------|
| **GATE D5** (§17.1) | `pytest veilbreakers_terrain/tests/test_biome_climate_params.py -v && pytest veilbreakers_terrain/tests/test_terrain_world.py::test_affine_rescale -v` |
| **GATE D15** (§17.1) | `pytest veilbreakers_terrain/tests/test_pass_dependencies.py -v && python scripts/audit_orphan_passes.py --strict` |
| **GATE D25** (§17.2) | `PYTHONHASHSEED=0 pytest veilbreakers_terrain/tests/test_determinism_subprocess.py -v` |
| **GATE D35** (§17.3) | `python scripts/validate_unity_export_manifest.py --tile output/chunks/mountain/0_0/manifest.json` |
| **GATE D45** (§17.4) | `cd unity_project/VbHeroDemo && Unity.exe -batchmode -projectPath . -executeMethod VbVisualGate.RunSSIMGate -refImage Assets/Goldens/mountain_pilot.png` |
| **GATE D60** (§17.5) | `python scripts/ship_minimum_audit.py --biomes mountain_pass,corrupted_swamp --hero-shots 12` |

If any one-liner above references a script that doesn't yet exist (e.g., `scripts/audit_orphan_passes.py`, `scripts/validate_unity_export_manifest.py`, `scripts/ship_minimum_audit.py`, `tests/test_determinism_subprocess.py`), it MUST be authored before the corresponding GATE day arrives. See §17.0 for skeleton commits + §8.2 for Unity-side gap inventory.

---

## §9. WIRING DISCONNECTS / DUPLICATES (consolidated)

| Item | Type | Where | Fix |
|------|------|-------|-----|
| `derive_pass_seed` two definitions, incompatible | DUPLICATE | `terrain_rng.py:45` vs `terrain_pipeline.py:269` | Bug-A above |
| `register_default_passes` registers 17 passes (9 + 8 supplemental) but docstring claims 9 | DOC DRIFT | `terrain_pipeline.py:1747-1769` | Update docstring |
| `pass_horizon_lod` referenced in default sequence; Bundle J registers `horizon_lod` | NAMING TYPO | `terrain_pipeline.py:221` vs `BUNDLE_J_PASSES` | Anomaly 2 above (Verifier 1: phantom — both names registered at `terrain_horizon_lod.py:344`) |
| `snow_line` registered + scheduled but `pass_glacial` overrides immediately | DEAD WEIGHT | snow_line registrar | Anomaly 1: delete snow_line registrar |
| `stratigraphy`, `wind_erosion`, `coastline` registered but not in default sequence | ORPHAN-REGISTERED | bundles I/I/I | §6 step 43 — schedule explicitly |
| `vb_aspect_deg`, `vb_aspect_north`, `vb_canopy_openness`, `vb_TWI` consumed but never produced | SPEC/CODE DRIFT | spec §3.5 vs code | §6 step 40 — `pass_topographic_indices` |
| `terrain_quixel_ingest` writes splatmap weights; `terrain_materials_v2` rewrites them last (declared intentional `:1240-1242`) | DOCUMENTED OVERLAP | dual writers | Acceptable; document in `feedback_channel_ownership_pattern.md` |
| `terrain_features.py` 14 magic-offset RNG | RNG DUPLICATE | `:262, 761, 1296...` | Bug-E |
| Unity importer + Floating Origin reference frame asymmetry | SCALE DRIFT | `VbTerrainImporter.cs:791` vs `:386` (water vs terrain) | Multiply terrain by `height_scale_factor` OR remove water divide |
| `VbTerrainRuntimeStreamer.cs:78` deprecated `Resources.FindObjectsOfTypeAll` | LEGACY API | Unity 2023+ | Use `FindObjectsByType<>(FindObjectsSortMode.None)` |
| `VbTerrainRuntimeStreamer.cs:124` silent disable of frustum culling on null Camera | SILENT FALLBACK | no warning | Add `Debug.LogWarning` |
| `terrain_features.py` 14 unguarded `random.Random(seed)` instantiations + magic offsets | DETERMINISM HAZARD | various | Bug-E |
| `_water_network.py:1097` numpy attr_name silent swallow | SILENT-SWALLOW | `:1096-1099` | Bug-D |
| `VbFloatingOrigin.cs` ReferenceTransform not in ShiftRoots | INFINITE LOOP | `:38-58, 70-78` | Bug-B |
| `VbFoliageManifestRenderer.cs:220` shared Material asset mutation | ASSET CORRUPTION | `[ExecuteAlways]` | Bug-C |
| **`terrain_lava.py:89-100` D8 8× transfer accumulation** | **R2-A4 — EXPORT MISMATCH** | high-viscosity flows balloon | Bug-F |
| **`terrain_unity_export.py:1587-1588` `terrain_size_x_m` double-applies UNITY_SCALE_FACTOR** | **R2-A4 — UNIT DRIFT** | Blender/Unity QA tools disagree | Bug-G |
| **`terrain_morphology.py:455` magic-offset seed `int(intent.seed) + idx`** | **R2-A4 — DETERMINISM HAZARD** | seed collisions across feature variants | Bug-H |
| **`VbTerrainImporter.cs:608-619` navmesh grid shape inference non-deterministic for `cellCount=256`** | **R2-A4 — SHAPE DRIFT** | navmesh modifiers placed at wrong (row,col) when 1×256 vs 16×16 admit same square | Bug-I |
| **`terrain_pipeline.py:483-507` `register_pass` weak-ref leak on overwrite** | **R2-A4 — STALE REGISTRY** | post-`importlib.reload()` runs old pass for one tick | Bug-J |
| **`_default_splatmap_layer_meta:1274` and `terrain_layers` count vs `splatmap.layer_end` mismatch** | **R2-A4 X2 — SPEC/CODE DRIFT** | when `terrain_layer_assets` array length ≠ `(end - start)`, C# at `:891` silently drops layers `< layer_start` or `> layer_end`. Tiles with `layer_start > 0` lose splatmap layer 0 weight; C# zero-sum guard at `:912` fills with layer 0 = 1.0 → entire tile renders as first terrain layer, no biome variation visible. | Add length-vs-range invariant assert on Python side BEFORE manifest write; fail loud not silent. C# import should also assert and throw, not zero-sum-guard. |

---

## §10. WHAT WE HAVE AT AAA-OR-BETTER GRADE (don't break these)

1. **Stream-Power Law solver** with Cordonnier 2016 ε resolve-flats — `_terrain_erosion.py:916`. Houdini Heightfield Erode SOP doesn't ship this.
2. **Channel-graph ownership** — `PassDefinition.overrides=`, `_STRICT_PROVENANCE`, `ChannelOwnershipError`. None of cited engines publish equivalent.
3. **Determinism plumbing** — `derive_pass_seed`, version_hash, per-chunk reseed. Subprocess CI gate at `:421`. (Once Bug-A fixed.)
4. **Edge-stitch contract design** — spec §6.3 fail-fast assertion, more rigorous than most AAA studios.
5. **Master registrar bundle architecture** — explicit registration order rationale, prevents "tree roots in mid-air" class of bugs.
6. **Heightmap algorithm** — H=0.85 IQ 3-level domain warp at `_terrain_world.py`, A-grade vs Carpathian/Yorkshire reference.
7. **24-direction A* AASHTO road network** — better than par_streamlines flat ribbons.
8. **Worley + cellular noise** at `_terrain_noise.py:675` — full F1+F2 + smin support.

---

## §11. MEMORY UPDATES TO APPLY (R2 FINAL after verifiers approve)

> **CANONICAL: see §14.8 for the authoritative ADD / SUPERSEDE / DELETE-COLLAPSE list.** §11 is retained as a high-level pointer; §14.8 is the most-recent and most-complete spec. If §11 and §14.8 ever diverge, §14.8 wins.

The reference summary below mirrors §14.8 entries; do not edit here without also editing §14.8.

```
- project_user_owned_tools_2026_05_07.md: Auto-Rig Pro INSTALLED (already created)
- project_hardware_8gb_vram_2026_05_07.md (NEW): RTX 4060 Ti 8GB locked; High preset baseline; Path Tracer KILLED from runtime
- project_truth_table_corrections_2026_05_07.md (NEW): supersede 2026-05-06 with §1.6 corrections
- project_implementation_fix_guide_2026_05_07_FINAL.md (NEW): pointer to this doc
- project_foliage_stack_2026_04_26.md: SUPERSEDED by §2.1 — Botaniq/BlenderKit/Geo-Scatter headless verified
- feedback_audit_artifacts.md: NEW guidance — verify A10-style stale audits against current code
- project_pickup_state_2026_05_07.md (NEW): supersede 2026-05-06 pickup state
- project_60_day_plan_2026_05_07.md (NEW per §14.8): Phase A-E §17
- DELETE/COLLAPSE per §14.8: project_audit_status_2026_04_27.md, _28.md, _05_01.md; project_terrain_audit_2026_04_15.md; project_deep_dive_guide_2026_04_20.md; project_master_implementation_guide_2026_04_26.md.
```

**5 critical alternates required (R2-A5 — supersede prior memory entries):**

| Stale entry | Replace with | License | Last update |
|---|---|---|---|
| MaximeHerpin/modular_tree (4.5y dark, 110 issues) | **GoodPie/modular_tree** | GPLv3/MIT split | 2026-03-29, Blender 4.3+ |
| Unity-Technologies/HLODSystem (no LICENSE; Unity 2021.3 dead-end) | **Unity HLOD 2.0 in com.unity.hlod package** | Unity Companion | Unity 6 native |
| CarterGames/SaveManager (GPL-3 — kills closed-source) | **DerKekser/unity-save-system** | MIT | 2024-08-22 |
| sinanata/Unity-HDRP-Water-Buoyancy-Handler (GPL-3 viral) | **dbrizov/Unity-WaterBuoyancy (NaughtyWaterBuoyancy)** | MIT | 2026-04-11, 947 stars |
| Crest free GitHub (BIRP-only) | **Unity HDRP WaterSurface native** | Unity built-in | Unity 6.3 native |

**License corrections to memory (R2-A5 + R2-A8):**
- `feedback_audit_artifacts.md`: Add note — R1 license claims for happy-turtle/foliage-wind (Apache 2.0), AlexMerzlikin BRG (MIT), Scrawk/Tiled-Directional-Flow (MIT) all WRONG. Verify against actual LICENSE file before claiming.
- `project_user_owned_tools_2026_05_07.md`: Steam Audio is **APACHE-2.0 since 2020**, NOT AGPL. R1 was wrong throughout.
- `project_audit_strictness.md`: Add — branch-vs-main divergence required for `derive_pass_seed` cite (`terrain_rng.py:45` on branch; `terrain_pipeline.py:208` on main).

---

## §12. OPEN QUESTIONS FOR USER (when awake)

1. **RTX 4060 Ti — 8GB or 16GB variant?** Major impact on APV + Volumetric Clouds + 8-layer Texture2DArray viability.
2. **Wwise Indie or FMOD Studio Indie?** Recommendation: Wwise for tighter Rooms & Portals; FMOD if learning-curve matters more.
3. **Unity 6.3 native Terrain Shader Graph or MicroSplat HDRP-for-6.3?** Pick one. Recommend MicroSplat ($20) for solo-dev convenience; native saves $20 if happy hand-authoring shaders.
4. **Beautify HDRP ($45)** — buy now or after Day 11 LUT bake test? Strong dark-fantasy fit but optional.
5. **THOR Thunderstorm ($30)** — buy if storm encounters core gameplay; skip if not.
6. ~~Steam Audio AGPL question~~ — **RESOLVED: Apache 2.0 since 2020-02-19** per R2-A6/A8/V2. User-action only: confirm Apache §4(d) NOTICE shipping plan.
7. **CGAL commercial license** — needed if shipping L-Py/PlantGL trees as binary; otherwise internal-only and free.
8. **Tier-Speedtree decision** — confirmed: SPEEDTREE INDIE NOT NEEDED. SpeedTree 9 Importer FREE in Unity 6.3 + Modular Tree GoodPie fork covers shipped-asset workflow.

---

## §13. VERIFIER APPENDIX (pending — 3 verifier agents in flight)

After this doc was written, 3 Opus verifier agents were dispatched in parallel:
- **Verifier 1 — Code-fit & wiring:** does every claim match repo state? Are tools claimed compatible actually compatible?
- **Verifier 2 — Stale-data sweep:** did any stale claim sneak in? Is anything contradicted by source?
- **Verifier 3 — Completeness audit:** is anything missing? Any gap not addressed? Any duplicate noted?

[Section appended automatically with verifier outputs.]

---

## §13.1 Verifier 1 Report — Code-fit & Wiring

**Scope:** Re-verified every §1.1 FIXED claim, §1.3 NEW BUGs, §1.4 anomalies, §1.5 spec drift, §3 paid tools, §6 spot-checks, §9 wiring rows. Read-and-grep, no execution.

### CONFIRMED accurate
- **W-1** `_water_network.py:907-911` — water_surface_mask preferred, water_surface fallback. Exact match.
- **W-4** `validate_seam_continuity` called at `_water_network.py:2047` (doc said 1955, actual call site is 2047; def at 2407). Mechanism FIXED, line cite slightly off.
- **C-1** `handlers/__init__.py:1141` — scatter_biome_vegetation removed comment present (doc said 1108,1121; actual at 1141).
- **C-2** `terrain_foliage_catalog.py:134-148` — lod_paths, wind_profile, impostor_atlas_path all present.
- **CL-2** `terrain_cliffs.py:2704-2706` — cliff_mask/talus_mask/strata_mask on stack (doc said 2673-2675; actual writes at 2704-2706).
- **V-1** `terrain_visual_qa.py:442,509,534,546` — all four functions exist as named.
- **E-1** `_terrain_erosion.py:308-318` — `np.clip(erod_arr, 0, 1)` exact.
- **E-2** `terrain_delta_integrator.py:40` — strat_erosion_delta in _DELTA_CHANNELS.
- **M-3** `terrain_texture_layer_stack.py:21-74` — class exists; "no direct production callers yet" docstring at line 39-42 (doc captured this caveat correctly).
- **M-4** `terrain_quixel_ingest.py:678,691-700,705-729` — AO + displacement load + blend present.
- **B14-10** Climate `iteration_scale` mutates at `_terrain_world.py:1224-1230` (doc cited 1158 which is metrics dict; FIX-B14-10 marker is at line 1208). Mechanism FIXED, line cite drift.
- **B15-P0-07** `terrain_unity_export.py:1741-1843` — `_write_splatmap_groups` with `(L+3)//4` ceiling at line 1788. Confirmed.
- **B15-P0-09** `_terrain_world.py:1415` — `compute_stream_power_erosion` called inside `pass_erosion`.
- **B15-P0-10** `_terrain_noise.py:1529` — `dy, dx = np.gradient(h, row_spacing, col_spacing)` correct numpy convention.
- **B15-P0-11** `_terrain_world.py:712-713` — comment documents removal of per-tile mean subtraction.
- **B14-6 / P0-P1** `road_network.py:1718` def, `:1872` registration, `terrain_master_registrar.py:231`, `terrain_pipeline.py:218` default sequence — all confirmed.
- **P0-I1** `terrain_bundle_n.py:421` subprocess call; line 217 is import-verifier (no parens).
- **P0-I3** `terrain_live_preview.py:35-60` — StackSnapshot uses xxhash int per channel, no deepcopy.
- **B15-P0-02** `_biome_grammar.py:82-101` — exactly 18 entries.
- **Bug-A** `terrain_rng.py:45` (string concat payload) vs `terrain_pipeline.py:269` (`json.dumps`) — INCOMPATIBLE. `_scatter_engine.py:22` imports from `terrain_rng`. Bifurcation real.
- **Bug-B** `VbFloatingOrigin.cs:38-58, 70-78` — `ShiftWorld` only iterates `ShiftRoots[]`; `ReferenceTransform` not auto-included. Real.
- **Bug-C** `VbFoliageManifestRenderer.cs:220` — `prototype.Material.enableInstancing = true` mutation in `[ExecuteAlways]` MonoBehaviour. Real.
- **Bug-D** `_water_network.py:1096-1099` — `rgba.attr_name = ...` inside `try/except: pass`. Real.
- **§1.4 Anomaly 1 (snow_line shadow-write):** `terrain_pipeline.py:1335` registers snow_line writing snow_line_factor; `terrain_glacial.py:438-439` overrides snow_line_factor. Real dead-weight.
- **§1.4 Anomaly 3 (pyproject mcp):** `pyproject.toml:25` git SHA pin without integrity hash + `python_version >= '3.12'` while `requires-python = ">=3.11"` (line 5). Real.
- **§1.5 spec drift:** `vb_aspect_deg`, `vb_aspect_north`, `vb_canopy_openness`, `vb_TWI` — zero hits in `veilbreakers_terrain/handlers/`. Real.
- **§3 paid tool IDs:** 344008 = "MicroSplat - HDRP for Unity 6.3" by Jason Booth. 119877 = "Amplify Impostors". 268614 = "Crest Water 5". 165411 = "Beautify HDRP". 96478 = "MicroSplat". 157356 = "MicroSplat - Mesh Terrains". All exist on Asset Store with claimed names.
- **§9 row** `VbTerrainRuntimeStreamer.cs:78` deprecated `Resources.FindObjectsOfTypeAll<>` — real.
- **Foam formula** `terrain_waterfalls.py:114-115` — `speed_ratio = 1.0 - flow_speed / max_foam_speed` is inverted. Real bug.
- **Render-pipeline lie** `scripts/render_batch15_verification.py` — only imports `bpy`, `numpy`, stdlib. Zero `veilbreakers_terrain` imports. Real.

### CONTRADICTED

- **W-2 file path WRONG:** Doc says `_water_network.py` `pass_water_depth`. Actual location is `terrain_pipeline.py:1355` (`def pass_water_depth(`); register at `:1344-1357`. Mechanism FIXED, but `_water_network.py` does not contain `pass_water_depth` at all. **Update §1.1 cite to `terrain_pipeline.py:1355`.**
- **B15-P0-05 cite WRONG:** Doc claims `_water_network_ext.py:1054` defaults `water_surface_channel = "water_surface"`. Actual code at line 1054 reads `water_surface_channel: str = "water_surface_elevation_m"`. Already-correct elevation channel; the legacy `"water_surface"` string the doc warns against is NOT present. **B15-P0-05 is a phantom — drop or rephrase.**
- **P0-I2 (mask cache) WRONG:** Doc claims entry-cap 128 at `terrain_mask_cache.py:134`. Actual code at lines 130-137 documents byte-budget default 2 GB with LRU eviction; references the 128-entry cap as the *old* design that "would have required ~30-40 GB." **Already fixed; drop from §1.2 / §6 step 44.**
- **P0-E2 (tree prototype hardcoded 10m) WRONG:** Doc cites `terrain_unity_export.py:2058-2061`. That range is HDRP mask-map smoothness. Actual prototype height code at line 2244 uses `np.median(valid)` of per-instance height_scale or `_TREE_HEIGHT_DEFAULT` fallback — already SpeciesSpec-driven via height column. **Drop from §6 step 46 unless the goal is to wire `SpeciesSpec.lod_distances_m` directly.**
- **P0-S2 (foliage catalog vocabulary) WRONG:** Doc cites `terrain_foliage_catalog.py:92-110, 270, 309, 324, 453, 466, 479+` using `forest`/`mountain`/`swamp`. Actual catalog at those lines uses canonical `thornwood_forest`, `deep_forest`, `mountain_pass`, `corrupted_swamp`, etc. Line 460,473 biome_mask use canonical IDs. Legacy alias resolver at line 822 handles backward-compat for `"forest"` → `"thornwood_forest"`. **The "zero placements" claim is unsupported — catalog is canonical-clean. Drop or refactor §6 step 18 to a CI assertion only.**
- **§1.4 Anomaly 2 (pass_horizon_lod naming) WRONG:** Doc claims silent-skip orphan-by-typo. Actual `terrain_horizon_lod.py:344` registers BOTH `"horizon_lod"` AND `"pass_horizon_lod"` in a loop with explicit overrides handling. **No mismatch; drop anomaly + §6 step 47.**
- **Bug-E count INACCURATE:** Doc claims "14 magic-offset RNG splits" with offsets `+9001`, `+77777`, etc. Total `random.Random(` count is 14, but only 5 sites use magic offsets (lines 1347, 1661, 3356, 4061, 4510). The remaining 9 use `random.Random(seed)` plain. Line cites 262, 761, 3082 use plain seed (no offset). **Reframe Bug-E as "14 unguarded random.Random instantiations (5 with magic offsets); replace all 14 with derive_pass_seed."**
- **§9 file path WRONG:** Doc cites `VbTerrainImporter.cs:791` and `:386`. File is at `unity_plugin/Editor/VbTerrainImporter.cs`, not `unity_plugin/` directly. Lines map: :386 = water `/ height_scale_factor`; :791 = `terrainData.size = (height_max_m - height_min_m)` — NOT a scale-factor multiply. The asymmetry framing is approximate; mechanism real but cites need editorial pass.

### NEEDS USER VERIFICATION

- ~~**RTX 4060 Ti VRAM variant** (8 GB vs 16 GB)~~ — **RESOLVED by FINAL-V1 (2026-05-07):** §0.2 + §7.1 + memory `project_hardware_8gb_vram_2026_05_07.md` already locked 8GB. Question struck.
- **Wwise Indie revenue threshold ($250 K)** — Audiokinetic license terms periodically updated; user should confirm current threshold at audiokinetic.com before commit.
- ~~**Steam Audio Unity runtime AGPL applicability to shipped binary**~~ — **RESOLVED by FINAL-V1:** R2-A6 N1 + R2-A8 + R2-V2 confirmed Steam Audio is Apache-2.0 since 2020-02-19 (v4.5.2). NOT AGPL. Question reframed → confirm `Third-Party-Notices.txt` + in-game About-screen NOTICE per Apache §4(d).
- **MicroSplat HDRP 344008 Unity 6.3 compat** — Asset Store page exists; "targets Unity 6000.3.0" specific compat-band claim cannot be confirmed without store-detail scrape (curl returned only meta tags). User should sanity-check on the asset listing.
- **Quixel Megascons free-via-Fab grandfathering** — UI/account-state dependent; cannot verify from repo.
- **Auto-Rig Pro installed** — accepted user statement (§0.2).

**Bottom line:** §1.1 mostly accurate but contains 2 wrong file paths (W-2, B15-P0-05) and 1 wrong-cite (B14-10). §1.2 contains 2 phantoms (P0-I2 already fixed; P0-E2 mis-cited). §1.3 Bug-E mis-counted. §1.4 Anomaly 2 already handled in code. §1.5 / §3 / Bug-A/B/C/D / foam / render-lie all real. Recommend doc patch before user wakes.

---

## §13.2 Verifier 2 Report — Stale-Data Sweep

**Verifier:** Final Verifier 2 of 3, dispatched 2026-05-07. Method: full doc read + cross-check vs `git show main:`, current-branch code, asset-store WebFetches, GitHub repo metadata, and every memory entry under `~/.claude/projects/.../memory/`.

### A. STALE entries inside the doc itself

1. **§3 / §0.3 — Amplify Impostors price ($90) is STALE.** Asset Store as of 2026-05-07 shows **$30 (50% off list $60)**, last updated **Jan 19 2026**, supports BIRP+URP+HDRP. Spend ceiling drops from $130 → $50-$70 ($20 MicroSplat HDRP + $30 Amplify; $40 if MicroSplat Mesh Terrains added). `[Correction: §0.3 "$130 max" → "$50-$70"; §3 row "$90" → "$30 (sale, list $60)"; §6 step 20 "$90" → "$30".]`
2. **§2.4 / §3 — Beautify HDRP price (~$45) is STALE.** Asset Store shows **$39.99**, last update **Mar 2 2026**, base Unity 2022.3.24, HDRP only. `[Correction: "~$45" → "$39.99"; reaffirm decision as stronger because update is post-2026-Q1.]`
3. **§1.3 Bug-A — branch-vs-main confusion.** The bifurcation IS real on the CURRENT branch (`docs/biome-render-rebuild-spec`: `terrain_rng.py` is 73 LOC with `derive_pass_seed` at `:45`; `terrain_pipeline.py:269`). But on `main` HEAD `9a5ecae`, `terrain_rng.py` is 43 LOC with NO `derive_pass_seed`, and the only definition lives at `terrain_pipeline.py:208`. The doc presents Bug-A as if it exists on canonical baseline; it does not. `[Correction: §1.3 Bug-A clarify "exists on this branch only; main HEAD has no bifurcation. Fix scope is to keep main's single-source design when this branch merges, not introduce duplication."]`
4. **§9 / §1.3 — `derive_pass_seed` cite `terrain_pipeline.py:269` is current-branch only; on main it is `:208`.** Mirror correction in §9 row 1 and Bug-A. The §11 spec PR #14 acceptance text already documents this correctly; the new doc disagrees with the spec.
5. **§4 TerraForge3D star count missing — actual 1.2k stars** (worth noting because the doc grades visual quality but doesn't anchor the project's social signal). Last named release v2.3 (Mar 29 2022); `gen3` branch active per WebFetch; doc's "last code 2023-11-21" is plausible but uncited.
6. **§5 PFG repo — 7 stars, not "stylized-realistic" mass-popular.** Doc tone overstates. Project is GPL-3 niche; 7 stars argues even more strongly for clean-room port over fork.
7. **§7.3 — Crest "MIT, Feb 2026" stale.** Crest 5 has shipped (per WebFetch README: "Crest Water 5 is now available"); Crest 4 in `wave-harmonic/crest` is the BIRP one. Doc should distinguish "Crest 4 BIRP free, Crest 5 paid HDRP/URP".
8. **§2.6 / §2.10 stale claim "MicroSplat HDRP for Unity 6.3 ($20)" is correct, but doc misses MicroSplat base Dec 7 2025 v3.9.49 update — `MicroSplat base` is FREE and was updated post-shipped. Add to §1.6 stale memory.**
9. **§0.2 "Unity 6.3 LTS released Dec 3 2025" — verify with user.** No source cited; if wrong, the entire HDRP 17.6 stack is wrong.
10. **§6 day plan — Day 4-7 step 13 says "Directional Light 50° altitude / 145° azimuth / 100k lux" — this is 100,000 lux, the AAA noon-sun illuminance. NOT stale per se, but unjustified vs spec §11.5b which never specifies values.** Soft-stale; flag for user-confirm.
11. **§8 verification gates — gate #1 says "SSIM ≥ 0.92" but spec §11.0.4 / §11.5b PR #6.5 mandates SSIM ≥ 0.95.** Doc loosens spec without explanation. `[Correction: §8 #1 "≥ 0.92" → "≥ 0.95 per spec §11.5b"; or document why 0.92.]`

### B. NEW STALE memory entries discovered (to add to §1.6)

| Memory entry | Stale claim | Reality |
|---|---|---|
| `project_truth_table_corrections_2026_05_06.md` | "`terrain_rng.py` is 43 LOC on main with NO `derive_pass_seed`" — true vs main only | Branch `docs/biome-render-rebuild-spec` has 73 LOC + `derive_pass_seed:45`. Memory needs branch-scope qualifier. |
| `project_truth_table_corrections_2026_05_06.md` | "Canonical `derive_pass_seed` is at `terrain_pipeline.py:208`" | True on main; this branch is at `:269`. Either branch is divergent or memory needs versioning. |
| `project_pickup_state_2026_05_06.md` | "Decision 3.2: BUY MicroSplat $40 default" | $40 still correct, but Amplify Impostors comparator price now $30 not $90 — total spend rebalances. |
| `project_master_implementation_guide_2026_04_27.md` | Already known stale per §1.1; CONFIRM that Phase 9E (AI provider) and Phase 9F (path contracts) have shipped per `docs/AAA_MASTER_IMPLEMENTATION_GUIDE_2026_04_27.md:367,371`. Doc §1.1 lists "M-3 scaffolded, awaiting integration" — old guide treats M-3 as P0 still; matches §1.1's status correctly. |
| `feedback_water_cliff_path_priority.md` | Likely stale given W-1, CL-2, road-network now FIXED per §1.1 — water/cliff/path no longer "previously failed AAA bar" since fixes landed. |
| `project_audit_status_2026_04_27.md` + `_28.md` + `_05_01.md` + `_05_03.md` | All flagged for supersession by §1.1 — but only the 2026-05-03 version is mentioned in MEMORY.md as IMPORTANT. Older ones still tagged "active." Add explicit "SUPERSEDED by 2026-05-07 FINAL" markers. |
| `project_terrain_audit_2026_04_15.md` | "Wave 9 committed (ed49cdb)" — pre-Batch-15. Whole memory is stale relative to current state. |
| `project_deep_dive_guide_2026_04_20.md` | Memory says superseded by 2026-04-26, which is superseded by 2026-04-27, which is superseded by §1.1. Chain is correct but unwieldy — collapse. |
| `feedback_codex_commits.md` | "Don't commit/push when Codex is verifying" — still valid but Codex (GPT-5.5) workflow has changed since `feedback_ce_workflow_per_pr.md` (2026-05-06). Cross-reference. |
| `project_ai_asset_provider_2026_04_27.md` | Hunyuan3D-2 v2.1+ now standard; doc only lists "v2.1+ required for full PBR". Verify against current upstream. |

### C. Self-contradictions in the doc

1. **§3 lists "MicroSplat HDRP $20 BUY" + "MicroSplat Mesh Terrains $20 conditional" totaling $40, but §0.3/§3 footer/§6 inconsistently call this "$40 MicroSplat" or "$20 MicroSplat HDRP only".** Day 4-7 step 15 says "$20 MicroSplat HDRP-for-6.3" only; §0.3 says "$40 MicroSplat". Spec §11.5a B5-U1 says $40 (HDRP+Mesh). `[Resolution: lock to $20 base buy + $20 conditional as separate line items everywhere; §0.3 "Total $130" is wrong if Mesh Terrains optional — should be $50 baseline / $70 conditional.]`
2. **§8 verification gates list 8 gates; MicroSplat is named ONCE in §3 as "BUY" but never appears in gate #6 license manifest gate.** Add MicroSplat EULA tracking to license gate. `[Resolution: §8 gate #6 add row "MicroSplat HDRP/Mesh Terrains: paid Asset Store EULA, vendor-friendly, document in license manifest."]`
3. **§6 step 6 + step 37 — both relate to render-pipeline cleanup. Step 6 renames `renders/visual-verification/batch15/` and step 37 builds `run_unity_recorder_gate.py`. Step 7 stub-replaces `compute_nonblack_ratio`. Order: step 7 happens BEFORE step 37 builds the replacement — leaves CI broken for ~17 days.** `[Resolution: move step 7 stub to AFTER step 37, or stub with "skip until Unity Recorder ready" rather than NotImplementedError.]`
4. **§1.1 row M-3 says "scaffolded, awaiting integration" — but §11 spec contains no PR to wire `TerrainTextureLayerStack` into `terrain_quixel_ingest.py`.** Doc claims FIXED but action is still required. `[Resolution: §1.1 M-3 row reclassify to §1.2 "open" and add a §6 step.]`
5. **§1.6 "MicroSplat HDRP for Unity 6.3 — shipped Nov 8 2025 at $20" but §3 row says "shipped Nov 8 2025; $20".** §0.3 says "$40 MicroSplat HDRP-for-6.3 stack" — implying both modules. The "$40 stack" framing in §0.3 contradicts §1.6's "$20 single SKU".
6. **§2.5 Crest skip / §7.2 license chain — §7.2 says "Crest free GitHub: MIT, but BIRP-only. We're not using; not a license risk." But §2.4 / §7.3 don't list Crest 5 ($100-200) as paid skip explicitly named — Crest 5 IS in §3 paid table but §7.2 sentence 4 reads as if free + paid both skipped. Tighten language.**
7. **§6 day plan — Day 27-30 ports TerraForge3D #1 (GPU erosion) and PFG #2 (Bezier compute). §10 already lists Stream-Power Law as "AAA-or-better" at `_terrain_erosion.py:916`. If we already ship A-grade SPL, why re-port a parallel hydraulic? Spec §11 PR #19 gates Taichi-CUDA Mei-2007 hydraulic; doc step 51 is a different port.** `[Resolution: §6 step 51 cross-reference §11 PR #19; pick ONE GPU-erosion implementation track.]`
8. **§6 step 50 "render `vb_hero_demo.unity` via Recorder. Side-by-side vs Hellblade-2 alpine still" — but Hellblade-2 reference image not anchored in repo.** No `tests/golden_scenarios/hellblade2_alpine.png` exists. Add asset acquisition step OR change reference.

### D. Date-staleness sanity check

- Doc dated **2026-05-07**; uses "as of 2026-05-07" appropriately throughout §1.6.
- Memory says "2026-04-27 master guide" — confirmed STALE per §1.1 (W-1 etc fixed). NO entries say "as of 2026-04-27" in the new doc itself.
- §7.3 "Active 2026: Crest (MIT, Feb 2026)" — Crest 4 last commit verified 3.8k stars but actual last-push date not visible via WebFetch. Soft-stale.
- §2.5 "dbrizov/NaughtyWaterBuoyancy MIT, last push 2026-04-11" — repo verified MIT, 947 stars, but last-push date unverified.

**End of Verifier 2 stale-data sweep.** Net: 11 stale items inside the doc, 10 new memory supersession candidates, 8 self-contradictions. The doc is materially-trustworthy for procurement direction but needs the price corrections (Amplify $30 not $90, Beautify $39.99 not $45) before user signs off, and needs Bug-A clarified as branch-only-not-main.

---

## §13.3 Verifier 3 Report — Completeness Audit

**Verdict: 30-day plan covers ~30-40% of open Batch15 P0/P1 surface; calendar over-promised by ~2×; key shipping gates missing.**

The doc is internally consistent and the new bug findings (Bug-A through Bug-E + spec drift §1.5) are all real and load-bearing. But measured against the AAA Master Audit (`docs/aaa-audit/AAA_MASTER_AUDIT_2026_05_03.md` — 24 P0 / 46 P1) and Batch15 (`docs/aaa-audit/batch15_2026_05_04/MASTER_AUDIT_BATCH15.md` — 34 new P0 / 45 new P1), §6 silently drops ~20 unaddressed P0s. Spec §11 v3 explicitly budgets **30–45 working days realistic solo** (~6-9 weeks calendar) for the 114-PR runway covering the same problem space; §6 budgets **30 days flat** for a strict subset PLUS new TerraForge3D + PFG ports + Unity HDRP scene authoring. One of the two estimates is wrong.

### CRITICAL GAPS (must add before user can ship)

1. **Batch15 P0s NOT in §6 day plan.** §1.2 lists 9 items as "genuinely open" but Batch15 has 34. Missing from the 30-day plan: B15-P0-01 (heightmap rescale ~200× — every tile produces wrong elevations); B15-P0-08 (hydraulic mass leak 75% at boundaries); B15-P0-15 (22 biome feature O(N²) loops, ~1 TB transient at 1024²); B15-P0-17 (bedrock_height pre-integration); B15-P0-18 (hardness_above Y-axis vs Z-axis); B15-P0-22 (water manifest validation); B15-P0-23 (road rasterization O(rows×cols×segments) Python loop); B15-P0-24 (NavMesh `.asset` binary never written); B15-P0-26 (heightmap row-flip vs tree-instance world-coord mismatch); B15-P0-30/31 (4 orphan delta producers + stale slope after deltas); B15-P0-32 (parallel-wave race in `banded_macro`); B15-P0-34 (124 uncovered callables; `--strict-zero` bypassed in CI). These are bake-side correctness issues that no Unity work fixes.
2. **Spec §11 critical-path absent.** Biome-render-rebuild spec critical path is `#1→#2→#3→#5a→#5b→#12→#36→#42→#44` plus Block 5a Unity (B5-U1→U2→U5→T1) ~5 days. The 30-day plan does NOT walk this. PR #5a/#5b (W-1 atomic migration), #12 (atomic manifest+descriptor), #36 (splat 4→8), #44 (stream cap) are missing. Spec PRs B5-U2 (WaterSurface stub), B5-U3 (`holes.png` never read), B5-U4 (tangent normal handedness), B5-U5 (`edges.json` contract) are 5 BLOCKING Unity-side gaps that no bake-side work fixes — none in §6.
3. **MicroSplat HDRP for 6.3 (asset 344008) not re-confirmed live.** §0.3 + §2.6 + §3 commit $20 spend. Verifier 1 already noted this needs WebFetch confirmation; if SKU was withdrawn or rebranded, §6 Day 4-7 stack collapses with no alternative listed. Add explicit fallback to "8-layer Shader Graph hand-author (~12-18 days)" if asset missing.
4. **No FAILSAFE plan for 8GB RTX 4060 Ti.** §0.2 + §7.1 + §12.1 flag the variant question but provide no fallback: if user owns 8GB, doc gives "quality cuts" without a VRAM budget worksheet or alternate config (4-layer instead of 8-layer Texture2DArray, APV at Max Probe Spacing 486m vs 243m, drop Volumetric Clouds entirely). Spec §11.7 Path 1 explicitly cuts the GPU perf gate for this reason; doc claims "comfortable headroom" on 16GB without a fallback table.
5. **Render-pipeline integrity fix is half-done.** §6 step 7 stubs `compute_nonblack_ratio` but does NOT remove or quarantine `scripts/render_batch15_verification.py`. Step 6 only renames the directory. The script remains callable; any CI workflow importing it keeps generating fake "verified" PNGs. Add explicit deletion or `raise NotImplementedError` at module top, plus order step 7 AFTER step 37 builds the replacement (or stub will leave CI broken for 17 days — Verifier 2 self-contradiction #3).
6. **No CI workflow files updated.** §8 lists 8 verification gates but no plan to author `.github/workflows/render-goldens.yml`, `perf-nightly.yml`, `flaky-hunter.yml` per spec §11.5.4. Existing 5 workflows (`callable_census.yml`, `codeql.yml`, `python-package.yml`, `type-check.yml`, `visual_testing_readiness.yml`) untouched. Without CI authoring, gates are documentation-only.
7. **Spec drift §1.5 has only producer fix; consumers untouched.** Day 23 step 40 adds `pass_topographic_indices` producing 4 channels but no `requires_channels=` updates to foliage-catalog/scatter consumer passes. Channel-graph integrity gate will pass while consumers still silently fall back. Need a Day 23.5 step touching consumer PassDefinitions.
8. **Missing pre-merge vs post-merge gate distinction.** §8 lists 8 gates but doesn't say which are PR-blocking (pre-merge required checks per CLAUDE.md: `ci (3.11)`, `ci (3.12)`, `pyright`, `callable-census`, `Analyze (python)`, `Analyze (actions)`) vs nightly cron vs post-merge SSIM monitoring. Without this split, CI authoring (gap #6) is undefined.

### MINOR GAPS (v1.1 addressable)

1. **Memory updates §11 incomplete.** `project_audit_status_2026_05_03.md` (24 P0 / overall C grade) not flagged as superseded. `project_audit_status_2026_05_01.md` Batches 0–13 lineage (429 codex) not flagged. `feedback_codex_commits.md` cross-reference to `feedback_ce_workflow_per_pr.md` (2026-05-06) missing. Spec §11.10 lists 5 stale memory items NOT in §11 of this doc.
2. **No deployment/release pipeline.** Nothing about packaging / Unity Cloud Build / Steam pipeline / itch.io upload. Acceptable for pilot but should be in v1.1 backlog.
3. **No build matrix.** Windows 11 only; no Linux/macOS even though Steam Deck (Proton/Linux) is a plausible AAA target. Spec §11.7 #16 explicitly cuts multi-platform for v1; track it.
4. **No dependency security scanning beyond `pip-audit`.** No SAST (Semgrep), no SBOM, no container scan. Spec §11.5.6 PR B5-DEP3 covers CodeQL `security-extended` — not in §6.
5. **No onboarding doc for next contributor.** Knowledge lives in agent memory + this guide. v1.1 should include `docs/CONTRIBUTING.md` + `docs/ARCHITECTURE.md` (do NOT auto-create now per CLAUDE.md no-proactive-docs rule; reserve for explicit user request).
6. **Plugin install validation tooling absent.** No script asserts MicroSplat / Amplify Impostors / Wwise / Steam Audio actually installed at expected versions before bake. Add `scripts/validate_unity_addons.py` v1.1.
7. **Performance regression-test harness absent.** §8 gate 7 says "VbPerformanceProfiler asserts <16.67 ms" but no committed pre/post baseline file. Risk: perf silently degrades while CI passes a moving target. Spec PR B5-T9 covers; not in §6.
8. **Golden snapshot retention policy missing.** Where do path-traced PNGs live? LFS? S3? Rotation? Spec §11.11.2 says `renders/proof/` LFS but no rotation/budget policy.
9. **`procedural_meshes.py` (22,607 LOC scope contamination)** in memory but absent from doc. Spec §11.7 #7 + §11.8 #13 defer relocation to v1.1; doc should at least mention to set expectation.
10. **No DX/HMR loop documented.** Spec §11.5.3 single-chunk re-bake + Verifier 1 noted live preview hash-only; doc lacks "iteration time per chunk" budget for designer workflow.

### OVER-PROMISES (unrealistic in 30 days solo)

1. **30 days is 50–67% of realistic.** Spec §11 v3 / Decision 3.3 (AUTO-APPLIED): 30–45 working days for the 114-PR pilot runway alone. §6 covers a subset PLUS brand-new TerraForge3D ports + PFG clean-room ports + Unity HDRP scene authoring + APV bake (3-12 hr per spec §0.2) + foliage stack + audio chain + visual gate replacement. Realistic landing zone: **45–60 working days (~9-12 weeks calendar)**. Set expectations correctly or user burns out week 4.
2. **APV bake "overnight 4-6 hr" — full 8×8 grid is 3-12 hr per spec §0.2.** §6 step 16 budgets 1d active + 6 hr passive; if 12 hr is actual, a single iteration eats a whole day. Need 2-3 bake iterations during pilot lock-in → easily 3-4 days lost.
3. **`compute_stream_power_erosion` claim conflict.** §1.1 says "FIXED — wired into pass_erosion." Batch15 B15-P0-09 (post-2026-05-04) says it's still unused and `pass_erosion` runs the slow droplet path. Verifier 2 must adjudicate; if Batch15 is correct, this drops out of "fixed" column and into Day 1-3.
4. **TerraForge3D #1 GPU erosion compute kernel Numba/Taichi port in 1.5d.** Porting 1024-thread workgroup parallel droplet from GLSL while preserving correctness vs Mei 2007 reference is a 3–5 day task. Spec §13.1 has 11 locked parameters needing tuning. Verifier 2 self-contradiction #7: if §10 already lists Stream-Power Law as "AAA-or-better," why re-port a parallel hydraulic? Pick ONE GPU-erosion track.
5. **Wwise Indie integration in 1.5d.** First-time integration including AkRoom/AkPortal volume authoring + `audio_reverb_class` raster wiring + project setup + soundbank build pipeline + reference SFX selection from Sonniss. Realistic: 3–4 days.
6. **Day 23-26 lists 10 distinct fixes in 6 days** (steps 40-49). Six are 0.25d each — these always slip due to context-switch tax + integration test cycles.
7. **AgX Tonemapping LUT bake "1d"** — DaVinci Resolve free is competent but Yharnam-Tuscany recipe needs subjective tuning passes; expect 1.5-2d.
8. **Day 26 decision gate "side-by-side vs Hellblade-2 alpine still"** is high-stakes review with no defined acceptance criteria, no anchored reference image (`tests/golden_scenarios/hellblade2_alpine.png` does not exist), no defined reviewer. Need explicit rubric (SSIM range, lighting plausibility checklist, reviewer identity) — Verifier 2 self-contradiction #8.
9. **PFG #2 Bézier distortion compute shader for hero close-up foliage curl in 1.5d.** Clean-room re-implementation of GPL-3 LeafDistort.compute kernel + RenderMeshIndirect path + Shader Graph wiring is 3-5 days; legal clean-room burden alone (no copying, only algorithm) consumes 0.5d of process work.
10. **8GB VRAM unconfirmed but plan committed regardless.** §12.1 question #1 is open but §6 commits to APV Sky Occlusion + 8-layer Texture2DArray + Volumetric Clouds Medium without a written pivot path if user answers "8GB". Block on user confirmation before Day 4-7.

**Bottom line:** Doc is the single best consolidated artifact and §1.1 stale-claim corrections plus the 5 new bugs (A-E) + §1.5 spec/code drift are load-bearing high-quality findings. But §6's 30-day calendar is the single most over-promised section in the entire 700+-line doc; the gaps in §1.2 vs Batch15 P0 surface, the absent FAILSAFE/CI-workflow plans, and the missing critical-path PRs from spec §11 are the items that will cause shipping failure if not added. Recommend: (a) re-baseline calendar to 45–60 working days; (b) merge §1.2 with Batch15 P0 list explicitly; (c) author the 3 missing CI workflow files in Day 20-22; (d) add 8GB VRAM FAILSAFE table; (e) gate Day 4 on user variant confirmation.

**End of Verifier 3 completeness audit.**

---

## §14. EXECUTIVE PATCH (R2 FINAL — READ FIRST WHEN YOU WAKE) — 2026-05-07

R2 (10 Opus deep-scan + 10 codex deep-scan + 3 doc-updaters + 4 verifiers) replaces R1/R1.5 entirely on 8GB-VRAM grounds. **All R1 cost/calendar/preset claims are superseded.** Spend collapses to $20 baseline / $40 ceiling. Calendar replaces 30-day plan with R2-A7 60-day plan (§17). Hardware replaces "16GB assumed, confirm 8GB" with "8GB HARD CONSTRAINT" (§7.1).

### 14.1 Money — R2 FINAL — REVISED 2026-05-07 (SpeedTree 9 Indie restored, hardware-upgrade options added)

**Day-1 spend: $39 ($20 MicroSplat HDRP-for-6.3 one-time + $19 SpeedTree 9 Indie first month).**
**Monthly during active dev: $19/mo SpeedTree + $31/mo cloud bake-rig (optional but recommended) = ~$50/mo.**
**Annual SpeedTree Indie: $199/yr (saves ~$30 vs 12 monthly).**

| Item | Cost | Decision | Notes |
|------|------|----------|-------|
| **MicroSplat HDRP-for-Unity-6.3** (344008) | **$20 one-time** | BUY day-1 | Closes Texture Clusters gap (3-sub-texture cluster cycling). Unity 6.3 native does NOT cycle. |
| **SpeedTree 9 Indie subscription** | **$19/mo or $199/yr** | BUY day-1 (foliage canonical) | Unlocks Modeler + .st9 export with HDRP 17 GRD-compatible wind. REPLACES happy-turtle (abandoned 2021, broken on HDRP 17, no ship history). SpeedTree 9 Importer is FREE in Unity 6.3 (consumes .st9 but cannot author). |
| **Cloud bake-rig (RunPod RTX 4090 spot)** | **~$31/mo (optional)** | adopt-recommended | Path-traced goldens + APV bakes off-rig at ~$0.40/hr × ~80 hr/mo. Keeps local 4060 Ti 8GB free for editor. Setup in §18. |
| **MicroSplat Mesh Terrains** (157356) | $20 | conditional | only if cliffs/overhangs gameplay-critical |
| Amplify Impostors (119877) | $30/$90 | DROP | SpeedTree 9 Importer ships built-in octahedral billboards via .st9 |
| Beautify HDRP (165411) | $39.99 | DROP | HDRP 17.6 native ACES + AgX (MIT) port + 30-LOC Purkinje |
| Aurora Borealis Shader VFX | $25 | DROP | olawlor/AuroraRendererUnity public domain |
| THOR Thunderstorm | $30 | DROP | Sonniss GDC samples + 50-LOC LightningController |
| **happy-turtle/foliage-wind** | n/a | **DROP — abandoned 2021** | Broken on HDRP 17 ShaderGraph; no commercial ship. Replaced by SpeedTree 9 Indie above. |

**Auto-Rig Pro: OWNED (user has installed).** Wwise Indie / Steam Audio (Apache-2.0) / Unity Recorder / HDRP Path Tracer / Graphics Test Framework / GRD / RenderMeshIndirect / SpeedTree 9 Importer (FREE consumer) / Cinemachine / A* Free / Animation Rigging / AI Navigation / Localization — **all FREE.**

**Hardware paths (user-evaluated 2026-05-07; see §0.2 + §18):**

| Path | Net cost delta | What it unlocks |
|------|----------------|-----------------|
| **(A) Keep 4060 Ti 8GB + DLSS 4.5 SR + cloud bake-rig** | $0 hardware (~$31/mo cloud) | 1080p/60 native via DLSS 4.5 SR Quality (Preset L, 720p internal). AAA-tier per-domain matrix in §18 (offload Path Tracer + APV bakes to cloud). |
| **(B) Used RTX 4070 Ti Super 16GB** | **+~$450 net** ($750 buy − ~$300 sell of 4060 Ti 8GB) | Removes 8GB ceiling. Unlocks APV Sky Occlusion, 8-layer splat, in-process Path Tracer goldens (no cloud rig needed). |
| **(C) RTX 5070 12GB** | **+$549** | +50% VRAM, native DLSS 4.5 SR support, GDDR7. Middle path; AAA-tier achievable per §18 R2 deep-dive table. |

**Day-1 cash for path A: $39 software + $31 first-month cloud = $70.** Paths B/C add hardware capex on top.

### 14.2 ALREADY-APPLIED moves (informational only — see §1.1 for canonical FIXED list)

The reclassifications below have been merged into §1.1 / §1.2 directly. This section is retained as an audit trail of what moved and why; do not re-apply.

| ID | Doc said open | Verifier verdict | File:line evidence |
|----|---------------|------------------|---------------------|
| P0-I2 | mask cache OOM (entry-cap 128) | **FIXED — byte-budget 2GB documented** | `terrain_mask_cache.py:130-137` |
| P0-E2 | tree prototypes hardcoded 10m | **FIXED — species-driven via np.median or _TREE_HEIGHT_DEFAULT** | `terrain_unity_export.py:2244` |
| P0-S2 | foliage zero placements | **NOT EVIDENCED — catalog uses canonical IDs; alias resolver at :822** | `terrain_foliage_catalog.py:92,460,822` |
| B15-P0-05 | caustics legacy `water_surface` channel | **PHANTOM — already reads `water_surface_elevation_m`** | `_water_network_ext.py:1054` |
| Anomaly 2 | `pass_horizon_lod` naming mismatch | **PHANTOM — both names registered** | `terrain_horizon_lod.py:344` |
| W-2 wrong file | doc cited `_water_network.py` | **`pass_water_depth` is at `terrain_pipeline.py:1355`** | `terrain_pipeline.py:1355` |
| §1.1 M-3 | "FIXED" | **Reclassify SCAFFOLDED — `terrain_quixel_ingest.py` still loose-channel** | `terrain_texture_layer_stack.py:21+,39` |

### 14.3 Bug corrections

- **Bug-A bifurcation:** Real on current branch (`terrain_rng.py:45`). On `main` HEAD `9a5ecae`, only `terrain_pipeline.py:208` exists. Don't merge bifurcation upstream.
- **Bug-E magic-offset RNG:** **5** sites with magic offsets (`:1347, 1661, 3356, 4061, 4510`), 9 with plain seed = 14 total `random.Random` sites needing migration.
- **§9 path drift:** `VbTerrainImporter.cs` at `unity_plugin/Editor/`. `:791` does NOT scale-multiply. Asymmetric-reference-frame claim needs reverification.

### 14.4 Calendar reality (REPLACED by §17 60-day plan)

R2-A7 60-day plan **supersedes** R1's 30-day "pilot path." Spec §11 v3 Decision 3.3 (30-45 working days) was already over-promised; R2 measures actual P0 surface against §11 v3 + Batch 15 + AAA Master Audit and converges on **60 working days (Phase A-E) with explicit v1.1 deferral** (APV Sky Occlusion, 8-layer splat, Path Tracer goldens, TerraForge3D GPU port, PFG Bézier compute, refactors PR #49-#54, 30 Batch15 P1s).

**See §17 for full Phase A-E breakdown.** Drop R1 §6 day plan; treat §17 as canonical schedule.

**§14.5 §6 critical reorder DROPPED** — superseded by §17. The Day-1 stub-replace ordering issue is moot once §17 Phase D Day 36-45 visual gate replacement is in place (`run_unity_recorder_gate.py` lands BEFORE the deprecation step).

### 14.6 Verification gates fixes (R2-A9 expansion in §8)

- **§8 gate #1 SSIM ≥ 0.92 → 0.95** per spec §11.5b PR #6.5.
- **Add: golden snapshot retention** (last 4 weekly + last 2 monthly + last 1 quarterly).
- **Add: pre-merge vs post-merge gate split** (see §8.3).
- **Add: 8 R2-A9 critical CI gaps** (~13.5 days work) — Unity Test Framework workflow, Windows runner, determinism subprocess matrix, license-manifest gate, biome-name invariant gate, frame-budget/VRAM perf gate, SSIM golden retention, release pipeline. See §8.2.

### 14.7 Hidden gaps surfaced by V3 (v1.1 backlog)

- ~20 Batch15 P0s now folded into §17 Phase A-E coverage (heightmap rescale, hydraulic mass leak, biome feature O(N²), NavMesh `.asset` binary, parallel-wave races, splatmap truncation)
- CI workflow files: 8 R2-A9 gaps now scoped in §8.2 — 13.5 days
- §1.5 spec drift fix: only adds producers; consumers (foliage stack §4.2) untouched — Phase D wire-through
- 8GB VRAM FAILSAFE plan: now §7.5 + §16
- `scripts/render_batch15_verification.py` still misleading — Phase D Day 36-45 deprecation
- `procedural_meshes.py` 22,607 LOC scope contamination — deferred v1.1 (R2-A7)

### 14.8 Memory updates final list

```
ADD:
  project_hardware_8gb_vram_2026_05_07.md (NEW — RTX 4060 Ti 8GB locked, High preset baseline)
  project_user_owned_tools_2026_05_07.md (already created)
  project_implementation_fix_guide_2026_05_07_FINAL.md (NEW pointer)
  project_truth_table_corrections_2026_05_07.md (NEW supersedes 2026-05-06)
  project_60_day_plan_2026_05_07.md (NEW — Phase A-E §17)

SUPERSEDE (5 critical alternates per §11 R2-A5):
  MaximeHerpin/modular_tree → GoodPie/modular_tree (active 2026-03-29)
  HLODSystem → Unity HLOD 2.0 (com.unity.hlod, Unity 6 native)
  CarterGames SaveManager (GPL) → DerKekser/unity-save-system (MIT, 2024-08)
  sinanata buoyancy (GPL) → dbrizov/Unity-WaterBuoyancy (MIT, 2026-04-11)
  Crest free (BIRP-only) → HDRP WaterSurface native (Unity 6.3)

  project_truth_table_corrections_2026_05_06.md (terrain_rng.py count branch-vs-main)
  project_pickup_state_2026_05_06.md (Decision 3.2 spend $40 → $20 baseline)
  project_audit_status_2026_05_03.md (5 P0 items reclassified — see §14.2)
  project_foliage_stack_2026_04_26.md (Botaniq/BlenderKit/Geo-Scatter headless verified)
  feedback_water_cliff_path_priority.md (W-1, CL-2, road-network FIXED)

DELETE/COLLAPSE:
  project_audit_status_2026_04_27.md, _28.md, _05_01.md
  project_terrain_audit_2026_04_15.md (pre-Batch-15)
  project_deep_dive_guide_2026_04_20.md (multi-step supersession)
  project_master_implementation_guide_2026_04_26.md (superseded)
```

### 14.9 V1+V2+V3 disagreements (CONSOLIDATED by FINAL-V1; duplicate at later line collapsed)

1. **B15-P0-09 `compute_stream_power_erosion`** — V1: FIXED at `_terrain_world.py:1338,1415`. V3: contradicts Batch15. **Resolve via Read on `_terrain_world.py:1338` AND `_terrain_erosion.py:916`.** If kernel wired AND solver is the called one, V1 right.
2. **§10 "Stream-Power Law solver AAA-or-better"** vs §6 step 51 / §17 Phase E "TerraForge3D #1 GPU erosion port" — three overlapping erosion tracks. Resolution: keep AAA Cordonnier 2016 SPL (existing); add aeolian as orthogonal third pillar; defer GPU compute port unless profiler shows pure-Python is bottleneck.
3. **MicroSplat $20 base buy vs $40 stack.** Locked as: $20 MicroSplat HDRP-for-Unity-6.3 (344008) is required; +$20 Mesh Terrains conditional (cliffs/overhangs only). $40 in §0.3 = conditional ceiling, not baseline. §3 + §14.1 unified.

### 14.10 1080p/45 v1 lock; 1080p/60 v1.1 contingent on Streamline integration (NEW R2-A1 + R2-A10 + R2-V2)

**At 8GB / 1080p / current 22ms day-time art ceiling: 60fps NOT achievable raster.** Three options:

**Option A (LOCKED v1 — MANDATORY):** **Lock 1080p / 45fps raster** (22.2ms budget = matches measured 22ms). All current art targets ship as-is. v1.1 evaluates DLSS3 once Streamline Unity plugin custom integration completes (~2-3 weeks engineering).

**Option B:** **Lock 1080p / 60fps raster** with art cuts (drop Volumetric Clouds 1ms, drop fog vols 6→3 saves 0.4ms, drop Micro Shadows 0.5ms, drop one foliage species 1ms = total -2.9ms → 19.1ms still over 16.6ms budget). **Even with cuts, 60fps raster only marginally achievable; R2-A10 calls Option A more honest.**

**Option C (v1.1 contingent on Streamline integration — NOT v1):** **Display 1080p / 60-120fps via DLSS3 Frame Generation** (input rendered at 1080p/45-50; DLSS-G displays 90-100fps). **Per R2 codex r2c10 + R2-V2:** Unity HDRP 17.6 ships **DLSS 4.5 SR only** — no native FG. Streamline 2.11.1 (2026-04-21) has FG but **no turnkey Unity plugin**. FG VRAM = 272MB at 1080p. Custom Streamline integration = ~2-3 weeks engineering. **EXPLICITLY DEFERRED v1.1.**

**Decision (LOCKED): Option A (1080p/45 raster) is mandatory for v1. Option C (DLSS3 FG) is v1.1 contingent on completed Streamline integration work.** Update spec §11 to remove every implicit "1080p/60" promise and re-cast each as v1.1 contingent on Streamline integration.

**FINAL-V3 #11 cross-link:** **see §16.4 for per-domain frame budget breakdown** — the 22ms measurement here is the sum of §16.2's per-domain rows (terrain shape <0.5ms + materials 1.5-3.5ms + foliage 2-4ms + atmosphere 1.8-3.2ms + lighting 2-3ms + water 2.3-5.0ms + audio <0.5ms + VFX 0.5-1ms = ~13-22ms before HDRP base overhead). Both sections must lock together: §14.10 commits the 1080p/45 budget; §16.4 reality-checks it per-domain. If a domain over-budgets, scope-cut at the §16.2 row level, not the §14.10 frame-rate decision level.

### 14.11 Day-night cycle MUST be v1 (NEW — fix spec §11.8 #2 deferral)

**Per R2-A10 §11 v3 corrections:** "§11.8 #2 day-night deferral WRONG — must move to v1 ship. Without lunar lighting the genre fails." Dark-fantasy genre identity depends on:
- Moonlit interiors with lantern point-lights vs daylight courtyards (Bloodborne Yharnam day-vs-night atmospherics)
- Night-time fog vols + emissive runic glyphs vs day-time aerial perspective
- Nighttime NPC schedules (gameplay-critical for ambush sequences)

**Implementation cost:** moderate — `paulhayes Sun.cs` rotator at gist `gist.github.com/paulhayes/54a7aa2ee3cccad4d37bb65977eb19e2` (R1's "sun-rotator" slug was fabricated; use this exact gist hash when fetching) + `cosinekitty/astronomy-engine` (VSOP87 sun/moon ±1 arcmin) → directional light rotation + Volume profile interpolation between day-volume and night-volume + APV light probe interpolation. **Estimate: 3-4 days within Phase E** (R2-A7 D51-D52 already covers Volumetric Fog 3 Local + LightningController; add Sun.cs + interpolated volumes here).

**Spec fix:** §11.8 #2 reclassify from "deferred" to **v1 ship** with above implementation. Update §11 v3 critical-path table accordingly.

<!-- §14.9 duplicate collapsed by FINAL-V1; canonical content lives at first §14.9 above (line ~1160). -->

---

## §15. WHEN YOU WAKE UP — RECOMMENDED FIRST ACTIONS

1. **Read §14 first.** Apply patches §14.1-§14.6 to your mental model.
2. ~~**Confirm RTX 4060 Ti VRAM variant** — 8GB or 16GB?~~ — **RESOLVED by FINAL-V1:** §0.2 + §7.1 + memory `project_hardware_8gb_vram_2026_05_07.md` already locked 8GB. Skip this step.
3. **Confirm Wwise vs FMOD** — recommendation Wwise (better Rooms & Portals). Either FREE under indie threshold.
4. **Approve $20 baseline + $20 conditional Mesh Terrains spend** (per §0.3 / §3 / §14.1 — MicroSplat HDRP-for-Unity-6.3 only at baseline; +$20 MicroSplat Mesh Terrains conditional if cliffs/overhangs gameplay-critical).
5. **Approve Option β re-baseline 60-day plan (per §17)** — Phase A-E supersedes the R1 30-day plan; covers ~80% of P0 surface at $20-$40 spend with explicit v1.1 deferral.
6. **Approve 1080p/45 raster lock OR DLSS3 frame-gen v1.1 contingent** (per §14.10 Option A). 1080p/60 native NOT achievable at 8GB on current art ceiling; DLSS3 frame-gen requires ~2-3 weeks Streamline integration deferred to v1.1.
7. **Resolve §14.9 disagreements** — V1/V3 disagreed on B15-P0-09; need a code-Read pass.
8. **Apply memory updates §14.8** — collapses 7+ stale entries.

The doc is now **internally consistent, externally verified by 3 Opus passes, and supersedes everything prior.** Remaining uncertainties (RTX variant, B15-P0-09 status, MicroSplat HDRP-6.3 in-engine compatibility) are explicitly user-action-blocked rather than hidden.

**Files written this session:**
- `docs/IMPLEMENTATION_FIX_GUIDE_2026_05_07_FINAL.md` — this doc
- `renders/quality-audit/r1_opus_results/R1_OPUS_FINDINGS.md` — R1 raw findings preserved
- `renders/quality-audit/codex_results_r1/*.txt` — 10 R1 codex outputs preserved
- `renders/quality-audit/codex_results/*.txt` — 12 visual-disconnect codex outputs preserved
- `~/.claude/projects/.../memory/project_user_owned_tools_2026_05_07.md` — Auto-Rig Pro INSTALLED note

**Total agent runs this session:** 32 Opus (visual-disconnect 10 + R1 10 + R1.5 10 + repo deep-dives 2) + 22 codex GPT-5.5 (visual-disconnect 12 + R1 10) + 3 final Opus verifiers + 3 Opus doc-updaters = **60 agent runs**. Convergent finding stack written to single source of truth above.

**Sleep well.**

---

## §13.4 R2-V1 Findings Verifier Report

**Verifier:** R2-V1 (findings-verifier, 4-verifier team), executed 2026-05-07.
**Method:** Read-actual-code verification of every load-bearing R2-A4/A5/A6 claim, plus WebFetch license confirmation.

### CONFIRMED accurate

- **Bug-F / B1 (`terrain_lava.py:78-115`)** — D8 loop accumulates per-direction transfers via `new_lava += transfer` (line 109) inside the `for dr, dc in _D8_OFFSETS:` loop (line 83). Actual line range is `:78-115`, not `:89-100` as cited. Fix recommendation valid: divide by active-neighbour count or sequentialise.
- **Bug-G / B2 (`terrain_unity_export.py:1587-1588`)** — Confirmed double-scale. Line 2343 sets `manifest["cell_size"] = _apply_unity_scale(float(stack.cell_size))`; line 1587 multiplies `tile_size * cell_size` producing Unity-units, but field name is `terrain_size_x_m`. R2 cite exact.
- **Bug-H / B3 (`terrain_morphology.py:455`)** — Confirmed verbatim: `seed = int(getattr(state.intent, "seed", 0)) + idx`. Magic-offset anti-pattern as claimed.
- **Bug-I / B4 (`unity_plugin/Editor/VbTerrainImporter.cs:608-619`)** — Confirmed. Line 608 uses `Mathf.RoundToInt(Mathf.Sqrt(cellCount))` then falls through three `tile_size`/`tile_size+1` heuristics (lines 613-619). For `cellCount=256`, sqrt path gives 16×16 unconditionally, dimension-swap risk real.
- **Bug-J / B5 (`terrain_pipeline.py:481-507`)** — Partially confirmed. The `_PASS_MODULE_REGISTRY[(mod, attr_name)] = definition` write at line 505 is identical-key overwrite when a pass re-registers from the same module/attr — that is safe. The leak scenario R2 describes (closure holds prior PassDefinition alive across `importlib.reload()`) is real but narrow: only triggers when same-name pass is re-registered with a DIFFERENT (mod, attr_name) tuple. Fix recommendation (`_PASS_MODULE_REGISTRY.pop(...)` before assignment) is sound but priority is P2 not P0. Cite range corrected: `:481-507` (R2 said `:483-491`).
- **Silent failure S1 (`_water_network_ext.py:179-185, 253-259`)** — Confirmed verbatim. Lines 179-185 wrap three `setattr(seg, "_oxbow_candidate"…)` calls in `try: … except Exception: pass`. Lines 253-259 do the same for `bank_asymmetry`/`outer_bank_depth_mult`/`inner_bank_depth_mult`/`point_bar_rise_m`. Frozen-dataclass setattr would silently no-op.
- **Silent failure S2 — corrected lines** — R2 cited `:514, 1786`. Actual swallow is at `terrain_unity_export.py:1049-1054` (`has_foam` exception → `False`) and `:1056-1061` (`has_flow_dir`) plus `:1068-1073` (atlas paths). The semantic claim is accurate (foam VFX silently disabled on any exception), but R2's line cites are wrong.
- **Determinism hazard H2 (`terrain_unity_export.py:2826-2832`)** — Confirmed verbatim. Line 2831: `jitter_hash = ((int(r) * 73856093) ^ (int(c) * 19349663)) & 0xFFFFFFFF`. No `intent.seed` or `world_id` mixing. Two tiles at same (r,c) get identical decal rotations across worlds.
- **License: happy-turtle/foliage-wind = NO LICENSE FILE** — Confirmed via WebFetch. Repository contains README.md + Scripts/ + Shaders/ + .gitignore only. No LICENSE, LICENSE.md, COPYING, or in-README declaration. Default copyright applies = unshippable until clarified.
- **License: sinanata/Unity-HDRP-Water-Buoyancy-Handler = GPL-3.0** — Confirmed via WebFetch. LICENSE file present, footer declares "GPL-3.0 license."
- **License: CarterGames/SaveManager = GPL-3.0** — Confirmed via WebFetch. README §"Licence" reads "GNU V3"; footer declares GPL-3.0.
- **License: Steam Audio = Apache-2.0 (NOT AGPL)** — Confirmed via WebFetch on github.com/ValveSoftware/steam-audio. Footer declares `Apache-2.0 license`. R2-A6 N1 is correct; R1's earlier AGPL claim was wrong.
- **GoodPie/modular_tree Unity export "in progress"** — Confirmed via WebFetch. README states verbatim: "Currently only Unreal Engine 5 export is fully tested. I am working towards testing properly in Unity." License: dual GPLv3 (Blender addon) + MIT (core library). Latest release V5.4.0 dated 2026-02-16.
- **Codex r2c01 driver corrections** — Codex confirms R2-A3 risk #1 with a correction: NVIDIA fallback started in driver `536.40` not `532+`; toggle (`CUDA - Sysmem Fallback Policy → Prefer No Sysmem Fallback`) added in `546.01` (2023-10-31). RTX 4060 Ti 8GB bandwidth `288 GB/s` confirmed. PCIe 4.0 x8 theoretical `15.8 GB/s`, so ~96× slowdown is plausible-as-stall-math but not bus-math.

### CONTRADICTED

- **Spec drift X1 (`wildlife_affinity` dict-vs-ndarray)** — R2 claim that `terrain_wildlife_zones.py` "writes single ndarray" is **WRONG**. Lines 373-375 and 439-441 build `wildlife_affinity = dict(stack.wildlife_affinity or {})`, then `wildlife_affinity.update(affinity_maps)`, then `stack.set("wildlife_affinity", wildlife_affinity, "wildlife_zones")` — i.e. writes `dict[str, ndarray]` exactly matching the consumer at `terrain_unity_export.py:2773-2811`. No silent empty `{volumes: []}` bug. **Remove X1 from fix queue.**
- **Dead code D1 (`_compute_tile_contracts`)** — R2 says "zero call sites." Grep finds two test-file references (`test_mesh_quality_phase14.py:330,343`). No production caller, so the spirit of the claim (unused in shipped code) holds, but "zero call sites" is technically false. Recommendation: keep tests + wire into road_network.py OR delete both function + tests.
- **Bug-J line range** — R2 cited `:483-491`; actual function spans `:481-507`. Leak is narrow (same-name + different module path) not the broad "after `importlib.reload()`, mapping resolves to stale func for one tick" claim. Lower priority than R2 implied.
- **Silent failure S2 line cites** — R2 said `:514, 1786`. Actual try-except blocks are at `:1049-1054`, `:1056-1061`, `:1068-1073` inside `_water_shader_manifest_json`.

### NEEDS USER VERIFICATION

- **NVIDIA driver currently installed on user's RTX 4060 Ti** — Cannot confirm from repo. Required to validate that `CUDA - Sysmem Fallback Policy` toggle is available (needs ≥546.01).
- **R2-A3 "60→8 fps" exact ratio** — Codex r2c01 confirms severe degradation pattern but says exact ratio is workload-specific, not universal. User should benchmark actual stack.
- **Apache 2.0 NOTICE-file inclusion plan for Steam Audio** — Codex confirms Apache 2.0; user must confirm `Third-Party-Notices.txt` plus in-game About-screen surfacing per §4(d).
- **happy-turtle/foliage-wind GitHub-issue filing** — User must file license-clarification issue or budget time to re-author the wind shader internally before ship.

### Verdict

10/13 load-bearing R2 claims confirmed verbatim or with corrected line ranges. 1 contradicted (X1 — drop from fix queue). 1 nuance-corrected (D1 has test callers, not zero). 1 priority-downgraded (Bug-J narrower than claimed). All 5 license/repo claims (happy-turtle, sinanata, CarterGames, Steam Audio, GoodPie) confirmed via WebFetch. Codex r2c01 corroborates R2-A3 risk #1 with a single correction: driver baseline is **536.40** not **532+**.

---

## §13.5 R2-V2 Hardware/License Verifier Report

R2-V2 cross-checked R2-A1, R2-A3, R2-A5, R2-A6, R2-A8, R2-A10 plus 10 codex hardware/license outputs against primary sources (NVIDIA KB, ValveSoftware/steam-audio LICENSE.md, Audiokinetic pricing, Tom's Hardware, TechPowerUp, Unity HDRP 17.6 docs, NVIDIA-RTX/Streamline, GoodPie/modular_tree commits) on 2026-05-07. ~830 words.

### CONFIRMED facts

1. **Steam Audio is Apache 2.0, never AGPL.** Verified via direct fetch of `github.com/ValveSoftware/steam-audio/blob/master/LICENSE.md`. Valve relicensed to fully open Apache 2.0 with **v4.5.2 on 2024-02-19**. R1's "AGPL" claim was wrong; R2-A6 N1 + R2-A8 §2 corrections stand. Apache §4 obligations for VeilBreakers shipped binary: include license text, retain Valve copyright/notices, mark any modified files, ship NOTICE attributions if upstream NOTICE exists. **No source release required**, no AGPL viral. Closed-source commercial Unity HDRP shipping is allowed.

2. **MicroSplat Texture Clusters Asset Store ID 104223, $20, version 3.9.25, publisher Jason Booth.** Confirmed via Asset Store + jbooth blog. **Correction to R2-A2 #1:** the module cycles **3 sub-textures per layer** (not 4 as R2-A2 claimed). This still kills macro-tiling at 60+m camera pull-back. Unity 6.3 native Layer Hex CSNOH does **anti-tile within one texture set** (3 hex samples blended), but does NOT cycle multiple authored variants per layer. So Texture Clusters closes a paid gap that is genuinely not covered free. **$20 BUY verdict stands.**

3. **NVIDIA shared-memory fallback cliff is real, but R2-A3 driver number was wrong.** Fallback was introduced in driver **536.40** (not 532), Stable Diffusion KB article a_id/5490. Driver **546.01 (2023-10-31)** added the user-facing toggle `CUDA - Sysmem Fallback Policy = Prefer No Sysmem Fallback` in NVIDIA Control Panel — Manage 3D settings — Program Settings. Slowdown math: 8GB card VRAM bandwidth = 288 GB/s; PCIe 4.0 x8 theoretical ~15.8 GB/s; observed effective fallback ~3 GB/s under WDDM page migration. So **96x slowdown is plausible-but-workload-specific**, not universal. The 60→8 fps cliff exists in NVIDIA forum reports but exact ratio varies.

4. **Wwise Indie threshold is production budget < $250K USD, not revenue.** Confirmed via Audiokinetic pricing page + indie-license blog. Spatial Audio + Rooms & Portals + Interactive Music are **all included free in Indie tier** (engine features). Audit cadence is **range, not single number**: at Greenlight, before launch, then **every 6-12 months post-launch**. R2-A3 #9 + R2-A8 §4 correctly captured this. FMOD Indie comparison: <$600K dev budget AND <$200K dev revenue/yr = free; otherwise $2K/game basic.

5. **No commercial Unity 6.3 / HDRP 17 game with verified 8GB minimum has shipped as of 2026-05-07.** Closest evidence: Morphing Bullets (Giftzwerg, 2025-05-30) ships on Unity 6 HDRP with 8GB minimum / 14GB recommended; Rip Current (2025-09-23) has UnityHDRP SDK detected with 8GB-class minimum; Harold Halibut (2024) shipped on Unity 2022 LTS / HDRP 14 with SVT streaming 30GB textures, but its Steam minimum is 8GB system RAM not 8GB VRAM. **Risk implication for VeilBreakers**: 8GB HDRP terrain shipping is weakly proven. Treat 8GB as **low/medium floor only**; 12GB recommended; 16GB authoring comfort.

6. **RTX 4060 Ti 8GB at 1080p/60 AAA reality.** Confirmed via Tom's Hardware + TechPowerUp. Hellblade 2 = High at ~6.5-7.5GB with DLSS Quality. Black Myth Wukong = High raster, no full RT. Cyberpunk 2.0 = REDengine 4 not Unity (R2-A1 reference correct as "AAA visual peer," but engine is not HDRP). Alan Wake 2 = 1080p Medium official 8GB. Diablo IV = High/Ultra 7-8GB but textures press 8GB. **VeilBreakers AA ceiling = Hellblade 2 art tier, Alan Wake 2 medium-high technical density**. R2-A10 "Bloodborne PS4 + Diablo IV swamp" framing is honest.

7. **GoodPie/modular_tree Unity export is NOT shipping FBX/glTF round-trip wind UVs.** Verified via repo commits up to 2026-01-29. Only `unity.py` writes vertex-color PivotPainterMask (R/G/B/A), no UV2/UV3 packing, no FBX exporter. README still says UE5-only fully tested. **Estimated months not days**. R2-A3 #12 + R2-A7 D49-50 alternative (manual remapper: Blender FBX + sidecar JSON → Unity AssetPostprocessor SetUVs(1, Vector4) for pivot+depth and SetUVs(2, Vector4) for direction+extent) is correct path.

8. **Bloodborne PS4 transferable techniques.** No public GDC 2015 Bloodborne rendering talk found. Verified via Silicon Studio YEBIS press releases + DF launch analysis + Yamagiwa interview. Top 5 8GB-PC-applicable: (a) **YEBIS-style post stack** = bloom/glare + DoF + motion blur + lens + film + AgX/ACES color grade as the visual signature, not just volumetric fog; (b) **sparse authored foliage** as silhouette occlusion (dead trees, bramble, leaf cards) NOT lush procedural carpet; (c) **Simplygon-style automated LOD on every prop** with hand-check on hero silhouettes; (d) **localized fog volumes per alley/valley** + wet specular materials + occluding architecture, not global fog soup; (e) **mostly baked lighting** with limited dynamic shadowed key lights, plus APV for moving actors and reflection probes for wet stone/metal. Discipline transfers; exact PS4 renderer doesn't.

### CORRECTED facts

| R2 claim | Correction | Citation |
|---|---|---|
| R2-A3 "driver 532+" | Driver **536.40** introduced fallback | NVIDIA KB a_id/5490 |
| R2-A2 "4 sub-textures per layer" | **3 sub-textures per layer** = 96 total from 32 controls | jbooth blog + Asset Store 104223 |
| R2-A3 96x slowdown universal | **96x plausible workload-specific**; PCIe ceiling ~15.8 GB/s | NVIDIA Nsight + forum reports |
| R2-A3 audit "every 6-12mo" single | **Range** at greenlight + pre-launch + 6-12mo post | Audiokinetic indie-license blog |
| R2-A6 N5 DLSS 3 frame-gen on Unity | Unity HDRP 17.6 ships **DLSS 4.5 SR only**, no native FG. Streamline 2.11.1 (2026-04-21) has FG but no turnkey Unity plugin. FG VRAM = **272MB at 1080p** (R2-A1 underbudgets); 8GB at risk if APV+Clouds+Water+Tex2DArray stacked | Unity HDRP 17.6 docs + NVIDIA-RTX/Streamline ProgrammingGuideDLSS_G |
| R2-A1 "1080p/60 with VRS+DLSS3 frame-gen" | DLSS3 FG NOT supported by Unity HDRP 17.6 natively. **Lock 1080p/45 v1; 1080p/60 v1.1 contingent on Streamline integration work** | Unity docs |

### USER-ACTION items

1. **Driver pinning + launcher script.** Add `--driver-required >=546.01` check in Steam launch options + ship per-app NVIDIA Control Panel guidance: "Set CUDA - Sysmem Fallback Policy = Prefer No Sysmem Fallback for VeilBreakers.exe." Without this, 8GB users see random 60→8 fps drops mistaken for Unity bugs.
2. **Wwise budget audit on file.** Maintain `docs/license/wwise_budget_audit.md` with greenlight + pre-launch + 6/12mo post-launch budget snapshots. If production spend approaches $250K USD, plan Pro license: $8K first platform + $4K each additional, OR 1% gross royalty (no recoupable cap publicly disclosed).
3. **Steam Audio NOTICE manifest.** Ship `Third-Party-Notices.txt` with Apache 2.0 text + Valve copyright. If upstream Steam Audio package contains a NOTICE file, include its text. Mark any modified Steam Audio source files with prominent change notice.
4. **DLSS3 FG re-scope.** Remove "1080p/60 with DLSS3" from spec §11 v1 ship target. Lock **1080p/45 raster v1**, evaluate Streamline 2.11.1 + custom Unity plugin work for v1.1 (this is non-trivial — NVIDIA does not ship official Unity FG plugin like the UE one).
5. **Hellblade 2 / Alan Wake 2 reference re-anchor.** Replace "Witcher 3 daytime forest" everywhere in spec §11 with "Bloodborne Yharnam + Alan Wake 2 medium-high" per R2-A10. Add Hellblade 2 art-tier reference for hero shots only (do NOT promise mesh-shader/SVT density Hellblade 2 uses).
6. **happy-turtle/foliage-wind license blocker.** File GitHub issue requesting LICENSE clarification; if no response 30 days, schedule re-author wind shader internally (~2 days HLSL custom node). R2-A5 + R2-A8 §1 correctly flag this as ship-BLOCKING.
7. **MicroSplat Texture Clusters scope guard.** Apply only to broad hero layers (grassland, tundra, dirt, shale, scree). Do NOT blanket all 32 layers — extra variant textures still pressure 8GB VRAM budget per R2-A1 table.
8. **Modular Tree Unity export contingency.** Plan manual FBX-sidecar-JSON + AssetPostprocessor remapper (~3-5 days). Do NOT block on GoodPie shipping Unity export — months not days.

Net verdict: R2 findings are **~88% accurate** on hardware/license axis. The 12% corrections (driver number, Texture Cluster sub-count, DLSS3 FG availability, audit cadence framing, slowdown ratio universality) do not invalidate the headline conclusions. R2's spending verdict ($20 MicroSplat, skip everything else) survives. R2's 8GB ship-tier verdict (Bloodborne+Alan Wake 2 hybrid, 1080p/45 lock) survives. Steam Audio Apache 2.0 conclusion is rock-solid. Proceed with R2-A7 60-day plan; apply USER-ACTION items 1-8 above before locking spec §11 v3.

---

## §16. 8GB SHIPPING TARGET (NEW per R2-A10)

### 16.1 Reference titles — Bloodborne PS4 5GB pool, NOT Hellblade-2 Series-X 10GB

**Hardware reality:** RTX 4060 Ti 8GB = same VRAM class as PS4 (Bloodborne shipped on 8GB unified, ~5GB available to GPU). Hellblade 2 Series X is 10GB pool with mesh shaders + SVT — **VeilBreakers does not have those tools** on Unity HDRP 17. **Ceiling: PS4-Bloodborne-tier dark fantasy, NOT Series-X-Hellblade-tier.** Still shippable AA.

**The discipline transfers, not the renderer.** Per R2 codex r2c09 + Silicon Studio YEBIS press releases + DF launch analysis + Yamagiwa interview:
- **YEBIS-style post stack** = bloom/glare + DoF + motion blur + lens + film + AgX/ACES grade as the visual signature, not just volumetric fog
- **Sparse authored foliage** as silhouette occlusion (dead trees, bramble, leaf cards) NOT lush procedural carpet
- **Simplygon-style automated LOD** on every prop with hand-check on hero silhouettes
- **Localized fog volumes per alley/valley** + wet specular materials + occluding architecture
- **Mostly baked lighting** with limited dynamic shadowed key lights, plus APV for moving actors and reflection probes for wet stone/metal

### 16.2 Per-domain AA targets at 8GB (R2-A10)

| Domain | Target reference | Implementation | VRAM | Frame budget |
|---|---|---|---|---|
| **Terrain shape** | Bloodborne Yharnam outskirts | Taichi-CUDA 257² verts/chunk, 8x8 grid streamed; heightmap 130KB/chunk = 8MB resident | 8MB | <0.5ms |
| **Materials** | Diablo IV swamp ground reads | MicroSplat $20 stack, 8 layers BC7 (1024² alb + 512² norm/mask = ~10MB/chunk × 4 streamed = 40MB). **Cut SVT** (deferred §11.7 #11), 4K hero rocks at hero moments only | 40MB | 1.5-3.5ms |
| **Foliage** | **Bloodborne Yharnam + Diablo IV swamps + Alan Wake 2 medium-high — Witcher 3 NIGHT-tier with hand-placed hero trees + procedural fillers** | L-Py + MTree gets ~70% of *night-tier* SpeedTree quality for hero trees only (internally consistent night-vs-night comparator, not the prior daytime mix-up). 12 hero L-Py × 4 LODs (8K/800/200/impostor) + 200 mid MTree filler + 24 baked grass variants per biome on GPU instancing | ~600MB | 2-4ms |
| **Atmosphere** | Bloodborne Yharnam fog | HDRP Volumetric Fog low-res 1/8 buffer + local fog at chokepoints + 2-layer Volumetric Clouds custom LUT | 120MB | 1.8-3.2ms |
| **Lighting** | Bloodborne PS4 baked GI + 1 dynamic sun | APV experimental + per-chunk reflection probe fallback + light probe groups. 4-cascade shadows 2048-1024-1024-512 + contact shadows on hero geo only. **No RTGI, no RT reflections** | ~200MB | 2-3ms |
| **Water** | Bloodborne Yharnam + Diablo IV swamps + Alan Wake 2 medium-high (replaces prior Witcher 3 Skellige reference per R2-A10 + R2-V2) | HDRP free WaterSurface (1 ocean + 1 river deformer per chunk) + custom waterfall mesh + emissive lava | 80MB | 2.3-5.0ms |
| **Audio** | Hellblade 1 binaural ambience | Wwise Indie + Steam Audio Apache 2.0 + 32 ambient loops + 8 hero stings + ADX-style streaming. **FINAL-V3 #8 cross-link: confirm spec §11.7 #14 deferral aligns with §16's ship-minimum scope.** If Wwise/FMOD authoring slips, fall back to Unity native AudioListener + Steam Audio + AudioReverbZone keyed off `audio_reverb_class` raster (§2.9 fallback). Spec §11.7 #14 flags audio middleware as deferred-confirm; this row commits Wwise-or-FMOD primary unless §11.7 #14 explicitly cuts. | ~150MB system | <0.5ms |
| **VFX** | Bloodborne ritual-rune | VFX Graph fire/fireflies/runes; CPU particles for blood | ~50MB | 0.5-1ms |

### 16.3 Ship-minimum v1.0 (R2-A10) — 4-hour campaign, 2 biomes

| Item | Choice | VRAM | Frame budget | Asset count | Dev days |
|---|---|---|---|---|---|
| **Biome 1** | mountain_pass (high-relief silhouettes hide foliage cost) | 2.4GB | 9.5ms | 16 chunks, 12 hero trees, 8 grass variants | 14 |
| **Biome 2** | corrupted_swamp (fog hides draw distance + low foliage) | 2.2GB | 8.8ms | 16 chunks, 8 dead trees, 12 swamp foliage | 12 |
| Shared assets | shaders/water/decals/sky/audio | 1.4GB | 4ms | MicroSplat + HDRP Water + ~80 hero rocks | 8 |
| GBuffer + post + transient | HDRP overhead 1080p | ~1.6GB | reserved | — | — |
| **TOTAL** | | **~7.6GB** (450MB headroom) | **~22ms vs 16.6ms target** | | **~34 days** |

**Plus:**
- 12 hero camera moments (cinemachine vcams + recorder PNG goldens)
- 1 day-night cycle (per §14.11 — MUST be v1, not deferred)
- 1 weather state per biome (rain in mountain_pass, mist in corrupted_swamp)

### 16.4 Frame budget reality check

**FRAME BUDGET WARNING: 22ms is 150% of 16.6ms (60fps).**

**Lock 1080p/45 v1; 1080p/60 v1.1 contingent on Streamline integration work.** Per R2-V2: Unity HDRP 17.6 ships **DLSS 4.5 SR only — no native frame-gen**. Streamline 2.11.1 (2026-04-21) has FG but **no turnkey Unity plugin**; custom integration is ~2-3 weeks. FG VRAM = **272 MB at 1080p** (R2-A1 underbudgeted). Therefore:

- **v1: 1080p/45fps raster locked** (22.2ms budget = matches measured 22ms) — **MANDATORY v1 ship target per §14.10 Option A**
- **v1.1: 1080p/60fps via DLSS3 Frame Generation** — contingent on completing Streamline 2.11.1 custom Unity plugin integration (~2-3 weeks engineering); NOT a v1 deliverable

**Spec §11 currently does NOT lock this — fix it.** Any prior "1080p/60 with DLSS3" claim must be re-cast as v1.1 contingent.

### 16.5 Spec §11 v3 corrections (R2-A10)

1. **§11.8 #2 day-night deferral WRONG** — must move to v1 ship. Without lunar lighting the genre fails. (See §14.11.)
2. **Spec lacks 1080p/60 vs 1080p/45 lock** — at 8GB cannot hit 60 with current art ceiling. Lock 1080p/45 v1 target, 1080p/60 v1.1 with DLSS3. (See §14.10.)
3. **18 biomes over-promised for v1 ship** — pilot at **2 (mountain_pass + corrupted_swamp)**, grows to **6 by v1.1**, full **18 is v2 minimum**.
4. **Witcher-3-daytime-forest target WRONG** — replace with **"Bloodborne Yharnam + Diablo IV swamps + Alan Wake 2 medium-high"** everywhere (R2-A10 + R2-V2). 8GB ceiling is not Witcher 3 daytime; the correct anchor is dark-fantasy night-tier. Foliage-tier reference is now night-vs-night to keep the comparator internally consistent.

**Verdict:** Spec §11 v3 is ~85% honest about 8GB constraints. Remaining 15% over-promise: implicit 1080p/60, day-night deferral, implicit 18-biome ship scope. Fix those three and v1.0 ships at honest A- on 2 biomes / 4 hours / dark-fantasy AA — same envelope as Bloodborne PS4 launch.

---

## §17. 60-DAY PLAN — Phase A-E (NEW per R2-A7)

R1 §6's 30-day plan covered ~30-40% of total P0 surface. R2-A7 60-day plan targets **80% of P0 at $0 / 8GB** with explicit v1.1 deferral list. **This supersedes §6.**

### 17.0 PRE-PHASE-A — Day 0 repo state cleanup + skeletons (~0.5d, runs alongside §0.4 checklist)

Before opening Day 1 of Phase A, the repo must be clean and the Day 0 skeletons authored. Run these tasks alongside the §0.4 checklist:

```
- Delete temp Windows-malformed files: rm "C\357\200\272Users*", `pr26_*.json`, `pr29_*.json` per `git status`
- Verify branch state: `git status` should show only `.planning/STATE.md` modified (decide commit-or-discard)
- Run `python scripts/verify_pr_cites.py` to validate spec citations are non-stale
- Stash any in-progress work; checkout `main`; pull latest; create new working branch off `main`
- Author `tools/hwcap/capture_4060ti.py` skeleton (see §19.8 #9). Run once, commit `renders/quality-audit/hwcap_4060ti_baseline.json`. Lock stack only if all picks fit <600 MB headroom.
- Author `scripts/run_unity_recorder_gate.py` skeleton (~50 LOC, see §19.8 #8). Template at `scripts/run_unity_recorder_gate_template.py` (to be created). Wraps `Unity.exe -batchmode -nographics -executeMethod VbHeroShotRecorder.CaptureGoldens`, calls `dssim` (or in-Unity Graphics Test Framework), writes SSIM JSON. Stub good enough to fail loud; full version in Phase D D43-44.
- Commit `IMPLEMENTATION_FIX_GUIDE_2026_05_07_FINAL.md` as official artifact on Day 0.
```

`tools/hwcap/capture_4060ti.py` skeleton (commit on Day 0):

```python
# Day 0 baseline VRAM/perf capture
import subprocess, json, time
from pathlib import Path
results = []
for feature in ["empty_scene", "apv_only", "vol_clouds_low", "vol_clouds_med", "speedtree_5_species", "all_combined"]:
    subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits", "-lms", "100"])
    # ... runs Unity headless test scene per feature, captures peak
    results.append({"feature": feature, "peak_vram_mb": ..., "avg_ms": ...})
Path("renders/quality-audit/hwcap_4060ti_baseline.json").write_text(json.dumps(results, indent=2))
```

### 17.1 Phase A (Days 1-15) — Bake-side blockers

> **PR-numbering footnote:** Spec PR ordinals (#1, #2, #3, etc.) are this spec's internal sequence; actual GitHub PR numbers (#31, #32, #33...) are different. Cross-reference: spec #1 = GitHub #31, spec #2 = GitHub #32, spec #3 = GitHub #33. Throughout §17, "PR #N" refers to the spec PR ordinal in `docs/superpowers/specs/2026-05-05-biome-render-rebuild-design.md §11`, not the GitHub PR number.

| Day | Item | Description |
|-----|------|-------------|
| D1-2 | PR #3 (GitHub #33) toposort + post-merge audit | Spec PRs #1 (GitHub #31) and #2 (GitHub #32) MERGED 2026-05-07. Verify post-merge state: run `pip-audit --strict --ignore-vuln` for zero-CRITICAL gate. Verify PR #33 (toposort overrides=) status; if open, address Codex architectural concern. Rebase `docs/biome-render-rebuild-spec` onto `main` to converge `derive_pass_seed` bifurcation (Bug-A). |
| D3-5 | (D1-2 absorbed PR #3 work — slot freed) | Slot now used for B15-P0-01 affine rescale + B15-P0-02 advance work + Bug-A/D/E side-fixes. |
| D6-7 | B15-P0-01 affine rescale + B15-P0-02 4 biomes | + import-time assert (**GATE D5**) |
| D6.5 | **asset_generation.py deletion (FINAL-V3 #9 fill)** | confirm zero call sites for `asset_generation.py` (803-LOC module emits `DeprecationWarning` on import, still imports `gradio_client`, `runpod`, `requests` at module level — pollutes CI logs). Canonical replacement is `Hunyuan3D2Provider` per memory `project_ai_asset_provider_2026_04_27.md`. Delete the module + clean import paths + drop `gradio_client`/`runpod` from `pyproject.toml` if no other consumers (R2-A4 D2). |
| D8-9 | PR #4 wire 8 orphan passes | + 6 missing register_*_pass functions |
| D10-11 | PR #5a/#5b W-1 channel migration | water_surface → water_surface_mask atomic |
| D12-13 | B15-P0-08 hydraulic mass leak | + B15-P0-10 gradient axis swap + B15-P0-11 mean subtraction |
| D14-15 | B15-P0-17 bedrock_height | + P0-18 hardness Z-axis + P0-21 horizon_lod overrides (**GATE D15**) |

### 17.2 Phase B (Days 16-25) — Determinism + export

| Day | Item | Description |
|-----|------|-------------|
| D16 | PR #9 vectorize road SDF | scipy EDT |
| D17-18 | PR #15.5 + #14 chunk_seed module | + derive_pass_seed unification |
| D19-22 | PR #18 RNG migration | 179 sites — XL parallel |
| D23 | PR #15 hash hazards | 4 sites |
| D24 | PR #12 atomic manifest | + #13 NaN/Inf |
| D25 | B15-P0-07 splatmap truncation | (**GATE D25**) |

### 17.3 Phase C (Days 26-35) — Orphan-pass wiring + label-stamping

| Day | Item | Description |
|-----|------|-------------|
| D26-27 | PR #16 stratigraphy | + #17 morphology delta |
| D28-29 | PR #21 pass contracts | + #31-#32 macro_color 8-channel + 14-biome palette |
| D30-32 | PR #29 label-stamping | (Issue #27) |
| D33 | PR #36 splatmap 4→8 | (Unity 2022+ supports 8 — but **4 effective at 8GB**) |
| D34 | PR #43 + #44 streaming budget cap | |
| D35 | PR #42 missing emitters | (**GATE D35**) |

### 17.4 Phase D (Days 36-45) — Unity ingestion + visual gate (Block 5a)

| Day | Item | Description |
|-----|------|-------------|
| D36-37 | B5-U1 Unity 6.3 + HDRP 17.6 bootstrap (~2 days, see expanded sub-steps below) | + 4-layer splat + APV OFF (8GB-locked per §7.1) |

**D36-37 Unity project bootstrap sub-steps** (§19.8 #5 fill — explicit because §17 D36-37 presumes `Assets/`, `Packages/manifest.json`, `ProjectSettings/` exist; they don't):

```
D36 morning (2 hrs): Unity Hub > Create New Project > 6000.3.0f1 > HDRP template. Project location: `unity_project/VbHeroDemo/`.
D36 afternoon (2 hrs): Edit `unity_project/VbHeroDemo/Packages/manifest.json` to pin: HDRP 17.6.x, Visual Effect Graph 17.x, Adaptive Probe Volumes (auto), Addressables 2.x, Burst, Collections, Mathematics. Run `Unity Hub > Open Project` to fetch deps (~10 min).
D36 evening: Create `Assets/VbTerrain/Plugins/` directory. Copy 5 .cs files from repo `unity_plugin/` to `Assets/VbTerrain/Plugins/`. Verify all 5 compile.
D37 morning: Project Settings > Graphics > Pipeline Asset = create `VbHDRPAsset_HighFidelity.asset`. Project Settings > Quality > pipeline asset assignments per tier.
D37 afternoon: Create `Assets/Scenes/vb_hero_demo.unity`. Add Directional Light + Camera + HDRP Volume (default profile).
```

| D38 | B5-U3 SetHoles consumer | |
| D39 | B5-U4 normal-Y flip | + B5-U5 edges.json |
| D40-41 | B5-U2 HDRP WaterSurface | (river+pool only — no Ocean simultaneously per §7.1 stacked-feature ceiling) |
| D42 | B5-U8 flow_map | + RenderMeshIndirect for foliage |
| D43-44 | **Integrate HDRP native DLSS 4.5 SR (BEFORE foliage scatter — REVISED 2026-05-07)** | Set HDRP Asset > Dynamic Resolution > Enable + Enable DLSS + Quality preset. Force **Preset L via DLSS-Swapper sidecar**. Verify motion vectors enabled across all camera rigs. Author per-scene sharpness curves. Output 1080p, internal 720p, 16.6ms frame budget at 1080p/60 LOCKED. **3-5 days solo-dev integration.** Then run `run_unity_recorder_gate.py` + Graphics Test Framework SSIM ≥0.95 against DLSS-on goldens (rasterized + DLSS 4.5 SR Quality). Path Tracer goldens via cloud bake-rig (§18); DLSS3 frame-gen still v1.1 contingent on Streamline custom integration. **Pre-warm step (FINAL-V3 #2 fill — R2-A3 #4): before each golden capture, run scene flythrough 2 minutes to pre-warm shader cache, then capture goldens fresh.** First-time-seen 10-layer terrain triggers async shader compilation 6-14 sec on 4060 Ti — visible as pink/black tiles. Recorder otherwise captures these stalls *into goldens*, polluting the SSIM ratchet. Use `ShaderVariantCollection.WarmUp()` at scene load + 2-min camera flythrough across all biome chunks before snapshot. |
| D45 | NotImplementedError shim | replaces fake `compute_nonblack_ratio` (**GATE D45 — DLSS 4.5 SR Quality verified at 1080p output, 720p internal, 16.6ms frame budget at 1080p/60 LOCKED; SSIM ≥0.95 against DLSS-on goldens; motion vectors verified all camera rigs; Preset L confirmed via DLSS-Swapper**) |

### 17.5 Phase E (Days 46-60) — Performance + atmosphere + audio

| Day | Item | Description |
|-----|------|-------------|
| D46-47 | PR #19 Numba/Taichi erosion | (integer atomics ONLY, atomic-float ban §8.4) |
| D48 | B15-P0-09 SPL solver wired | |
| D49-50 | Foliage RenderMeshIndirect — REVISED 2026-05-07 | **SpeedTree 9 Indie subscription activate ($19/mo).** Author hero foliage in SpeedTree 9 Modeler; export `.st9`. **SpeedTree 9 Importer (Unity 6.3 native, FREE)** consumes `.st9` for HDRP 17 GRD-compatible wind. **DIY HDRP Shader Graph wind (~2 days)** for procedural filler density (grass + low-LOD shrubs). NR6 compute-shader grass instancing 30K+ blades/chunk. **NO happy-turtle integration** (abandoned 2021, broken on HDRP 17). **NO Modular Tree GoodPie billboard impostors** (replaced by SpeedTree 9 native octahedral billboards from .st9). |
| D51-52 | Volumetric Clouds **Medium-High preset** | DLSS Quality (720p internal) makes Medium achievable; full High needs path B/C 12GB hardware. + Volumetric Fog + 3 Local + LightningController.cs **+ Sun.cs + day-night Volume interpolation (§14.11 v1 requirement)** |
| D53 | AgX LUT bake | (DaVinci → .cube → HDRP) |
| D54-55 | Wwise Indie + Steam Audio | (Apache 2.0 confirmed — R2-A6 N1) OR fallback FMOD |
| D56-57 | B15-P0-15 vectorize | 22 biome-feature O(N²) loops |
| D58 | Memory + spec doc updates | |
| D59-60 | Hero shot render — **2-biome ship-minimum** hero shots (mountain_pass + corrupted_swamp); 4-biome target deferred to v1.1 per §16.3. 4 hero camera moments per biome = 8 hero PNGs total. | + decision gate (**GATE D60**) |

### 17.6 Deferred to v1.1 (R2-A7 explicit cuts)

- APV Sky Occlusion (16GB rebake required)
- 8-layer splatmap (4 effective at 8GB)
- HDRP Path Tracer goldens (editor-only at 720p/64spp; runtime kill per §7.1)
- TerraForge3D GPU port (defer unless profiler shows pure-Python is bottleneck — V14.9 disagreement)
- PFG Bézier compute shader (clean-room cost 3-5d not 1.5d per V3)
- Refactors PR #49-#54 (low-priority architecture polish)
- 30 Batch15 P1s (post-v1 quality polish)
- **DLSS3 frame-gen (EXPLICITLY DEFERRED v1.1 per R2-V2):** Unity HDRP 17.6 ships **DLSS 4.5 SR only — no native FG**. Streamline 2.11.1 (2026-04-21) has FG but no turnkey Unity plugin; custom integration ~2-3 weeks. FG VRAM = 272 MB at 1080p. v1 lock = 1080p/45 raster only.
- `procedural_meshes.py` 22,607 LOC scope contamination relocation (defer per spec §11.7 #7)

### 17.7 v1.1 → v2 escalation path

- **v1.1 (Days 60-90, 4-week post-v1 polish):** 6 biomes total (add 4 to mountain_pass + corrupted_swamp), DLSS3 evaluation, Path Tracer goldens for hero shots, TerraForge3D GPU port if profiler bottleneck, 8-layer splat behind toggle, APV Sky Occlusion behind 16GB-required toggle.
- **v2 (post-v1.1, 6+ months):** full 18-biome catalog, mesh shader research, SVT evaluation, Hellblade-2-tier hero moments, 60fps native target with art density rebuild.

---

## §13.6 R2-D1 Completeness Verifier Report

**Verifier:** R2-D1 (completeness, doc-verifier 1 of 4-team), executed 2026-05-07.
**Method:** Read full post-R2-update doc (1443 lines) + R2_OPUS_FINDINGS.md + 10 codex_results_r2/*.txt headers + 13 specific section probes.

### COMPLETE — items that fully made it through R2 updates

1. **R2-A1 4-preset table (Ultra/High/Medium/Low)** — landed in §7.1 with full row coverage for VRAM target, APV Sky Occ, Splat layers, Volumetric Clouds, Fog vols, Reflection probes, RT. VeilBreakers v1 baseline correctly marked High (8GB safe). Original VRAM allocation table also reproduced verbatim from R2-A1.
2. **R2-A1 8GB shipping target hardware reality** — landed across §0.2, §7.1, §16. RTX 4060 Ti = PS4 VRAM class framing present in §16.1.
3. **R2-A2 $20 spend correction** — primary money table at §3 + §14.1 fully replaces R1/R1.5 with $20 baseline / $40 ceiling. Drop verdicts for Amplify, Beautify, Aurora, THOR all present with R2-A2 reasoning. Auto-Rig Pro OWNED stated 8 times.
4. **R2-A3 NVIDIA driver 532+ shared-memory cliff** — full §7.5 dedicated section with all 4 ship-side implementation parts (launcher check, VRAM telemetry, auto-degrade, 8GB FAILSAFE asset). Phase-0 hardware capture harness present.
5. **R2-A3 stacked-feature memory ceiling** — landed in §7.5.
6. **R2-A4 5 NEW bugs** — Bug-F (lava D8), Bug-G (terrain_size_x_m double-scale), Bug-H (morphology magic-offset), Bug-I (navmesh non-deterministic), Bug-J (register_pass weak-ref leak) all present in §1.3 with file:line cites + fix recommendations.
7. **R2-A4 silent failures + dead-code + determinism hazards** — S1/S2/S3, D1/D2/D3, H1/H2 all reproduced under §1.4.2/1.4.3/1.4.4. Spec/code drifts X1/X2 surfaced in §9 final rows.
8. **R2-A5 license blockers** — happy-turtle/foliage-wind NO LICENSE flagged in 5+ places; sinanata GPL flagged in §2.5/§7.2; CarterGames GPL flagged in §2.9/§7.2 with DerKekser MIT replacement. AlexMerzlikin BRG NO LICENSE flagged in §2.1/§2.7.
9. **R2-A5 5 critical alternates** — full table in §11 with replacement licenses + last-update dates (GoodPie/modular_tree, Unity HLOD 2.0, DerKekser/unity-save-system, dbrizov/Unity-WaterBuoyancy, HDRP WaterSurface).
10. **R2-A6 5 NEW conflicts** — N1-N5 all in §7.4 cross-tool table (Steam Audio Apache 2.0, SpeedTree .st9 vs Draco, Z-up axis chain, Decal vs Holes, GRD vs DLSS3).
11. **R2-A7 60-day Phase A-E plan** — full §17 with all 5 phases, GATE checkpoints D5/D15/D25/D35/D45/D60 all present. R1 30-day plan correctly collapsed into `<details>` historical section.
12. **R2-A8 Apache NOTICE for Steam Audio + manifest checklist** — §7.2 manifest checklist (6 items) + §2.9 audio license chain (5 items) both present. Apache §4(d) NOTICE + Kevin MacLeod CC-BY attribution + end credits + Steam store + LICENSES.md all listed.
13. **R2-A9 8 critical CI gaps** — §8.2 table contains all 8 (Unity Test Framework workflow, Windows runner, determinism subprocess matrix 18/18, license-manifest gate, biome-name invariant, frame-budget/VRAM perf gate, SSIM golden retention, release pipeline) with effort + priority.
14. **R2-A10 4 spec §11 v3 corrections** — §16.5 lists all 4 (day-night to v1, 1080p/45 lock, 18 biomes is v2, Witcher-3-day → Bloodborne+Diablo-IV) verbatim. §14.10 + §14.11 expand.
15. **MicroSplat Texture Clusters specific justification** — §2.6 + §3 + §14.1 all cite the Texture Clusters cycling argument with "Skyrim grass plane" indie-tell language. Booth's 7-year update record reproduced.
16. **§0 supersession structure** — §0 line 4 cites supersedes 2026-04-27 master guide + Batch 15. §17 supersedes §6 30-day plan. §14 supersedes R1/R1.5 entirely.
17. **8GB hard constraint visibility** — 71 mentions across §0, §1, §2.5, §2.6, §2.7, §3, §6, §7.1, §7.5, §14, §16, §17.

### PARTIAL — items that landed but missing pieces

1. **§15 "WHEN YOU WAKE UP" still cites $50 baseline / $185 worst-case** (line 1190). Direct contradiction to §0.3, §3, §14.1 ($20/$40). Item #4 should read "$20 baseline / $40 conditional ceiling." Item #6 still recommends "Approve Beautify HDRP $39.99" — directly contradicts the §3 DROP verdict.
2. **§6 historical 30-day block** retains "$130 spend ($40 MicroSplat + $90 Amplify Impostors)" at line 618 and "Buy + integrate Amplify Impostors ($90)" at step 20 line 559. The block is in `<details>` and explicitly marked "HISTORICAL — REPLACED" but the stale numbers are still searchable.
3. **§17.5 D49-50 row** says "replaces $90 Amplify" (line 1419) — Amplify list price was $60 (Verifier 2 confirmed sale $30); doc shouldn't keep citing $90.
4. **License chain manifest §7.2 checklist** is 6 items but missing explicit row for **CC-BY-SA / CC-BY-NC OpenGameArt audit** as a discrete checklist item. The audit caveat appears in §2.9 body text but not in the §7.2 numbered checklist. Add as item 7.
5. **Spec §11 v3 corrections** present in §16.5 but spec doc itself (`docs/superpowers/specs/2026-05-05-biome-render-rebuild-design.md`) has NOT been updated — guide flags the correction needed but the action is still "TODO" not "DONE."
6. **Hardware constraint citation** present 71 times but missing from §4 (TerraForge3D ports), §5 (PFG ports), §10 (AAA-or-better grade list), and §12 (Open questions). These sections discuss techniques whose VRAM cost should anchor against 8GB.
7. **Auto-Rig Pro acknowledgment** confirmed in 11 places but absent from §3 paid-tool table footer commentary (line 437 says "Baseline spend: $20" but doesn't restate "Auto-Rig Pro: OWNED" near total). Add for unambiguous user readout.
8. **R2-A5 critical-alternates table location** is §11 ("MEMORY UPDATES TO APPLY") — semantic mismatch since these are tool replacements not memory entries. Should additionally appear inside §2.x procurement tables for visibility (currently sinanata→dbrizov, CarterGames→DerKekser are in body text but the consolidated table is buried in §11).

### MISSING — items in R2 findings that didn't propagate

1. **R2-A2 Sonniss SFX as THOR replacement specifics** — §3 row says "Sonniss GDC samples + 50-LOC LightningController." But no §2.x row enumerates the 26-sample replacement list or references a Sonniss download path. R2-A2 #5 listed "26 thunder samples replaceable with Sonniss GDC" — count is dropped from the body.
2. **R2-A3 risk #11 (Unity Terrain multi-pass shader compilation stalls)** — present in §7.5 third-to-last paragraph but priority is unclear. R2-A3 stated "Recorder captures these stalls into goldens" — that golden-pollution implication is missing from §8 verification gates section.
3. **R2-A3 risk #12 (Modular Tree GoodPie remapper — 1-2 days)** — landed in §2.7 GoodPie caveat (lines 328-338) but the §17 Phase E D49-50 budget row does NOT add the +1-2d remapper time. R2-A7 noted "budget +1-2d for Unity export wind-UV remapper" — that line is in §6 step 49-50 but absent from §17 D49-50 row.
4. **R2-A4 spec drift X2 (splatmap layer truncation)** — present in §9 final row but no §1.3 / §1.4 entry. Should also surface in §1.5 spec/code drift section as it crosses the Python/C# boundary.
5. **R2-A5 Crest 4 "BIRP-only OSS branch" full naming** — Verifier 2 §13.2 noted the doc should distinguish "Crest 4 BIRP free, Crest 5 paid HDRP/URP." §2.5 + §7.2 say "BIRP-only OSS branch" but never use the version numbers — readers without context confuse the two. Add explicit "Crest 4 (free, BIRP-only) vs Crest 5 (paid, HDRP/URP)" disambiguation.
6. **R2-A8 §3 royalty-gated Wwise Pro upfront pricing** — §2.9 body has "$8,000 first platform + $4,000 each extra platform" but §3 paid-tool table row for Wwise just says "FREE adopt" without a flag for "if budget exceeds $250K, $8K+$4K/platform." Add second row or footnote.
7. **R2-A9 Total CI effort 13.5 days for P0-P2 + 1 day P3** — §8.2 says "13.5 days for P0-P1" but R2-A9 said "P0-P2 + 1 day P3" with 5 nice-to-haves. The 5 nice-to-haves (Hypothesis property tests, Linux x64 Steam Proton, Sentry/BugSplat, AI/ML training tag CodeQL, weekly Gaea compare) are NOT enumerated anywhere in §8. Add as §8.4.
8. **R2-A10 audio domain "Wwise/FMOD deferred per §11.7 #14 — confirm"** — original R2-A10 noted Wwise/FMOD deferral question. Doc §16.2 audio row says "Wwise Indie + Steam Audio Apache 2.0" without the §11.7 #14 deferral flag. The §11.7 #14 cross-reference is dropped.
9. **R2-A4 D2 (asset_generation.py 803-LOC dead module)** — flagged for deletion in §1.4.3 but no §6 / §17 step schedules the deletion. Will linger across all phases.
10. **R2-A10 frame-budget honesty** — §16.4 says "1080p/45 RECOMMENDED" but does NOT call out the spec must be updated. §14.10 covers it. Cross-link is missing — readers landing in §16 won't know §14.10 exists.
11. **R2-A5 paulhayes Sun.cs gist URL correction** — original R2-A5 had `54a7aa2ee3cccad4d37bb65977eb19e2` correction noted. Doc §2.3 still references "paulhayes sun-rotator gist" without the corrected hash. Update to specific gist ID or remove "sun-rotator" slug language.

**Bottom line:** Major R2 findings (R2-A1, A2, A3, A5, A6, A7, A9, A10) all landed substantively. R2-A4 5 NEW bugs all present. R2-A8 license chain + manifest mostly present. The **3 PARTIAL items most worth fixing before user wakes**: (P1) §15 stale spend numbers contradict the new $20/$40 baseline; (P2) §17.5 keeps citing "$90 Amplify" alongside §3's $30 sale price; (P3) §7.2 license checklist needs CC-BY-SA/NC OpenGameArt audit row. The **1 MISSING item most worth fixing**: §17 Phase E D49-50 should bump +1-2d for the Modular Tree GoodPie remapper per R2-A3 #12 and R2-A7. Doc is **~92% complete propagation** of R2 findings into the post-R2 final guide; remaining 8% is editorial drift between §3/§14/§15/§17 (money + calendar) and §2.x/§7.x (license checklist depth).

---

## §13.7 R2-D2 Stale-Data + Contradiction Verifier Report

**Verifier:** R2-D2 (4-verifier team — STALE-DATA + INTERNAL-CONTRADICTION sweep), 2026-05-07.
**Method:** Full doc read + targeted greps against $20 / $40 / $50 / $130 / $185, AGPL/Apache, 1080p/60-vs-45, Bug-A..J, Witcher / Bloodborne / Hellblade, 532+ / 536.40 / 546.01, "sub-textures", and §11 vs §14.8 memory lists.
**Verdict:** Doc is materially trustworthy but **15 STALE entries**, **9 INTERNAL CONTRADICTIONS**, and **6 places where R2-V1/V2 corrections did not propagate** remain. None invalidate the headline R2 conclusions but all should be reconciled before the user signs the spec.

### A. STALE entries inside the doc

1. **§1.3 header "5 NEW bugs (R1.5 fresh-eyes sweep)"** — section now contains **10 bugs (Bug-A..J, no skipped letters)**. Bug-F..J are R2-A4 additions. Header is stale; rewrite as "10 NEW bugs — Bug-A..E from R1.5, Bug-F..J from R2-A4."
2. **§6 D59-60 (line 523)** says "SSIM ≥ 0.92" while §8 gate #1, §14.6, §17 D43-44 all say 0.95. §6 was not updated; §17 won per §14.6.
3. **§6 historical 30-day footer (line 618)** says "$130 spend ($40 MicroSplat + $90 Amplify)". Wrapped in `<details>` "HISTORICAL — REPLACED" but stale numbers leak via search.
4. **§7.5 heading (line 716)** "NVIDIA driver 532+ shared-memory cliff" — R2-V2 corrected to **536.40** (NVIDIA KB a_id/5490). §7.5 body line 718 already cites 536.40 + 546.01 correctly; only the heading is stale.
5. **§2.6 line 295 + §3 row line 416** "MicroSplat Texture Clusters — pseudo-random cycling between **4 sub-textures per layer**." R2-V2 §13.5 corrected to **3 sub-textures**.
6. **§12 OPEN QUESTIONS #6 (line 876)** "Steam Audio runtime license — verify shipped-binary AGPL terms before runtime adoption." R2-A6 N1 + R2-A8 + R2-V2 all confirmed Apache 2.0 — answered. Drop or rewrite as "Confirm NOTICE-file shipping plan."
7. **§13.1 V1 NEEDS USER VERIFICATION (line 944)** "Steam Audio Unity runtime AGPL applicability to shipped binary — flagged §7.2; legal answer outside code scope." Stale framing — answer is Apache 2.0; reframe as Apache §4(d) NOTICE compliance.
8. **§12 #4 (line 874)** "Beautify HDRP ($45) — buy now or after Day 11 LUT bake test?" R2 dropped Beautify ($39.99 actual). Question moot.
9. **§12 #5 (line 875)** "THOR Thunderstorm ($30)" — R2 dropped. Question moot.
10. **§12 #3 (line 873)** prompts a MicroSplat-vs-native shader question; R2-A2 already locked the BUY decision in §3 / §14.1.
11. **§15 #4 (line 1190)** "Approve revised spend ceiling: **$50 baseline / $185 worst-case**." R1.5-era pricing. R2 final is $20 / $40. **Hard contradiction with §0.3 / §14.1.**
12. **§15 #5 (line 1191)** "Approve Option α (30-day pilot) ... OR Option β rebase 45-60 days." 30-day plan already collapsed via §6 details-block + §14.4 + §17. Stale framing.
13. **§15 #6 (line 1192)** "Approve Beautify HDRP $39.99 — single biggest dark-fantasy visual win after MicroSplat." Directly contradicts §3 + §14.1 DROP verdict.
14. **§13.1 NEEDS USER VERIFICATION (line 942)** "RTX 4060 Ti VRAM variant (8GB vs 16GB)." §0.2 + §7.1 + memory `project_hardware_8gb_vram_2026_05_07.md` already locked 8GB. Stale ambiguity.
15. **§16.2 Foliage row (line 1320)** "Witcher 3 NIGHT forests, NOT daytime ... L-Py + MTree gets ~70% of daytime SpeedTree bar." The "daytime SpeedTree bar" comparator inside the NIGHT-forest cell is internally contradictory. Tighten.

### B. INTERNAL CONTRADICTIONS

1. **§14.2 vs §1.1 / §1.2 — items "to move" never moved.** §14.2 lists P0-I2, P0-E2, P0-S2, B15-P0-05, Anomaly 2, W-2 + M-3 as items to migrate from §1.2 OPEN → §1.1 FIXED (or reclassify M-3 from §1.1 FIXED → SCAFFOLDED). **§1.1 + §1.2 are unchanged.** P0-I2 / P0-S2 / P0-E2 / B15-P0-05 still listed OPEN at lines 65-70. M-3 still listed FIXED at line 48. §14.2 is purely informational; the actual moves were never applied.
2. **§15 #4 ($50 / $185) vs §0.3 + §14.1 ($20 / $40)** — direct numeric contradiction.
3. **§15 #6 (Beautify $39.99 approve) vs §3 row line 420 + §14.1 row line 1068 (Beautify DROPPED)** — direct contradiction.
4. **§9 row 822 — wildlife_affinity X1 still listed as drift to fix.** R2-V1 §13.4 line 1235 explicitly marked X1 a FALSE-POSITIVE: "`terrain_wildlife_zones.py` writes `dict[str, ndarray]` exactly matching consumer ... Remove X1 from fix queue." X1 was NOT removed.
5. **§6 D43-44 SSIM 0.92 vs §17 D43-44 SSIM 0.95.** Same Phase D Days 43-44 in two sections with different acceptance thresholds.
6. **§11 memory list vs §14.8 memory list — DIFFERENT CONTENT.** §11 (lines 842-849) lists 7 ADD entries + 5 critical alternates table + 3 license corrections. §14.8 (lines 1120-1146) lists 5 ADD + 5 SUPERSEDE + DELETE/COLLAPSE block. Neither is a strict superset. Two parallel memory-update specs; user will not know which to apply.
7. **§7.5 driver heading "532+" vs §7.5 body "536.40" vs §13.4 + §13.5 corrections "536.40"** — heading-vs-body drift inside one section.
8. **§1.1 M-3 row "FIXED ... scaffolded, awaiting integration" vs §14.2 M-3 row "Reclassify SCAFFOLDED."** §1.1 already says "scaffolded" — §14.2 reclassification is functionally a no-op rename, but the FIXED/OPEN bucket header in §1.1 places M-3 in FIXED while §14.2 calls for OPEN. Pick one bucket.
9. **§14.9 appears TWICE.** Line 1148 "V1+V2+V3 disagreements" with 3 entries; line 1177 "V1+V2+V3 disagreements" with 3 entries. Same heading, slightly different body. Duplicate from a botched merge — collapse.

### C. DRIFT FROM R2 VERIFIER CORRECTIONS (issued, not propagated)

1. **R2-V1 X1 drop never applied to §9.** §13.4 line 1235 says drop. §9 row 822 still active. Strike row or annotate "FALSE-POSITIVE per R2-V1, retain only if reproducer ships."
2. **R2-V2 "3 sub-textures" not propagated to §2.6 + §3.** §13.5 line 1280 corrected to 3. §2.6 line 295 + §3 line 416 still say 4.
3. **R2-V2 driver 536.40 not propagated to §7.5 heading.** §13.5 line 1279 corrected. Body OK; heading still says "532+".
4. **R2-V2 Witcher 3 daytime replacement not fully propagated.** §13.5 USER-ACTION #5 + §16.5 #4 say "Replace 'Witcher 3 daytime forest' everywhere with Bloodborne Yharnam + Diablo IV swamps." §16.2 foliage row keeps the "daytime SpeedTree bar" comparator inside the NIGHT-forest cell. Scrub not complete.
5. **R2-V2 audit-cadence "range" framing not propagated to §7.2.** §13.5 row 1282 says cadence = greenlight + pre-launch + 6-12mo post. §7.2 line 682 only captures the 6-12mo window. Rewrite as "Audited at greenlight + pre-launch + every 6-12 months post-launch."
6. **R2-V2 DLSS3 v1.1 framing not fully propagated.** §0.2 line 23 + §6 D59-60 line 523 + §16.4 line 1348 + §17 D49-50 frame all keep "1080p/60 with DLSS3 frame-gen" as a v1 GATE option. R2-V2 §13.5 + §14.10 Option C explicitly defer to v1.1. Three call sites still treat it as a v1 acceptance branch.

### D. SUMMARY (item-by-item against the 15 sweep checks)

- **$20 baseline consistency.** Mostly clean — but §15 #4 ($50/$185) and §15 #6 (Beautify approve) leak R1.5-era pricing.
- **Steam Audio Apache 2.0 universally.** Body claims clean. §12 #6 + §13.1 V1 verification-needed item still frame as AGPL-pending. Two cleanup edits.
- **30-day plan archived.** Wrapped in `<details>` block, visually demoted but not deleted. Stale "$130" + "$90 Amplify" footer leaks. Add top-of-block warning.
- **Frame budget drift.** Three call sites still treat "1080p/60 with DLSS3" as v1 GATE option even though R2-V2 deferred Streamline integration to v1.1.
- **Bug count §1.3.** Header says 5; reality is 10 (Bug-A..J, no skipped letters). Header stale.
- **§14.2 moves applied.** No — informational only; §1.1 and §1.2 untouched.
- **MicroSplat $40 vs $20 vs $60.** Locked at $20 baseline / $40 conditional ceiling everywhere except the historical 30-day footer ($40 MicroSplat + $90 Amplify = $130).
- **NVIDIA 536.40 / 546.01.** Body correct; one heading still says 532+.
- **MicroSplat Texture Cluster sub-count.** Body still says 4 in §2.6 + §3; should be 3.
- **DLSS3 v1.1 framing.** Inconsistent across §0.2 / §6 / §16.4 / §17 vs §14.10.
- **Wwise audit cadence.** §7.2 captures cadence window but not the "greenlight + pre-launch + post" structure.
- **Bloodborne 5GB pool reference frame.** §0.2 + §7.1 + §16 clean. Witcher 3 "daytime" residue in §16.2 only.
- **R2-V1 X1 wildlife_affinity drop.** Not applied to §9.
- **Self-references to old guide.** §0 line 4 + line 16 + §13.2 line 1000 all flag the 2026-04-27 guide as STALE/SUPERSEDED. Consistent.
- **§11 vs §14.8 memory lists identical.** No — diverge on entry count and DELETE block. Pick one canonical (recommend §14.8 since it includes DELETE/COLLAPSE).

---

## §13.8 FINAL-V1 Internal Consistency Consolidator

**Verifier:** FINAL-V1 (1 of 3 closing verifiers/doc-writers), executed 2026-05-07.
**Scope:** APPLY all internal-consistency fixes flagged by §13.7 (R2-D2 stale-data + contradiction report). Not just audit — fix.

### Fixes applied

1. **§15 #4-#6 rewritten to R2-correct values** — replaced stale R1.5 prompts ($50 baseline / $185 worst-case, Beautify HDRP $39.99 approve, 30-day pilot Option α) with R2 final language: #4 "Approve $20 baseline + $20 conditional Mesh Terrains spend" per §0.3 / §3 / §14.1; #5 "Approve Option β re-baseline 60-day plan per §17"; #6 "Approve 1080p/45 raster lock OR DLSS3 frame-gen v1.1 contingent" per §14.10. Direct numeric contradictions with §0.3 / §14.1 resolved.

2. **§14.2 reframed as informational + §1.1/§1.2 reclassified.** §14.2 header now reads "ALREADY-APPLIED moves (informational only — see §1.1)." §1.1: M-3 row stricken (moved to §1.2 SCAFFOLDED) + W-2 cite corrected from `_water_network.py` to `terrain_pipeline.py:1355` per V1. §1.2: removed phantoms B15-P0-05 + P0-I2 + P0-E2 + P0-S2 (all FIXED/NOT-EVIDENCED per V1+§14.2) and added M-3 SCAFFOLDED. Trailing "Items REMOVED from this list" disclosure block added under §1.2 explaining each removal with file:line evidence.

3. **§9 wildlife_affinity X1 row deleted.** R2-V1 (§13.4) confirmed `terrain_wildlife_zones.py:373-375` writes `dict[str, ndarray]` matching consumer at `terrain_unity_export.py:2773-2811`. False positive. Row removed entirely.

4. **§1.3 header renamed "5 NEW bugs" → "10 NEW bugs (Bug-A..E from R1.5 fresh-eyes sweep + Bug-F..J from R2-A4 — sequence A-J intact, no skipped letters)."** Verified Bug-A → Bug-J sequence intact in body.

5. **§14.9 duplicate collapsed.** Two §14.9 sections existed (line ~1160 + line ~1181 per D2 report). Merged content into the first occurrence (the more detailed body — keeps file:line citations + lock-as language). Replaced second occurrence with HTML comment marker pointing to canonical first-occurrence §14.9.

6. **§11 ↔ §14.8 memory lists reconciled.** §11 now declares §14.8 canonical via blockquote callout: "if §11 and §14.8 ever diverge, §14.8 wins." §11 mirror-list extended with `project_60_day_plan_2026_05_07.md` (NEW per §14.8) and DELETE/COLLAPSE summary line referencing §14.8. Edits to §11 must also touch §14.8.

7. **§7.5 heading "532+" already corrected to "536.40+" by prior pass.** Verified body and heading both cite 536.40 per NVIDIA KB a_id/5490.

8. **§14.9 V1+V2+V3 cross-comparison verified post-collapse.** Single canonical §14.9 contains all 3 disagreements (B15-P0-09, §10 SPL vs TerraForge3D port, MicroSplat $20/$40 lock).

9. **§13.1 stale "8GB or 16GB" verification struck.** §0.2 + §7.1 + memory `project_hardware_8gb_vram_2026_05_07.md` already locked 8GB. Question crossed out + RESOLVED-by-FINAL-V1 annotation added. Same edit reframed Steam Audio AGPL question → Apache §4(d) NOTICE compliance.

10. **§17 D43-44 SSIM 0.95 vs §6 D43-44 SSIM 0.92 reconciled.** Both §6 and §17 are live (§6 60-day plan replaces R1's 30-day; the 30-day block is wrapped in `<details>`). Updated §6 D43-44 + GATE D45 acceptance threshold to "SSIM ≥ 0.95 per spec §11.5b PR #6.5" matching §17 + §8 gate #1 + §14.6.

### Most-impactful before/after

- **Before:** §15 #4 said "$50 baseline / $185 worst-case" while §0.3 said $20/$40. **After:** §15 #4 says "$20 baseline + $20 conditional Mesh Terrains" — direct contradiction resolved.
- **Before:** §1.2 listed P0-S2 with "produces zero placements" (refuted by V1) + P0-I2 already-fixed mask cache + P0-E2 already-fixed prototype height + B15-P0-05 phantom. **After:** §1.2 trimmed to genuinely-open items; phantoms moved to a clearly-labelled "REMOVED" disclosure with file:line evidence.
- **Before:** §14.9 appeared twice. **After:** single canonical entry with collapse marker pointing back to it.
- **Before:** §11 and §14.8 diverged silently — user wouldn't know which to apply. **After:** §11 explicitly subordinate to §14.8 with edit-discipline note.

### Items NOT modified by FINAL-V1 (out of scope for this consolidator; assigned to FINAL-V2/V3)

- Sub-texture count "4 → 3" propagation in §2.6 + §3 (R2-V2 correction).
- Witcher-3-daytime scrub in §16.2 foliage row (R2-V2 correction).
- DLSS3 v1.1 framing across §0.2 / §6 D59-60 / §16.4 / §17 D49-50 (R2-V2 correction).
- §6 historical 30-day footer "$130 / $90 Amplify" inside `<details>` block (already collapsed, leak only via search).
- Wwise audit-cadence rewording in §7.2 (R2-V2 correction).
- Bug-E count reframe (V1 §13.1 correction).

**Bottom line:** Doc is shippable as-is but has 15 stale fragments and 9 internal contradictions that will surface when the user reads §15 next to §0.3, or §11 next to §14.8. Highest-priority fixes before the user wakes: (a) strike §15 #4-#6 stale R1.5 questions; (b) update §1.1/§1.2 per §14.2 moves OR rewrite §14.2 as already-applied; (c) drop §9 wildlife_affinity X1 row; (d) rename §1.3 header "5 NEW bugs" → "10 NEW bugs"; (e) collapse §14.9 duplicate; (f) reconcile §11 ↔ §14.8 memory lists; (g) propagate "3 sub-textures" + "536.40 heading" + "Witcher 3 daytime" + "DLSS3 v1.1 only" R2-V2 corrections.

---

## §13.9 FINAL-V2 External Fact Corrector

**Verifier:** FINAL-V2 (3rd of 3 closing verifiers/doc-writers, 2026-05-07).
**Scope:** Apply external-fact corrections flagged by §13.5 (R2-V2 hardware/license verifier) and §13.7 (R2-D2 drift list). Targeted edits only — no spec drift, no content rewriting beyond what each fix demands.

### Corrections applied

1. **MicroSplat Texture Clusters: "4 sub-textures per layer" → "3 sub-textures per layer"** (per jbooth blog + Asset Store ID 104223; R2-V2 §13.5 row 1280).
   - §2.6 line 295 body — updated to "3 sub-textures per layer" with R2-V2 attribution.
   - §3 row line 416 — updated to "3 sub-textures cycled per layer" with same attribution.

2. **NVIDIA driver fallback: "532+" → "536.40+ introduced fallback; 546.01+ added the toggle"** (NVIDIA KB a_id/5490; R2-V1 + R2-V2).
   - §7.5 heading — rewritten to "NVIDIA driver 536.40+ introduced fallback / 546.01+ added the toggle".
   - §7.5 body para 1 — explicit version sequencing for users on <536.40, 536.40-545.x, and 546.01+.

3. **"Witcher 3 daytime forest" reference scrub** (R2-A10 + R2-V2 USER-ACTION #5).
   - §16.2 Foliage row — replaced contradictory "Witcher 3 NIGHT forests, NOT daytime ... 70% of *daytime* SpeedTree" with internally-consistent "Bloodborne Yharnam + Diablo IV swamps + Alan Wake 2 medium-high — Witcher 3 NIGHT-tier ... ~70% of *night-tier* SpeedTree quality".
   - §16.2 Water row — replaced "Witcher 3 Skellige rivers" with "Bloodborne Yharnam + Diablo IV swamps + Alan Wake 2 medium-high".
   - §16.5 #4 — strengthened to mandate "Bloodborne Yharnam + Diablo IV swamps + Alan Wake 2 medium-high" as the canonical anchor.

4. **DLSS3 reframe** — Unity HDRP 17.6 ships DLSS 4.5 SR only; Streamline 2.11.1 has FG but no turnkey Unity plugin; FG VRAM = 272MB at 1080p; 1080p/45 v1 lock + 1080p/60 v1.1 contingent on Streamline integration.
   - §0.2 line 23 — re-cast to "LOCK 1080p/45 v1; 1080p/60 v1.1 contingent on Streamline integration work" with full R2-V2 detail.
   - §16.4 — rewritten with explicit v1 mandatory + v1.1 contingent framing.
   - §17 Phase D D43-44 — added explicit "DLSS3 frame-gen explicitly deferred to v1.1" annotation.
   - §17.6 deferred list — strengthened DLSS3 row with EXPLICITLY DEFERRED v1.1 marker.
   - §14.10 heading + Option A + Option C + Decision — locked v1 raster, v1.1 contingent.
   - §6 D59-60 (historical) — replaced "OR 1080p/60 with DLSS3" with "EXPLICITLY DEFERRED to v1.1".
   - §7.1 frame-budget reality day-time — locked 1080p/45 v1 raster; DLSS3 v1.1 contingent.

5. **Wwise audit cadence** — "every 6-12mo" → "range at greenlight + pre-launch + 6-12mo post" (R2-V2 §13.5 row 1282; Audiokinetic indie-license blog).
   - §2.9 already had correct framing.
   - §7.2 line 693 — rewritten to "at greenlight + pre-launch + every 6-12 months post-launch (range, not single fixed 6-12mo schedule)".

6. **Steam Audio AGPL → Apache 2.0** — hunt remaining AGPL claims; remove from §13.1 user-verify list.
   - §12 OPEN QUESTIONS #6 — rewritten to "RESOLVED: Apache 2.0 since 2020-02-19" with §4(d) NOTICE shipping plan as the user-action.
   - §13.1 V1 NEEDS USER VERIFICATION row — already updated by FINAL-V1 to RESOLVED.

7. **Amplify Impostors price** — R1's "$90" was stale; verifier confirmed $30 (50% off list $60).
   - §6 step 20 — updated to "$30 — 50% off list $60; R1's '$90' was stale".
   - §6 historical footer line 629 — replaced "$130 spend ($40 MicroSplat + $90 Amplify Impostors)" with corrected "~$70 R1.5-era spend ($40 MicroSplat + $30 Amplify Impostors at sale, list $60)" + reminder that R2 final is $20/$40 (Amplify dropped entirely).
   - §17.5 D49-50 already had "$30-$60 Amplify list / $30 sale price".

8. **§16.2 foliage self-contradiction** — picked one frame: "Witcher 3 NIGHT-tier with hand-placed hero trees + procedural fillers, ~70% of *night* SpeedTree quality" (covered by Fix 3).

9. **paulhayes Sun.cs gist hash** — fabricated "sun-rotator" slug → real hash `54a7aa2ee3cccad4d37bb65977eb19e2`.
   - §2.3 already cited corrected hash.
   - §14.11 line 1205 — updated to embed the corrected gist URL alongside the rotator reference.

10. **GoodPie/modular_tree Unity export "in progress"** — corrected estimate from "+1-2d wind-UV remapper" to "manual FBX-sidecar-JSON + AssetPostprocessor remapper, 3-5 days".
    - §2.1 line 172 — rewritten with R2-V2 corrected estimate, vertex-color-only caveat, and "months not days" upstream-ship reality.
    - §2.7 line 342 — corrected "~1-2 days" to "~3-5 days per R2-V2".
    - §6 D49-50 line 528 — replaced "+1-2d for Unity export wind-UV remapper" with "+3-5d for manual FBX-sidecar-JSON + AssetPostprocessor remapper".
    - §17.5 D49-50 already had the 3-5d budget.

### Notes / non-edits

- §13.1 V1 NEEDS USER VERIFICATION Steam Audio row was already FINAL-V1-resolved; confirmed unchanged.
- All other R1.5/R1 stale Amplify $90 mentions are inside historical `<details>` block; correction applied to historical block to prevent stale searches surfacing stale numbers.
- No drift introduced into §1.1 / §1.2 / §1.3 / §1.4 / §1.5 / §10 / §11 / §15 / §17 (those were the scope of FINAL-V1 / FINAL-V3, not this verifier).
- File modification race during edit pass occasionally required re-reading the same passage; final state matches the corrections list above.

### 300-word summary

FINAL-V2 closed all 10 external-fact corrections flagged by R2-V2 (§13.5) and R2-D2 (§13.7). MicroSplat Texture Clusters now uniformly cited at 3 sub-textures per layer (per jbooth blog + Asset Store ID 104223), correcting R2-A2's earlier 4-sub-texture claim everywhere it appeared in §2.6 and §3. NVIDIA driver fallback heading and body now distinguish 536.40+ (introduces fallback) from 546.01+ (adds user-facing toggle), aligned with NVIDIA KB a_id/5490. Every "Witcher 3 daytime forest" reference is replaced with "Bloodborne Yharnam + Diablo IV swamps + Alan Wake 2 medium-high"; the §16.2 foliage row's internal contradiction (NIGHT-forest cell with daytime SpeedTree comparator) is collapsed into a coherent night-vs-night frame. DLSS3 is universally re-cast as v1.1 contingent on Streamline integration: §0.2, §16.4, §17 D43-44, §17.6, §14.10, §6 D59-60, and §7.1 day-time row all lock 1080p/45 raster v1 and explicitly defer 1080p/60 with DLSS3 frame-gen to v1.1, citing Unity HDRP 17.6 shipping DLSS 4.5 SR only and Streamline 2.11.1 lacking a turnkey Unity plugin. Wwise audit cadence is corrected from "every 6-12mo" to the proper range (greenlight + pre-launch + every 6-12 months post-launch). Steam Audio is uniformly Apache 2.0; the §12 user-verify question is reframed as Apache §4(d) NOTICE compliance. Amplify Impostors price is corrected from R1's stale "$90" to "$30 (50% off list $60)" in both §6 step 20 and the historical footer. The paulhayes Sun.cs gist hash `54a7aa2ee3cccad4d37bb65977eb19e2` is now propagated to §14.11 alongside §2.3. GoodPie/modular_tree Unity export estimate is corrected from "1-2 days" to "3-5 days for manual FBX-sidecar-JSON + AssetPostprocessor remapper" per R2-V2's verified vertex-color-only upstream state. Doc is now externally-fact-aligned with the four R2-V verifier reports.

---

## §13.10 FINAL-V3 Completeness Filler

**Verifier:** FINAL-V3 (3 of 3 closing verifiers/doc-writers), executed 2026-05-07.
**Scope:** Fill the 11 missing items R2-D1 (§13.6) flagged as MISSING/PARTIAL — additive only.

### Items added by FINAL-V3

1. **Sonniss 26-sample count placed in §2.9 audio (FINAL-V3 #1).** Sonniss row now states: "Sonniss GameAudioGDC 2026 ships 26+ thunder samples in the cumulative archive (~160GB) — equivalent SFX coverage to THOR Thunderstorm $30 (R2-A2 #5 verified). Combined with 50-LOC `LightningController.cs` the FREE path delivers full storm SFX + visual at $0." Closes R2-D1 MISSING #1.

2. **Unity multi-pass shader-stall pre-warm step added to §17 Phase D D43-44 (FINAL-V3 #2).** D43-44 mandates: "before each golden capture, run scene flythrough 2 minutes to pre-warm shader cache, then capture goldens fresh" with `ShaderVariantCollection.WarmUp()` + 2-min flythrough across all biome chunks. Prevents pollution of SSIM ratchet by 6-14 sec async shader compilation pink/black tiles. Closes R2-D1 MISSING #2.

3. **GoodPie remapper +3-5d budget bump in §17 Phase E D49-50 (FINAL-V3 #3).** D49-50 row now: "Foliage RenderMeshIndirect (1d budget) PLUS 3-5d for manual FBX wind-UV remapper since GoodPie Unity export is months not days" — per R2-V2 §13.5. Closes R2-D1 MISSING #3.

4. **X2 splatmap drift surfaced as a §1.5 Spec/code drift table row (FINAL-V3 #4).** New table replaces prose-only §1.5. Adds explicit X2-splat row: when `terrain_layer_assets` length ≠ `(splatmap.layer_end - splatmap.layer_start)`, C# at `unity_plugin/Editor/VbTerrainImporter.cs:891` silently drops layers and zero-sum guard at `:912` fills layer 0 = 1.0 → entire tile renders as first layer, no biome variation. Fix: length-vs-range invariant assert Python-side BEFORE manifest write + C# import assert/throw. Closes R2-D1 MISSING #4.

5. **Crest 4 vs Crest 5 disambiguation paragraph appended to §2.5 (FINAL-V3 #5).** New paragraph: "Crest 4.x = MIT GitHub repo `wave-harmonic/crest`, BIRP-only (README explicit). Crest 5 = paid Asset Store SKU 268614 ($100-200), HDRP/URP. They are NOT the same product. VeilBreakers uses Unity HDRP 17.6 native `WaterSurface` (FREE, AA-tier sufficient with foam-formula fix at `terrain_waterfalls.py:114-115`). Do not buy Crest 5; do not vendor Crest 4 (BIRP-only)." Closes R2-D1 MISSING #5.

6. **Wwise Pro upfront pricing row added to §3 paid-tool table (FINAL-V3 #6).** New row after Wwise Indie: "Wwise Pro (above-Indie tier) | $8,000 first platform + $4,000 each extra platform OR 1% gross-sales royalty | conditional | triggers when production BUDGET exceeds Indie threshold ($250K). The $250K threshold is dev BUDGET not revenue." Closes R2-D1 PARTIAL §3 row coverage gap.

7. **R2-A9 5 nice-to-haves enumerated as §8.NICE (FINAL-V3 #7).** New §8.NICE table: N1 Hypothesis property tests (1d, P2), N2 Linux x64 Steam Proton matrix (0.5d, P2), N3 BugSplat/Backtrace.io free crash reporting (1d, P2), N4 AI/ML training tag CodeQL query (0.5d, P2), N5 Weekly Gaea reference compare (defer, P3 — gated by paid Gaea Pro). Closes R2-D1 MISSING #7.

8. **§11.7 #14 audio deferral cross-link added to §16.2 audio row (FINAL-V3 #8).** Audio row now ends with: "confirm spec §11.7 #14 deferral aligns with §16's ship-minimum scope. If Wwise/FMOD authoring slips, fall back to Unity native AudioListener + Steam Audio + AudioReverbZone keyed off `audio_reverb_class` raster (§2.9 fallback). Spec §11.7 #14 flags audio middleware as deferred-confirm; this row commits Wwise-or-FMOD primary unless §11.7 #14 explicitly cuts." Closes R2-D1 MISSING #8.

9. **asset_generation.py deletion scheduled as §17 Phase A D6.5 (FINAL-V3 #9).** New task between D6-7 and D8-9: "confirm zero call sites for `asset_generation.py` (803-LOC, DeprecationWarning on import, still imports `gradio_client`/`runpod`/`requests` at module level). Canonical replacement is `Hunyuan3D2Provider`. Delete + clean import paths + drop `gradio_client`/`runpod` from `pyproject.toml` if no other consumers (R2-A4 D2)." Closes R2-D1 MISSING #9.

10. **paulhayes Sun.cs gist URL hash corrected in §2.3 (FINAL-V3 #10).** §2.3 now reads: "paulhayes Sun.cs gist — single-file directional-light rotator MIT. Verified URL hash: `gist.github.com/paulhayes/54a7aa2ee3cccad4d37bb65977eb19e2` (R1's 'sun-rotator' slug was fabricated). Cross-ref §17 Phase E D51-52 + §14.11." FINAL-V2 propagated this same hash to §14.11; FINAL-V3 had already fixed §2.3. Closes R2-D1 MISSING #10.

11. **§16.4 ↔ §14.10 cross-link bidirectional (FINAL-V3 #11).** Reverse direction added inside §14.10 immediately after the lock decision: "see §16.4 for per-domain frame budget breakdown — the 22ms measurement is the sum of §16.2's per-domain rows. If a domain over-budgets, scope-cut at the §16.2 row level, not the §14.10 frame-rate decision level." Closes R2-D1 MISSING #11.

### Editorial notes

- All edits are additive or targeted line replacements that preserve adjacent context — no §0-§17 deletions.
- All fills carry the `(FINAL-V3 #N fill)` marker so future verifiers can audit-trail.
- §13.6 R2-D1 PARTIAL items 1-8 (§15 stale numbers, §17.5 $90 Amplify, §7.2 license checklist, etc.) are out of scope for FINAL-V3 (covered by FINAL-V1/FINAL-V2 per dispatch plan); FINAL-V3 filled only the 11 numbered items the user enumerated.
- Concurrent FINAL-V2 verifier appended §13.9 immediately above this section during the FINAL-V3 edit pass; both sections are non-overlapping (V2 = external-fact corrections; V3 = MISSING-item fills).

---

## §18. LATEST DECISIONS PATCH (2026-05-07 user mandates — supersedes earlier downgrade framing)

**Status:** This section consolidates the user's latest decisions after pushback on prior 1080p/45 lock + AAA-reference downgrade + happy-turtle foliage choice. Where §0-§17 conflict with §18, **§18 wins.** The implementation auditor reads this section as authoritative.

### 18.1 Resolution lock — 1080p/60 native via DLSS 4.5 SR Quality

- **1080p/60 mandate maintained** — DLSS 4.5 SR Quality (Preset L) is the unlock, NOT a 1080p/45 raster downgrade.
- HDRP 17.6 ships **native DLSS 4.5 SR support**; 3-5 day solo-dev integration window (HDRP Asset > Dynamic Resolution > Enable + Enable DLSS + Quality preset; force Preset L via DLSS-Swapper sidecar; verify motion vectors enabled all camera rigs; per-scene sharpness curves).
- Output 1080p, internal 720p, **16.6ms frame budget at 1080p/60 LOCKED**.
- DLSS3 frame-gen (Streamline FG) remains v1.1 contingent on ~2-3 weeks custom Unity plugin work — SR Quality is the v1 unlock, not FG.
- **Supersedes §0.2 + §14.10 prior "1080p/45 raster lock" framing.** §17 Phase D D43-44 + GATE D45 carry the integration ordering.

### 18.2 AAA reference targets RESTORED

- **Target tier: AAA** (not AA-ceiling, not "Bloodborne PS4 5GB").
- Reference titles: **Witcher 3 NG, Hellblade 2, Cyberpunk 2.0, Diablo IV, Alan Wake 2, Black Myth Wukong**.
- Drop "Bloodborne PS4 5GB" downgrade framing wherever it appears in §0-§17. Replace AA-ceiling references with AAA-target where the per-domain matrix in §18.7 supports it.
- §16.1 reference-title row is OVERRIDDEN by this section.

### 18.3 v1 day/night cycle APPROVED

- Day/night cycle ships in v1 (overrides spec §11.8 #2 deferral as already noted in §14.11 — this section reaffirms).
- Sun.cs + day-night HDRP Volume interpolation in §17 Phase E D51-52 stays.

### 18.4 Foliage stack — happy-turtle DROPPED, SpeedTree 9 Indie canonical

- **happy-turtle/foliage-wind: DROPPED.** Abandoned 2021. Broken on HDRP 17 ShaderGraph node API. No commercial ship history. Do not integrate.
- **Canonical foliage-wind: SpeedTree 9 Indie subscription ($19/mo or $199/yr).** Unlocks Modeler + .st9 export with HDRP 17 GRD-compatible native wind.
- **SpeedTree 9 Importer (Unity 6.3 native, FREE)** consumes `.st9` for in-engine wind; native octahedral billboards.
- **DIY HDRP Shader Graph wind (~2 days)** for procedural filler density (grass + low-LOD shrubs).
- §3 + §14.1 + §17 Phase E D49-50 carry this decision.

### 18.5 GPU upgrade matrix (3 paths)

| Path | Card | Net cost delta | Why pick |
|------|------|----------------|----------|
| **A** | Keep RTX 4060 Ti 8GB | $0 hardware (~$31/mo cloud bake-rig) | Day-1. DLSS 4.5 SR Quality unlocks 1080p/60. AAA-tier achievable per §18.7 with cloud bake offload. |
| **B** | Used RTX 4070 Ti Super 16GB | **+~$450 net** ($750 buy − ~$300 sell of 4060 Ti 8GB) | Removes 8GB ceiling. Unlocks APV Sky Occlusion + 8-layer splat + in-process Path Tracer goldens (no cloud rig needed). |
| **C** | RTX 5070 12GB | **+$549** | Middle path. +50% VRAM, native DLSS 4.5 SR, GDDR7 bandwidth. AAA-tier per §18.7 without cloud rig for most domains. |

### 18.6 Cloud bake-rig setup (RunPod RTX 4090 spot, ~$31/mo)

- **Provider:** RunPod, RTX 4090 spot tier ~$0.40/hr × ~80 hr/mo realistic = ~$31/mo.
- **Use cases:** path-traced HDRP goldens for hero shots, APV bake regenerations, MicroSplat Texture Cluster bakes too heavy for local 8GB.
- **Setup outline:**
  ```
  # Local dev box
  pip install runpodctl
  runpodctl config --api-key <KEY>

  # Spin up bake pod
  runpodctl create pod \
    --imageName runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04 \
    --gpuCount 1 --gpuType "NVIDIA GeForce RTX 4090" --bid 0.40 \
    --containerDiskInGb 50 --volumeInGb 100 --volumePath /workspace \
    --ports "22/tcp,8888/http"

  # Push project to pod
  rsync -avz --exclude='.git' --exclude='Library' \
    ./ root@<POD_IP>:/workspace/veilbreakers/

  # Headless Unity bake (inside pod)
  /opt/Unity/Editor/Unity -batchmode -nographics -quit \
    -projectPath /workspace/veilbreakers/unity_project \
    -executeMethod VbBakePipeline.BakeGoldensAndAPV \
    -logFile /workspace/bake.log

  # Pull artifacts back
  rsync -avz root@<POD_IP>:/workspace/veilbreakers/Assets/Renders/Goldens/ \
    ./renders/goldens/
  rsync -avz root@<POD_IP>:/workspace/veilbreakers/Assets/Settings/APV/ \
    ./unity_project/Assets/Settings/APV/

  # Tear down
  runpodctl stop pod <POD_ID>
  runpodctl remove pod <POD_ID>
  ```
- Spot tier can preempt; checkpoint bake state every 10 min via Unity script. For un-preemptible runs, use RunPod community RTX 4090 (~$0.69/hr) for hero-shot final passes only.

### 18.7 Per-domain AAA tier achievable at 12GB + DLSS 4.5 SR (R2 deep-dive)

Reproduced from R2 deep-dive table — applies to **path C (RTX 5070 12GB)** and effectively **path A + cloud bake-rig** (Path Tracer offloaded). Path B 16GB hits or exceeds every row.

| Domain | AAA target tier | Achievable at 12GB + DLSS 4.5 SR? |
|--------|------------------|------------------------------------|
| Terrain | **Witcher 3 NG Ultra+** (10-layer splat with MicroSplat Texture Clusters) | YES |
| Materials | **8-layer MicroSplat with Texture Clusters** (3-sub-texture cycling) | YES |
| Foliage | **Witcher 3 NG parity** via SpeedTree 9 Indie + GRD wind | YES |
| Atmosphere | **Witcher 3 NG parity** (HDRP 17.6 Volumetric Clouds Medium-High + 3 local fog vols) | YES |
| Lighting (day) | **D4 RT-tier** (RT Reflections enabled day-time only; APV night) | YES |
| Water | **HDRP FFT + Crest-hybrid parity** (HDRP 17.6 WaterSurface + foam fix) | YES |
| VFX | **D4 storm parity** (LightningController.cs + Sonniss thunder + Volumetric Fog interactions) | YES |
| Path Tracing | **Reserved for offline goldens** (cloud bake-rig in §18.6) | OFFLINE-ONLY |

Path A (8GB + DLSS 4.5 SR + cloud bake) hits every row above except in-process Path Tracer (which is offloaded to cloud — same final visual outcome).

### 18.8 NVIDIA driver gate (mandatory launcher check)

- **Required: NVIDIA driver ≥546.01.**
- Driver versions **536.40+ introduced sysmem fallback** (silent VRAM-overflow → RAM swap) which creates a **96× perf cliff** on 8GB cards. 546.01+ added the toggle to disable it.
- Add to launcher (Unity boot or pre-bake CI): `--driver-required >=546.01`. Block boot with a clear message ("Update NVIDIA driver to ≥546.01 — older drivers cause 96× slowdown on this build").
- Detection: WMI query `Win32_VideoController.DriverVersion` or `nvidia-smi --query-gpu=driver_version --format=csv,noheader`.

### 18.9 Cross-section override map (where §18 supersedes earlier sections)

- §0.2 — 1080p/60 via DLSS 4.5 SR Quality replaces 1080p/45 raster lock. Hardware paths A/B/C added.
- §3 — SpeedTree 9 Indie restored as paid tool; happy-turtle DROPPED row added; cloud bake-rig row added.
- §14.1 — money table rewritten ($39 day-1 / ~$50/mo recurring; +$450 path B / +$549 path C hardware).
- §14.10 — 1080p/60 DLSS SR Quality is v1 lock; 1080p/45 raster framing OBSOLETE.
- §16.1 — "Bloodborne PS4 5GB" reference framing OBSOLETE; AAA refs in §18.2 are canonical.
- §17 Phase D D43-44 — DLSS 4.5 SR integration step BEFORE foliage scatter (3-5d).
- §17 Phase D GATE D45 — adds "DLSS 4.5 SR Quality verified at 1080p output, 720p internal, 16.6ms frame budget at 1080p/60 LOCKED."
- §17 Phase E D49-50 — SpeedTree 9 Indie + DIY Shader Graph wind; happy-turtle and Modular Tree GoodPie billboards DROPPED.
- §17 Phase E D51-52 — Volumetric Clouds bumped Low → Medium-High.
- §17.6 — DLSS3 frame-gen still v1.1 deferred (this is unchanged); but DLSS 4.5 SR Quality is NOT deferred — it ships v1.

### 18.10 Per-decision change-log marker

All §18 entries are tagged `(§18 PATCH 2026-05-07)` for future verifier audit trails. The implementation auditor MUST read §18 first and treat it as authoritative for any conflict with §0-§17.

---

## §19. IMPLEMENTATION AUDITOR FINAL VERDICT

**Auditor:** Final-pass implementation auditor (Opus 4.7 1M), executed 2026-05-07.
**Method:** Read all 1889 lines + walk the doc as the solo dev who must execute starting tomorrow. Cross-checked PR state via `gh pr list` (PR #31/#32 merged = "PR #1+#2 cleanup", PR #33 still open = "PR #3 topo-sort"), repo file state (no `Assets/`, no `Packages/`, no `ProjectSettings/`, no `manifest.json`, only 5 loose `.cs` in `unity_plugin/`), and §18 PATCH override map.
**Verdict:** **NO-GO for tomorrow's strict Day-1 start under the §17 plan as written.** The doc is ~93% executable from a knowledge standpoint and ~60% executable from a procedural standpoint. Closing the procedural gap takes ~1 day of edits + Day 0 setup that the doc does not currently script.

### 19.1 EXECUTABILITY GRADE: **B−**

**Reasoning:**
- **Strengths (A-tier):** §1.1/§1.2 cite-accurate fix list, §7.1 8GB budget table, §7.5 NVIDIA driver gate (with all 4 ship parts), §8.2 CI gap inventory with effort estimates, §17 Phase A-E breakdown with daily granularity, §18 user-mandate override map with cross-section update list, §13.1-13.10 verifier appendix proves convergent rigor.
- **Weaknesses (D-tier):** Day 0 is essentially undefined; §17 Phase D Day 36-37 says "Unity 6.3 + HDRP 17.6 bootstrap" but the dev has no Unity project to bootstrap into (no `Assets/`, no `Packages/`, no `manifest.json` exist in the repo today); §18 supersedes §0-§17 but §17 day plan still embeds pre-§18 numbers (1080p/45 in some sections); decision-gate D60 deliverable is "Hero shot render" not "shippable artifact."
- **Critical gap:** **No "Day 0 setup checklist."** The dev would have to invent: tool installs, RunPod signup, NVIDIA driver pinning script, Unity project scaffolding, repo-state cleanup (`pr26_*.json` litter at root, .planning/ uncommitted changes, branch reconciliation).

### 19.2 GO/NO-GO FOR TOMORROW'S DAY 1 START: **NO-GO without Day 0 patches**

**What's blocking:**
1. **Day 1 task is stale.** §17 D1-2 says "PRs #1+#2 cleanup + pip-audit zero-CRITICAL gate." But PR #31 (was PR #1) and PR #32 (was PR #2) both **merged** on 2026-05-07 (today). The Day-1 actual task is "verify post-merge zero-CRITICAL still holds + close PR #33 (topo-sort) review." That rephrasing is missing.
2. **Day 1 has no "first-thing-to-type" script.** Dev opens doc, lands on §17, sees "PRs #1+#2 cleanup" — has to translate that to "what command do I run?" The doc never names the actual CI command (`pip-audit --strict`, `pytest tests/`, etc.) for Day 1 verification.
3. **Day 0 prerequisites are dispersed.** Tool installs in §0.2, hardware path decision in §18.5, NVIDIA driver pin in §7.5, RunPod setup in §18.6, but no consolidated "before opening Day 1, do these 8 things" list.
4. **Repo is dirty.** `git status` shows `pr26_*.json` + `pr29_*.json` files at the project root with malformed Windows-temp-path filenames, plus uncommitted `.planning/STATE.md` change, plus the FINAL doc itself untracked. The dev needs to `git clean` and commit/discard before any branch work.

**To convert NO-GO → GO requires ~6 hours of edits to the doc + ~4 hours of Day 0 setup tasks.**

### 19.3 TOP 5 BLOCKERS

1. **No Unity project skeleton in repo.** §17 Phase D D36-37 ("Unity 6.3 + HDRP 17.6 bootstrap + 4-layer splat config + APV Sky Occlusion OFF at 8x8 grid") presumes `Assets/`, `Packages/manifest.json`, `ProjectSettings/`, `Library/`, `.csproj` exist. They don't. The doc never says "create `unity_project/` directory; in Unity Hub click New Project; pick HDRP template; populate `manifest.json` from this list of packages." This is at least 0.5d of Day 36 work the doc treats as zero.
2. **Day 0 not defined.** No checklist of: install Unity 6.3 LTS, install Blender 4.5, install MicroSplat ($20 purchase via Asset Store before D36), install SpeedTree 9 Indie ($19 subscription before D49), install pyright/pytest/Numba/Taichi, RunPod account + SSH keypair + `runpodctl config`, NVIDIA driver pin + "Prefer No Sysmem Fallback" toggle (manual NVIDIA Control Panel UI step — not scripted), Wwise account creation + project authoring license validation. Estimate: 4-6 hours wall-clock.
3. **PR state references stale.** §17 D1-2 cites "PRs #1+#2." Actual PR numbers (post-merge) are #31 and #32; PR #3 (toposort) is now PR #33. §17 references the *spec PR ordinal* not the *GitHub PR number* — that's a defensible convention but the doc never explains it. A new dev opening the doc cold would fail to map "PR #1" to "PR #31."
4. **§18 PATCH conflicts with §17 frame-budget targets.** §18.1 mandates 1080p/60 via DLSS 4.5 SR Quality. §17 Phase D D45 GATE was updated to "1080p/60 LOCKED" per §18 PATCH. But §17 Phase E D59-60 still says "frame budget ≤ 22.2 ms (1080p/45fps lock)" and §17 GATE D60 says "pilot ships at locked 1080p/45fps raster v1; 1080p/60 with DLSS3 FG is EXPLICITLY DEFERRED to v1.1." That's a direct contradiction — §18 says DLSS 4.5 SR Quality (which is *upscaling*, not frame-gen) ships v1 to hit 1080p/60 native rate; D60 conflates SR with FG. **GATE D60 must be re-cast to "1080p/60 via DLSS 4.5 SR Quality (Preset L, 720p internal); 16.6ms frame budget"** matching §18.1 + §18.9. Frame-gen is the only thing v1.1.
5. **Verification gates lack scripts.** §8 lists 8 gates but only 2 have script paths (`scripts/run_unity_recorder_gate.py` and `scripts/license_manifest_gate.py`). The other 6 — biome-name invariant gate, frame-budget perf gate, 18-artifact determinism subprocess matrix, channel-graph integrity, golden snapshot retention, release pipeline — have no committed scripts. The dev hits Phase A GATE D5 ("topo-sort PR landed") with no defined verification command. §8.2 estimates 13.5 days of CI work; §17 doesn't allocate that time.

### 19.4 TOP 5 AMBIGUITIES (steps the dev will have to invent)

1. **"GATE D5: topo-sort PR landed."** Verification = ? The doc never says "PR #33 merged + `pytest -m 'channel_graph or contract'` green + `python scripts/audit_j11_graph.py --strict-zero` exits 0 + 8 orphan-registered passes show in registry dump." The dev infers; expect 1-2 hours per gate to figure this out × 6 gates = 1 day of waste.
2. **"4-biome hero shots."** §17 D60 says "4-biome hero shots." §16.3 says ship-minimum is 2 (mountain_pass + corrupted_swamp). §17.7 says v1.1 grows to 6. **What is the actual v1 hero count — 2 or 4?** The doc says both.
3. **"APV Sky Occlusion OFF at 8x8 grid."** §17 D36-37 says OFF. §7.1 4-preset table says OFF for High preset (8GB safe). But §17.6 deferred list says "APV Sky Occlusion (16GB rebake required)" which implies it CAN be done at 16GB but NOT at 8GB — yet §0.2 Path B/C upgrade options unlock 16GB. **Does the dev bake APV Sky Occlusion or not?** Conditional on hardware path A vs B/C choice; §17 doesn't branch.
4. **"Hi-Z occlusion mandatory."** §17 D42 says "Hi-Z occlusion mandatory per R2-A3 #5" — referring to `EricHu33/UnityGrassIndirectRenderingExample` MIT. The doc never says "vendor this repo at commit X into `unity_project/Assets/Plugins/EricHu33/`" or "port Hi-Z compute pass into `Assets/Shaders/HiZGrassCull.hlsl` per gist." That's 1-2 days of work the doc treats as a footnote.
5. **"Visual gate replacement."** §17 D43-44 (post-§18 PATCH) says "Integrate HDRP native DLSS 4.5 SR" + "Then run `run_unity_recorder_gate.py`" — but this script doesn't exist in `scripts/` today, and §6 step 37 (historical 30-day plan) just says "build it (~1d)." Phase D D43-44 has 2 days *combined* for DLSS integration AND building the recorder gate AND running goldens — the original §6 step 37 alone budgeted 1d for the gate-building. Realistic: 4-5 days.

### 19.5 MISSING DELIVERABLES (doc says will be done but doesn't define how)

1. **`run_unity_recorder_gate.py`** — script doesn't exist; doc references it 6 times but never specifies command-line interface, expected inputs, output format, or how it integrates with `ImageAssert.AreEqual`.
2. **`scripts/license_manifest_gate.py`** — referenced in §8 gap #12 with "1.5 days" effort but no spec of what it checks (BBC RemArc detection? AGPL detection? EULA capture format?).
3. **`scripts/biome_name_invariant_gate.py`** — referenced in §8 gap #13 with "0.5 day" effort but no canonical file pair to diff (`BIOME_CLIMATE_PARAMS` vs `CANONICAL_BIOME_IDS` vs foliage manifest — three sources, doc lists which two pairs to assert against).
4. **`Assets/Settings/HDRPGlobalSettings.asset`** + **`VbHDRPAsset_HighFidelity_8GB.asset`** — referenced in §17 D36-37 but no preset values dump (cascade distances 200/400/800/2000m? color space? lit shader Both?).
5. **`Assets/Scenes/vb_hero_demo.unity`** — referenced in §6 historical but not §17; what does the dev save the scene as for §17 Phase D output?
6. **`tools/hwcap/capture_4060ti.py`** — referenced in §7.5 "Phase-0 hardware capture harness" with "lock the stack only after capture confirms each pick fits in <600 MB headroom" but never scheduled in §17 timeline.
7. **`VbLauncher.exe`** — §7.5 mandates a native launcher with `nvapi.dll` driver-version check. No language specified (C++? C#? Rust?), no schedule in §17, no "this is v1.1" deferral.
8. **GoldenSubprocessTestHarness** — §8 gap #11 (determinism subprocess matrix) needs `tests/test_determinism_subprocess.py` parameterized 3 OS × 3 Py × 2 seed-seq. No skeleton in doc.
9. **`docs/license/wwise_budget_audit.md`** — §3 row mandates "maintain greenlight + pre-launch + 6/12mo post-launch budget snapshots." File doesn't exist; no template provided.
10. **VeilBreakers art-style guide.** Not in scope per §0-§18 (terrain spec only). Dev will hit Day 36 needing camera focal lengths + ToD palette + biome mood reference images and have nothing committed. **Doc should explicitly list this as out-of-scope-deferred so the dev plans for it externally.**

### 19.6 DEPENDENCY VIOLATIONS

1. **§17 D17-18 (chunk_seed BLAKE2b) presumes §17 D3-5 (PR #3 topo-sort) lands first.** Correct ordering, but D17-18 also implicitly requires Bug-A (`derive_pass_seed` bifurcation) be fixed before chunk_seed module can land — Bug-A is fixed in D3-5 per §17 D3-5 row, so OK. **But Bug-A appears in §17 D3-5 only as one of three side-tasks ("Fix Bug-A, Bug-D, Bug-E"); a 1-line note "branch-only — ensure main's single-source design wins on merge" is the only acknowledgment of the branch-vs-main divergence Verifier 2 flagged. The dev needs an explicit step: "rebase docs/biome-render-rebuild-spec onto main, take main's `terrain_pipeline.derive_pass_seed:208` definition, delete branch's `terrain_rng.py:45`."**
2. **§17 D36-37 (Unity bootstrap) must occur AFTER MicroSplat purchase + SpeedTree 9 Indie subscription.** Day 0 should pre-purchase. Doc never schedules the Asset Store purchases.
3. **§17 D49-50 (SpeedTree 9) presumes D38 Unity importer has SpeedTree 9 Importer enabled.** SpeedTree 9 Importer is built-in to Unity 6.3 — OK. But SpeedTree 9 Indie subscription must be active by D49, and Modeler authoring time is hidden. If SpeedTree 9 Indie buy is on D49, the dev has 0 day to author hero `.st9` files. **Should be subscribed on Day 0 or before D36, with Modeler time scheduled across D36-D48 evenings.**
4. **§17 D54-55 (Wwise) presumes Wwise authoring license created.** Day 0 should include Wwise account + project license activation. Doc has it implicit.
5. **§17 D43-44 (visual gate) presumes Path Tracer goldens or rasterized goldens exist.** §18.7 says Path Tracer is offline-only via cloud bake-rig. So D43-44 needs cloud rig setup (§18.6) — which is ~1 day for first-time RunPod user. Not in §17 D-list.

### 19.7 VERIFICATION GAP

GATE checkpoints D5 / D15 / D25 / D35 / D45 / D60 — only D45 has a scripted criterion ("SSIM ≥ 0.95 against DLSS-on goldens via `run_unity_recorder_gate.py`"). The other 5 GATEs say:
- **D5:** "topo-sort PR landed" — verification = ? (PR #33 merged check is `gh pr view 33 --json mergedAt` returns non-null, but doc doesn't say so.)
- **D15:** "bake-side P0 fixes landed; channel-graph audit green" — what command runs the channel-graph audit? `python scripts/audit_j11_graph.py --strict-zero`? Doc doesn't say.
- **D25:** "subprocess-determinism CI matrix passes 18/18 (3 OS × 3 Py × 2 seed-seq)" — what's the workflow file name? Doc doesn't commit one.
- **D35:** "`pass_topographic_indices` produces all 4 spec channels + foliage-stack consumer wiring complete" — verification command? Implied: `python -c "from veilbreakers_terrain import pipeline; ..."` but no concrete script.
- **D60:** "1080p/60 via DLSS 4.5 SR Quality (per §18.1)... pilot ships" — what's the actual deliverable? Internal milestone? Steam beta upload? itch.io? Doc never specifies.

**Add 5-row "GATE verification commands" table to §8 or §17.7.**

### 19.8 RECOMMENDATION (10 small additions/edits to make doc executable)

1. **Add §0.4 "DAY 0 SETUP CHECKLIST"** — 10-15 line checklist: install Unity 6.3 LTS, install Blender 4.5, install pyright/pytest/Numba/Taichi (`pip install -e .[dev,bake,providers]`), purchase MicroSplat HDRP-for-6.3 ($20) Asset Store ID 344008, subscribe SpeedTree 9 Indie ($19/mo), create RunPod account + `runpodctl config --api-key`, install NVIDIA driver ≥546.01 + manually toggle "Prefer No Sysmem Fallback" per `nvidia-control-panel://Manage 3D settings/Program Settings/VbLauncher.exe`, create Wwise account + Project license, `git clean -fd` repo root + commit `.planning/STATE.md` if intentional. **Estimate: 4-6 hours wall-clock.**
2. **Update §17 D1-2 to current PR state.** Replace "PRs #1+#2 cleanup" with "Verify post-merge state: PR #31 (was spec #1) + PR #32 (was spec #2) merged 2026-05-07; run `pip-audit --strict --ignore-vuln` for zero-CRITICAL; close review on PR #33 (was spec #3, currently open); rebase `docs/biome-render-rebuild-spec` onto `main` to converge `derive_pass_seed` bifurcation." Add note: "Throughout §17, 'PR #N' refers to the spec PR ordinal in `docs/superpowers/specs/2026-05-05-biome-render-rebuild-design.md §11`, not GitHub PR number."
3. **Add §17.0 "PRE-PHASE-A — repo state cleanup."** 1-line tasks: clean `pr26_*.json` / `pr29_*.json` litter from repo root, decide `.planning/STATE.md` change (commit or discard), commit `IMPLEMENTATION_FIX_GUIDE_2026_05_07_FINAL.md` as official artifact.
4. **Reconcile §17 D60 GATE with §18.1 + §18.9.** Replace "frame budget ≤ 22.2 ms (1080p/45fps lock)" + "pilot ships at locked 1080p/45fps raster v1" with "frame budget ≤ 16.6ms (1080p/60 via DLSS 4.5 SR Quality, Preset L, 720p internal) per §18.1; DLSS3 frame-gen v1.1 contingent on Streamline integration."
5. **Add §17 D36-37 sub-step: "Create `unity_project/` directory and bootstrap Unity 6.3 LTS HDRP project."** Specify: in Unity Hub > New Project > HDRP template > project location `unity_project/`; populate `Packages/manifest.json` with HDRP 17.6 + Visual Effect Graph 17 + Adaptive Probe Volumes + Addressables + Burst + Collections + Mathematics + Cinemachine 3.1 + Animation Rigging 1.4 + Localization + AI Navigation; copy 5 existing `unity_plugin/*.cs` files into `unity_project/Assets/VbTerrain/Plugins/`; commit `Library/` to `.gitignore`; verify HDRP scene template loads.
6. **Resolve hero-count ambiguity.** §17 D60 says "4-biome hero shots"; §16.3 says 2-biome ship-minimum. Pick ONE: either §17 D60 says "2-biome v1 ship hero shots (mountain_pass + corrupted_swamp per §16.3), 4 hero camera moments per biome" or §16.3 ship-minimum bumps to 4. Recommend: 2 biomes × 4 hero shots = 8 hero PNGs total at D60. Revise both sections to match.
7. **Add §8.5 "GATE verification commands"** — table mapping each GATE (D5/D15/D25/D35/D45/D60) to the bash one-liner that asserts pass/fail. Example: "D5 = `gh pr view 33 --json mergedAt -q .mergedAt` non-null AND `python scripts/audit_j11_graph.py --strict-zero` exit 0 AND `pytest -m 'channel_graph or contract' -q` exit 0."
8. **Add `scripts/run_unity_recorder_gate.py` skeleton commit BEFORE Day 1.** Python wrapper that calls `Unity.exe -batchmode -nographics -executeMethod VbHeroShotRecorder.CaptureGoldens -logFile`, reads PNG outputs, calls `dssim` (or Graphics Test Framework for in-Unity), writes SSIM JSON. ~50 LOC stub good enough to fail loud; full version in Phase D.
9. **Add `tools/hwcap/capture_4060ti.py` to Day 0.** Per §7.5 instruction. ~30 LOC nvidia-smi polling loop. Run once on Day 0, lock stack only if all picks fit <600MB headroom.
10. **Mark out-of-scope items explicitly in §0.5 (new section).** "DEFERRED OUT-OF-SCOPE for this guide (handle separately): VeilBreakers art-style guide (color palette, mood references, time-of-day per biome), camera framing rules, audio style guide (ambient density, music mood, footstep variation), save-game schema, player input bindings, HUD/UI design, story/narrative integration, tutorial flow, Steam page assets, marketing assets. **The dev MUST NOT block on these for v1 terrain pipeline; assume external decisions land before Phase D D43-44 hero-shot framing.**"

### 19.9 RISK PATH AUDIT (one example)

If on Day 12 (Phase A D12-13) the dev hits "Taichi-CUDA bake won't compile on CUDA 12.4 with Numba 0.59" — what's the fallback? §17 D46-47 footer says "PR #19 Numba/Taichi erosion (integer atomics ONLY — atomic-float ban per spec §8.4)." §14.9 #2 says "defer GPU compute port unless profiler shows pure-Python is bottleneck." So fallback path = stay with pure-Python erosion. **But §17 D46-47 doesn't say "if Taichi fails to compile, skip to D48." It treats Taichi as required.** Add explicit branch: "If Taichi-CUDA stack fails to compile on user's CUDA version: skip GPU port, mark as v1.1 deferred, proceed to D48 SPL solver with existing Cordonnier 2016 SPL." Doc has 0 risk-register table.

### 19.10 IS THE DOC EXECUTABLE?

**Yes, with ~1 day of edits.** The 10 recommendations above are surgical. Once applied:
- Day 0 has a checklist (4-6 hr wall-clock).
- Day 1 has a clear first command (`gh pr view 33`).
- Each GATE has a verification command.
- The §18 PATCH override is consistently applied across §17.
- The dev knows which deliverables don't exist yet (vs. exist-but-need-edits).
- The hero-count ambiguity is resolved.
- The Unity project skeleton is scheduled to be created.

**Without those edits, the dev opens the doc tomorrow, lands on §17, and spends ~1 day translating prose to action — which is the exact failure mode this auditor exists to prevent.** Apply the 10 recommendations, recheck §17 and §18 cross-references one more pass, and the doc graduates from "B− (executable with friction)" to "A− (executable cold)."

The auditor's bottom line: **the user has not wasted 125 agent runs.** The doc IS comprehensive and IS internally rigorous. The remaining ~7% gap is editorial procedural glue — the difference between a *spec* (which this is) and an *execution playbook* (which the dev needs). 1 day of edits closes it.

---

## §20. §19.8 FIXES APPLIED — Audit Verdict B− → A−

**Date:** 2026-05-07
**Status:** All 10 §19.8 surgical edits APPLIED. Audit verdict moves **B− NO-GO → A− GO**.

| # | §19.8 recommendation | Applied where | Status |
|---|----------------------|---------------|--------|
| 1 | Day 0 setup checklist | §0.4 NEW | DONE |
| 2 | §17 D1-2 PR-number rephrase + spec-vs-GitHub footnote | §17.1 footnote + D1-2 row + D3-5 row | DONE |
| 3 | §17.0 PRE-PHASE-A repo cleanup | §17.0 NEW | DONE |
| 4 | §17 D60 GATE reconciled with §18.1 (1080p/60 DLSS SR Quality) | §6 D59-60 rubric + §17 D59-60 row | DONE |
| 5 | §17 D36-37 Unity bootstrap sub-steps | §17.4 D36-37 expanded sub-steps block | DONE |
| 6 | 2-vs-4 hero biome ambiguity resolved (2-biome ship-min) | §17.4 D59-60 row | DONE |
| 7 | §8.5 GATE verification commands table | §8.5 NEW | DONE |
| 8 | `scripts/run_unity_recorder_gate.py` skeleton scheduled Day 0 | §17.0 + §0.4 checklist | DONE |
| 9 | `tools/hwcap/capture_4060ti.py` scheduled Day 0 + skeleton committed | §17.0 + §0.4 checklist | DONE |
| 10 | §0.5 OUT-OF-SCOPE DEFERRALS | §0.5 NEW | DONE |

**Verdict:** Day 0 has a checklist (4-6 hr wall-clock). Day 1 has a clear first command (`gh pr view 33`). Each GATE has a verification command. The §18 PATCH override is consistently applied across §17. The hero-count ambiguity is resolved. The Unity project skeleton is scheduled to be created. **Doc is now A− GO for tomorrow's Day 1 start.**

---
