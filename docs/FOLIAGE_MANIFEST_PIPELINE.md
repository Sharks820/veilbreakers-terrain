# VeilBreakers Foliage Manifest Pipeline

3ds Max / Forest Pack handoff is retired. Production foliage scatter now stays
data-driven:

1. Terrain/scatter pass writes `scatter_points.json`.
2. Artists provide a mesh-library JSON with Unity asset paths, LOD meshes,
   atlas paths, collider mode, wind-bake flag, and render mode.
3. `scripts/export_foliage_manifest.py` writes
   `output/unity/foliage_placement_manifest.json`.
4. Unity importer consumes `mesh_library`, `instances`,
   `position_terrain_norm`, `rotation_y_rad`, `scale_xyz`, `lod_level`,
   biome/category metadata, moisture, tint, and color-variation seeds.

Example:

```powershell
python scripts/export_foliage_manifest.py `
  --input output/aaa_node_v6/scatter_points.json `
  --mesh-library assets/foliage_mesh_library.json `
  --output output/unity/foliage_placement_manifest.json `
  --biome thornwood_forest `
  --season autumn
```

Rules:

- No placeholder scatter grids in production exports.
- No DCC-specific coordinate remaps.
- No editor plugin as source of truth.
- Mesh IDs are generated from the mesh-library species keys actually used.
- Unknown species are dropped with a warning instead of creating invalid
  runtime references.
- `position_terrain_norm` exists for `TerrainData.SetTreeInstances`;
  `position_world` and `scale_xyz` exist for GPU instanced renderers.
