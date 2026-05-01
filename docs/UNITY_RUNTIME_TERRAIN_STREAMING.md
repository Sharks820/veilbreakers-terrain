# Unity Runtime Terrain Streaming

VeilBreakers terrain import now has runtime-side large-world support instead of
depending on a DCC handoff.

## Components

- `VbTerrainRuntimeStreamer`
  - finds imported `VbTerrainTileMetadata` terrain tiles
  - prioritizes camera-frustum tiles first
  - activates tiles by distance and `MaxActiveTiles`
  - limits activation churn with `MaxTilesChangedPerFrame`
  - applies near/mid/far Unity Terrain quality from `Lod0DistanceM`,
    `Lod1DistanceM`, and `Lod2DistanceM`
  - reconnects active terrain neighbors with `Terrain.SetNeighbors`
- `VbFloatingOrigin`
  - recenters configured scene roots when player/camera exceeds
    `MaximumDistance`
  - keeps imported terrain, water, scatter, sidecars, and particles stable in
    large worlds
  - publishes `OnOriginMoved` for gameplay systems that store world-space state
- `VbFoliageManifestRenderer`
  - consumes `foliage_placement_manifest.json`
  - draws assigned foliage prototypes through `Graphics.DrawMeshInstanced`
  - batches by mesh/material/LOD and keeps per-frame draws under Unity's 1023
    instance call limit
  - uses manifest LOD distances, cull distance, and per-instance tint

## Scene Setup

1. Import terrain bundles with `VbTerrainImporter`.
2. Create an empty `VB_TerrainRuntime`.
3. Add `VbTerrainRuntimeStreamer`.
4. Assign the player or main camera to `ViewTarget`.
5. Set `WorldId` when multiple terrain worlds exist in one scene.
6. Add `VbFloatingOrigin` to the same object.
7. Put imported terrain roots, water roots, scatter roots, and world-effect
   roots in `ShiftRoots`.
8. Add `VbFoliageManifestRenderer` for GPU foliage manifests.
9. Assign the manifest `TextAsset` and prototype meshes/materials by `mesh_id`
   or `species_key`.

## Rules

- Do not add per-tile one-shot loaders that bypass `VbTerrainTileMetadata`.
- Do not disable `Terrain.SetNeighbors`; seam hiding depends on active
  neighbor reconnection.
- Keep `MaxTilesChangedPerFrame` low on content-heavy scenes.
- Keep `MaximumDistance` well below the point where vegetation or water starts
  precision flicker.
- Use `VbFoliageManifestRenderer` for dense foliage. Unity `TreeInstance`
  remains acceptable for terrain-tree prototypes, not dense grass or debris.
- Blender or Unity rendered proof is still required before making visual AAA
  claims.
