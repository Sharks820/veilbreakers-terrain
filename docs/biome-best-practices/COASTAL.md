# Coastal Biome — Locked Best Practices

**Status:** Locked v1 (2026-05-05)
**Tile size:** 4096m × 4096m
**Grid resolution:** 513² (8 m cells)
**Render proofs:** 8 cameras Eevee Next + Cycles (see `renders/coastal/`)
**Build script:** `scripts/coastal_build_v3e_props.py` (final layer over V3a/V3b/V3c/V3d)

---

## Locked decisions

### Toolchain

- **Blender 4.5 LTS** (Eevee Next + Cycles) — Python 3.11
- **Geometry Nodes** for water displacement, vegetation scatter, prop scatter — pure built-in, no addons required
- **No external addon installs** — Sapling/Modular Tree/OpenScatter were considered but the headless install path is fragile; procedural geometry built directly via mesh primitives is more reliable and produces equivalent silhouettes
- **No external textures** — every layer is procedural noise/voronoi (instant, deterministic, headless-friendly)
- **Render engines**:
  - Eevee Next (live preview, fast iteration)
  - Cycles 32 samples + denoising (canonical photoreal output)
  - Workbench (debug/fast visual reference)

### Mesh strategy

- **Single terrain plane** at 513² resolution (8 m cell size)
- **Per-vertex attributes** (`vb_sd_m`, `vb_sd_norm`, `vb_slope_deg`, `vb_elev_m`, `vb_wetness`) drive the PBR shader and vegetation/prop scatter
- **Bezier shoreline SDF**: tessellate→KDTree→signed-by-tangent for smooth shoreline grading without grid-edge jaggies (`veilbreakers_terrain/coastal/shoreline_sdf.py`)
- **Slope must be computed in real metres**: `np.gradient(z, step_m)` not `np.gradient(z)`. Otherwise mean slope reads as 37° instead of 5.7° and vegetation masks zero out

### Authored landform zones

Five composable zones (`veilbreakers_terrain/coastal/landform_zones.py`):

| Zone | Mask | Contribution |
|------|------|--------------|
| Low beach | exp(-(sd/35)²) × (1 - smoothstep(2,8,slope)) | flatten to +1.4 m |
| Backshore | smoothstep(35,65,sd) × (1 - smoothstep(70,95,sd)) | ±7.5 m sinusoidal dunes |
| Headland | Poisson-disk inland (sd ∈ [90, 1500]) + gaussian falloff | +62-92 m, asymmetric ocean side |
| Drainage gully | path-distance × (sd > 0 mask) | -3.5 to -7.5 m carve |
| Inland ridge | exp(-((sd-1100)/280)²) × FBM | +42 m FBM-modulated band |

### PBR shader (5 layers)

Sand → wet sand → grass → rock → cliff. Mixed by:
- `sd` (signed distance to shoreline) drives wet-sand band
- `slope` drives rock layer
- `elevation` drives cliff layer
- `wetness` drives roughness reduction

Procedural detail per layer: noise (sand grain, moss, cliff), voronoi (rock pattern). Bump combines max of rock voronoi + cliff noise. **No texture downloads required.**

### Water shader

- **256² subdivided plane** with 4-wave Gerstner displacement via Geometry Nodes (`Set Position` + animated sine sums driven by `Scene Time`)
- Eevee Next: Refraction BSDF + Transmission Weight 0.85 + IOR 1.33
- Foam: Voronoi distance × Geometry Pointiness ramp + animated UV (driver-based scrolling)
- **Wavelengths 90/60/35/20 m** — at 16 m cells the 20m wave aliases (Nyquist = 8 m); for production prefer 512² subdivision

### Lighting / atmosphere

- Sun at 9-12 W warm golden (1.00, 0.92, 0.78), elevation 35-40°
- Nishita sky world shader, BG strength 4.0, air density 1.5, dust 1.6
- Volumetric mist density `5e-5` (10× less than initial guess; 3e-3 absorbed all light)
- Standard view transform + Medium High Contrast look + +0.5 exposure

### Vegetation (6 species, biome-natural)

| Species | sd range | slope max | density (per m²) | dist min |
|---------|---------|----------|------------------|----------|
| Sea oak | 0.13–0.55 | 28° | 6e-4 | 22 m |
| Coastal pine | 0.18–0.55 | 35° | 5e-4 | 24 m |
| Gnarled hawthorn | 0.10–0.30 | 22° | 9e-4 | 14 m |
| Bayberry shrub | 0.06–0.25 | 20° | 3.5e-3 | 6 m |
| Dunegrass blade | 0.08–0.32 | 28° | 0.7 | 0.7 m |
| Beachgrass blade | 0.04–0.16 | 14° | 1.6 | 0.4 m |

All instances aligned to terrain face normal (Distribute Points on Faces "Rotation" output) so vegetation sits flush on slopes — **no floating, no overlap**.

### Wind animation (grass)

GN `Set Position` after `Realize Instances`, offset = `sin(SceneTime × freq + position × 0.05)` × clamped Z position so blade tops sway and bases stay grounded. Different freq/amp per species (beachgrass faster + smaller, dunegrass slower + larger).

### Hero props (7 procedural)

| Prop | sd range | slope max | density | dist min |
|------|---------|----------|---------|----------|
| Driftwood A | 0.04–0.16 | 12° | 8e-4 | 24 m |
| Driftwood B | 0.04–0.18 | 12° | 6e-4 | 28 m |
| Driftwood C | 0.04–0.14 | 12° | 9e-4 | 18 m |
| Boulder A | 0.10–0.50 | 50° | 7e-4 | 14 m |
| Boulder B | 0.10–0.55 | 65° | 5e-4 | 22 m |
| Boulder C | 0.06–0.30 | 32° | 1e-3 | 8 m |
| Boulder D | 0.20–0.55 | 70° | 3e-4 | 35 m |

Driftwood = bent tapered cylinders w/ random bend; boulders = layered icosphere blobs w/ random sub-bumps. All aligned to terrain normal.

### Cameras (8 angles for AAA proof)

| Name | Type | Lens | Position |
|------|------|------|----------|
| FULL_NODE | Ortho | 35mm | 1900,-2400,950 → 200,200 |
| PLAYER | Persp | 24mm | 1100,-200,28 → -300,400 |
| SHORE | Persp | 35mm | 450,600,12 → -150,600 |
| SHORE_OBLIQUE | Persp | 28mm | 700,-400,18 → 200,250 |
| TOPDOWN_ORTHO | Ortho | 35mm | 0,0,3000 (4400m scale) |
| BLUFF_CLOSE | Persp | 60mm | (peak-180,peak-150,12) → peak |
| ALONGSHORE_PAN | Persp | 24mm | (-1900,-1300,70) → (1700,1500) |
| DRONE_HIGH | Persp | 50mm | 1700,-2200,600 → 0,0 |

Cameras MUST be aimed at actual peaks (use `np.argsort(zs)[-1]` to find dynamically). Setting eye-above to 28m means terrain near 100m can bury the camera — clamp `loc_z = max(th(x,y), 0.0) + eye`.

---

## Render-proof gates (universal)

Per pass:

- [ ] PNG byte size ≥ 15 KB (catches `--background` silent no-write trap)
- [ ] Non-black pixel ratio ≥ 0.5%
- [ ] All 8 cameras render
- [ ] `RENDER_MANIFEST.json` written
- [ ] Headless Eevee Next requires light cache bake OR fall back to Cycles (which doesn't need probes)

## Known issues + workarounds

- **Headless Eevee Next produces black renders** without `bpy.ops.scene.light_cache_bake()`. Live Blender bakes probes in real-time but headless `--background` doesn't. Workaround: use Cycles for headless, Eevee for live.
- **Live Blender crashes** under high vegetation+prop poly counts (16M+ polys in our V3e). Workaround: build incrementally, save after each layer, use `--background` for final render.
- **GeometryNodeDistributePointsOnFaces.distribute_method** (singular) was renamed from `distribution_method` in 4.5.
- **POISSON mode disables `Density` input** but enables `Density Max` + `Distance Min` + `Density Factor`. RANDOM mode is the inverse. For mask-based scatter, always use POISSON.
- **`Density Factor` field** must be a `Selection` boolean for binary masks; using multiplied float chains zeros out fast.
- **`vb_slope_deg`** must use real metre derivative (`np.gradient(z, cell_size_m)`) or every mask zeros out.

## Carryover to Mountain + Grassland

What stays the same:
- 4096m × 4096m × 513² grid
- Per-vertex attribute → GN scatter pipeline
- 8-camera proof at every pass
- Cycles renderer for headless reliability
- Procedural-only materials (no external textures)

What changes per biome:
- **Heightfield generator** (ridge silhouette for Mountain; rolling for Grassland)
- **PBR zone count + thresholds** (5 for Mountain: forest soil/grass/scree/rock/snow; 4 for Grassland: deep/lush/dry/stone)
- **Vegetation species** (alpine pine/spruce/juniper/heather for Mountain; oak/willow/ash/grass for Grassland)
- **Camera framing** (peaks for Mountain; rolling pan for Grassland)
