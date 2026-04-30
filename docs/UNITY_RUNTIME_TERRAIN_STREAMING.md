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

## Scene Setup

1. Import terrain bundles with `VbTerrainImporter`.
2. Create an empty `VB_TerrainRuntime`.
3. Add `VbTerrainRuntimeStreamer`.
4. Assign the player or main camera to `ViewTarget`.
5. Set `WorldId` when multiple terrain worlds exist in one scene.
6. Add `VbFloatingOrigin` to the same object.
7. Put imported terrain roots, water roots, scatter roots, and world-effect
   roots in `ShiftRoots`.

## Rules

- Do not add per-tile one-shot loaders that bypass `VbTerrainTileMetadata`.
- Do not disable `Terrain.SetNeighbors`; seam hiding depends on active
  neighbor reconnection.
- Keep `MaxTilesChangedPerFrame` low on content-heavy scenes.
- Keep `MaximumDistance` well below the point where vegetation or water starts
  precision flicker.
- Blender or Unity rendered proof is still required before making visual AAA
  claims.
