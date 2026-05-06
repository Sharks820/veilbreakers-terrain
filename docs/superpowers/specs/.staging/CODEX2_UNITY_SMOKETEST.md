# CODEX2 Unity Import Smoketest

Date: 2026-05-06  
Scope: `unity_plugin/Editor/VbTerrainImporter.cs`, `unity_plugin/VbTerrainTileMetadata.cs`, §11.5.1 B5-U1..B5-U14 in `docs/superpowers/specs/2026-05-05-biome-render-rebuild-design.md`.

Unity Editor validation was not run. Repo has `unity_plugin/` only; no `Assets/`, `Packages/`, `ProjectSettings/`, `.shadergraph`, `.mat`, or full Unity project exists.

## Current Import Contract

Current plugin is descriptor-driven, not final chunk-contract driven:

- Required entry file: `unity_import_descriptor.json`; missing descriptor hard-fails import (`unity_plugin/Editor/VbTerrainImporter.cs:18`, `:308-315`).
- Descriptor fields define current artifacts: heightmap, terrain normal map, mesh attributes, splatmaps, terrain/detail layers, tree instances, audio/gameplay/wildlife/decals sidecars, water rasters, navmesh area grid, supplemental meshes, foliage manifest, lights, probes (`unity_plugin/Editor/VbTerrainImporter.cs:20-82`).
- Current Python writer emits `heightmap.raw`, `splatmap_00.raw`, `terrain_normals.bin`, `terrain_normals_tangent.png`, generic channel `.bin` files, `tree_instances.json`, `foliage_placement_manifest.json`, sidecar JSON, `water_shader_manifest.json`, `manifest.json`, and `unity_import_descriptor.json` (`veilbreakers_terrain/handlers/terrain_unity_export.py:1523-1688`, `:1927-1962`, `:1989-2223`, `:2495-2520`).
- Target §6.1 final contract is a different bundle: `terrain.raw`, `splat.png`, `splat_secondary.png`, `holes.png`, `macro_variation.png`, `overlay_dynamic.png`, `triplanar_mask.png`, `flow_map.png`, `navmesh.png`, `vertex_ao.bin`, `layers/*`, `foliage.json`, `grass.json`, `water.json`, `edges.json`, `probes.json`, `decals.json`, `meta.json` (`docs/superpowers/specs/2026-05-05-biome-render-rebuild-design.md:524-553`).

## 18 Target Chunk Artifacts

These are the 18 Block-5 artifact classes implied by §6.1 / PR #42, excluding optional `caves/`:

| # | Target artifact | Format / role | Current Unity-side status |
|---|---|---|---|
| 1 | `terrain.raw` / legacy `heightmap.bin` | U16 little-endian heightmap | Current importer expects descriptor `heightmap.file`, normally `heightmap.raw`, not `terrain.raw` or `heightmap.bin` (`VbTerrainImporter.cs:85-94`, `terrain_unity_export.py:1594-1602`). |
| 2 | `splat.png` | RGBA layers 0-3 | Current importer expects raw RGBA bytes, normally `splatmap_00.raw`, not PNG (`VbTerrainImporter.cs:851-925`, `terrain_unity_export.py:1741-1839`). |
| 3 | `splat_secondary.png` | RGBA layers 4-7 | Same raw-vs-PNG mismatch. |
| 4 | `holes.png` | R8 terrain holes | No consumer, no `TerrainData.SetHoles` path (`VbTerrainImporter.cs:799-803`; B5-U3 at spec `:1777`). |
| 5 | `macro_variation.png` | anti-tile shader texture | No consumer or shader binding. |
| 6 | `overlay_dynamic.png` | wet/dust/disturb/snow overlay | No consumer or shader binding. |
| 7 | `triplanar_mask.png` | slope mask | No consumer or shader binding. |
| 8 | `flow_map.png` | RG16 HDRP river current map | Current importer references `flow_direction.bin`, not `flow_map.png`, and water creation is disabled (`VbTerrainImporter.cs:52-55`, `:1116-1164`; B5-U8 at spec `:1782`). |
| 9 | `navmesh.png` | R8 walkable mask | Current importer references `navmesh_area_id.bin`, not `navmesh.png` (`VbTerrainImporter.cs:59-60`, `:583-633`). |
| 10 | `vertex_ao.bin` | vertex color AO | No terrain vertex-color consumer (B5-U6 at spec `:1780`). |
| 11 | `layers/*_albedo/normal/mask/height/detail.png` | HDRP layer textures | Only diffuse/normal/mask are supported; height/detail ignored (`VbTerrainImporter.cs:112-129`, `:1981-2016`; B5-U10 at spec `:1784`). |
| 12 | `foliage.json` | Addressables tree/prop instances | Current importer uses `foliage_placement_manifest.json` plus manual prototypes, not Addressables (`VbTerrainImporter.cs:61-63`, `:1355-1403`; B5-U11/B5-U12 at spec `:1785-1786`). |
| 13 | `grass.json` | sub-cell GPU grass | No consumer (spec requires `grass.json` at `:546`, runtime load at `:615`). |
| 14 | `water.json` | HDRP WaterSurface bodies | No consumer; current `water_shader_manifest.json` path logs and exits (`VbTerrainImporter.cs:1116-1154`; B5-U2 at spec `:1776`). |
| 15 | `edges.json` | N/S/E/W seam contract | No reader/assertion; only `seam_contract` descriptor metadata and `SetNeighbors` by tile coords (`VbTerrainImporter.cs:65`, `:2353-2403`; B5-U5 at spec `:1779`). |
| 16 | `probes.json` | reflection + light probes | Current importer expects `probe_placements.json` and creates only `LightProbeGroup`, no reflection probes (`VbTerrainImporter.cs:63-64`, `:1290-1325`). |
| 17 | `decals.json` | HDRP DecalProjectors | Current importer stores JSON as sidecar only, no projector creation (`VbTerrainImporter.cs:49`, `:1411-1465`; B5-U7 at spec `:1781`). |
| 18 | `meta.json` | version, spawn, Addressables, budget, nav/audio hints | No `meta.json` reader; metadata component lacks required fields (`VbTerrainTileMetadata.cs:11-49`; B5-U13 at spec `:1787`). |

## Unity-Side Bugs

### U-001: Final chunks cannot import without legacy descriptor

Evidence: importer hard-requires `unity_import_descriptor.json` (`VbTerrainImporter.cs:18`, `:310-315`). Target contract starts from `meta.json`, `terrain.raw`, splats, holes, water, edges (`biome-render-rebuild-design.md:524-553`, `:607-624`).

Bug: a valid Block-5 chunk bundle will fail before any artifact is read.

Ship impact: every new chunk generated to §6.1 contract appears broken in Unity with "Missing unity_import_descriptor.json".

### U-002: Heightmap filename/format drift

Evidence: current descriptor defaults to `heightmap.raw` with `raw_u16_le` (`VbTerrainImporter.cs:85-94`), writer emits `"file": "heightmap.raw"` (`terrain_unity_export.py:1594-1602`), while §6.1 calls for `terrain.raw` (`biome-render-rebuild-design.md:526`) and user task references `heightmap.bin`.

Bug: three names exist for same contract: `heightmap.raw`, `terrain.raw`, `heightmap.bin`.

Ship impact: chunk loaders and QA tests can pass different bundles while Unity silently targets another file or hard-fails missing file.

### U-003: Heightmap endianness field is ignored

Evidence: descriptor has `encoding` and `endianness` (`VbTerrainImporter.cs:90-93`), but reader always decodes 16-bit little-endian via `bytes[offset] | (bytes[offset + 1] << 8)` (`VbTerrainImporter.cs:2286-2307`).

Bug: Unity cannot detect or honor big-endian/mislabeled RAW data.

Ship impact: terrain imports as quantized spikes/terraces or inverted elevation bands; Python byte verifier can still pass if file hash and shape match.

### U-004: Non-16-bit heightmaps are corruptly decoded

Evidence: `ReadHeightmap01` computes expected bytes from `bit_depth`, but any non-16 path samples one byte per pixel using `offset = srcY * width + x` (`VbTerrainImporter.cs:2288-2320`).

Bug: if descriptor says 32-bit or 24-bit, file length check passes but pixel stride is wrong.

Ship impact: terrain becomes near-random low-amplitude noise instead of rejecting unsupported bit depth.

### U-005: Heightmap flip defaults can double-flip

Evidence: Python pre-flips `heightmap_raw_u16` (`terrain_unity_export.py:285-299`) and writes descriptor `flip_vertical=False` (`terrain_unity_export.py:1927-1935`); C# descriptor default is `flip_vertical=true` (`VbTerrainImporter.cs:91-93`) and importer flips when true (`VbTerrainImporter.cs:2300-2307`).

Bug: any descriptor missing `flip_vertical` or alternate writer using defaults imports north/south mirrored.

Ship impact: chunk edges, rivers, roads, and navmesh align in Python artifacts but appear reversed in Unity.

### U-006: Splatmap contract is raw RGBA, not PNG RGBA

Evidence: target wants `splat.png` and `splat_secondary.png` (`biome-render-rebuild-design.md:527-528`); current writer emits `splatmap_00.raw` (`terrain_unity_export.py:1812-1837`); importer reads raw bytes and checks `width * height * channels` (`VbTerrainImporter.cs:873-879`).

Bug: PNG splatmaps are not decoded. Unity-side PNG channel/order bugs cannot be caught because PNG path does not exist.

Ship impact: final artifact bundle fails size check immediately, or a hand-renamed PNG imports as garbage bytes.

### U-007: Splatmap channel order is assumed, not validated

Evidence: writer records `channel_layout: RGBA` (`terrain_unity_export.py:1821-1836`); importer ignores `encoding`/layout and maps byte channel 0..3 to layers (`VbTerrainImporter.cs:887-897`).

Bug: ARGB/BGRA/Unity texture swizzle drift is invisible to importer.

Ship impact: grass/rock/snow/mud layers swap channels; visual terrain materials look wrong while weights still sum to 1.

### U-008: Secondary splat dimension mismatch is not checked before write

Evidence: alphamap array dimensions come from first splatmap (`VbTerrainImporter.cs:862-870`); loop does not verify each later splatmap matches those dimensions before indexing (`VbTerrainImporter.cs:871-899`).

Bug: malformed `splat_secondary` can throw index errors or partially overwrite wrong coordinates.

Ship impact: second material group breaks import late, after terrain layers may already be created/dirty.

### U-009: `holes.png` is completely missing

Evidence: terrain import sequence runs heightmap, terrain layers, splatmaps, detail layers, trees only (`VbTerrainImporter.cs:799-803`). No `SetHoles` call exists. B5-U3 explicitly requires `terrainData.SetHoles` (`biome-render-rebuild-design.md:1777`).

Bug: cave/undercut holes cannot be represented in Unity Terrain.

Ship impact: caves are sealed by terrain surface; player collision/navmesh treats entrances as solid ground.

### U-010: HDRP shader graph stack absent

Evidence: no `Assets/` or `unity_project/` exists in repo; spec requires shader graphs or MicroSplat fallback (B5-U1, `biome-render-rebuild-design.md:1775`; deeper audit at `:1927`).

Bug: importer creates Unity `TerrainLayer` assets, but no committed HDRP material graph can consume triplanar, anti-tile, distance normals, dynamic overlays, flow maps, or macro variation.

Ship impact: terrain imports as basic Unity Terrain layers, not target AAA biome material stack.

### U-011: TerrainLayer height/detail maps are ignored

Evidence: descriptor supports only `diffuse_texture_file`, `normal_texture_file`, `mask_texture_file` (`VbTerrainImporter.cs:125-127`). Layer binding only sets diffuse, normal, mask (`VbTerrainImporter.cs:1981-2016`). §6.1 layer contract includes height/detail PNGs (`biome-render-rebuild-design.md:537-542`), B5-U10 requires binding them (`:1784`).

Bug: parallax/displacement and close-range detail maps are dropped.

Ship impact: close terrain reads flat/blurry; material QA can pass Python asset existence but fail in Unity viewport.

### U-012: Mask textures import as sRGB

Evidence: mask texture is imported through `ResolveLayerTexture(... normalMap:false)` (`VbTerrainImporter.cs:2003-2016`); `ImportTextureAsset` sets `sRGBTexture = !normalMap` (`VbTerrainImporter.cs:2117-2119`). Unity docs require masks/lookup textures to bypass sRGB sampling.

Bug: HDRP mask map channels get gamma-transformed.

Ship impact: AO, detail, smoothness, roughness/metal channels render numerically wrong; wetness/snow thresholds drift in shader.

### U-013: Normal-map handedness is not locked or tested

Evidence: exporter packs tangent-space normal directly into RGBA (`terrain_unity_export.py:334-342`, `:1949-1960`); importer only sets `TextureImporterType.NormalMap` and does not alter G channel (`VbTerrainImporter.cs:2097-2123`). B5-U4 says current path lacks required G-channel decision (`biome-render-rebuild-design.md:1778`).

Bug: Unity-side convention is undocumented in code, and spec/doc evidence conflicts enough that blind import is unsafe.

Ship impact: slopes shade from wrong direction; mountains look inside-out under directional light.

### U-014: `water.json` / HDRP WaterSurface path absent

Evidence: current descriptor has `water_shader_manifest_file` and raster sidecars, not `water.json` (`VbTerrainImporter.cs:51-55`). `CreateWaterSurfaces` validates rasters, parses material manifest, then always logs "skipped raster-backed water mesh creation" and returns (`VbTerrainImporter.cs:1116-1154`). B5-U2 requires HDRP `WaterSurface` from `water.json` (`biome-render-rebuild-design.md:1776`).

Bug: no lake/river/ocean/waterfall Unity objects are created.

Ship impact: pilot chunk loads with dry riverbeds or no visible water.

### U-015: `flow_map.png` is not bound to water

Evidence: spec requires river `currentMap = flow_map.png` (`biome-render-rebuild-design.md:616-620`, B5-U8 at `:1782`). Current importer references `flow_direction_file` and `flow_accumulation_file` as sidecars only (`VbTerrainImporter.cs:52-55`, `:1417-1420`).

Bug: flow data never reaches HDRP Water current map.

Ship impact: rivers have no directional motion, or flow appears static/wrong.

### U-016: Water elevation semantics are lossy

Evidence: Python manifest emits `water_surface_elevation_m` (`terrain_unity_export.py:2385-2387`), but descriptor carries only `water_level_unity_units` (`terrain_unity_export.py:1639-1640`). Importer stores metadata by subtracting origin and dividing by scale (`VbTerrainImporter.cs:384-387`), while metadata field is named `WaterSurfaceElevationM` (`VbTerrainTileMetadata.cs:33-35`).

Bug: absolute water surface elevation collapses into local relative value.

Ship impact: gameplay/water systems reading metadata can place water planes, fog, audio, or swim volumes at wrong Y.

### U-017: `edges.json` seam contract absent

Evidence: target requires edge assertions with height tolerance, water tolerance, and feature-thread match (`biome-render-rebuild-design.md:570-601`); B5-U5 requires Unity-side validator (`:1779`). Current importer only connects neighbors by `TileX/TileY` and never reads `edges.json` (`VbTerrainImporter.cs:2353-2403`).

Bug: seam correctness is never checked in Unity.

Ship impact: height/color/water/road seam pops ship unnoticed until visual playtest.

### U-018: `vertex_ao.bin` is not consumed

Evidence: target requires `vertex_ao.bin` into vertex color (`biome-render-rebuild-design.md:535`, B5-U6 at `:1780`). Current Unity Terrain path has no vertex color write and sidecar list does not include `vertex_ao.bin` (`VbTerrainImporter.cs:1405-1429`).

Bug: baked AO never affects terrain or supplemental meshes.

Ship impact: contact shadows/cave occlusion disappear; ambient renders look flat.

### U-019: Supplemental mesh normals/tangents/colors from export are discarded

Evidence: writer emits `normal`, `tangent`, `uv0`, `uv1`, `color` streams (`terrain_unity_export.py:946-978`). C# spec class only defines `vertices`, `faces`, `uvs`, `drip_edge_indices` (`VbTerrainImporter.cs:195-205`); builder sets UV0/UV1 drip mask and recalculates normals (`VbTerrainImporter.cs:1624-1691`).

Bug: Unity importer ignores authored normals, tangents, lightmap UVs, and vertex color.

Ship impact: cave/cliff meshes lose smoothing, tangent-space normal correctness, AO/color data, and lightmap channels.

### U-020: Cave FBX handoff missing

Evidence: §6.1 has optional `caves/*.fbx` (`biome-render-rebuild-design.md:543-544`), and B5-U9 requires importing cave FBX children (`:1783`). Current importer only supports `supplemental_mesh_specs.json` (`VbTerrainImporter.cs:1062-1114`).

Bug: authored cave geometry directory is ignored.

Ship impact: undercuts/caves do not appear unless converted into legacy supplemental JSON.

### U-021: Decals are stored, not instantiated

Evidence: `decals.json` gets only a `VbTerrainSidecarReference` (`VbTerrainImporter.cs:1411-1465`; sidecar stores strings at `VbTerrainSidecarReference.cs:9-15`). B5-U7 requires HDRP `DecalProjector` instances (`biome-render-rebuild-design.md:1781`).

Bug: decal payload never becomes renderable decals.

Ship impact: mud, moss, wet rock, footprints, and cliff detail decals are invisible.

### U-022: Raw sidecar schema drift is unchecked

Evidence: only descriptor top-level keys are warned (`VbTerrainImporter.cs:1467-1536`). Raw sidecars are copied/read into `JsonPayload` with no schema validation (`VbTerrainImporter.cs:1456-1464`). B5-U14 requires sidecar unknown-key warnings (`biome-render-rebuild-design.md:1788`).

Bug: `audio_zones.json`, `decals.json`, `water_shader_manifest.json`, etc. can drift silently.

Ship impact: runtime binders receive malformed schemas later, far from import-time root cause.

### U-023: `meta.json` / 25-field metadata missing

Evidence: metadata component has fields through snow/primary biome plus `ChannelBounds` only (`VbTerrainTileMetadata.cs:11-49`). B5-U13 requires `version_hash`, `character_spawn_safe_pos`, `addressable_deps`, `neighbor_prefetch_hints`, `memory_budget_mb`, `audio_zones`, `navmesh_hints`, `seed`, `is_landmark`, `basin_id/segment_id`, and migration (`biome-render-rebuild-design.md:1787`).

Bug: target runtime metadata is not deserialized or stored.

Ship impact: save-version validation, spawn safety, streaming budget, prefetch, quest landmarks, audio/nav hints, and water basin IDs are unavailable.

### U-024: `ChannelBounds` never populated

Evidence: metadata declares `ChannelBounds` (`VbTerrainTileMetadata.cs:42-49`), importer never assigns it while `mesh_attributes_file` is only sidecar-referenced (`VbTerrainImporter.cs:378-379`, `:1421`).

Bug: channel min/max metadata does not survive into Unity components.

Ship impact: shaders/gameplay systems cannot normalize raw sidecar channels consistently.

### U-025: Addressables strategy absent

Evidence: §6.4 requires Addressables prefab instantiation for foliage/props (`biome-render-rebuild-design.md:614`) and B5-U11 requires species prefab loading from Addressables (`:1785`). Current tree loader uses `AssetDatabase.LoadAssetAtPath`, then creates a Capsule prefab fallback (`VbTerrainImporter.cs:2229-2283`). No Addressables references exist in `unity_plugin/`.

Bug: no group/key strategy, async load, unload, or fallback atlas path.

Ship impact: pilot biomes render placeholder capsules or nothing; streaming cannot manage prefab memory.

### U-026: Foliage manifest renderer cannot render by itself

Evidence: importer attaches `VbFoliageManifestRenderer` and warns if no manual `Prototypes` have mesh/material entries (`VbTerrainImporter.cs:1373-1403`). Renderer resolves only preassigned prototypes by `mesh_id`/`species_key` (`VbFoliageManifestRenderer.cs:65-69`, `:267-281`).

Bug: imported `foliage_placement_manifest.json` is not enough to draw foliage.

Ship impact: trees/props disappear unless a Unity user manually wires prototypes after import.

### U-027: Foliage UV2/UV3/wind/vertex-color contract absent

Evidence: B5-U12 requires UV2/UV3 Pivot Painter wind and vertex colors (`biome-render-rebuild-design.md:1786`). Renderer consumes only position, rotation, scale, LOD, tint (`VbFoliageManifestRenderer.cs:44-53`, `:203-226`, `:308-320`).

Bug: no imported wind metadata or lightmap UV pass-through.

Ship impact: foliage cannot satisfy wind animation/lightmap acceptance; diagonal/static-looking vegetation risk remains.

### U-028: Foliage coordinate mode is ambiguous

Evidence: renderer has `ConvertTerrainXzyToUnityXyz` and `PositionsAreWorldSpace` switches (`VbFoliageManifestRenderer.cs:77-82`); importer hard-sets `ConvertTerrainXzyToUnityXyz=false`, `PositionsAreWorldSpace=true` (`VbTerrainImporter.cs:1391-1394`). Position conversion changes x/y/z interpretation (`VbFoliageManifestRenderer.cs:295-305`).

Bug: final `foliage.json` local/world or XZY/XYZ schema drift can place foliage off-tile without import failure.

Ship impact: trees float, sink, or shift one axis; Python can verify numeric positions while Unity uses wrong coordinate mode.

### U-029: Light/probe contract is partial

Evidence: current importer creates Light GameObjects from `light_placements.json` (`VbTerrainImporter.cs:1231-1288`) and `LightProbeGroup` from `probe_placements.json` (`:1290-1325`). Target uses `probes.json` for reflection + light probes (`biome-render-rebuild-design.md:549`, `:621`).

Bug: reflection probes are absent and filename does not match target.

Ship impact: water/caves/materials lack expected reflection volumes; GI proof can pass probe JSON generation but fail in scene.

### U-030: NavMesh asset is built but not attached for runtime use

Evidence: importer builds `NavMeshData` and writes/updates an asset (`VbTerrainImporter.cs:553-579`), stores path in metadata (`:378-379`), but no `NavMesh.AddNavMeshData` or scene component is created.

Bug: imported terrain can have an asset on disk but no active runtime navmesh instance.

Ship impact: agents may not navigate in play mode despite import reporting `NavMeshDataAssetPath`.

### U-031: Navmesh map orientation/format mismatch

Evidence: target `navmesh.png` is R8 walkable mask (`biome-render-rebuild-design.md:534`), current importer reads `navmesh_area_id.bin` as little-endian ushort grid with inferred square dimensions (`VbTerrainImporter.cs:583-633`).

Bug: final R8 PNG cannot import; current binary grid has no explicit flip/origin validation.

Ship impact: walkable/water/cliff exclusions can be rotated, flipped, or ignored.

### U-032: Texture wrap mode is blindly `Repeat`

Evidence: all imported textures in `ImportTextureAsset` set `wrapMode = Repeat` (`VbTerrainImporter.cs:2117-2121`); generated textures also repeat (`:2147`, `:2213`). Target includes finite masks/maps like holes, overlay, triplanar, flow, macro, AO.

Bug: mask-like or edge-sensitive maps need explicit Clamp/Repeat by semantic type, not one default.

Ship impact: edge pixels bleed across chunk borders or repeat within shader samples, causing seam artifacts.

### U-033: Manifest field types can default silently

Evidence: descriptor uses Unity `JsonUtility` into primitive fields with defaults (`VbTerrainImporter.cs:20-82`, `:318-325`). There is no required-field validation beyond failed export status (`:414-424`).

Bug: missing or type-mismatched numbers become `0`/defaults instead of import errors.

Ship impact: chunks can load at origin, wrong tile coords, wrong terrain size, zero biome ID, no water, or default LOD distances while Python schema drift remains hidden.

### U-034: `manifest.json` is not consumed

Evidence: current importer never reads `manifest.json`; it reads only `unity_import_descriptor.json` (`VbTerrainImporter.cs:308-325`). Python writes `manifest.json` atomically and updates files index after descriptor write (`terrain_unity_export.py:2495-2520`).

Bug: hash/size/file inventory in manifest is unused by Unity.

Ship impact: Unity cannot catch missing/stale/corrupt artifacts at import time unless descriptor-specific code happens to touch them.

### U-035: Generated sidecar GameObjects have no lifecycle/binder contract

Evidence: `CreateSidecarReference` creates `VB_<PayloadType>` children with raw JSON text/byte size only (`VbTerrainImporter.cs:1431-1465`; `VbTerrainSidecarReference.cs:9-15`).

Bug: audio/gameplay/wildlife/particle/atmosphere/wind/cloud sidecars are attached as inert blobs.

Ship impact: scene looks imported but runtime systems never receive components, colliders, audio zones, emitters, wind, or cloud-shadow bindings.

## B5-U Cross-Reference

| PR | Unity-side finding |
|---|---|
| B5-U1 | U-010. No shader graphs/MicroSplat fallback; no Unity project files. |
| B5-U2 | U-014, U-015, U-016. `water.json`/WaterSurface/currentMap path absent. |
| B5-U3 | U-009. `holes.png` / `SetHoles` absent. |
| B5-U4 | U-013. Normal-map handedness not locked/tested. |
| B5-U5 | U-017. `edges.json` validator absent. |
| B5-U6 | U-018, U-019. Vertex AO and vertex-color streams ignored. |
| B5-U7 | U-021, U-022. Decals sidecar only; no DecalProjector/schema validation. |
| B5-U8 | U-015. `flow_map.png` not bound to water. |
| B5-U9 | U-020. Cave FBX handoff absent. |
| B5-U10 | U-011, U-012, U-032. Layer height/detail ignored; mask texture import settings unsafe. |
| B5-U11 | U-025, U-026. Addressables/tree prefab loader absent; Capsule fallback. |
| B5-U12 | U-027, U-028. Foliage UV2/UV3/wind/vertex color and coordinate contract absent. |
| B5-U13 | U-023, U-024, U-033. Metadata fields/migration/schema validation absent. |
| B5-U14 | U-022, U-035. Sidecar unknown-key warnings and binders absent. |

## Highest-Risk Ship Failures

1. Final Block-5 chunks do not import at all because current plugin expects legacy `unity_import_descriptor.json`.
2. Even legacy chunks import without water, holes, edge checks, real decals, real foliage assets, shader graph stack, or metadata.
3. Unity-specific color-space/normal/coordinate/endianness bugs remain untested by Python verifiers.
4. Sidecars are mostly inert blobs, not runtime systems.
5. No Unity project means no actual Editor smoke test can prove any visual/runtime claim yet.
