# I2 — Scatter, Vegetation, and LOD Wiring Audit

**Date:** 2026-04-27
**Scope:** End-to-end trace of tree scatter, rock/prop scatter, grass, vegetation density, and far-terrain LOD pipelines from intent → pass → channel → export.
**Working tree:** `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain` (branch `main`)
**Method:** static read of `veilbreakers_terrain/handlers/__init__.py` (COMMAND_HANDLERS), `terrain_master_registrar.py` (bundle order), every `register_pass(...)` callsite, every `pass_*` function, and every `stack.set(<channel>, ...)` for the relevant channels.

> **TL;DR — five P0 wiring gaps, one P1 export gap, one P2 dead-code module:**
>
> 1. **P0 — `procedural_grass.py` is a 770-line orphan.** No pass, no handler, no importer in production. Confirms D1 finding.
> 2. **P0 — `vegetation_system.py` (handlers/) is a 1700-line orphan.** Defines `compute_vegetation_placement`, `build_biome_density_map`, `scatter_biome_vegetation`, `build_foliage_placement_manifest` etc., but is not registered as a pass and is not imported by any production handler. Only test code touches it. The C-1 deprecation note left this module dead instead of removing it.
> 3. **P0 — `pass_emergent_grass` runs but its output `grass_density_map` is never exported to Unity.** `terrain_unity_export._write_raw_array` channel list (lines 1265-1279) does not include `grass_density_map`. Channel is in the `TerrainMaskStack` schema and `EXPORT_CHANNEL_NAMES` (`terrain_semantics.py:616`), but no production exporter writes it.
> 4. **P0 — `horizon_elevation_angles` is computed by `pass_horizon_lod` but never serialised.** Same exporter omission as item 3 (`terrain_semantics.py:621` lists it among "Unity-ready" channels but no export sink exists).
> 5. **P0 — `pass_horizon_lod` upsamples its 16x16 silhouette back to full resolution before writing `lod_bias`.** Defeats the entire purpose of horizon LOD and produces visible block boundaries (already noted as BUG-100 in `docs/TERRAIN_UPGRADE_MASTER_AUDIT.md:1504`; still active).
> 6. **P1 — There is no production "tree mesh emit" path.** `tree_instance_points` is written by `pass_scatter_intelligent` and serialised to `tree_instances.json`, but nothing in the pipeline turns those points into actual placed assets — Unity-side only.
> 7. **P2 — Stale Bundle E placement dict** (`state._bundle_e_placements`) is written but never read by another pass.

---

## 1. Tree scatter wiring

### 1.1 Production path (the only path that actually runs)

| Layer | Module | Symbol | Status |
|------|--------|--------|--------|
| Intent | — | — | Trees not in intent schema; driven entirely from stack channels. |
| Pass | `terrain_assets.py` | `pass_scatter_intelligent` (line 790) | **REGISTERED** as `scatter_intelligent` via `register_bundle_e_passes` → bundled in `terrain_master_registrar` line 224. |
| Channels in | `height` (required), `slope` (required), `cliff_candidate` / `cave_candidate` / `waterfall_lip_candidate` (optional via `stack.get`) | — | Intentional soft-optional pattern. |
| Channels out | `tree_instance_points` (N×5), `detail_density` (dict[str → H×W]) | — | Both written; `populated_by_pass` updated. |
| Export | `terrain_unity_export._tree_instances_json` (line 1868) | `tree_instances.json` | Written. Tree prototype list also synthesised at line 1467. |

**Wiring verdict:** the canonical tree-scatter pass is fully wired. `tree_instance_points` survives to JSON.

### 1.2 Channels NOT consumed by `pass_scatter_intelligent`

`scatter_intelligent` does **not** read:
- `biome_id` — intent-driven biome density is bypassed; rules in `build_asset_context_rules()` are global, not biome-conditional.
- `wetness` (despite the docstring claim "reads height + slope + wetness")
- `splatmap_weights_layer` — texturing decisions don't influence scatter.
- `grass_density_map` (it's downstream of scatter anyway).
- `vegetation_density` (no such channel exists in production — see §3).

Consequence: tree placement is **not biome-aware**, despite the existence of `build_biome_density_map` in `vegetation_system.py` and biome-keyed rules in `terrain_foliage_catalog.py`. The two systems are completely disconnected.

### 1.3 Disconnected secondary tree path

`environment_scatter.handle_scatter_vegetation` (line 3066) is the legacy *Blender-side* command handler (registered in `__init__.py:1090` as `scatter_vegetation`). It:

- Reads heights from a Blender mesh, runs its own `compute_slope_map`, applies `_DEFAULT_VEG_RULES`, and creates Blender empties.
- Does **not** touch `stack.tree_instance_points` and is **not** part of the `TerrainPassController` pipeline.
- Is the path Blender artists invoke interactively; it is also the path tested by `test_environment_scatter_handlers.py`.

There are therefore **two separate tree-placement systems** that share no rules and no output channel. The `scatter_intelligent` pass writes to `tree_instance_points` for Unity export; `handle_scatter_vegetation` mutates Blender scene state for preview. Both call themselves "vegetation scatter."

---

## 2. Rock / prop scatter wiring

### 2.1 Production path
`pass_scatter_intelligent` also handles rocks via post-processing:
- `cliff_boulder` clusters via `cluster_rocks_for_cliffs` (when `cliff_candidate` present).
- `waterfall_rock` via `cluster_rocks_for_waterfalls` (when `waterfall_lip_candidate` present).
- `cave_rubble` via `scatter_debris_for_caves` (when `cave_candidate` present).

All three are folded into the same `placements` dict and emitted as additional rows of `tree_instance_points` (column 4 = prototype id). They are exported through the same `tree_instances.json` channel — which means in Unity terms they will end up on `TerrainData.treePrototypes` (not `detailPrototypes`), an incorrect category that will need a downstream remap.

**P2 misclassification:** rocks placed in `tree_instance_points` instead of a `prop_instance_points` channel. Unity will treat them as billboarded trees with bend factors applied.

### 2.2 `handle_scatter_props` (`environment_scatter.py:3520`)
Registered in `__init__.py:1097` as `scatter_props`. Same orphan-from-pipeline pattern as `handle_scatter_vegetation` — Blender-side only, never feeds back into the stack.

---

## 3. Grass wiring

### 3.1 `procedural_grass.py` — confirmed unwired (D1 finding reaffirmed)

```
File:    veilbreakers_terrain/handlers/procedural_grass.py  (770 lines)
Class:   ProceduralGrassSystem (vectorised, mature implementation)
Helpers: GrassSpecies, GrassPlacementRecord, _distance_transform_edt
Imports of this module across the codebase:
  - veilbreakers_terrain/tests/test_procedural_grass.py   (test only)
  - (zero production imports)
Pass registration:
  - none. No PassDefinition, no register_pass(...) call.
COMMAND_HANDLERS entry:
  - none.
```

This module reads `slope`, `drainage`, `biome_id`, `road_sdf_dist`, `cliff_label`, `water_surface`, `water_surface_elevation_m`, `hero_exclusion`, `poi_mask` — exactly the channels the rest of the pipeline produces. It is plumbed to consume the stack but never invoked. **The grass-blade scatterer that the project paid 770 lines to build is silently absent from every shipped tile.**

### 3.2 `pass_emergent_grass` — registered but output dropped on the floor

Located in `terrain_vegetation_depth.py:1760`. Registered via `register_emergent_grass_pass` → `register_bundle_o_passes` → `terrain_master_registrar`. Reads `splatmap_weights_layer`, multiplies the ground-layer weight by `GRASS_DENSITY_SCALE`, and writes `stack.grass_density_map`.

**Bundle order check:** `B-materials` (writes `splatmap_weights_layer`, registrar line 223) executes before `O` (registrar line 233), so the input is populated. Pass should produce real data on shipped tiles.

**The output is never serialised.** `terrain_unity_export.py:1265-1279` enumerates the channels written to per-tile `*.bin` files; `grass_density_map` is **not in that list**. It is included in `EXPORT_CHANNEL_NAMES` (`terrain_semantics.py:616`) — the schema acknowledges it as an export channel — but no exporter consumes it. Net result for the Unity importer: there is no grass density texture to drive `Terrain.SetDetailLayer`, so grass meadows will be empty in-engine.

### 3.3 `vegetation_system.build_biome_density_map`

Writes a *per-biome* density mask to `stack.detail_density` (a dict channel). `pass_scatter_intelligent` overwrites `stack.detail_density` from its own `_build_detail_density(...)` (terrain_assets.py:849) using a `dict.update(...)` merge, so any pre-existing biome density would be preserved. **But `build_biome_density_map` is never called in production.** It's reachable only via `vegetation_system.scatter_biome_vegetation`, a function that the `__init__.py:1105` comment explicitly marks as deprecated and unregistered.

### 3.4 Net grass status

| Subsystem | State |
|-----------|-------|
| Geo-Nodes / blade-mesh grass (`procedural_grass.py`) | unwired |
| Density-map grass for Unity DetailLayer (`pass_emergent_grass` → `grass_density_map`) | computed but **not exported** |
| Biome-conditioned scatter density (`vegetation_system.build_biome_density_map`) | unwired |

There is **no grass at all** in the production export.

---

## 4. LOD pipeline wiring

### 4.1 `pass_horizon_lod` — registered, partially broken

```
File:        terrain_horizon_lod.py
Pass name:   horizon_lod
Registered:  via register_bundle_l_horizon_lod_pass → register_bundle_l_passes
             → terrain_master_registrar line 231 (Bundle L)
Inputs:      height
Outputs:     lod_bias (FULL-RES, NN-upsampled from 16×16), horizon_elevation_angles (360,)
```

**Active bug (BUG-100, also flagged in `docs/TERRAIN_UPGRADE_MASTER_AUDIT.md:1504`):**

`compute_horizon_lod` produces a small `(out_res, out_res)` silhouette grid (typically `(16,16)` because `out_res = src_min // 64`). `pass_horizon_lod` then upsamples this grid back to the full source resolution with biased integer NN (`terrain_horizon_lod.py:270-272`) and writes that as `stack.lod_bias`. Two consequences:

1. **Same memory cost as the source heightmap.** The whole point of horizon LOD is a tiny silhouette texture; storing it at full res defeats the budget.
2. **Visible block boundaries.** Nearest-neighbour upsample produces 64×64-pixel rectangles in `lod_bias`. Any post-process that lerps using this channel (e.g. terrain LOD bias material function) gets aliasing.

Recommended fix: write the small (16×16) silhouette to a dedicated `horizon_silhouette` channel and let consumers sample it; only generate a full-res `lod_bias` if a downstream pass actually requires per-cell LOD weighting (none currently does — see §4.4).

### 4.2 `horizon_elevation_angles` — computed but not exported

`pass_horizon_lod` calls `build_horizon_skybox_mask` and writes `stack.horizon_elevation_angles` (a `(360,)` float32 array). `terrain_semantics.py:621` lists it as an export channel. `terrain_unity_export.py` **does not** include it in any write path — confirmed by absolute grep. The horizon profile is therefore generated every tile, lives in memory, and is discarded at serialisation.

### 4.3 `lod_bias` — exported

`terrain_unity_export.py:1277` lists `lod_bias` in the channel-write loop. Survives to disk. (It's the broken upsampled version, but it does ship.)

### 4.4 Mesh LOD — separate from horizon LOD, also wired

`lod_pipeline.py` (2039 lines) is **mesh** LOD (Quadric-Error-Metric edge collapse for tree/rock proxies), distinct from the horizon LOD discussed above (which is silhouette compression for far terrain). Wiring:

- `lod_pipeline.handle_generate_lods` is registered in `__init__.py:1117` as `terrain_generate_lods` — a Blender command handler, **not a pipeline pass**.
- `environment_scatter.py:81` imports `generate_lod_chain` (used only inside the deprecated `handle_scatter_vegetation` Blender path).
- Tests cover it (`test_lod_material_live_readiness.py`).
- No pass-level integration: nothing in the `TerrainPassController` graph builds tree/rock mesh LODs as part of tile generation. LOD is currently a Blender-only operation invoked manually on the artist side.

This is the inverse of the grass problem: mesh LOD is wired to the *handler* surface (Blender-side) but not to the *pass* surface (tile generation), so a headless export job doesn't produce LOD meshes for the trees it scatters.

---

## 5. Density map → scatter flow

There is **no `pass_vegetation_density` pass** that derives a density field from `biome_id`. The closest thing is `build_biome_density_map` in the orphan `vegetation_system.py`. The `scatter_intelligent` pass uses zone-based `place_assets_by_zone` keyed off slope/height/wetness viability functions, with no biome conditioning.

`pass_vegetation_depth` (`terrain_vegetation_depth.py:1526`) writes the `detail_density` dict (canopy/understory/shrub/ground_cover layers), but its produces channel is `detail_density` only — same channel `scatter_intelligent` overwrites. Audit `terrain_vegetation_depth.py:1701` to confirm registration order doesn't trip a duplicate-registration warning when both passes target the same dict channel.

**Wiring gap:** the system has three modules that all want to write `detail_density` (`vegetation_depth`, `scatter_intelligent`, `vegetation_system.build_biome_density_map`), and the actual production write order is `vegetation_depth` first, then `scatter_intelligent` overwrites it. The dict-merge in `scatter_intelligent` (`existing_detail = dict(stack.detail_density or {}); existing_detail.update(detail)`) preserves layers `vegetation_depth` set, but only if their keys don't collide with the scatter detail layers. There is no contract enforcing that.

---

## 6. The `vegetation_system` directory

**Does not exist as a directory.** What exists is `veilbreakers_terrain/handlers/vegetation_system.py` (single file, 1758 lines). Top-level functions:

```
compute_vegetation_placement        — computes per-cell vegetation viability
compute_wind_vertex_colors          — vertex-color animation hint
get_seasonal_variant                — biome→season→variant lookup
build_vegetation_placement_spec     — assembles a placement contract
build_biome_density_map             — writes stack.detail_density per biome
scatter_biome_vegetation            — DEPRECATED (handlers/__init__.py:1105)
load_mesh_library                   — load .fbx library metadata
build_foliage_placement_manifest    — Unity-ready manifest
write_foliage_placement_manifest    — JSON serialiser
```

Production references:
- `_setup_billboard_lod` is imported back from `lod_pipeline.py:1358`. (One internal callback.)
- `__init__.py:1105` explicitly states the dispatcher entry was removed.
- **Zero other production handlers import `vegetation_system`.**
- Tests reference it: `test_callable_evidence_bridge_vegetation.py`.

So `vegetation_system.py` is functionally a 1700-line dead module, kept alive only because:
1. `lod_pipeline._setup_billboard_lod` happens to live here (could be relocated in a single edit).
2. Tests cover it.

It contains the *only* implementation of biome-conditioned density-map building (`build_biome_density_map`). The density map is exactly what `pass_emergent_grass` should be reading instead of the splatmap ground-weight channel.

---

## 7. Master gap summary

| ID | Severity | Module | Symptom | Fix sketch |
|----|----------|--------|---------|------------|
| I2-01 | **P0** | `procedural_grass.py` | 770-line vectorised grass scatterer never registered. | Wrap `ProceduralGrassSystem.run()` in a `pass_procedural_grass` PassDefinition, requires `slope`, `biome_id`, `splatmap_weights_layer`; produces `grass_instance_points`. Register in Bundle E or a new Bundle. |
| I2-02 | **P0** | `vegetation_system.py` | 1700-line module not imported by production. Contains the only biome-density logic. | Either (a) wrap `build_biome_density_map` as `pass_biome_density` that runs before `scatter_intelligent` and `emergent_grass`, or (b) inline its logic into `pass_vegetation_depth` and delete the rest. |
| I2-03 | **P0** | `terrain_unity_export.py:1265` | `grass_density_map` produced by `pass_emergent_grass` is never serialised. | Add `"grass_density_map"` to the channel-write tuple at line 1265-1279. |
| I2-04 | **P0** | `terrain_unity_export.py` | `horizon_elevation_angles` produced by `pass_horizon_lod` is never serialised. | Same channel-write site; add a 360-element 1D dump (or a 1×360 2D dump) for the angle array. |
| I2-05 | **P0** | `terrain_horizon_lod.py:268-279` | `pass_horizon_lod` upsamples its 16×16 silhouette to full resolution before writing `lod_bias`. Defeats LOD savings, produces NN-upsample blocks. | Write the 16×16 grid to a `horizon_silhouette` channel; only build `lod_bias` if a downstream consumer is added (none currently exists). |
| I2-06 | **P1** | `terrain_assets.py:846` | Rocks/boulders/debris emitted into `tree_instance_points` (will become Unity treePrototypes). | Split into `tree_instance_points` and `prop_instance_points`; update Unity export to write a separate detailPrototypes-style file for the latter. |
| I2-07 | **P1** | `lod_pipeline.py` | Mesh LOD chain is a Blender command handler, not a pipeline pass — headless tile exports get no tree/rock LODs. | Promote LOD generation to a post-scatter pass that consumes `tree_instance_points` and writes per-prototype LOD assets to disk. |
| I2-08 | **P2** | `terrain_assets.py:855` | `state._bundle_e_placements` set but never read. | Either remove the `setattr` or document a downstream consumer. |
| I2-09 | **P2** | scatter dual-write | `pass_vegetation_depth` and `pass_scatter_intelligent` both write `stack.detail_density` (dict). Implicit merge contract. | Add a `produces_dict_keys` field to `PassDefinition` and validate non-collision. |
| I2-10 | **P2** | `environment_scatter.py:3066` | `handle_scatter_vegetation` (Blender) and `pass_scatter_intelligent` (pipeline) implement two unrelated tree-placement systems with different rules. | Either retire the Blender handler or have it read `stack.tree_instance_points` instead of recomputing scatter. |

---

## 8. Channel-population matrix (production)

| Channel | Producer pass | Producer is registered? | Channel reaches Unity export? |
|---------|---------------|-------------------------|-------------------------------|
| `tree_instance_points` | `scatter_intelligent` | ✅ | ✅ (`tree_instances.json`) |
| `detail_density` (dict) | `vegetation_depth` + `scatter_intelligent` | ✅ | ❌ (no exporter writes the dict) |
| `grass_density_map` | `emergent_grass` | ✅ | ❌ (omitted from `_write_raw_array` loop) |
| `horizon_elevation_angles` | `horizon_lod` | ✅ | ❌ (omitted from exporter) |
| `lod_bias` | `horizon_lod` | ✅ | ✅ (but broken — see I2-05) |
| `biome_id` | (`terrain_macro_color` / Bundle K) | ✅ | ✅ |
| `splatmap_weights_layer` | `materials_v2` | ✅ | ✅ |
| (no channel) | `procedural_grass.ProceduralGrassSystem` | **❌** | n/a |
| (no channel) | `vegetation_system.build_biome_density_map` | **❌** | n/a |

---

## 9. Quick-win fix order (minimum work, maximum surface impact)

1. **Add 2 strings to the export channel tuple** (`terrain_unity_export.py:1265`): `"grass_density_map"`, `"horizon_elevation_angles"`. Closes I2-03 + I2-04 in 30 seconds.
2. **Stop upsampling in `pass_horizon_lod`**: write the 16×16 grid to a new `horizon_silhouette` channel and drop the NN-upsample. Closes I2-05.
3. **Wrap `ProceduralGrassSystem` as `pass_procedural_grass`** with biome+splatmap inputs and a new `grass_instance_points` channel. Closes I2-01.
4. **Promote `build_biome_density_map` to a real pass** between materials and scatter, so `scatter_intelligent` can multiply its viability map by biome density. Closes I2-02 + makes I2-01 biome-aware.
5. **Split rocks out of `tree_instance_points`.** Closes I2-06.

After steps 1-5 the grass and horizon-LOD pipelines actually ship to disk, and tree scatter becomes biome-aware for the first time.

---

## 10. Files referenced

Absolute paths for follow-up edits:

- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\__init__.py` (handler registry, line 1086+)
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_master_registrar.py` (bundle order, line 213-234)
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_assets.py` (scatter pass + registration, lines 790-927)
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_horizon_lod.py` (entire file; bug at lines 268-279)
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_vegetation_depth.py` (emergent_grass at lines 1760-1810)
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_bundle_o.py` (Bundle O registrar)
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_unity_export.py` (channel-write loop at lines 1265-1290; missing exports)
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\procedural_grass.py` (orphan, 770 lines)
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\vegetation_system.py` (orphan, 1758 lines)
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\environment_scatter.py` (Blender-side scatter handlers, parallel system)
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\lod_pipeline.py` (mesh LOD; only handler-wired, not pass-wired)
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_semantics.py` (channel schema; lines 409-413, 614-621)
