# AAA Terrain Pipeline — Master Implementation Guide 2026-04-27

**Date:** 2026-04-27
**Supersedes:** `docs/AAA_MASTER_IMPLEMENTATION_GUIDE_2026_04_26.md` (7-wave wiring guide — all waves complete)
**Active plan:** `docs/superpowers/plans/2026-04-26-aaa-terrain-callable-upgrade-guide.md` (12-phase callable upgrade)
**Sources:** 6-agent parallel audit 2026-04-26, deep-dive audit 2026-04-26 (78 tool uses), texturing research, Hunyuan3D-2 research

---

## Domain Grades vs KCD2 / TW3 / RDR2

| Domain | Grade | Gap vs AAA |
|---|---|---|
| Heightmap generation | **A** | None — H=0.85, IQ 3-level domain warp. Genuinely AAA-ready. |
| Roads / paths | **B** | Rich A* exists but legacy fallback is silently triggered on any error; bridge depth is heuristic only |
| Cliffs / strata | **B-** | Carving solid, talus list emitted, but `cliff_mask`/`talus_mask`/`strata_mask` never rasterized to stack |
| Materials | **C+** | Height-blend wired, weight normalization correct, but `TerrainTextureLayerStack` doesn't exist and AO/displacement never emitted |
| Scatter / foliage | **C-** | Two competing scatter paths in `COMMAND_HANDLERS`, `SpeciesSpec` has no LOD/wind/impostor fields, `ScatterPointTable` not called in production |
| Water / hydrology | **D+** | `water_surface` channel has 3 incompatible meanings across files; `water_depth_m` and `water_surface_elevation_m` never emitted |
| Visual QA / render | **F** | `terrain_visual_qa.py` is a camera+screenshot utility with zero channel validation; render positions are hardcoded and mislabel features |
| Foliage assets | **D** | Python L-system cannot reach AAA; vegetation_lsystem.py is still wired and active |
| Legacy build scripts | **D** | 4 scripts bypass `TerrainPassController.run_pipeline` entirely |
| AI asset pipeline | **D** | `RodinBackend` has wrong base URL, wrong endpoints, wrong status casing — non-functional |
| Terrain shape & erosion | **C+** | Erodibility 1000x amplification bug (`_terrain_erosion.py:308`); stratigraphy differential erosion computed but never applied to height; hydraulic erosion is pure Python scalar loop — unusable at AAA tile sizes |

---

## P0 Blockers — Fix Before Any Further AAA Work

### W-1 (CRITICAL): `water_surface` dual-semantics silent bug
**Files:** `_water_network.py:798`, `terrain_audio_zones.py:574`, `procedural_grass.py:349`, `light_integration.py:222`

`water_surface` is used as a **binary mask** (>0.0 = water) in `_water_network.py:798` and `terrain_audio_zones.py:574`, but as **elevation meters** in `procedural_grass.py:349` where `mask *= (height >= ws).astype(np.float32)`. When `water_surface` is fed in as a 0/1 mask, `height >= 1.0` is almost always true — submersion exclusion silently fails.

**Fix:** Rename to `water_surface_mask` (binary 0/1) everywhere. Create separate `water_surface_elevation_m` (float meters) channel. Migrate all 12 call sites.

```python
# _water_network.py — producer side
stack.set("water_surface_mask", (water_raster > 0).astype(np.float32), provenance="hydrology")
stack.set("water_surface_elevation_m", water_elevation_raster, provenance="hydrology")

# procedural_grass.py:349 — consumer side
ws_elev = _stack_attr(stack, "water_surface_elevation_m")
if ws_elev is not None:
    mask *= (height_arr >= ws_elev).astype(np.float32)
```

---

### W-2: No `water_depth_m` / `water_surface_elevation_m` channels emitted
**Files:** No producer exists anywhere. `terrain_path_contracts.PathSegmentContract.water_depth_m` (line 79) takes this value but gets only a heuristic from `road_network._detect_bridges:908`.

**Fix:** Add `pass_water_depth` to the hydrology bundle that computes:
```python
depth = np.maximum(water_surface_elevation_m - height, 0.0)
stack.set("water_depth_m", depth, provenance="hydrology")
```

---

### W-4: `validate_seam_continuity` orphan
**File:** `_water_network.py:2315` — defined, zero production callers.

**Fix:** Wire into `pass_hydrology` after seam writes, or delete the function. Do not leave dead validators.

---

### M-3: `TerrainTextureLayerStack` does not exist
**Status:** Referenced in plans (`docs/superpowers/plans/...:886, 911`) and `terrain_quixel_ingest.apply_quixel_to_layer:411` writes directly into `stack.macro_color` / `stack.roughness_variation` — bypassing the abstraction that doesn't exist yet.

**Fix:** Create `TerrainTextureLayerStack` in `veilbreakers_terrain/handlers/terrain_texture_layer_stack.py`. See implementation spec in Phase 9D of the 12-phase plan. Each layer must carry: `layer_id`, `terrain_mask_source`, `weight_map`, `albedo`, `normal`, `roughness`, `height_displacement` (or explicit reason for absence), `ambient_occlusion`, `metallic`, `color_space_meta`, `tiling_scale`, `texel_density_m`.

---

### M-4: No AO or displacement channels emitted
**File:** `terrain_quixel_ingest.apply_quixel_to_layer:518-572` — only handles albedo/roughness/normal. Quixel megascans always ship AO + displacement. These are silently discarded.

**Fix:**
```python
# terrain_quixel_ingest.py — add to apply_quixel_to_layer
if ao_path := asset.get("ambient_occlusion"):
    ao_arr = _load_texture_as_float(ao_path, channels=1)
    layer.ambient_occlusion = ao_arr
if disp_path := asset.get("displacement"):
    disp_arr = _load_texture_as_float(disp_path, channels=1)
    layer.height_displacement = disp_arr
```

---

### C-1: Dual scatter paths both registered in `COMMAND_HANDLERS`
**File:** `veilbreakers_terrain/handlers/__init__.py:1073-1090`

Both `handle_scatter_vegetation` (calls `environment_scatter._scatter_pass` at lines 1015/1036/1053) and `scatter_biome_vegetation` (calls `vegetation_system.compute_vegetation_placement:284`) are exposed as MCP commands. No documented dispatch rule. Two scatter paths, one pipeline.

**Fix:** Pick `_scatter_pass` as canonical (richer, multi-pass, biome-aware). Deprecate `scatter_biome_vegetation` as a `DeprecationWarning` wrapper. Remove from `COMMAND_HANDLERS`. Phase out after Phase 4 of the 12-phase plan.

---

### C-2: `SpeciesSpec` missing LOD/wind/impostor fields
**File:** `terrain_foliage_catalog.SpeciesSpec:119` — has `unity_asset_path` (single string), `lod_viewer_distance_m` (single float). No LOD path list, no `wind_profile`, no impostor reference.

**Fix:**
```python
@dataclass
class SpeciesSpec:
    # ... existing fields ...
    lod_paths: tuple[str, ...] = ()
    wind_profile: str = "none"
    impostor_atlas_path: str = ""
    impostor_uv_strip_count: int = 0
    collision_proxy_path: str = ""
    max_tris_lod0: int = 50_000
```

---

### CL-2: `cliff_mask` / `talus_mask` / `strata_mask` not emitted to stack
**File:** `terrain_cliffs.py:2604-2663`

- `cliff_mask` derived ad-hoc from `cliff_candidate` in three separate files (`terrain_audio_zones.py:678`, `terrain_assets.py:816`, `terrain_caves.py:1073`)
- `talus_mask` lives on `Cliff` dataclass but never rasterized to stack — only `talus_boulder_placements` (a Python list)
- `strata_mask` doesn't exist on stack at all

**Fix:** In `pass_cliffs`, after carving completes:
```python
# Rasterize all cliff talus masks into unified stack channels
cliff_mask_arr = cliff_candidate.copy()
talus_arr = np.zeros_like(cliff_mask_arr)
strata_arr = np.zeros_like(cliff_mask_arr)
for cliff in cliff_objects:
    if cliff.talus_mask is not None:
        talus_arr = np.maximum(talus_arr, cliff.talus_mask)
    if cliff.strata_band_mask is not None:
        strata_arr = np.maximum(strata_arr, cliff.strata_band_mask)
stack.set("cliff_mask", cliff_mask_arr, provenance="cliff_pass")
stack.set("talus_mask", talus_arr, provenance="cliff_pass")
stack.set("strata_mask", strata_arr, provenance="cliff_pass")
```

---

### V-1: `terrain_visual_qa.py` has no channel validation
**File:** `terrain_visual_qa.py` (365 lines) — `fov_to_focal_length`, `auto_frame_terrain`, `capture_viewport_screenshot`. Zero QA logic.

**Fix:** Add `validate_channel_manifest(stack, spec)` and `compare_render_to_golden(render_path, golden_path, ssim_threshold=0.95)`. See Phase 11 of the 12-phase plan.

---

### V-2: No scenario golden snapshots — only generic seed-hash goldens
**File:** `terrain_golden_snapshots.py:264,276` — snapshots named `golden_{i:04d}_seed{...}`. No scenario fixtures for waterfall-with-plunge-pool, cliff-talus, deep-lake, cave-entrance.

**Fix:** Create `tests/golden_scenarios/` with hand-authored `TerrainIntentState` fixtures:
- `waterfall_plunge_pool.json`
- `cliff_talus_apron.json`
- `deep_lake_basin.json`
- `cave_entrance.json`

Commit hashed expected channel outputs. Gate CI on SSIM delta < 5%.

---

### E-1 (CRITICAL): Erodibility map arithmetic is 1000x wrong — `_terrain_erosion.py:308`
**File:** `_terrain_erosion.py:308`

`_erod_scale = np.clip(erod_arr, 0.0, None) / 1e-3` divides by 0.001, amplifying every erodibility value by 1000x. A cell with erodibility=1.0 (soft rock) produces `_erod_scale=1000`, multiplying `erode_amount` by 1000 at the brush application step. Any caller passing an `erodibility_map` gets terrain carved 1000x deeper than intended, producing a flat plane.

**Fix:**
```python
_erod_scale = np.clip(erod_arr, 0.0, 1.0)
```

---

### E-2 (CRITICAL): Stratigraphy differential erosion is a silent no-op — `terrain_stratigraphy.py:991`
**File:** `terrain_stratigraphy.py:991`

`apply_differential_erosion` returns a negative height delta. `pass_stratigraphy` stores it as a channel but never adds it to `stack.height`. Every mesa profile, overhanging ledge, and hardness-driven cliff form is computed then silently discarded. The stratigraphy system has zero geometric effect on terrain shape.

**Fix:**
```python
h_current = np.asarray(stack.height, dtype=np.float64)
stack.set("height", (h_current + erosion_delta).astype(stack.height.dtype), "stratigraphy")
```

---

### E-3 (CRITICAL): Hydraulic erosion inner loop is pure Python scalar — non-functional at AAA tile sizes — `_terrain_erosion.py:331-477`
**File:** `_terrain_erosion.py:331-477`

The entire droplet simulation iterates particle steps in a Python for loop. At 1024x1024, 8000 particles, 30 steps this is 5-20 minutes of CPU time — incompatible with on-demand terrain generation. The `_NUMBA_AVAILABLE` flag exists in `_terrain_noise.py` but is never applied in `_terrain_erosion.py`. The `_erode_brush` inner loop (lines 648-664) adds another O(radius squared) Python loop called per step.

**Fix priority:** Vectorise the particle batch (all N particles at step t in parallel via NumPy), or add `@numba.njit` path gated on `_NUMBA_AVAILABLE`. Full findings: `docs/aaa-audit/deep_dive_2026_04_27/A3_terrain_shape_erosion.md`.


---

## P1 Required — B-grade minimum

### C-3: `ScatterPointTable` not called in production
**File:** `terrain_scatter_points.py:63,168` — `ScatterPointTable` exists and validates, but `_scatter_pass` returns plain dict placements — never converted. `validate_scatter_point_table:168` never runs in production.

**Fix:** Have `_scatter_pass` emit `ScatterPointTable` and call `validate_scatter_point_table` before persisting results.

### C-4: Impostor atlas never baked
**File:** `vegetation_lsystem.generate_billboard_impostor:1615` — returns spec only. Atlas never rendered. `lod_pipeline.py:1887` imports this as if it works.

**Fix:** Implement actual N-view Blender bake to atlas PNG, or retire the impostor pipeline per the master guide foliage recommendation.

### L-1: 4 legacy build scripts bypass `TerrainPassController`
**Files:**
- `scripts/build_aaa_node_v1.py:16` — explicit note about bypassing heavy wiring
- `scripts/build_aaa_node_v2.py` — no `TerrainPassController` reference
- `scripts/build_scene_v2.py` — no `TerrainPassController` reference
- `scripts/build_scene_v3.py` — no `TerrainPassController` reference (2968 lines, live demo script)

**Fix:** Delete v1, v2, scene_v2. Rewrite scene_v3 to call `TerrainPassController.run_pipeline` end-to-end. This is the single most important structural fix for the entire pipeline.

### L-3: `vegetation_lsystem.py` still active but slated for retirement
**File:** `vegetation_lsystem.py` (2139 lines). Still wired via `_mesh_bridge.py:24`, `lod_pipeline.py:1887`, `environment_scatter.py:58`. Grade: D on impostor/billboard quality.

**Fix:** Implement L-Py replacement first (see Foliage Stack below), then delete `vegetation_lsystem.py` and `_mesh_bridge.dict_to_treespec` adapter at line 221.

### R-2: Road legacy fallback is hidden in production
**File:** `environment.py:6072-6082` — `generate_road_path_grid_legacy` triggered by any `LookupError, ValueError, RuntimeError` from the rich A\* path. Flag `road_routing_method = "legacy_fallback"` set silently.

**Fix:** Make `VEILBREAKERS_ROAD_STRICT=1` the default. Log at WARNING level when fallback activates. Schedule deletion of legacy grid solver after Phase 8 of the 12-phase plan is complete.

---

## Image Labeling Fix — `render_closeups_v3.py`

**Root cause:** All POI positions (`WATERFALL_XY`, `CAVE_ENTRY`, `LAKE_XY`, etc.) are hardcoded. When terrain seed/layout changes, cameras point at wrong features. Shot 5 "05_waterfall_closeup" points at `(-222, 146, 16)` which may be river bank if the waterfall was generated elsewhere.

**Fix (implemented):** `render_closeups_v3.py` now reads `output/scene_v3/generation_manifest.json` for POI positions, falling back to defaults only when the manifest is absent. The manifest is emitted by the terrain pipeline at generation time.

**Required pipeline side:** Add manifest emission to `build_terrain_aaa_node_v4.py` and/or `TerrainPassController.run_pipeline`:

```python
# In terrain_pipeline.py or build_terrain_aaa_node_v4.py — emit at end of run
manifest = {
    "poi": {
        "waterfall": state.waterfall_poi,        # {"x": ..., "y": ..., "z": ...}
        "cave_entry": state.cave_entry_poi,
        "cave_exit": state.cave_exit_poi,
        "lake_center": state.lake_center_poi,
        "lake_radius": state.lake_radius_m,
        "water_level": state.water_level_m,
        "bridge_a": state.bridge_pois[0] if state.bridge_pois else None,
        "bridge_b": state.bridge_pois[1] if len(state.bridge_pois) > 1 else None,
    },
    "seed": state.seed,
    "generated_at": datetime.utcnow().isoformat(),
}
manifest_path.write_text(json.dumps(manifest, indent=2))
```

**Also added:** 4 cardinal overview shots (N/S/E/W) at z=800 plus the existing z=1100 full tile overview — giving 5 broad context shots so no close-up is ever the first image seen.

---

## AI Asset Generation Pipeline — Hunyuan3D-2

**Decision:** Tencent Hunyuan3D-2 (open-source, local) replaces Rodin as primary AI 3D generation backend. Both coexist behind `ExternalAssetProvider` ABC.

### `ExternalAssetProvider` ABC
**New file:** `veilbreakers_terrain/providers/external_asset_provider.py`

```python
class ExternalAssetProvider(abc.ABC):
    provider_id: str

    def submit(self, request: AssetGenerationRequest) -> str: ...
    def poll(self, job_id: str) -> JobStatus: ...
    def download(self, job_id: str, dest_dir: Path, *, species_id: str) -> Path: ...
    def validate(self, glb_path, *, species_id, max_tris, require_pbr) -> AssetJobResult: ...
    def generate_blocking(self, request, dest_dir, ...) -> AssetJobResult: ...
```

All generated assets must pass validation before entering terrain scatter:
- File format is GLB or GLTF
- Mesh scale and axis conventions normalized
- Poly count ≤ `max_tris`
- UVs exist and are non-degenerate (trimesh check)
- PBR channels present: `BASE_COLOR`, `NORMAL`, `ROUGHNESS`; AO optional but flagged if absent
- Collision proxy can be generated (convex hull)
- License/source metadata recorded

### `Hunyuan3D2Provider`
**New file:** `veilbreakers_terrain/providers/hunyuan3d2_provider.py`

- Local-only (no hosted API). Requires running `Hunyuan3D-2/gradio_app.py` or `api_server.py` at `http://127.0.0.1:8080`
- v2.1+ required for full PBR (albedo + normal + roughness + ORM packed)
- Needs 16–24 GB VRAM for shape + texture pipeline
- Shape generation: `POST /generate` → `{"uid": "..."}`
- Status poll: `GET /status/{uid}` → `{"status": "processing"|"completed", "model_base64": "..."}`
- Texture pipeline: separate call or embedded depending on server version
- File: `(implemented)` — see `veilbreakers_terrain/providers/hunyuan3d2_provider.py`

### Broken `RodinBackend` Fix
**File:** `asset_generation.py`

Current bugs:
- `BASE_URL = "https://hyperhuman.deemos.com/api/v2/rodin"` — wrong domain; correct is `https://api.hyper3d.com/api/v2`
- `POST /jobs` — endpoint doesn't exist; correct is `POST /rodin` with multipart/form-data
- `GET /jobs/{id}` — doesn't exist; correct polling is `POST /status` with `{"subscription_key": key}`
- Status casing: code normalizes with `.lower()` then checks `"done"` but API returns `"Done"` (also accepted after lower())
- Download: must call `POST /download` to get pre-signed S3 URLs, then GET without auth header

Note: Rodin requires the Business plan ($96/mo) for API access. For VeilBreakers, Hunyuan3D-2 local is the primary path. Rodin is secondary.

Fix implemented in `asset_generation.py` — see commit.

---

## Texturing Package

### Free Foundation (use now)
- **ambientCG** — CC0 PBR terrain textures via `https://ambientcg.com/api/v2/full_json` (Python-scriptable)
- **Poly Haven** — CC0 HDRI + textures via `https://api.polyhaven.com` (Python-scriptable)

Both provide albedo, normal, roughness, AO, displacement as separate PNG/EXR files. Feed directly into `TerrainTextureLayerStack` via `terrain_quixel_ingest.apply_quixel_to_layer` once M-3/M-4 are fixed.

### Authoring (optional)
- **Adobe Substance 3D Designer** — $250/yr Texturing plan. Student license is NON-COMMERCIAL (do not ship with student license for VeilBreakers commercial release).

### Unity HDRP Integration
**Currently missing from `terrain_unity_export.py`:**
1. Normal map Y-flip: ambientCG/Poly Haven ship OpenGL normals; HDRP Terrain Lit needs DirectX convention. Flip G channel on import.
2. HDRP Mask Map packing: Unity Terrain Lit expects `R=Metallic, G=AO, B=Detail, A=Smoothness`. Currently not packed.

**Fix locations:**
- `terrain_unity_export.py` — add `_pack_hdrp_mask_map(metallic, ao, detail, smoothness)` 
- `terrain_unity_export.py` — add `_flip_normal_y(normal_arr)` for OpenGL→DirectX conversion
- Both must be called in the export bundle before writing PNGs

---

## Foliage Stack

**Retire:** `vegetation_lsystem.py` (Python L-system — cannot reach AAA, atlas never baked)

**Adopt:**
1. **L-Py + PlantGL** — best free headless tree generation for Blender 4.5. Installs in virtualenv, outputs `.blend`/`.fbx` tree meshes.
2. **GoodPie/modular_tree** (fork, v5.5.1 March 2026, GPL-3.0) — active Blender 4.x maintained fork of MaximeHerpin/modular_tree. Bypasses the broken operator registration from the abandoned original. Dark-fantasy tree variants achievable.
3. **Blender Sapling Tree Gen** — built-in, Blender 4.5 compatible. Use for fast block-out and fallback trees only.
4. **The Grove 2.3** (€199 Indie, Blender 4.5 compatible) — physically simulated tree growth. Best-in-class for dark-fantasy hero trees. Not free but strongly recommended for O(5) hero species.

**Pipeline contract:** All foliage sources must register in `terrain_foliage_catalog.py` with full `SpeciesSpec` (after C-2 fix) including LOD paths, wind profile, impostor atlas path. Place only through `ScatterPointTable`.

---

## 12-Phase Plan Status

| Phase | Status | Description |
|---|---|---|
| 0 | ☐ | Lock callable routing + anti-one-shot guardrails |
| 1 | ☐ | Terrain channel contract gate (add `water_surface_elevation_m`, `water_depth_m`) |
| 2 | ☐ | Promote hydrology to first-class output (fix W-1, W-2, W-4) |
| 3 | ☐ | Rebuild waterfalls around hydrology, not local decoration |
| 4 | ☐ | Canonicalize scatter as point data (fix C-1, C-2, C-3) |
| 5 | ☐ | Foliage assets provider-neutral and runtime-grade |
| 6 | ☐ | Material layers consume terrain physics |
| 7 | ☐ | Wire cliffs, strata, talus, weathering (fix CL-2) |
| 8 | ☐ | Route roads through rich road network (fix R-2) |
| 9 | ☐ | Recipe-level Blender and MCP terrain tools |
| 9B | ☑ initial | World Creator-style pointcloud (ScatterPointTable created; production wiring pending C-3) |
| 9C | ☐ | Substance-style PBR material manifests (fix M-3, M-4) |
| 9D | ☐ | TerrainTextureLayerStack contract (fix M-3) |
| 9E | ☐ | AI asset provider interface (ExternalAssetProvider ABC + Hunyuan3D2Provider — NEW) |
| 9F | ☑ initial | Path/road/river/bridge contracts (PathNetworkContract created; road emission pending) |
| 10 | ☐ | Export artifacts (channel manifest, scatter manifest, water manifest, QA render) |
| 11 | ☐ | Visual QA channels (fix V-1, V-2, render_closeups_v3 POI fix) |
| 12 | ☐ | Low-spec profile (reduce resolution, preserve channel set) |

**Next sprint focus (highest leverage):**
1. **Phase 2** — water channel discipline (W-1 is a silent production bug right now)
2. **Phase 11** — visual QA + render fix (immediately visible quality-of-life improvement)
3. **Phase 9E** — AI asset provider (unblocks Hunyuan3D-2 integration)
4. **Phase 4** — scatter canonicalization (C-1 is a dispatch correctness issue)

---

## 3ds Max / Maya Integration Notes

The 12-phase plan includes Maya/Bifrost and XGen research (added research delta at lines 181–196). Key translation:

**Maya Bifrost scatter → our scatter:**
- Density weights must be explicit input fields, not hidden random thresholds → `ScatterPointTable.density` field
- Point outputs must retain sampled geometry location → `ScatterPointTable` retains height, slope, biome, wetness context per point
- USD-style export manifests → `terrain_unity_export.py` exports prototype/instance/transform/material bindings separately

**XGen foliage → our foliage:**
- Species descriptions/collections by role → `SpeciesSpec` with biome constraints after C-2 fix
- Surface-bound primitive generation → `_scatter_pass` per-biome placement chains

**3ds Max Forest Pack:**
- Forest Pack Lite: capped at 3 species/4 areas, no CSV import, Reference Mode is Pro-only. Not suitable for this Blender-primary pipeline.
- The correct path for 3ds Max output is: generate `ScatterPointTable` → export as World Creator-style `InstanceInfo.json` → Forest Pack Pro reads CSV instance data (Pro license required) or use plain 3ds Max Scatter from the same CSV.

**Maya MtoA / Arnold render path:**
- Export from `terrain_unity_export.py` as USD → import into Maya with USD plugin → scatter instances render natively in Arnold via instance prototypes.
- No dedicated Maya handler needed; USD export covers it.

---

## Honest Assessment

The pipeline architecture is sound. The AAA gap is not a research problem:

1. **PBR incompleteness** — 3 channels emitted (albedo/normal/roughness), 3 missing (AO/displacement/metallic)
2. **Water channel discipline** — `water_surface` has three meanings and will silently corrupt grass exclusion
3. **Raster channel emission** — cliff/talus/strata masks computed but not put on the stack
4. **Visual QA depth** — camera utility masquerading as QA
5. **Build script isolation** — 4 scripts bypass the entire pipeline, making the canonical path untestable

Fix those five categories and the terrain hits B+ across all domains. The foliage and AI asset integration are D-tier because they depend on external tools (L-Py, Hunyuan3D-2 local GPU server) more than on pipeline correctness.

**A3 addendum (2026-04-27 deep-dive):** Terrain shape & erosion audit found 3 P0 + 7 P1 gaps. The hydraulic erosion erodibility arithmetic bug (E-1) and stratigraphy no-op (E-2) mean the two most visually impactful erosion subsystems produce silently wrong output on every run. Fix E-1, E-2, E-3 first — they block the entire erosion/stratigraphy/strata-form pipeline. After those, address P1-1 (no 3-pass erosion structure), P1-5 (saltation blend vs. physical transport), and P1-7 (white-noise vs. coherent ridge jaggedness). Full findings: `docs/aaa-audit/deep_dive_2026_04_27/A3_terrain_shape_erosion.md`.
