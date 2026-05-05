# Grassland Biome — Locked Best Practices

**Status:** Locked v1 (2026-05-05)
**Tile size:** 4096m × 4096m
**Grid resolution:** 513² (8 m cells)
**Z range:** ~ -5 to ~38 m (low rolling spread)
**Render proofs:** 8 cameras Cycles 32 samples
**Build script:** `scripts/grassland_full_build.py`

---

## Locked decisions

### Heightfield generator

- **Soft-only FBM** (no ridge sharpening — grassland is rolling, not jagged):
  - Macro 3 octaves × 26m amplitude
  - Mid 4 octaves × 8m
  - Fine 3 octaves × 2m
- **River band** along y≈200 with sin(x*0.003) wobble × 60m amplitude — carves -4m
- **Pond** at (-1100, -1000) radius 380m — carves -5m
- **3 soft hilltops** for tree clumps: (800,-700,30), (-700,1200,25), (1500,800,35) — anchor max-blend
- **Floor** at natural minimum (negative) — water plane covers low areas

### PBR shader (4 zones)

| Zone | Mask | Color base |
|------|------|------------|
| Deep soil | water_mask (low areas) | (0.16, 0.20, 0.10) |
| Lush grass | mid elevation, low slope | (0.30, 0.42, 0.16) |
| Dry meadow | elev > 18m | (0.50, 0.45, 0.22) |
| Stones | slope > 18° | (0.45, 0.42, 0.36) |

Roughness uniform 0.85 (grass + soil are dull).

Bump combines max of `stone_voronoi.Distance` + `deep_noise.Fac`. Bump strength 0.55 (subtler than mountain).

### Water plane

Sea-level plane at z=0.05 covering tile, BSDF transmission 0.5, alpha 0.7, roughness 0.08. Catches all `z < 0.05` areas naturally — produces the river + pond visually without needing a separate water mesh per feature.

### Vegetation (7 species, riparian-aware)

| Species | Elevation | Slope max | Density | Dist min | Notes |
|---------|-----------|----------|---------|----------|-------|
| Hero oak | 12–32 m | 18° | 2e-4 | 60 m | Sparse hill-top hero, large crown |
| Willow | 1–6 m | 16° | 1e-3 | 18 m | Riparian, near river/pond |
| Ash | 10–25 m | 22° | 5e-4 | 30 m | Mid-elev belt |
| Hawthorn shrub | 4–30 m | 20° | 3e-3 | 6 m | Everywhere on grass |
| Tall grass | 2–35 m | 28° | 1.5 | 0.4 m | Dense everywhere |
| Short grass | 1–12 m | 22° | 2.5 | 0.3 m | Low elev only (river banks) |
| Wildflowers | 2–30 m | 18° | 0.4 | 0.8 m | Open meadow patches |

Hero oaks intentionally rare (60m min spacing) — produces "lone tree on hill" silhouettes that read as iconic landmarks.

Willows specifically gated to elev 1-6m so they appear ONLY along the river and around the pond — natural riparian distribution.

### Lighting

- Sun 8.0 W neutral (1.00, 0.96, 0.88), elevation 40° (mid-day pastoral)
- Nishita sky, BG strength 4.0, dust 0.8 (clear summer day)
- No volumetric (clear air; saves render time)
- Standard view + Medium High Contrast + +0.3 exposure

### Cameras (8 angles)

| Name | Type | Lens | Position | Notes |
|------|------|------|----------|-------|
| FULL_NODE | Ortho | 35mm | 1900,-2400,600 → 200,200 (3800m) | Whole tile overview |
| VALLEY | Persp | 28mm | -300,-300,12 → 800,0 | Player-walking-through-grass POV |
| HILLTOP_CLOSE | Persp | 60mm | 700,-700,10 → 1000,-500 | Hero oak silhouette close |
| RIVER_OBLIQUE | Persp | 24mm | 300,-100,6 → -200,300 | Riparian willow shot |
| TOPDOWN_ORTHO | Ortho | 35mm | 0,0,2000 (4400m) | Pattern density top-down |
| GRASS_CLOSE | Persp | 80mm | 300,600,1.5 → -50,600 | 1.5m above ground, blade-level |
| PAN_LONG | Persp | 24mm | -1900,-1300,35 → 1700,1500 | Diagonal pan across tile |
| DRONE_HIGH | Persp | 50mm | 1700,-2200,500 → 0,0 | Aerial overview |

GRASS_CLOSE camera at 1.5m altitude with 80mm lens captures grass-blade detail and animated wind motion (when frame > 1).

## Carryover from Coastal + Mountain

- 4096m × 4096m × 513² grid
- Per-vertex attribute → GN scatter pipeline
- 8-camera multi-angle proof
- POISSON scatter + `Selection` boolean masks
- Cycles 32 samples canonical renderer
- Procedural-only materials

## What changed from Mountain

- 4 PBR zones instead of 5 (no snow)
- Water plane added (covers low river + pond)
- Hardwood trees (oak/willow/ash) instead of conifers
- 7 species instead of 5 (more variety because biome is more uniform geographically)
- Mid-day neutral sun instead of warm alpine sun
- No volumetric (clear summer)
- GRASS_CLOSE camera at blade-height (1.5m) for foreground detail proof
