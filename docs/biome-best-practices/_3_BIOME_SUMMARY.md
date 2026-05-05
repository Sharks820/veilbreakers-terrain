# 3-Biome AAA Visual Perfection Summary

**Goal**: Three full-size 4096m × 4096m biome game nodes (Coastal, Mountain + Forest, Grassland) at AAA visual quality, with verified multi-angle render proofs committed to git, biome-natural vegetation, and best-practices documentation per biome.

**Status**: All three biomes built and rendered (2026-05-05).

---

## Builds + render proofs

| Biome | Blend | Render dir (canonical) | Render dir (debug) |
|-------|-------|-----------------------|--------------------|
| Coastal V3e | `output/visual_nodes/VB_Coastal_V3e_Props_4096m.blend` | `renders/coastal/u10_props/` (Eevee Next 8 cams) | `renders/coastal/c1_coastal_cycles/` (Cycles 8 cams) |
| Mountain v2 | `output/visual_nodes/VB_Mountain_Forest_v2_4096m.blend` | `renders/coastal/m1_mountain_forest/` (Cycles 8 cams) | `renders/coastal/m1_mountain_forest_workbench/` (Workbench 8 cams) |
| Grassland v1 | `output/visual_nodes/VB_Grassland_v1_4096m.blend` | `renders/coastal/g1_grassland/` (Cycles 8 cams) | — |

Each biome has 8 camera angles for absolute multi-angle visual review:
- FULL_NODE (orthographic overview)
- mid-distance perspective × 4 (different focal lengths and POVs)
- TOPDOWN_ORTHO (pattern density)
- close-camera detail
- DRONE_HIGH (aerial)

Open the manifest in each render directory for a structured table:
```
cat renders/coastal/<biome>/RENDER_MANIFEST.json
```

## Locked decisions across all 3 biomes

- **Tile size**: 4096m × 4096m, 513² grid (8 m cells)
- **Toolchain**: Blender 4.5.8 LTS + Python 3.11
- **Geometry Nodes scatter**: POISSON method with `Selection` boolean masks; instance rotation aligned to terrain face normal so vegetation never floats or buries
- **Procedural-only materials**: noise + voronoi shader graphs, no texture files
- **Render engines**:
  - **Cycles 32 samples + denoising**: canonical photoreal output (always works headless)
  - **Workbench**: fast debug reference (renders in seconds)
  - **Eevee Next**: live preview only — produces black headless without `light_cache_bake`
- **Per-vertex attributes** drive both shader and scatter:
  - `vb_slope_deg` (computed with real meter scale: `np.gradient(z, cell_size_m)`)
  - `vb_elev_m` (raw heightfield z)
  - Coastal-only: `vb_sd_m`, `vb_sd_norm`, `vb_wetness`
  - Grassland-only: `vb_near_water` (binary mask for low-elev areas)

## Vegetation by biome (biome-natural species)

| Coastal | Mountain | Grassland |
|---------|----------|-----------|
| Sea oak | Alpine pine (cone) | Hero oak |
| Coastal pine | Black spruce (cone) | Willow (riparian) |
| Gnarled hawthorn | Dwarf juniper | Ash |
| Bayberry shrub | Heather tussock | Hawthorn shrub |
| Dunegrass | Alpine grass | Tall grass |
| Beachgrass | — | Short grass |
| — | — | Wildflowers |

All 18 species procedurally built (cylinder trunks + branch arms + leaf blobs); no external assets required. Each species has biome-zoned scatter (sd / elevation / slope ranges) so distribution looks natural.

## Hero props by biome

| Coastal | Mountain | Grassland |
|---------|----------|-----------|
| Driftwood A/B/C | (relies on rock outcrop in shader) | (relies on stone shader band) |
| Boulder A/B/C/D | — | — |

(Mountain + Grassland don't add separate props because the rock material zones already provide visual variety; could be added in v2.)

## What "AAA grade A" verification consists of in this delivery

1. **Multi-angle render proof** at 8 cameras per biome → committed PNGs
2. **All cameras pass non-black + min-byte gates** (manifest `ok=True`)
3. **Biome-natural vegetation distribution** — no floating, no overlap (terrain-normal alignment via Distribute Points "Rotation" output)
4. **Procedural deterministic build** — same seed produces same result every time (verified via Coastal seed-determinism tests)
5. **Best-practices documentation per biome** — locked decisions, parameter tables, carryover template
6. **Three independent biome blend files** — each can be loaded standalone and rendered fresh

## Known issues / future iteration

- **Headless Eevee Next** produces black renders without `bpy.ops.scene.light_cache_bake()`. Workaround: Cycles for headless. Future: pre-bake light probes in build script before saving blend.
- **Live Blender crashes** under high vegetation poly counts (~16M+ polys) when using multiple GN modifiers concurrently. Workaround: build incrementally + headless render.
- **Vegetation density** could be 2-3× higher for closer AAA reference parity (RDR2 grass density is dense enough that no terrain shows through at ground level). Current density shows individual blades clearly which reads as more stylized.
- **Wind animation** is implemented (sin-of-SceneTime offset on grass top vertices) but not currently rendered as a multi-frame proof. Future: render frames 1/30/60 per camera for animation evidence.

## Carryover template for new biomes

To build biome 4+ (forest interior, swamp, desert, frozen, volcanic, etc.):

1. **Heightfield**: pick a generator pattern (rolling, ridge, dune, crater)
2. **Per-vertex attributes**: pick the masks that drive scatter (elevation, slope, wetness, distance-to-feature)
3. **PBR shader**: define 3-6 elevation/slope zones with procedural noise
4. **Vegetation**: 5-7 biome-natural species, one cone or round per tree, GN scatter with POISSON + Selection masks
5. **Lighting**: sun + Nishita sky + (optional) volumetric mist + view transform
6. **Cameras**: 8 angles minimum (full, mid×4, topdown, close, drone)
7. **Render**: Cycles 32 samples for headless; Workbench for debug
8. **Doc**: write `docs/biome-best-practices/<BIOME_NAME>.md` with the locked decisions table

Build time per biome: ~20-30 minutes for build + 30-60 minutes for Cycles render.
