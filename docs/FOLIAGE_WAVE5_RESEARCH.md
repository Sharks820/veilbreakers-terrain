# Wave 5 Foliage Pipeline — Superseded Note

**Status:** superseded by `docs/FOLIAGE_MANIFEST_PIPELINE.md`.

The older DCC scatter handoff described here was retired after the workstation
removed 3ds Max. Current production path is:

1. Generate terrain-driven scatter points in Python.
2. Resolve species through the mesh-library JSON.
3. Emit `foliage_placement_manifest.json`.
4. Import that manifest directly into Unity Terrain / GPU instancing.

Kept decision:

- Python owns placement decisions: density, biome, slope, water, road, cliff,
  exclusion, LOD, tint, and per-instance seeds.
- External tools may author meshes, cards, atlases, and impostors, but they do
  not own scatter placement or runtime manifests.
- Unity import and render data are source-of-truth for shipping terrain.

Use `scripts/export_foliage_manifest.py` for CLI conversion from
`scatter_points.json` to the runtime manifest.
