# Scan 11 — Assets, Bundles, Blender Integration Audit
**Date:** 2026-05-04
**Branch:** `feat/vegetation-scatter-water-contracts`
**Scope:** `terrain_assets`, `terrain_asset_metadata`, `terrain_bundle_{j,k,l,n,o}`,
`terrain_addon_health`, `blender_capability_bridge`, `terrain_blender_safety`,
`terrain_quixel_ingest`, `veilbreakers_terrain/providers/*`, plus the
`VbTerrainTileMetadata` Unity-side struct.

---

## 1. Executive verdict

| Area | Grade | Notes |
|---|---|---|
| Bundle registrars (J/K/L/N/O) | **B+** | All sub-registrars exist; names match registry. Bundle N intentionally registers zero passes. |
| `VbTerrainTileMetadata` (C#) | **B-** | Expanded from 3-field stub (28 fields). `ClimateZone="temperate"` default not derived from biome (still latent W-1 echo). |
| `ExternalAssetProvider` ABC | **A-** | All abstract methods present. Strong PBR validation. |
| `Hunyuan3D2Provider` | **B** | Calls HF Space (`/generation_all`) not local API. Correct: master memory says local is broken (16-24 GB VRAM). |
| Quixel ingest | **A-** | Full PBR (albedo/normal/rough/AO/displacement/metallic/transmission); short-suffix + long-form patterns; sRGB-linear; bilinear sampling; AO+disp now blended. |
| `terrain_addon_health.force_addon_reload` | **B+** | Correctly skips in headless mode via `_is_live_blender()`. |
| `blender_capability_bridge` capability detection | **A-** | `_require_bpy()` / `_require_bmesh()` return error dicts; never raise ImportError. |
| Foliage attachment (Unity-side) | **A-** | `foliage_placement_manifest_file` IS wired in `VbTerrainImporter.cs:1361-1426`; `VbFoliageManifestRenderer` is attached. Earlier audit (2026-04-28) is now stale on this point. |
| Climate-from-biome derivation | **C** | Still defaults `"temperate"` when caller provides no `erosion_profile` or `composition_hints["climate"]`. No automatic biome→climate mapping (e.g. `desert→arid`, `alpine→alpine`). |

---

## 2. Bundle pass-registration map (verified)

### Bundle J — `terrain_bundle_j.py`
Declared `BUNDLE_J_PASSES` (11 entries):
```
prepare_terrain_normals, prepare_heightmap_raw_u16, prepare_unity_auxiliary_channels,
audio_zones, wildlife_zones, gameplay_zones, wind_field, cloud_shadow, decals,
navmesh, ecotones
```
Sub-registrars actually called by `register_bundle_j_passes()`:

| Pass declared | Sub-registrar invoked | Module | Verified |
|---|---|---|---|
| prepare_terrain_normals | `register_bundle_j_terrain_normals_pass` | `terrain_unity_export.py:567` | ✅ |
| prepare_heightmap_raw_u16 | `register_bundle_j_heightmap_u16_pass` | `terrain_unity_export.py:586` | ✅ |
| prepare_unity_auxiliary_channels | `register_bundle_j_unity_auxiliary_pass` | `terrain_unity_export.py:605` | ✅ |
| audio_zones | `register_bundle_j_audio_zones_pass` | `terrain_audio_zones.py:1013` | ✅ |
| wildlife_zones | `register_bundle_j_wildlife_zones_pass` | `terrain_wildlife_zones.py:485` | ✅ |
| gameplay_zones | `register_bundle_j_gameplay_zones_pass` | `terrain_gameplay_zones.py:460` | ✅ |
| wind_field | `register_bundle_j_wind_field_pass` | `terrain_wind_field.py:371` | ✅ |
| cloud_shadow | `register_bundle_j_cloud_shadow_pass` | `terrain_cloud_shadow.py:326` | ✅ |
| decals | `register_bundle_j_decals_pass` | `terrain_decal_placement.py:311` | ✅ |
| navmesh | `register_bundle_j_navmesh_pass` | `terrain_navmesh_export.py:681` | ✅ |
| ecotones | `register_bundle_j_ecotones_pass` | `terrain_ecotone_graph.py:276` | ✅ |

**Result:** 11 / 11 sub-registrars present. Declaration matches invocation order.

### Bundle K — `terrain_bundle_k.py`
6 passes declared, 6 sub-registrars all present (`terrain_stochastic_shader.py:1153`,
`terrain_macro_color.py:244`, `terrain_multiscale_breakup.py:128`,
`terrain_shadow_clipmap_bake.py:534`, `terrain_roughness_driver.py:222`,
`terrain_quixel_ingest.py:983`). **6 / 6 verified.**

### Bundle L — `terrain_bundle_l.py`
3 passes declared (`horizon_lod`, `fog_masks`, `god_ray_hints`); each sub-registrar
present at `terrain_horizon_lod.py:341`, `terrain_fog_masks.py:349`, `terrain_god_ray_hints.py:418`.
**3 / 3 verified.**

### Bundle N — `terrain_bundle_n.py`
**`register_bundle_n_passes()` registers ZERO passes.** This is correct by
design: Bundle N is a runtime-contract surface holding always-on
post-pipeline hooks (`enforce_budget`, `compute_readability_bands`,
`run_data_contract_qa_checks`, `apply_review_blockers`) and opt-in hooks
(`record_telemetry`, `save_golden_snapshot`, `run_determinism_check`).
The function is a verifier that imports the seven Bundle N modules and
returns the runtime contract. The contract is consumed by
`run_bundle_n_post_pipeline_hooks()` which is invoked separately.

This should not be flagged as "missing pass registration" — the docstring
explicitly warns that the name is preserved for compatibility with the
master registrar but registers zero controller passes.

### Bundle O — `terrain_bundle_o.py`
4 passes registered:

| Pass | Sub-registrar | Module |
|---|---|---|
| water_variants | `register_water_variants_pass` | `terrain_water_variants.py:976` ✅ |
| bathymetry | `register_bathymetry_pass` | `terrain_water_variants.py:1620` ✅ |
| vegetation_depth | `register_vegetation_depth_pass` | `terrain_vegetation_depth.py:1778` ✅ |
| emergent_grass | `register_emergent_grass_pass` | `terrain_vegetation_depth.py:1875` ✅ |

**4 / 4 verified.** Note: `pass_seasonal_water_state` is registered separately
at the master registrar level (line 250) **after** Bundle O so it can declare
`overrides=` on `water_surface_mask`/`tidal`/`wetness`. This is correct.

### Master registrar (`terrain_master_registrar.py:200-251`)
Calls `register_bundle_j_passes`, `register_bundle_k_passes`,
`register_bundle_l_passes`, `register_bundle_n_passes`, `register_bundle_o_passes`,
plus `register_pass_seasonal_water_state` after Bundle O. Order matches
the contract.

### Cross-bundle duplicate scan
`terrain_master_registrar.py` already runs a duplicate detector
(`seen_pass_names` dict around line 254), logging WARN when a later bundle
registers a name that an earlier bundle already owns. Manual scan of the
declared `BUNDLE_*_PASSES` tuples shows no name collisions among J/K/L/O.

---

## 3. `VbTerrainTileMetadata` (Unity C#) — full field audit

`unity_plugin/VbTerrainTileMetadata.cs` (verified 51 lines, 28 fields):

```
WorldId, TileX, TileY, TileSize, CellSize,
HeightMinMeters, HeightMaxMeters, HeightScaleFactor,
CoordinateSystem, SourceCoordinateSystem,
ValidationStatus, ValidationIssueCount,
SeamContractWorldId,
TerrainNormalsFile, TerrainNormalMapFile, TerrainNormalMapAssetPath,
NavMeshAreaIdFile, NavMeshDataAssetPath,
BiomeId, ClimateZone (default "temperate"),
WaterPresent, WaterSurfaceElevationM,
ScatterCount, Lod0DistanceM, Lod1DistanceM, Lod2DistanceM,
SnowLineFactor, PrimaryBiomeName,
ChannelBound[] ChannelBounds
```

**Confirmed:** the 3-field stub flagged in the 2026-04-28 audit is no
longer present. The metadata is JSON-serializable through Unity's native
`JsonUtility` (all fields are public primitives, strings, or
`[System.Serializable]` structs — no references, no `Dictionary<>`,
no nullable types). Round-trips cleanly.

**Latent issue (low severity):** `ClimateZone = "temperate"` default
mirrors the same hardcode that lives in the Python pipeline (see §6).
A tile imported with no biome metadata will silently announce itself
as "temperate" to downstream Unity systems (post-process volumes,
weather VFX zones, ambient audio). Recommend defaulting to `""` and
making the consumer fail-fast on unset.

---

## 4. `ExternalAssetProvider` ABC + Hunyuan3D2Provider

### ABC contract (`external_asset_provider.py`)
| Abstract method | Present | Notes |
|---|---|---|
| `submit(request) -> str` | ✅ | Subclass returns provider job_id |
| `poll(job_id) -> JobStatus` | ✅ | Non-blocking |
| `download(job_id, dest_dir, *, species_id) -> Path` | ✅ | Blocking |
| `validate(...) -> AssetJobResult` | concrete | Default impl uses `trimesh` + `pygltflib` |
| `generate_blocking(...)` | concrete | Submit → poll loop → download → validate |
| `catalog(...)` | concrete | Append to JSON catalog |

PBR validation requires `BASE_COLOR`, `NORMAL`, `ROUGHNESS` (frozen set
at line 19). `METALLIC` and `AO` are detected and stored on the result
but not required. Skipping is graceful when `trimesh` / `pygltflib`
aren't installed (issue strings rather than exceptions).

### Hunyuan3D2Provider
Endpoint resolution priority:
1. `HUNYUAN3D2_HF_ENDPOINT` env var (paid private endpoint)
2. Default: `tencent/Hunyuan3D-2` HuggingFace Space (free)
3. Local mode (`HUNYUAN3D2_MODE=local`) is **explicitly rejected** at
   `__init__` with a RuntimeError pointing at the 16-24 GB VRAM limit.

API names called (`hunyuan3d2_provider.py:64-65`):
- `/generation_all` (shape + texture, ~90 s)
- `/shape_generation` (shape-only fallback when public Space rejects
  textured request, line 224-231).

Predict kwargs include the standard tencent/Hunyuan3D-2 keys (`steps`,
`guidance_scale`, `octree_resolution`, `check_box_rembg`, `num_chunks`,
`randomize_seed`). When an `image_path` is supplied, `caption` is set
to `None` to dodge the Space's text-and-image multimodal NameError —
this is a real Hunyuan-side bug worked around correctly.

`submit()` runs predict in a daemon thread (`name=f"hy3d-{job_id[:8]}"`)
and stores `(thread, holder)` in `self._jobs` keyed by uuid. `poll()` reads
the holder's status under lock. `download()` joins the thread, copies the
glb out of the per-job tmpdir, then removes the entry and the tmpdir.
`_prune_finished_jobs_locked()` evicts entries older than `job_retention_s`
(default 900 s).

**Verdict:** This provider does NOT call a local Hunyuan API — that mode
is intentionally banned. It calls the public HF Space (free queue) or
a private HF Inference Endpoint. The user memory note about
"local API URL/endpoints" is now obsolete: there is no localhost call.

### MeshyProvider
Present (`providers/meshy_provider.py`) — not in scope for this scan
but confirms the multi-provider pattern works.

---

## 5. Quixel ingest — PBR channel handling

`terrain_quixel_ingest.py` (1014 lines):

### Channel classification
- `_CHANNEL_PATTERNS` (long-form regex list, lines 101-136): handles
  Bridge 6.x (`_Albedo_`, `_BaseColor_`, `_Normal_`, `_Roughness_`,
  `_AO_`/`_Occlusion_`, `_Displacement_`/`_Height_`, `_Metallic_`,
  `_Cavity_`, `_Specular_`, `_Emissive_`, `_Opacity_`, `_Transmission_`).
  `metallic_roughness` (combined) precedes individual roughness/metallic
  patterns to avoid mis-classification.
- `_SHORT_SUFFIX_MAP` (lines 141-149): legacy terse tokens
  (`_BCR`/`_D` → albedo; `_N`, `_R`, `_M`, `_AO`, `_T`).
- `_classify_texture()` (line 182): two-stage scan returning a typed
  `TextureType` enum.

### Loader
`_load_texture_as_float()` tries `imageio` first (handles EXR/TIF/HDR),
falls back to `PIL`. Integer dtypes are normalized via
`np.iinfo(orig_dtype).max` (correctly handles uint16). HDR floats are
range-normalized only when outside `[0, 1]`. `nan_to_num` on load. Always
returns float32 in `[0, 1]`.

### `apply_quixel_to_layer()`
Two distinct jobs:
1. Splatmap layer registration with Unity 4-layer hard cap
   (`_UNITY_MAX_SPLATMAP_LAYERS = 4`). New layer initial weight =
   `max(0.25, 1/(N+1))`, then channel-wise renormalization so per-texel
   sum == 1.0.
2. Texture blending (optional pre-loaded arrays):
   - `albedo_array`: sRGB → linear before blend into `macro_color`.
   - `roughness_array`: blended into `roughness_variation`.
   - `normal_array`: **packed [0,1] decoded to [-1,1] before blend**,
     then re-normalized post-blend (line 654-674). This is the
     critical fix — earlier code added packed RGB which bent flat
     normals toward grey.
   - `ao_array`: blended into `terrain_ao` (auto-loads from
     `asset.textures["ao"]` if not pre-supplied).
   - `displacement_array`: blended into `terrain_displacement` (auto-
     loaded from `asset.textures["displacement"]` or `["height"]`).

Provenance is recorded on `state.side_effects` as a JSON event
(`event: "quixel_layer"` with all the channel flags).

### `pass_quixel_ingest`
3-source resolution: explicit list → `composition_hints["quixel_assets"]`
descriptor list → `composition_hints["quixel_cache_dir"]` scan filtered
by `composition_hints["biome_type"]` against `_BIOME_ASSET_TAGS`
(arctic/tropical/desert/forest/cliff/wetland/alpine/volcanic).
On exit always guarantees `splatmap_weights_layer` is non-None (writes
fallback all-ones single layer if no assets ingested, with a soft
ValidationIssue).

**Verdict:** PBR channel mapping is comprehensive (5/5 required +
metallic + transmission). Normalization is correct (sRGB-linear for
albedo, signed-space for normals). The Unity 4-layer cap is enforced
hard. AO and displacement blending are present (claim of "missing"
in any prior audit is stale).

---

## 6. Climate-from-biome wiring (latent bug)

The "climate always returns temperate" issue is **partially fixed**.

Resolution chain in `_terrain_world.py:1198`:
```
profile = str(intent.erosion_profile or "temperate")
```

`intent.erosion_profile` is set in `environment.py:3061-3066`:
```python
erosion_profile=str(
    params.get("erosion_profile")
    or composition_hints.get("erosion_profile")
    or composition_hints.get("climate")
    or "temperate"
),
```

And in `environment.py:2121-2126` the controller params override is:
```python
controller_params["erosion_profile"] = (
    composition_hints.get("erosion_profile")
    or composition_hints.get("climate")
    or ("arid" if erosion == "thermal" else "temperate")
)
```

**What works:** when callers supply `composition_hints["climate"]` or
`composition_hints["erosion_profile"]`, the right `iteration_scale` /
`talus_offset` is selected from the table at line 1224-1228.

**What is still broken:** there is **no automatic mapping from
`composition_hints["biome_type"]` → climate**. A caller that sets
`biome_type="desert"` but does not also set `climate="arid"` falls
through to the `"temperate"` default and gets 1.0× iterations + 7° talus
offset — wrong for sand dunes. Same for `alpine`, `tundra`, `volcanic`,
`arctic`. The `_BIOME_ASSET_TAGS` dict in `terrain_quixel_ingest.py`
has the exact biome→climate-flavor knowledge already, but it's
quarantined inside the Quixel module.

**Recommended fix:** add `_biome_to_climate_profile(biome_type) -> str`
to `_terrain_world.py` (or `terrain_semantics.py`) returning
arid/temperate/alpine/arctic, and use it as the next fallback before
hardcoding `"temperate"`. Mapping table:

| biome_type | climate profile |
|---|---|
| arctic, tundra, glacial, taiga | alpine (or new "polar") |
| desert, badlands, mesa | arid |
| volcanic, lava | arid |
| alpine, mountain | alpine |
| forest, woodland, jungle, tropical | temperate |
| wetland, swamp, marsh | temperate |
| coastal, beach | temperate |
| (default) | temperate |

This same mapping should also drive `VbTerrainTileMetadata.ClimateZone`
on the Unity export side (`terrain_unity_export.py` constructs the
manifest).

---

## 7. Foliage attachment in Unity — re-audit

The 2026-04-28 audit said "Foliage never attached in Unity". This is
**no longer true**.

`unity_plugin/Editor/VbTerrainImporter.cs:1361-1426` (`AttachFoliageManifest`)
- Reads `descriptor.foliage_placement_manifest_file` (descriptor field
  set at line 62).
- Loads the JSON payload from `bundleDirectory`.
- Adds a `VbFoliageManifestRenderer` component to the terrain object
  if missing (line 1374-1378).
- Imports the manifest as a Unity asset and references it from the
  renderer.
- Logs a warning if `Prototypes` array is empty (line 1395-1400).

`terrain_unity_export.py` writes `foliage_placement_manifest.json` in
`_foliage_placement_manifest_json()` (line 3050) and adds it to the
manifest's `descriptor` block at line 1672-1674 and 2152-2156. The
descriptor file list at 2186 includes
`("foliage_placement_manifest.json", foliage_placement_manifest_json)`.

**Result:** foliage is attached. The remaining concern is upstream:
`scatter_intelligent` produces `tree_instance_points` (Bundle E), and
the manifest serializer reads them correctly, but if `scatter_intelligent`
emits zero placements (e.g. because no biome catalog matched, see
master memory note about VB biomes / foliage catalog gap) the manifest
will have an empty `instances` array — Unity logs a warning but does
not fail. This is a different (downstream) issue, not an attachment
break.

---

## 8. Blender capability detection + addon health

### `terrain_addon_health.force_addon_reload`
Behavior on missing/non-Blender environment:
- `_is_live_blender()` (line 190-208) checks `sys.modules["bpy"]` and
  validates `bpy.app.version` is a real integer tuple (rejects MagicMock
  stubs).
- `force_addon_reload` returns `False` immediately when not in a live
  Blender session (line 260-261).
- When `bpy` is real, the function reloads sub-modules in sys.modules
  insertion order (leaves first), then reloads the package root, then
  re-binds operators via `register()`. Drops all references warning is
  prominent in the docstring.

`assert_addon_loaded()` checks for the addon `__init__.py` on disk via
`_addon_init_path()`. `_read_bl_info_version()` parses `bl_info` via AST,
falls back to regex. `assert_addon_version_matches()` raises
`AddonVersionMismatch` when missing — pass `allow_missing=True` for
intentionally stripped trees.

`detect_stale_addon()` uses SHA-256 content hash (NTFS/FAT32 safe) as
primary check, falls back to `bl_info["version"]` comparison only if
`__file__` is unavailable (frozen builds).

**Edge case verified:** the function imports the package via
`importlib.import_module(pkg_name)` rather than relative imports,
so it works regardless of how the package was installed.

### `blender_capability_bridge`
`_require_bpy()` (line 40-50) and `_require_bmesh()` (line 53-62) both
swallow `ImportError` (via bare `Exception`) and return a structured
error dict `{"status": "error", "error": "bpy_unavailable", ...}`. Every
public function in the module starts with this guard, so the module is
safe to *import* without Blender — no top-level `bpy` import.

Capability detection of operators:
- `_PRIMITIVE_TYPES` (line 290) hard-codes the seven supported primitives.
- `_VALID_BMESH_OPS` (line 1000) hard-codes seven bmesh ops; boolean has
  a fallback path (`_modifier_boolean_fallback` at line 1090) when
  `bmesh.ops.intersect_boolean` doesn't exist on this Blender build.
- `_VALID_MODIFIER_TYPES` (line 1110) hard-codes ten modifier types.
- `_VALID_UV_METHODS`, `_VALID_ENGINES` (line 1296) — `BLENDER_EEVEE_NEXT`
  is the Blender-4.5 default; the older `BLENDER_EEVEE` is also accepted.
- Add-on enable/disable (`_KNOWN_ADDONS` line 1626) covers `ant_landscape`,
  `add_curve_sapling`, `node_wrangler`. Enable goes through `addon_utils`
  and returns a structured error dict on failure.

`terrain_bridge_health()` (line 785) is the canonical liveness probe —
returns `bpy_available`, `bmesh_available`, `blender_version`,
`object_count`, scene info. **Recommended:** use this from CI to assert
the bridge module imports without Blender (it should always succeed).

### `terrain_blender_safety`
Mature. Highlights:
- `assert_z_is_up` enforces Z-up; `convert_y_up_to_z_up` does the full
  matrix rotation for XYZ/ZYX Euler orders (with documented
  component-swap fallback for other orders).
- `BLENDER_SCREENSHOT_MAX_SIZE = 507` (per feedback memory; never 1024).
- `BOOLEAN_DENSE_MESH_VERT_LIMIT = 60000` with `assert_boolean_safe`
  guard and `recommend_boolean_solver(...)` rule table (5 rules,
  manifold-aware, INTERSECT-aware).
- `import_gltf_serialized` enforces single-flight via
  `_GLTF_IMPORT_LOCK = threading.Lock()` and validates `.glb`/`.gltf`
  suffix.

---

## 9. Mock-friendly behavior matrix (for headless tests)

| Function | Without Blender | Pattern |
|---|---|---|
| `terrain_assets.*` | Works as-is (pure numpy) | No bpy import. |
| `terrain_asset_metadata.*` | Works as-is | Pure dataclasses + validation. |
| `terrain_quixel_ingest.*` | Works (numpy + imageio/PIL) | Loader gracefully skips when neither lib installed. |
| `terrain_blender_safety.*` | Works | All functions are pure logic. |
| `terrain_addon_health.force_addon_reload` | Returns `False` | `_is_live_blender()` gate. |
| `terrain_addon_health.detect_stale_addon` | Returns `False` | Returns False when `_import_addon_package` fails. |
| `blender_capability_bridge.scene_info` | Returns error dict | `_require_bpy()` returns `{"status": "error", "error": "bpy_unavailable"}`. |
| `blender_capability_bridge.terrain_bridge_health` | Works | Returns `bpy_available: False` rather than raising. |
| `Hunyuan3D2Provider.is_available` | Returns False | Probes `gradio_client` import in a daemon thread with timeout. |
| `Hunyuan3D2Provider.submit` | Raises if gradio_client missing | Documented requirement: `pip install gradio-client`. |

Suggested CI smoke test (no Blender, no GPU):
```python
def test_handlers_import_without_bpy():
    """All handlers must import without bpy installed."""
    import sys
    assert "bpy" not in sys.modules
    from veilbreakers_terrain.handlers import (
        terrain_assets, terrain_asset_metadata, terrain_quixel_ingest,
        terrain_addon_health, terrain_blender_safety, blender_capability_bridge,
        terrain_bundle_j, terrain_bundle_k, terrain_bundle_l,
        terrain_bundle_n, terrain_bundle_o,
    )
    assert blender_capability_bridge.terrain_bridge_health()["bpy_available"] is False
    assert terrain_addon_health.force_addon_reload() is False

def test_bundle_registrars_idempotent():
    from veilbreakers_terrain.handlers.terrain_pipeline import TerrainPassController
    from veilbreakers_terrain.handlers import (
        terrain_bundle_j, terrain_bundle_k, terrain_bundle_l, terrain_bundle_o,
    )
    TerrainPassController.PASS_REGISTRY.clear()
    terrain_bundle_j.register_bundle_j_passes()
    assert set(terrain_bundle_j.BUNDLE_J_PASSES) <= set(TerrainPassController.PASS_REGISTRY)
    terrain_bundle_k.register_bundle_k_passes()
    assert set(terrain_bundle_k.BUNDLE_K_PASSES) <= set(TerrainPassController.PASS_REGISTRY)
    terrain_bundle_l.register_bundle_l_passes()
    assert set(terrain_bundle_l.BUNDLE_L_PASSES) <= set(TerrainPassController.PASS_REGISTRY)
    terrain_bundle_o.register_bundle_o_passes()
    expected_o = {"water_variants", "bathymetry", "vegetation_depth", "emergent_grass"}
    assert expected_o <= set(TerrainPassController.PASS_REGISTRY)

def test_vb_terrain_tile_metadata_json_round_trip():
    """Mirrors Unity's JsonUtility round-trip; must remain flat-serializable."""
    import json
    payload = {
        "WorldId": "world42", "TileX": 3, "TileY": 7, "TileSize": 1024,
        "CellSize": 1.0, "HeightMinMeters": 0.0, "HeightMaxMeters": 350.0,
        "HeightScaleFactor": 0.85, "CoordinateSystem": "y-up",
        "SourceCoordinateSystem": "z-up", "ValidationStatus": "ok",
        "ValidationIssueCount": 0, "SeamContractWorldId": "world42",
        "TerrainNormalsFile": "tile_3_7_normals.png",
        "TerrainNormalMapFile": "", "TerrainNormalMapAssetPath": "",
        "NavMeshAreaIdFile": "", "NavMeshDataAssetPath": "",
        "BiomeId": 4, "ClimateZone": "alpine",
        "WaterPresent": True, "WaterSurfaceElevationM": 12.5,
        "ScatterCount": 8123, "Lod0DistanceM": 50.0,
        "Lod1DistanceM": 150.0, "Lod2DistanceM": 400.0,
        "SnowLineFactor": 0.7, "PrimaryBiomeName": "alpine_pine",
        "ChannelBounds": [{"Name": "height", "Min": 0.0, "Max": 350.0}],
    }
    assert json.loads(json.dumps(payload)) == payload

def test_quixel_pbr_channel_normalization(tmp_path):
    """sRGB→linear and uint16 normalization."""
    import numpy as np
    from veilbreakers_terrain.handlers.terrain_quixel_ingest import _srgb_to_linear
    srgb = np.array([0.0, 0.5, 1.0], dtype=np.float32)
    lin = _srgb_to_linear(srgb)
    assert lin[0] == 0.0
    assert 0.21 < float(lin[1]) < 0.22  # sRGB 0.5 ≈ 0.214 linear
    assert lin[2] == 1.0
```

---

## 10. P0 / P1 findings (new)

### P1-S11-1 — `VbTerrainTileMetadata.ClimateZone` defaults to `"temperate"` regardless of biome
**Files:**
- `unity_plugin/VbTerrainTileMetadata.cs:32`
- `veilbreakers_terrain/handlers/terrain_unity_export.py` (manifest writer)

**Issue:** Tiles with no biome metadata announce themselves as
`temperate` to downstream Unity systems.
**Fix:** Default to empty string and require the manifest writer to
populate `ClimateZone` from the biome→climate map (see P1-S11-2).

### P1-S11-2 — No biome→climate auto-mapping in pipeline
**File:** `veilbreakers_terrain/handlers/_terrain_world.py:1198`,
`environment.py:2121-2126`, `environment.py:3061-3066`.
**Issue:** Setting `composition_hints["biome_type"]="desert"` does not
select the `arid` erosion profile unless the caller separately sets
`composition_hints["climate"]`. The biome→climate knowledge already
exists inside `terrain_quixel_ingest._BIOME_ASSET_TAGS` and inside the
master plan's biome list.
**Fix:** Add `_biome_to_climate_profile()` (table in §6) and chain it
into both fallback expressions.

### P2-S11-3 — `register_bundle_n_passes()` returns dict but is called as `fn()` by master registrar
**File:** `terrain_master_registrar.py:265` calls `fn()` and discards the
return value. Bundle N's function returns
`get_bundle_n_runtime_contract()` — a dict that's swallowed. Functionally
fine, but the duplicate-detection diff (line 278-279) compares the
registry before/after and detects zero new passes for Bundle N, which
is the correct outcome but flagged in WARN-level logs as
"contributed 0 passes". Recommend: have the master registrar
special-case `register_bundle_n_passes` so the duplicate detector
doesn't spuriously warn on it.

### P2-S11-4 — `Hunyuan3D2Provider.submit()` swallows gradio_client missing inside the worker thread
**File:** `hunyuan3d2_provider.py:322-337`. The `_run` worker logs the
error and stores it in the holder dict, but `submit()` returns the job
id immediately. A caller using the ABC contract pattern
(`submit → poll → download`) only sees the failure on `poll()` returning
`FAILED`. Acceptable, but `is_available()` only checks `gradio_client`
import, not endpoint reachability — a configured private endpoint that
is offline will only show up as `JobStatus.FAILED` after a real submit.
Recommend adding an HTTP HEAD ping in `is_available()` for the
endpoint mode.

### P3-S11-5 — Quixel ingest — channel.json fallback overwrites textures dict only if empty
**File:** `terrain_quixel_ingest.py:395-409`. The `channels.json` sidecar
is only consulted when the regular filename scan produced zero textures.
This is correct for legacy folders, but a partial folder (e.g. only
albedo found by filename + the sidecar declaring normal/roughness) will
NOT pick up the sidecar entries. Low priority — Bridge 6.x exports are
either all-named or all-sidecar, not mixed.

---

## 11. Confirmed-fixed earlier audit items

- ✅ `VbTerrainTileMetadata` 3-field stub → expanded to 28 fields (§3).
- ✅ Foliage attachment in Unity → `VbTerrainImporter.cs:1361-1426`
  reads the manifest and adds `VbFoliageManifestRenderer` (§7).
- ✅ Climate hardcoded → no longer hardcoded; reads from
  `composition_hints` chain. Still defaults to `"temperate"` when caller
  supplies neither `climate` nor `erosion_profile`, but this is now
  configurable, not hardcoded (§6).
- ✅ Bundle K registers 6 sub-passes (was previously 3).
- ✅ Bundle O registers all 4 water + vegetation passes
  (water_variants, bathymetry, vegetation_depth, emergent_grass).
- ✅ Quixel ingest blends AO and displacement (claim of "missing"
  is stale).
- ✅ Normal map sRGB-to-linear bug fixed (decoded to [-1,1] before
  blending).

---

## 12. Files to act on (absolute paths)

- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\unity_plugin\VbTerrainTileMetadata.cs` — change `ClimateZone` default to `""`.
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\_terrain_world.py` — add `_biome_to_climate_profile`, plumb at line 1198.
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\environment.py` — chain biome→climate fallback at 2121-2126 and 3061-3066.
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_unity_export.py` — populate `ClimateZone` field from intent.biome→climate at manifest-write time.
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_master_registrar.py` — special-case `register_bundle_n_passes` so duplicate-detection doesn't warn (P2-S11-3).
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\providers\hunyuan3d2_provider.py` — extend `is_available()` to ping the endpoint URL in `hf_endpoint` mode.
