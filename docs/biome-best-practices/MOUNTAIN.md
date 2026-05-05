# Mountain + Forest Biome — Locked Best Practices

**Status:** Locked v2 (2026-05-05)
**Tile size:** 4096m × 4096m
**Grid resolution:** 513² (8 m cells)
**Z range:** 18.6 to 320.0 m (245 m vertical spread)
**Render proofs:** 8 cameras Cycles 32 samples + 8 cameras Workbench
**Build script:** `scripts/mountain_from_coastal_template.py` + `scripts/mountain_render_cycles.py`

---

## Locked decisions

### Heightfield generator

- **Macro FBM** (4 octaves, base_freq 0.0006, persistence 0.55, lacunarity 2.05): broad mountain shapes
- **Ridge sharpening** `1 - |fbm|` raised to power 1.6: produces narrow ridge lines
- **Combine** `macro × 80 + ridge × 240`: ~320m peak relief
- **Valley carve** along y=-300, smoothstep band 600m wide: -25m valley floor
- **3 dominant peaks** anchored via `np.maximum`-blend: (1100,500,320), (-900,-1100,280), (1500,-1500,240)
- **Floor at z=-5m** (small lakes possible in deep valleys)

### PBR shader (5 zones)

| Zone | Elevation | Slope gate | Color base |
|------|-----------|-----------|------------|
| Forest soil | z 5-25 | — | (0.20, 0.18, 0.13) deep |
| Alpine grass | z 100-200 | — | (0.26, 0.32, 0.18) |
| Scree | z 200-260 | — | (0.50, 0.46, 0.40) |
| Rock | — | slope > 35° | (0.36, 0.34, 0.31) |
| Snow cap | z > 260 | — | (0.95, 0.96, 0.99) |

Layer mix order: forest → alpine → scree → rock (slope override) → snow (high-elev override).

Roughness ramp: snow_mask=0 → 0.92 (rough rock); snow_mask=1 → 0.55 (smoother snow).

Bump combines max of `rock_voronoi.Distance` + `scree_voronoi.Distance`. Bump strength 0.85, distance 0.18.

### Vegetation (5 species, alpine-natural)

| Species | Elevation | Slope max | Density | Dist min | Shape |
|---------|-----------|----------|---------|----------|-------|
| Alpine pine | 8–130 m | 38° | 8e-4 | 16 m | Cone (4 stacked blobs) |
| Black spruce | 10–120 m | 35° | 6e-4 | 20 m | Cone (4 stacked blobs) |
| Dwarf juniper | 80–200 m | 40° | 2.5e-3 | 4 m | Round (canopy) |
| Heather tussock | 120–230 m | 42° | 4e-3 | 2.5 m | Round (small) |
| Alpine grass blade | 80–240 m | 38° | 1.0 | 0.5 m | Triangle blade |

All instances aligned to terrain face normal. Conical canopies for pine/spruce produce real evergreen silhouettes via stacked blobs of decreasing radius.

### Lighting

- Sun 9.0 W warm (1.00, 0.94, 0.85), elevation 35° (alpine — cooler than coastal golden)
- Nishita sky, BG strength 4.0
- Volumetric mist density 6e-5 (very light alpine air)
- Standard view + Medium High Contrast + +0.5 exposure

### Cameras (8 angles)

| Name | Type | Lens | Position |
|------|------|------|----------|
| FULL_NODE | Ortho | 35mm | 1900,-2400,1100 → 200,200 (3800m scale) |
| VALLEY | Persp | 28mm | -200,-200,60 → 1100,500 |
| RIDGE_CLOSE | Persp | 60mm | 700,200,30 → 1100,500 |
| FOREST_OBLIQUE | Persp | 28mm | -300,0,40 → 200,800 |
| TOPDOWN_ORTHO | Ortho | 35mm | 0,0,3000 (4400m scale) |
| SNOWCAP_CLOSE | Persp | 50mm | 700,0,30 → 1100,500 |
| ALONGSHORE_PAN | Persp | 24mm | -1900,-1300,70 → 1700,1500 |
| DRONE_HIGH | Persp | 50mm | 1700,-2200,900 → 0,0 |

### Render engine

- **Cycles** is the canonical renderer (32 samples + denoising). Headless Eevee Next produces black renders without `light_cache_bake`; Cycles works directly without probe baking.
- **Workbench** is the fast visual reference (under 30s for all 8 cameras).
- Both renders committed for every Mountain build.

## Carryover from Coastal

- Same 4096m × 4096m × 513² grid
- Same per-vertex attribute → GN scatter pipeline
- Same 8-camera multi-angle proof discipline
- Same procedural-only material approach
- Same POISSON-mode scatter with `Selection` boolean field for binary masks

## What changed from Coastal

- 5 elevation/slope zones instead of 5 sd/wetness zones
- No water shader (mountain has no shoreline; just small lake floor at z=-5)
- Conical canopy trees instead of round canopy hardwoods
- Alpine sun (cooler color, lower elevation) instead of golden coastal sun
- Camera angles aimed at peaks instead of headlands
