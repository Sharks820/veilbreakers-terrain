# VeilBreakers Biome Render Rebuild — Design Spec

> **Status:** Draft for review
> **Date:** 2026-05-05
> **Branch:** feat/dynamic-quality-audit (spec doc only; implementation goes to feature-scoped branches)
> **Author:** Conner + Claude (brainstorming session 2026-05-05)
> **Supersedes:** All ad-hoc per-biome build scripts (`coastal_build_v3*`, `mountain_build_v1_full`, `grassland_full_build`, `render_*`), legacy `terrain_unity_export.py`
> **Honest grade target:** A- minimum on pilot, A on template polish, against shipped-AAA HDRP terrain bar

---

## 0. Problem Statement (verbatim from user critique)

> "The valley with grass and trees is probably the best of all the renders... a lot of your photos were totally black... mountains are not at all mountains but maybe a hilly area... the nodes are way too massive... we needed to utilize a node parameter that allowed for puzzle piece type drop ins for unity... your foliage in the mountains especially is all diagonal and does not look real... grass finally looks decent but it has no separation and is one constant height across the entire environment when in reality if you ultrathink and research real natural [seasons] you'd see how grass truly grew."

**Concrete failures identified:**
1. ~30% of frames are unlit (lighting / exposure not converged for headless Cycles)
2. Props inside trees (no inter-species exclusion masks)
3. Mountain peak relief 1:12.8 ratio (320m on 4096m tile) — reads as "hilly area," not mountains
4. Per-biome `.blend` "nodes" too massive to open without crashing Blender (~85k trees + millions of grass blades realized into single file)
5. No chunk system / no edge-stitch contract for Unity puzzle-piece traversal
6. Trees use `align_to_normal=True` → diagonal trunks on slopes (real trees have negative geotropism, grow vertical)
7. Grass = single 8-vert blade with no zonal variation, uniform height field
8. Foliage software unknown to user (was custom Python `make_tree()` primitives, not L-Py / MTree / Sapling / SpeedTree)
9. Honest export grade vs shipped AAA HDRP: F (~10% of 42-item contract)

**Source-of-truth evidence:** `scripts/coastal_build_v3d_vegetation_v2.py`, `scripts/mountain_build_v1_full.py`, `scripts/grassland_full_build.py`, `docs/aaa-audit/deep_dive_2026_04_27/F2_hdrp_export_completeness.md`, `docs/aaa-audit/batch15_2026_05_04/scan_03_water_system.md`.

---

## 1. Locked Decisions Register

Every decision below was negotiated with the user during the 2026-05-05 brainstorming session. Each is the final, durable design commitment.

| # | Decision | Choice | Rationale |
|---|---|---|---|
| Q1 | Chunk size | **512m × 512m** | AAA mid-range default (Skyrim/Elden Ring zone-cell). 64-piece puzzle per 4096m biome zone. Keeps Blender responsive. |
| Q2 | Edge contract depth | **C: heights + structural masks + feature threads** | Continuous rivers/roads/ridges across chunks; per-chunk `edges.json` with N/S/E/W edge structs |
| Q3 | Vertex resolution | **257 verts/side, 2m grid, ~66k verts/chunk** | Encodes individual rocks, cart ruts, micro-erosion in heightfield itself |
| Q4 | Heightmap source | **Hybrid DEM + procedural detail, Gaea/Houdini-quality bar** | NASA SRTM 30m macro + 3-octave fbm overlay + Taichi erosion + drainage |
| Q5 | Compute backend | **Taichi-CUDA primary, CPU fallback** | Free MIT license, AAA-grade (Embark, Coalition), 50–200× over NumPy on RTX 4060 Ti |
| Q6 | Foliage stack | **MTree filler + L-Py hero + vertical-Z trunks + exclusion masks** | Real branched topology, kills diagonal-tree bug, structurally prevents props-inside-trees |
| Q7 | Grass system | **L-Py blade variants + zonal Voronoi field + 12-24 baked variants per species + 3-tier LOD** | Real grass complaint is field problem (not blade problem); GoT-style Voronoi clumping breaks "one constant height" |
| Q8 | Render contract | **A: three-light + ACES + manual exposure** | AAA-cinematic. Sun key 50° altitude + sky-bounce fill 30% + rim 10%. Filmic+ACES. 95%+ nonblack guarantee. |
| Q9 | Unity import | **C: hybrid Unity Terrain (heightmap+splat) + Addressables prefabs (foliage/water/props)** | Uses both pipeline outputs in their native lossless forms. HDRP committed (verified in code). |
| Q10 | Pilot scope | **Mountain + grassland end-to-end first** | Stresses heightmap (mountain) + foliage (grassland) — exercises ~80% of pipeline surface |
| Q11 | Acceptance gate | **C: functional + visual + reference parity** | A- minimum, A target. Reference-photo plausibility (Carpathians + Yorkshire). Promotion gate to template. |
| Q12 | Runtime water stack | **A: HDRP built-in water (free, native, AAA) + custom waterfall mesh + custom lava emissive** | Unity 2026 strategy: HDRP maintenance mode but still ships free water; URP migration deferred to future project |
| Q13 | Lava treatment | **A: custom emissive surface shader (NOT through water)** | Lava emits light, doesn't refract — water shader produces wrong physics |
| Q14 | Anti-tile / triplanar / macro / distance normals | **A: free ultrathink stack** | Per-chunk unique macro variation + ground-clutter scatter + HDRP Shader Graph custom variants. $0. Fallback: MicroSplat $120 if blocked. |
| Q-jungle | Jungle scope | **B: jungle-style assets as wet-zone overrides on coastal+grassland** | No 7th biome; cloud-forest aesthetic available via `wet_zone_override` mask in highest-moisture sub-zones |

---

## 2. Architecture Overview

Two-stage pipeline: **Bake** (offline, Python + Blender + Taichi) produces deterministic per-chunk artifacts; **Runtime** (Unity HDRP) consumes them with native streaming.

```
┌────────────────────── BAKE STAGE (offline) ──────────────────────┐
│                                                                   │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐       │
│  │ DEM (SRTM│ → │ Heightmap│ → │ Erosion  │ → │ Mask     │       │
│  │ 30m) +   │   │ hybrid   │   │ (Taichi  │   │ channels │       │
│  │ procedur │   │ 4m grid  │   │ hyd+therm│   │ (50+)    │       │
│  │ overlay  │   │ upscale  │   │ +flow+   │   │          │       │
│  │          │   │          │   │ strat)   │   │          │       │
│  └──────────┘   └──────────┘   └──────────┘   └──────────┘       │
│                                                  ↓                │
│                                  ┌─────────────────────────┐      │
│                                  │ Slice to 64 chunks      │      │
│                                  │ (8×8 grid, 512m each,   │      │
│                                  │  257² verts per chunk)  │      │
│                                  └─────────────────────────┘      │
│                                                  ↓                │
│       ┌──────────────┬───────────┴───────────┬──────────────┐    │
│       ↓              ↓                       ↓              ↓    │
│  ┌─────────┐   ┌─────────┐            ┌──────────┐  ┌─────────┐  │
│  │ Foliage │   │ Hero    │            │ Edge     │  │ Splat   │  │
│  │ scatter │   │ + grass │            │ data     │  │ + macro │  │
│  │ + ground│   │ + props │            │ + water  │  │ + holes │  │
│  │ clutter │   │         │            │ threads  │  │ + AO    │  │
│  └─────────┘   └─────────┘            └──────────┘  └─────────┘  │
│       ↓              ↓                       ↓              ↓    │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ Per-chunk artifacts (10+ files):                            │ │
│  │   terrain.raw, splat.png, splat_secondary.png, holes.png,   │ │
│  │   layers/{0..7}_{albedo,normal,mask,height,detail}.png,     │ │
│  │   foliage.json, grass.json, water.json, edges.json,         │ │
│  │   flow_map.png, macro_variation.png, navmesh.png,           │ │
│  │   probes.json, decals.json, meta.json                       │ │
│  │   caves/*.fbx (optional per chunk)                          │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                  ↓                                │
│                       ┌──────────────────┐                        │
│                       │ ACES Cycles      │                        │
│                       │ render proofs    │                        │
│                       │ (8 cam × 64      │                        │
│                       │  chunks + hero + │                        │
│                       │  traversal MP4)  │                        │
│                       └──────────────────┘                        │
└───────────────────────────────────────────────────────────────────┘
                                 ↓
┌──────────────────── RUNTIME STAGE (Unity HDRP) ────────────────────┐
│                                                                     │
│  Addressables → VbChunkLoader → Unity Terrain (heightmap + splat) │
│                                  + custom HDRP TerrainLit variant  │
│                                  (triplanar + anti-tile + distance │
│                                  normal blend)                     │
│                              → HDRP Water (ocean/river/lake)       │
│                              → Prefab instantiation (foliage/props)│
│                              → Terrain.SetNeighbors() from edges   │
│                              → Edge-weld assertion (fail-fast)     │
│                              → HDRP Decals + Probes + Fog volumes  │
│                              → Audio zones + Navmesh hints         │
└─────────────────────────────────────────────────────────────────────┘
```

**Key architectural properties:**

1. **Heightmap is the primary product.** Everything else (masks, foliage, splat, water, renders) derives from it.
2. **Bake before slice.** Erosion, drainage, stratification run on the merged 4096m field before chunking, so seam-spanning features (rivers, ridges) carry across chunks naturally.
3. **Many small files per chunk** — never one big monolithic `.blend`. The "node won't open in Blender" failure mode is structurally impossible.
4. **Determinism is per-chunk.** Each chunk seeds from `hash(biome, chunk_x, chunk_y, version)`. Single-chunk re-bake supported.
5. **Two pipelines, one source of truth.** Blender renders are *proofs*, not the shipping asset. Unity Terrain consumes the same heightmap/splat/instance data.
6. **HDRP committed.** Unity render pipeline = HDRP (verified in `terrain_unity_export.py:357-411`, `_pack_hdrp_mask_map`, `_flip_normal_y`, F2 audit). URP migration is a separate future project.

---

## 3. Heightmap Pipeline

Runs once per biome on the merged 4096m field, before chunk slicing. Total wall-clock target on RTX 4060 Ti: **30–45 seconds per biome**.

### 3.1 — Stage 3.1: DEM macro source (Python, ~3 sec)

```
NASA SRTM 30m tile  →  resample to 4096m square  →  upscale 30m → 2m
                       (cubic interp + sub-pixel jitter to break grid regularity)

Reference range per biome (locked):
  mountain:   Carpathian foothills (Tatry / Bieszczady) — moody broken ridges
  grassland:  Yorkshire Dales / Welsh borderlands — rolling temperate
  coastal:    Scottish Hebrides / Pembrokeshire — cliffs + headlands
  volcanic:   Aeolian Islands / Iceland highlands
  frozen:     Greenland Norse coast / Spitsbergen
  desert:     Wadi Rum / Sinai (or VeilBreakers hostile-aesthetic alternate)
```

DEM provides macro silhouette only. We never ship recognizable real geography because procedural overlay (3.2) and erosion (3.3) reshape the surface. License: SRTM is public domain.

### 3.2 — Stage 3.2: Procedural detail overlay (Taichi, ~2 sec)

3-octave fbm at 4m / 16m / 64m wavelengths, amplitudes 0.5m / 2m / 6m. Seeded from `hash(biome, version)`.

### 3.3 — Stage 3.3: Erosion suite (Taichi-CUDA, ~25–35 sec)

Three passes in sequence on the merged field:

```
(a) Hydraulic — Mei et al. 2007 shallow-water flux solver
    Fields: water_depth, sediment, flux_LR/UD, velocity_xy
    200 iterations, dt = 0.1, rain rate = 0.012 m/iter
    Produces: river valleys, deposition fans, eroded slopes
    Cost: ~12-18 sec on RTX 4060 Ti at 4096²

(b) Thermal/talus — angle-of-repose redistribution
    50 iterations, talus angle = 33° (loose rock), 45° (consolidated)
    Produces: scree fans below cliffs, smoothed ridge tops
    Cost: ~3-5 sec

(c) Stratification erodibility modulation
    Wires existing terrain_stratigraphy.py (A-grade, currently unwired per audit)
    Layered noise modulates per-pixel erodibility, then re-runs 50 hydraulic iters
    Produces: banded cliff faces — visible rock layers cut by erosion
    Cost: ~5-8 sec
```

**Bug fixes folded in:**
- E-1 (audit P0, `_terrain_erosion.py:308`): Taichi solver uses calibrated Mei et al. constants, NOT the buggy 1000× erodibility values.
- E-2 (audit P0, `terrain_stratigraphy.py:991`): explicitly re-runs hydraulic AFTER stratification weights so the modulation actually affects the heightmap.
- E-3 (audit P0): pure-Python loop replaced by Taichi GPU kernels.

### 3.4 — Stage 3.4: Drainage + Water Network Extraction (Taichi, ~5 sec)

Single source of truth for ALL water types. Replaces the W-1 dual-semantics bug by emitting non-overlapping channels:

```
(a) D8 flow direction               vector field from hydraulic step
(b) flow_accumulation                upstream catchment area per pixel
(c) channel_carve_depth              heightmap lowered 1.5-4m where
                                     flow_accum > river_threshold
(d) water_surface_z                  SINGLE-SEMANTIC absolute Z of water surface
                                     ocean: sea_level (0m) where terrain_z < sea_level
                                     lake:  local_min from depression-fill
                                     river: terrain_carved_z + bed_offset (0.3-1.2m)
                                     no water: NaN sentinel
(e) water_depth                      water_surface_z - terrain_z, clamped >= 0
(f) shoreline_mask                   |terrain_z - water_surface_z| < 1.0m, smoothed
(g) wet_fetch                        distance from nearest shoreline, clamped 0-6m
(h) flow_velocity_xy                 2-channel velocity from hydraulic solver,
                                     averaged last 50 iterations
(i) foam_potential                   max(velocity_mag > 1.5, wave_fetch > 50m, waterfall)
(j) waterfall_mask                   slope > 60° AND flow_accum > river_threshold
                                     each connected component → waterfall instance
(k) caustic_mask                     water_depth in [0.1, 3.0]
(l) wave_fetch                       per-shoreline-pixel distance to open water interior
```

**W-1 fix structural:** replace ambiguous legacy `water_surface` with `water_surface_mask` (binary) + `water_surface_elevation_m` (absolute Z) + `water_depth_m` (delta). All 4 consumers (`detect_wetlands`, `pass_water_variants` seed merge, `pass_bathymetry`, `compute_riverbed_caustics`) migrate. Add `TerrainMaskStack.set()` guard rejecting legacy name.

### 3.5 — Stage 3.5: Mask channel production (existing 1875-callable pipeline, ~5 sec)

Wire existing pipeline to read post-erosion heightmap, produce the 50+ derived channels:

```
vb_slope_deg, vb_elev_m, vb_elev_norm, vb_curvature
vb_moisture (drainage-weighted), vb_TWI
vb_aspect_deg (compass-direction slope), vb_aspect_north (dot with +Y)
vb_ridge_mask, vb_cliff_mask, vb_riparian_mask, vb_disturbance
vb_canopy_openness (initially 1.0, refined after foliage scatter)
per-biome zone IDs for shader splat
... etc.
```

### 3.6 — Stage 3.6: Chunk slicing (Python, ~2 sec)

```
Merged 2049² verts (4m grid)  →  64 chunks of 257² verts each
Edge sharing: chunk[i,j].east_verts == chunk[i+1,j].west_verts (vert-shared, not duplicate)
Edge contract written to chunk_<x>_<y>_edges.json from same source data
Heights serialized to 16-bit raw for Unity Terrain native import
Splat textures composed from biome-zone masks → splat.png + splat_secondary.png
```

### 3.7 — Determinism guarantees

- Same `seed = hash(biome, version)` → identical heightmap pixel-for-pixel
- Single-chunk re-bake possible (re-slice from cached merged field)
- `version_hash = sha256(pipeline_git_sha + biome_yaml + taichi_kernel_sha + dem_blob_sha)` stored in every chunk's `meta.json`

---

## 4. Foliage System

### 4.1 — Algorithmic Foundation

Stack ordered for ecological correctness, applied per chunk:

```
1. Resource-competition convolution (REDengine 3 / Witcher 3, GDC 2014)
   moisture × slope × elevation × shadow_fraction → forest_potential field

2. Reaction-diffusion mask (Klausmeier / Rietkerk)
   Gray-Scott solver injects noise into forest_potential → clump_probability
   Breaks periodicity; produces irregular clumps with natural gaps

3. Variable-radius Poisson-disk scatter (Bridson 2007)
   Within clump_probability mask
   Radius varies: 60m open zones, 8m dense zones

4. Voronoi-colony sapling sub-scatter (mother-tree mycorrhizal pattern)
   For each placed tree above size threshold:
     micro-Poisson at 0.5× radius, 3-8 saplings same species in 5-15m radius
   Encodes Simard et al. mother-tree research; Eastshade production rule

5. Hero tree candidate scoring (manual override list)
   ridge_curvature + river_bend_curvature + clearing_centroid
   → 5-10 hero candidates per chunk, exposed for manual override before bake

6. Voronoi clumping for grass field (Sucker Punch Ghost of Tsushima, GDC 2021)
   Each Voronoi cell carries dominant_height + species_id + density
   Per-blade height = lerp(H_min, H_max, M) × clump_offset[0.8, 1.25]
   The clump_offset alone breaks "one constant height"

7. Canopy openness derivation
   Top-down depth render of placed canopy → openness mask
   Drives undergrowth species selection inversely (HZD light-gap rule)

8. Path/disturbance suppression
   path_mask multiplied through undergrowth density
   Edge boost: +10-20% fern density at path edges (moisture retention)

9. Ground-clutter scatter (NEW — anti-tiling via content)
   5-30 props/m² of small stones, twigs, dead leaves, pebbles, grass tufts
   Density driven by biome_lush_ceiling × disturbance × seasonal
   Same scatter pipeline as foliage, downstream of all other masks
```

### 4.2 — Mask channels consumed

```
TWI = ln(upslope_area / tan(max(slope_rad, 0.001)))     # Terrain Wetness Index
aspect_north = dot(slope_normal, vec3(0, 1, 0))         # North-facing weight
moisture_M = saturate((TWI - TWI_min) / (TWI_max - TWI_min))
slope_S = 1 - saturate((slope_deg - 15) / 25)           # 1 at flat, 0 at 40°+
disturbance_D = 1 - path_mask
biome_lush_ceiling = per-biome cap [0.2 desert ... 1.0 grassland]

L = M × S × D × biome_lush_ceiling
class = bucket L into {sparse: <0.15, cropped: <0.40, meadow: <0.72, lush: >=0.72}
```

### 4.3 — Three-Tier Stack

| Tier | Tool | Tris each | Density | Variants |
|---|---|---|---|---|
| Hero trees | L-Py + PlantGL | ~5k | 5–15/chunk, scored | 1–3 per biome |
| Filler trees | MTree (`bypass_operator`) headless | 1–2k | 200–800/chunk Poisson | 4–6 species × 3 ages |
| Grass blades | L-Py baked variants | 50–200 | 30k–80k/chunk GN-instanced | 12–24 per species |

All vertical-Z (no `align_to_normal`). Base flare merge on bottom 10cm of trunk vertices snapped to terrain Z, blended over next 30cm.

### 4.4 — Five-Layer Stratification (forest biomes)

```
Layer        Height     Density (per ha)    Notes
Emergent     30-50m     1-3                 Hero tier; ridge crests, river bends
Canopy       12-30m     150-400             Filler tier; mass forest
Understory   3-12m      500-800             Subcanopy palms, juvenile species
Shrub        0.5-3m     thousands           Ferns, large-leaf plants
Herb/floor   0-0.5m     millions instances  Moss, fungi, litter, herbs
```

**Inverse-canopy rule:** closed canopy (>80%) → moss carpet + lichen, almost no shrub layer (boreal/spruce signature). Open canopy (<30%) → grass/forb explosion (deciduous gaps).

### 4.5 — Per-Biome Species Inventory

See **Appendix B** for full inventory. Headlines:

- **Mountain pilot:** alpine pine, Engelmann spruce, dwarf juniper, sheep fescue, alpine bluegrass; cushion plants only above treeline.
- **Grassland pilot:** lone old oak hero, Big Bluestem (1.5–3m blue-green→copper), Switchgrass, Indiangrass, Buffalo Grass sward, cattails/sedges riparian, full wildflower mix.
- **Coastal:** sea oak hero, weathered cypress, marram dune-binder, salt marsh cordgrass.
- **Volcanic:** scorched-bark pine survivors, lichen→moss→fern→shrub age-zoned succession on cooling lava.
- **Frozen:** dwarf willow prostrate mats, krummholz pockets, sedges, cottongrass, reindeer lichen — no tall trees.
- **Desert (post-pilot):** **Boojum tree, Dragon Blood Tree, bleached saguaro husks, Ocotillo whip-stems, Jumping cholla ghost-stands, Agave spent flower spikes** (rejecting touristy Sonoran). Creosote allelopathic 1.5–3m exclusion rings. Tiger bush slope bands. Biological soil crust 70–80% surface.
- **Wet-zone overrides (jungle option B):** cloud-forest mossy giants 20–35m (no buttress roots), gnarled dark canopy, prehistoric ferns, dark-leaved palms, **bioluminescent emissive mushrooms**, vine/liana catenary curves, strangler-fig lattice columns. Triggered by `(TWI > 8.5) AND (canopy_openness < 0.3) AND biome ∈ {coastal, grassland}`.

### 4.6 — Inter-Species Exclusion Order (kills "props inside trees")

```
1. Hero tree positions  → 15m radius footprint, locked first
2. Filler trees Poisson, exclude hero footprints → tree_footprint accumulates 4m radius each
3. Shrubs/ferns, exclude tree_footprint → dense_veg_mask 1.5m radius each
4. Wildflowers, exclude dense_veg_mask → ground_clutter 0.3m radius each
5. Grass field, exclude ground_clutter ∪ path_mask ∪ bare_rock_mask
6. Rocks/props/clutter, exclude tree_footprint ∪ path_mask
```

### 4.7 — Desert Turing Patterns (post-pilot)

Replace pure Poisson scatter for desert with reaction-diffusion (Klausmeier/Gilad/Rietkerk):

- Tiger bush bands on 3–15% slopes, perpendicular to slope, 8–20m wide, 15–40m gaps
- Creosote 1.5–3m allelopathic exclusion rings
- Wash/wadi attractor: 5–15m buffer along D8 drainage lines
- Oasis clusters at extreme-flow-accum threshold (rare, 0.01–0.1% of area)
- Biological soil crust as material layer (70–80% coverage), subtracted by track/path mask exposing pale tan underneath
- Nebkha sand drift at 34° angle of repose downwind from every obstacle (length = 12× obstacle height)

### 4.8 — LOD Chain (RTX 4060 Ti budget)

```
LOD0 full geometry           0–40m    2-8k tris, full shader, wind animation
LOD1 reduced geometry        40–100m  branch count halved, leaf-card clusters
LOD2 low-poly shell          100–200m simplified normals, no wind
LOD3 imposter atlas          200–400m 8-16 angle billboard, normal-mapped
Terrain-painted detail       400m+    color/normal blend, no instances
```

**HZD zero-overdraw rule:** depth prepass first (cheap no-color), then G-buffer with depth-equal test → eliminates overdraw cost on the expensive G-buffer write. Single largest perf win for dense forest. Applied to all foliage tiers.

**Crysis dual-wind (GPU Gems 3 Ch.16):** per-instance trunk bend + per-leaf detail bending, GPU triangle-wave (no sine in inner loop). Wind metadata baked to UV2/UV3 vertex channels per SpeedTree convention:

```
UV2 = (sway_freq, branch_amplitude, leaf_flutter, gust_freq)
UV3 = (gust_strength, phase_offset, wind_axis_x, wind_axis_y)
```

### 4.9 — Per-chunk Foliage Output

```
chunk_<x>_<y>_foliage.json:
  {
    hero_trees: [{species_id, position, rotation_y, scale, variant_seed, is_landmark}],
    filler_trees: [...],
    shrubs: [...],
    wildflowers: [...],
    rocks: [...],
    ground_clutter: [...]
  }

chunk_<x>_<y>_grass.json:
  Subdivided into 32m × 32m sub-cells for streaming.
  Each sub-cell: [{species_id, position, rotation_y, scale, variant_id, class}]
  Total ~30k–80k entries per chunk.
```

### 4.10 — Performance Budget

Per-chunk on RTX 4060 Ti:
- Resource-competition + RD pass: ~2 sec
- Hero scoring + scatter: ~1 sec
- Filler Poisson + Voronoi-colony saplings: ~4 sec
- Grass Voronoi field + scatter: ~5 sec
- Shrubs / wildflowers / rocks / ground-clutter: ~3 sec
- **Total per-chunk foliage: ~15 sec.** 64 chunks × 15s ≈ 16 min per biome.

---

## 5. Render System

### 5.1 — Lighting Rig (Q8: A — three-light + ACES)

```
Sun key:       Nishita sky, altitude 50°, azimuth 145° (south-by-southeast)
               Strength 4.5 W/m², color temp 5800K
Sky-bounce:    Nishita sky dome at 30% strength, no sun in dome
               Catches all surfaces sun key misses
Rim:           Distant sun-strength area light at azimuth 325° (opposite)
               10% strength, slight cool tint (4500K)
View:          AGX (Blender 4.5 default) → ACES Filmic preview
               Manual exposure 0.0 EV with grey-card calibration
```

Per-biome overrides:
- Cloud-forest (wet-zone override): sun key × 0.4, dark depth-fog bonus, dappled god-rays via volumetric scatter
- Frozen: sun key × 0.7, blue-shifted (6500K), heavy AO
- Volcanic: sun key × 0.6, warm-shifted (4200K), heavy haze, lava emissive
- Desert: sun key × 1.3, neutral 5800K, hard shadows, low ambient

### 5.2 — Camera Rig (8 per chunk + 8 hero + 4 marketing)

**Character proxy (required for 3rd-person rigs):**

```
Asset:    VB_CHAR_PROXY — generic humanoid, 1.78m tall
          Hierarchical bones for idle/walk/run pose snapshots
          Material: matte mid-grey (#7A7A7A, roughness 0.6) — no lighting bias
Position: chunk_spawn_safe_position — first valid pixel where:
            slope_deg < 25 AND water_depth == 0 AND tree_footprint == 0
            AND NOT inside cliff/cave overhang
          Defaults to chunk_center if center is spawn-safe
          Stored in meta.json deterministically
Pose:     idle (default for QA), walk-forward (for marketing traversal)
Eye:      character_position + (0, 0, 1.65m)
```

**Per-chunk camera set:**

```
Camera                Position relative to char/center        Lens   Output
QA — terrain audit (3):
  isometric           chunk_center + (300, 300, 250)          50mm   2048×1152
  topdown_ortho       chunk_center + (0, 0, 800)              ortho  2048×2048
  sideprofile         chunk_center + (650, 0, 80)             35mm   2048×1152

Player-experience (5):
  third_person_std    char_pos + (0, -4.5, 1.95)              50mm   2048×1152
  third_person_wide   char_pos + (0, -10.0, 3.20)             35mm   2048×1152
  third_person_action char_pos + (1.8, -2.5, 1.55)            35mm   2048×1152
  first_person_pov    char_pos + (0, 0, 1.65)                 35mm   2048×1152
  crouched_pov        char_pos + (0, 0, 0.95)                 50mm   2048×1152
```

Character faces "interesting direction" — scored by nearby features (river, peak, hero tree, water body) within 600m. Falls back to +Y if no landmark scores.

**Per-biome hero cameras (8):** hand-positioned at landmark chunks. 4096×2304, 1024 samples.

**Per-biome marketing traversal (4):** 60-frame walking path, 30fps MP4 + 3 keyframe PNGs each.

### 5.3 — Cycles Settings

```
Engine: Cycles
Device: GPU (OptiX, RTX 4060 Ti)
Samples (QA):       256, adaptive 0.01 noise threshold
Samples (hero):     1024, adaptive 0.005
Denoiser:           OptiX, "high quality" preset, prefilter accurate
Light paths:        Diffuse 4, Glossy 4, Transmission 12, Volume 2
Caustics:           Reflective ON, refractive ON
Persistent data:    ON
Tile size:          256×256 (OptiX optimal)
View transform:     AGX with ACES filmic look
```

Per-chunk render budget: ~60s avg × 8 cameras × 64 chunks = ~8.5 hours per biome QA pass. Hero: 8 × 240s = ~30 min. Traversal: ~4 hours per biome. **Total per biome: ~13 hours render** (overnight bake).

### 5.4 — Output naming

```
renders/pilot/{biome}/qa/chunk_<x>_<y>_<camera>.png
renders/pilot/{biome}/hero/hero_<idx>_<descriptor>.png
renders/pilot/{biome}/traversal/path_<idx>_<descriptor>/frame_NNN.png
renders/pilot/{biome}/traversal/path_<idx>_<descriptor>.mp4
renders/pilot/{biome}/composites/{biome}_8x8_third_person_grid.png    # AAA QA artifact
renders/pilot/{biome}/composites/{biome}_8x8_first_person_grid.png    # AAA QA artifact
renders/pilot/{biome}/composites/{biome}_8x8_isometric_grid.png
renders/pilot/{biome}/reference/comparison_<benchmark>.png
```

The two new player-perspective composite grids are **the most important QA artifacts** — they show what the world looks like to the player at every chunk.

### 5.5 — Acceptance criteria additions for renders

- Character proxy at human scale validates terrain feature scale (mountains feel mountainous next to 1.78m silhouette; grass eats up to crouched player's chest in lush zones)
- Third-person view shows playable, navigable terrain — no impossible cliffs framing the player, no clipping into geometry
- First-person POV at standing height: ~25m visible in lush forest, ~200m+ in open grassland (per biome read)
- Crouched POV shows grass occlusion appropriate to grass class
- No diagonal foliage when character stands on slopes (kills the bug from ground-truth player perspective)

### 5.6 — Render pipeline integration

```
Bake stage produces all chunk artifacts → Render stage reads them → Cycles outputs proofs
Render stage NEVER modifies pipeline state. Read-only visualization of bake.
```

---

## 6. Unity Import Contract (free ultrathink stack)

### 6.1 — Per-Chunk Artifact Manifest (final)

```
output/chunks/{biome}/<x>_<y>/
  ├─ terrain.raw                       # 16-bit unsigned, 257×257
  ├─ splat.png                         # RGBA, 257×257, layers 0-3
  ├─ splat_secondary.png               # RGBA, 257×257, layers 4-7
  ├─ holes.png                         # R8, 257×257
  ├─ macro_variation.png               # RGBA, 512×512, UNIQUE per chunk (anti-tile via content)
  ├─ overlay_dynamic.png               # RGBA, 257×257 (R:wet G:dust B:disturb A:snow)
  ├─ triplanar_mask.png                # R8, 257×257 (1.0 at slope>45°)
  ├─ flow_map.png                      # RG16, 257×257 (water flow direction + magnitude)
  ├─ navmesh.png                       # R8, 257×257 (walkable mask)
  ├─ vertex_ao.bin                     # baked per-vertex AO in vertex_color.r
  ├─ layers/
  │  ├─ layer_0_albedo.png             # 4096² tileable Quixel-tier
  │  ├─ layer_0_normal.png             # tangent-space DX-Y
  │  ├─ layer_0_mask.png               # RGBA: R:Metal G:AO B:Detail A:Smooth
  │  ├─ layer_0_height.png             # R16, parallax/displacement
  │  ├─ layer_0_detail.png             # 1024² high-freq normal+roughness
  │  └─ layer_<1..7>_*                 # same fileset per layer
  ├─ caves/                            # optional, only if cave geometry present
  │  └─ cave_<idx>.fbx                 # static mesh handoff for undercuts
  ├─ foliage.json                      # tree + prop instance list
  ├─ grass.json                        # grass instance list, 32m sub-cells
  ├─ water.json                        # rivers/lakes/waterfalls/ocean
  ├─ edges.json                        # N/S/E/W edge contract
  ├─ probes.json                       # reflection + light probe placements
  ├─ decals.json                       # HDRP decal projector positions
  └─ meta.json                         # biome, seed, version_hash, character_spawn_safe_pos,
                                       # addressable_deps, neighbor_prefetch_hints,
                                       # memory_budget_mb, audio_zones, navmesh_hints
```

### 6.2 — Splat Layer Assignment Per Biome

```
Biome      Layer 0       Layer 1       Layer 2       Layer 3       Layers 4-7
Mountain   alpine_grass  forest_soil   scree         rock          snow, dry_grass, talus, cliff
Grassland  meadow_lush   meadow_dry    river_silt    bare_path     wet_soil, stone, gravel, ash
Coastal    beach_sand    dune_grass    salt_marsh    cliff_rock    wet_sand, kelp, shell, head_grass
Volcanic   ash           pumice        cooled_lava   hot_lava      obsidian, sulfur, tephra, scorched
Frozen     snow_fresh    snow_packed   ice           frozen_soil   bare_rock, lichen, frost, melt
Desert     sand_clean    sand_crusted  cracked_clay  rocky_pave    bio_crust, salt_flat, scree, oasis
```

### 6.3 — Edge Stitch Contract

`edges.json`:
```json
{
  "schema_version": 2,
  "chunk_xy": [4, 3],
  "biome": "mountain",
  "edges": {
    "N": {
      "heights": [257 floats],
      "slope_deg": [...],
      "biome_id": [...],
      "moisture": [...],
      "water_surface_z": [257 floats or NaN],
      "feature_threads": [
        {"kind": "river", "edge_pos": 0.42, "width_m": 8.2, "depth_m": 1.4,
         "flow_velocity_xy": [-1.2, 0.4], "surface_z": 12.6},
        {"kind": "ridge", "edge_pos": 0.08, "ridge_height_m": 240.0,
         "ridge_aspect_deg": 75.0},
        {"kind": "road", "edge_pos": 0.71, "width_m": 3.5, "type": "dirt"}
      ]
    },
    "S": {...}, "E": {...}, "W": {...}
  }
}
```

**Edge-weld assertions on chunk load (fail-fast):**
- `this.S.heights[i]` == `neighbor_north.N.heights[i]` (tolerance 1e-3m)
- `this.S.water_surface_z[i]` matches (NaN-safe, tolerance 0.05m)
- Each `feature_thread` matches at `edge_pos` ±2%

Mismatch → fail-fast log + visible debug overlay in editor (red wireframe at bad edge). No silent seam pop.

### 6.4 — Runtime Stitch Stack (`VbChunkLoader`)

```
OnLoad:
  1. Read meta.json → biome, version_hash, character_spawn_safe_pos
  2. Read terrain.raw → Terrain.terrainData.SetHeightsDelayLOD()
  3. Read splat.png + splat_secondary.png → terrainData.SetAlphamaps()
  4. Read holes.png → terrainData.SetHoles()
  5. Bind layers/* → terrainData.terrainLayers (8 HDRP TerrainLayers)
  6. Bind macro_variation, overlay_dynamic, triplanar_mask, flow_map → custom shader
  7. Read edges.json → store for SetNeighbors() and assertions
  8. Read foliage.json → AddressableAssets.Instantiate(prefab_id, position) per entry
  9. Read grass.json → batched GPU instancing per 32m sub-cell, lazy on player proximity
 10. Read water.json → instantiate HDRP WaterSurfaces:
        ocean_interface  → WaterSurface Ocean type, infinite mesh
        lakes            → WaterSurface Pool type, mesh from polyline
        rivers           → WaterSurface River type, currentMap = flow_map.png
        waterfalls       → custom WaterfallStrip prefab + VFX Graph spray
 11. Read probes.json → Reflection Probe + Light Probe placements
 12. Read decals.json → HDRP Decal Projector instantiation
 13. Read caves/*.fbx if present → GameObject children of chunk
 14. Subscribe neighbor-loaded events → SetNeighbors() + assert edges

OnUnload:
  1. Release Addressable handles
  2. Destroy terrain GameObject
  3. Cleanup HDRP WaterSurfaces (unregister from sim)
  4. Unsubscribe events
```

### 6.5 — Streaming + LOD

```
Streaming radius:
  chunks within 1024m of player are loaded (3×3 region)
  chunks within 2048m are LOD2 (terrain + heroes only, no fillers)
  chunks within 4096m are LOD3 (terrain mesh only, baked albedo)
  beyond 4096m: skybox composite (per-biome panorama)

Foliage LOD chain (per Section 4.8)

Tree HLOD groups: 16 trees per HISM cluster (Hierarchical Instanced Static Mesh)
                  Cluster culls as one unit when no tree-cluster intersects camera frustum

Streaming budget: max 9 chunks Loaded, 16 LOD2, 64 LOD3 simultaneous
                  Hard memory cap: 2GB on chunk artifact data
```

Async load: all reads on background thread; only SetHeights, Instantiate, material-bind on main thread. Chunk load target: <120ms p99.

### 6.6 — HDRP Custom Shader Stack (free ultrathink, $0)

```
hdrp_shader_graph_assets/
  ├─ VbTerrainLitTriplanar.shadergraph     # native Triplanar Sample 2D Array node
  │                                          (top splat layer when slope_dot < 0.55)
  ├─ VbTerrainLitAntiTile.shadergraph       # stochastic sampling Custom Function HLSL
  │                                          (Heitz & Neyret 2018, ~80 lines)
  ├─ VbTerrainLitDistanceNormal.shadergraph # Camera Distance node → Lerp far-normal
  └─ VbTerrainLitOverlayDynamic.shadergraph # blends overlay_dynamic.png (wet/dust/snow/disturb)
                                              over splat result before BSDF
```

Combined into one `VbTerrainLit.shadergraph` Master node. Anti-tile + triplanar + distance blend + dynamic overlay all in single shader pass. ~3-5 days Shader Graph work. **Fallback: MicroSplat $120 if blocked.**

### 6.7 — Quixel Megascans Integration (free with Unity license)

4–8 ground texture sets per biome, sourced from Quixel library. Existing `terrain_quixel_ingest` handles import; `_flip_normal_y` + `_pack_hdrp_mask_map` handle convention conversion.

### 6.8 — Spawn-Safe + Gameplay Hooks

`meta.json.character_spawn_safe_pos` consumed at runtime by:
- New game / fast travel: places player at biome's "safest" chunk
- Save/respawn: nearest spawn-safe pos to last save point
- AI navmesh bake: starts from spawn-safe pos and expands

`foliage.json` entries carry `is_landmark` flag for hero trees → quest system map markers.

`water.json.lakes[*].basin_id` and `water.json.rivers[*].segment_id` are stable keys for quest references across saves and version hashes.

### 6.9 — F2 Audit Bug Fixes Folded In

Per F2 HDRP export audit (graded C-, but honest grade vs shipped AAA = F):
- ✅ Per-layer albedo + normal + mask + height + detail textures (6.1 layers/)
- ✅ Holes mask emitted (6.1 holes.png)
- ✅ Tangent-space normals, DirectX-Y convention (`_flip_normal_y`)
- ✅ Mask map packed RGBA per HDRP convention (`_pack_hdrp_mask_map`)
- ✅ 8-layer splat support (was implicitly 4-layer)
- ✅ Anti-tiling via per-chunk macro + stochastic sampling
- ✅ Triplanar for slopes >45°
- ✅ Distance-based normal blending
- ✅ Wetness/snow/dust overlay
- ✅ Per-vertex baked AO + ambient tint
- ✅ Foliage HISM groups + UV2/UV3 wind metadata + SSS per material
- ✅ Reflection/light probes + GI lightmap UVs + sky occlusion
- ✅ Volumetric/height fog + decals
- ✅ Cave mesh handoff
- ✅ Detail micro-variation maps
- ✅ Streaming metadata + audio zones + navmesh hints + off-mesh links

### 6.10 — Honest Grade Table (Locked Targets)

| Stage | 42-item coverage | Grade | Cost |
|---|---|---|---|
| Current export (no rebuild) | ~5/42 | F (~10%) | $0 |
| Pilot acceptance gate (mandatory floor) | 40-41/42 | **A-** | $0 |
| Pilot stretch goal (with hand-tuned art passes) | 41-42/42 | **A** | $0 |
| Beyond | requires raytraced GI / RT reflections | A+ | separate conversation |

**No B+ target.** Pilot acceptance requires A- minimum. Free ultrathink stack must hit it; MicroSplat fallback authorized if shader work blocks.

---

## 7. Pilot Scope, Acceptance, Timeline

### 7.1 — Pilot Scope (Q10: C — mountain + grassland end-to-end)

```
Pilot deliverables (mountain + grassland, 64 chunks each):

Heightmap pipeline:
  ✓ DEM ingested (Carpathians for mountain, Yorkshire/Welsh for grassland)
  ✓ Taichi-CUDA hydraulic + thermal + flow + stratification — runs <60s per biome
  ✓ Drainage → water_surface_z + shoreline + foam channels (kills W-1 bug)
  ✓ Slice into 8×8 chunks @ 257 verts × 2m grid, edge-vert shared

Foliage system:
  ✓ Hero L-Py + Filler MTree + Grass L-Py instanced
  ✓ Voronoi clumping for grass field (4 visible classes per chunk)
  ✓ Tussock-vs-sward growth-form split rendered
  ✓ Vertical-Z trunks (no slope tilt)
  ✓ Inter-species exclusion masks (no props inside trees)
  ✓ Mother-tree mycorrhizal sapling colonies
  ✓ TWI-driven moisture math + biome lush ceiling
  ✓ Ground-clutter scatter (5-30 props/m²)

Render system:
  ✓ 3-light + ACES rig
  ✓ 8 cameras per chunk (3 QA + 5 player-experience including 3rd-person)
  ✓ Character proxy at spawn-safe position
  ✓ 8 hero cameras + 4 marketing traversal MP4s per biome
  ✓ 8x8 composite grids per camera type per biome
  ✓ 95%+ nonblack frames

Unity export contract (free ultrathink stack):
  ✓ Per-chunk: 18-file artifact set as in Section 6.1
  ✓ HDRP Shader Graph custom TerrainLit variant: triplanar + distance normal +
    stochastic anti-tile + dynamic overlay
  ✓ HDRP native: water (built-in), weather/wetness, decals, fog volumes,
    reflection probes, light probes, GI lightmaps
  ✓ Foliage wind data baked to UV2/UV3
  ✓ Quixel Megascans ground materials integrated and tuned per biome
  ✓ ≥3 lighting iteration loops per biome before pilot pass
  ✓ ≥30 hand-authored decal variants per biome
  ✓ Edge-weld assertions on chunk load (fail-fast)
```

### 7.2 — Pilot Acceptance Gate (Q11: C, A- minimum / A target)

Acceptance criteria are grouped by category. **All criteria in all categories must pass for the gate to promote that biome to template phase.** "Seam pop" defined: any visible height discontinuity, color discontinuity, foliage instance break, or flow-direction reversal at a chunk edge that exceeds the edge-weld tolerance (1e-3m for heights, 0.05m for water_surface_z, ±2% for feature thread positions per Section 6.3).

**Mountain pilot pass criteria:**

*Geometric (heightmap correctness):*
- ✓ Peak relief ≥ 1000m measured as `max(z) − min(z)` within the bounds of the highest chunk OR across any 3-chunk-radius window centered on a hero peak (whichever is larger)
- ✓ Banded cliff strata visible on ≥4 chunks (stratification working)
- ✓ River network traverses ≥3 chunks without seam pop (per definition above)

*Visual quality (foliage + materials):*
- ✓ Trees vertical-trunk on all slopes — manual inspection on ≥10 sample chunks, zero diagonal foliage instances
- ✓ 0 props inside tree footprints — `tree_footprint_mask` exclusion verification across all 64 chunks
- ✓ Visibly out-classes current mountain renders in side-by-side QA review
- ✓ Reference-photo plausibility check against **Carpathian foothills** sample set (Tatry / Bieszczady, matching Section 3.1 lock)
- ✓ Player-experience cameras (3rd-person, 1st-person, crouched) read correctly
- ✓ Character proxy at human scale validates terrain feature scale (1.78m silhouette feels small against mountain peaks)

*Technical performance:*
- ✓ 95%+ nonblack frames per camera
- ✓ <60 min full biome bake on RTX 4060 Ti (Taichi heightmap + foliage scatter + chunk slicing combined)
- ✓ Each chunk opens in Blender in <10s

*Contract compliance:*
- ✓ Honest grade ≥ A- against 42-item HDRP contract (Appendix A)
- ✓ Unity Editor loads chunks, all edge-weld assertions pass (no failures in fail-fast logging)
- ✓ Quixel Megascans ground materials integrated and tuned for mountain biome
- ✓ ≥3 lighting iteration loops completed with documented changes per loop
- ✓ ≥30 hand-authored decal variants placed procedurally

**Grassland pilot pass criteria:**

*Geometric (heightmap correctness):*
- ✓ Rolling-terrain character: max slope <30° on >85% of chunk surface area; no peak >120m above local baseline
- ✓ River traverses ≥4 chunks without seam pop; pond appears in ≥1 chunk

*Visual quality (foliage + materials):*
- ✓ 4 visible grass classes (sparse/cropped/meadow/lush) within a single chunk where the field demands it
- ✓ Density variation visible across ≥6 chunks
- ✓ L-Py blade variants render as botanical (multi-segment, naturally curved), not as straight triangles
- ✓ Tussock-vs-sward distinction visible: raised mounds with bare gaps (Big Bluestem, Switchgrass) coexisting with smooth interlocked mat (Buffalo Grass, Bluegrass)
- ✓ Trees vertical-trunk on all slopes; 0 props inside tree footprints
- ✓ Visibly out-classes current grassland renders
- ✓ Reference-photo plausibility check against **Yorkshire Dales / Welsh borderlands** sample set (matching Section 3.1 lock)
- ✓ Player-experience cameras read correctly; character proxy at scale

*Technical performance:*
- ✓ 95%+ nonblack frames per camera
- ✓ <45 min full biome bake on RTX 4060 Ti (faster than mountain due to less erosion compute)
- ✓ Each chunk opens in Blender in <10s

*Contract compliance:*
- ✓ Honest grade ≥ A- against 42-item HDRP contract
- ✓ Unity Editor loads chunks, all edge-weld assertions pass
- ✓ Quixel Megascans ground materials integrated and tuned for grassland biome
- ✓ ≥3 lighting iteration loops completed with documented changes per loop
- ✓ ≥30 hand-authored decal variants placed procedurally

Plus 2-4 reference-comparison iterations per biome before promotion to template phase. Each iteration is a documented change set; "iteration" is not informal tweaking.

### 7.3 — Estimated Timeline

```
Week 1     Pipeline foundation
           - Taichi setup + erosion kernels (hydraulic + thermal + flow)
           - DEM ingestion for mountain (Carpathians) + grassland (Yorkshire)
           - Chunk-slice infrastructure (8×8, 257 verts, edge sharing)
           - Edge contract format + writer
           - W-1 bug fixes (W-1A/B/C/D in existing water code)
           
Week 2     Foliage pipeline
           - L-Py species library (mountain + grassland heroes)
           - MTree filler species (4-6 per pilot biome)
           - L-Py grass blade library (12-24 variants per species)
           - Voronoi clumping field generator
           - TWI math + 4-class threshold
           - Inter-species exclusion mask order
           - Ground-clutter scatter pass
           - Vertical-Z trunk fix + UV2/UV3 wind bake
           
Week 3     Render system
           - 3-light + ACES rig in Blender 4.5
           - 8-camera setup per chunk + character proxy
           - Hero camera positioning script
           - Marketing traversal animation rig
           - 8×8 composite grid generator
           - Cycles GPU bake on RTX 4060 Ti
           
Week 4     Unity export contract (free ultrathink stack)
           - HDRP Shader Graph TerrainLit variant
             (triplanar + anti-tile + distance normal blend + overlay dynamic)
           - Per-chunk macro variation baker
           - Vertex AO bake (Cycles 256 samples)
           - HDRP decal placement procedural
           - 8-layer splat + per-layer textures
           - meta.json + navmesh hints + probe placement + audio zones
           - Edge-weld assertions in Unity loader
           
Week 5     Pilot bake (sequential, 2 overnights)
           - Mountain biome: full 64-chunk bake + render (overnight 1)
           - Grassland biome: full 64-chunk bake + render (overnight 2)
           - 8×8 composite grids generated for both biomes
           - Reference-photo comparison set assembled
           - Quixel Megascans materials initial integration

Week 6     Lighting iteration loop 1 (per biome) + decal authoring
           - Lighting iteration 1: mountain + grassland (loop ends with re-bake
             of affected chunks if probe placement changes)
           - ≥30 hand-authored decals per biome placed procedurally
           - Quixel materials tuning iteration 1

Week 7     Lighting iteration loops 2 + 3 + hero art pass
           - Per-biome reflection/light probe bake refinement
           - Hand-tuned hero camera shots
           - Atmospheric haze tuning
           - Material tuning iteration
           
Week 8     Pilot gate review + iteration buffer
           - Honest AAA-bar review against 42-item contract
           - Reference-photo plausibility check
           - 2-4 iterations of foliage density tuning
           - Final pilot gate review
           
TOTAL PILOT: ~8 weeks calendar, ~5 weeks active dev
```

### 7.4 — Post-Pilot (Template Phase)

After pilot acceptance:
- Coastal biome (3-4 weeks — water complexity highest)
- Volcanic biome (2-3 weeks)
- Frozen biome (2-3 weeks)
- Desert biome (3-4 weeks — Turing patterns, biological soil crust, nebkha)
- Wet-zone override assets (jungle option B): 1-2 weeks across coastal + grassland

**Total project: ~8 weeks pilot + ~12-16 weeks template = ~6 months calendar, ~3-4 months active dev.**

### 7.5 — Risk Register

| Risk | Probability | Mitigation |
|---|---|---|
| HDRP Shader Graph blocker on triplanar/anti-tile | 15% | Fallback: $120 MicroSplat |
| Taichi GPU OOM on 4096² hydraulic | 5% | Tile heightmap in 2048² halves, stitch results |
| L-Py grass density crashes scatter | 10% | LOD + culling already designed; reduce density 30% if hit |
| Reference-photo gate fails twice | 30% | Plan for 2-4 iterations per biome (built into timeline) |
| Edge-weld assertion failures | 20% | Fail-fast logging surfaces in dev; bake redo |
| Schedule slip 20-30% | 50% | Pilot scope is 2 biomes minimum; can absorb |
| Quixel Megascans license verification needed | 10% | Confirm Unity bundling — public confirmation: yes, free |
| Blender 4.5 + Taichi compat (CUDA + Python venv) | 20% | Use system Python for Taichi, separate from Blender bpy |
| SRTM data licensing | 5% | Public domain confirmed; check derivative use clause |
| Wind UV2/UV3 baker needs custom L-Py / MTree work | 30% | Blender Python API supports UV writes; budget 1-2 days |

---

## 8. Module Structure / Repo Layout

### 8.1 — New modules (additive)

```
veilbreakers_terrain/
├─ chunks/                          # NEW — chunk system
│  ├─ chunk_grid.py                 # 8×8 slicing, 257-vert, edge-vert sharing
│  ├─ edge_contract.py              # N/S/E/W edge data writer/reader/validator
│  ├─ chunk_baker.py                # orchestrates per-chunk bake
│  ├─ blender_bridge.py             # IPC to Blender for foliage/render bakes
│  └─ stitch_assertions.py          # edge-weld validation
│
├─ erosion_taichi/                  # NEW — Taichi backend
│  ├─ taichi_init.py                # GPU/CPU detection, fallback, VRAM management
│  ├─ hydraulic_mei2007.py          # Mei et al. shallow-water solver
│  ├─ thermal_talus.py              # angle-of-repose redistribution
│  ├─ flow_d8.py                    # D8 flow direction + accumulation
│  └─ stratification_taichi.py      # wraps existing terrain_stratigraphy.py
│
├─ heightmap_dem/                   # NEW — DEM ingestion
│  ├─ srtm_fetch.py                 # NASA SRTM 30m downloader + cache
│  ├─ resample.py                   # cubic + jitter upscale 30m → 2m
│  ├─ procedural_overlay.py         # 3-octave fbm 4/16/64m
│  └─ biome_references.py           # per-biome DEM coordinates lookup
│
├─ foliage/                         # NEW
│  ├─ lpy_hero.py                   # L-Py hero tree library
│  ├─ mtree_filler.py               # MTree headless via bypass_operator
│  ├─ lpy_grass.py                  # L-Py grass blade library + bake-to-variants
│  ├─ scatter/
│  │  ├─ resource_competition.py    # REDengine-style convolution
│  │  ├─ reaction_diffusion.py      # Gray-Scott clump probability
│  │  ├─ poisson_variable.py        # variable-radius Poisson disk
│  │  ├─ voronoi_colony.py          # mother-tree sapling sub-scatter
│  │  ├─ voronoi_clumping.py        # GoT-style grass clumps
│  │  ├─ desert_turing.py           # Klausmeier RD + tiger-bush bands
│  │  └─ exclusion_masks.py         # inter-species exclusion order
│  ├─ ecology/
│  │  ├─ twi.py                     # ln(upslope_area / tan(slope))
│  │  ├─ aspect.py                  # north-facing weight
│  │  ├─ canopy_openness.py         # derived from placed tree density
│  │  ├─ stratification_layers.py   # 5-layer canopy/sub/shrub/herb/floor
│  │  └─ ground_clutter.py          # high-density ground prop scatter
│  ├─ wind_uv_bake.py               # bake wind metadata to UV2/UV3 at mesh export
│  └─ species_libs/
│     ├─ mountain.yaml
│     ├─ grassland.yaml
│     ├─ coastal.yaml
│     ├─ volcanic.yaml
│     ├─ frozen.yaml
│     ├─ desert.yaml
│     └─ wet_zone_overrides.yaml    # cloud-forest jungle assets
│
├─ water_v2/                        # NEW — replaces partial water with single-semantic
│  ├─ surface_field.py              # water_surface_z + water_depth (kills W-1)
│  ├─ shoreline_masks.py            # shoreline + foam + wet_fetch + caustic
│  ├─ waterfall_detect.py           # auto-detect from slope+flow_accum
│  ├─ tidal_harmonics.py            # M2/S2 (replaces F-grade stub)
│  ├─ flow_map_export.py            # D8 → 16-bit RG flow texture for HDRP
│  └─ hdrp_water_bridge.py          # writes water.json for Unity HDRP Water consumption
│
├─ render_v2/                       # NEW — replaces scripts/render_*
│  ├─ lighting_rig.py               # 3-light + ACES + Nishita
│  ├─ camera_rig.py                 # 8 per chunk + 8 hero + 4 traversal
│  ├─ character_proxy.py            # VB_CHAR_PROXY scale validator
│  ├─ spawn_safe_detect.py          # finds character_spawn_safe_pos per chunk
│  ├─ cycles_settings.py            # OptiX + AGX + ACES preset
│  ├─ composite_grids.py            # 8×8 mosaic generator
│  └─ traversal_animator.py         # 60-frame walking animation rig
│
├─ unity_export_v2/                 # REPLACES handlers/terrain_unity_export.py
│  ├─ chunk_artifacts.py            # writes 18-file chunk artifact set
│  ├─ splat_layers.py               # 8-layer splat with per-layer textures
│  ├─ macro_variation_baker.py      # per-chunk unique macro RGBA
│  ├─ hdrp_mask_pack.py             # R=Metal G=AO B=Detail A=Smooth
│  ├─ vertex_ao_bake.py             # Cycles AO bake → vertex color
│  ├─ navmesh_hints.py              # walkable mask + jump/climb anchors
│  ├─ probe_placement.py            # reflection + light probe positions
│  ├─ decal_placement.py            # procedural HDRP decal positions
│  ├─ fog_volume_emit.py            # local volumetric fog markers
│  ├─ audio_zone_emit.py            # reverb/footstep/ambient zones
│  ├─ addressable_metadata.py       # streaming bundle deps
│  ├─ cave_mesh_export.py           # FBX export for undercut meshes
│  └─ hdrp_shader_graph_assets/     # custom TerrainLit Shader Graph .shadergraph
│     ├─ VbTerrainLit.shadergraph                  # master combining all extensions
│     ├─ subgraph_triplanar.shadersubgraph
│     ├─ subgraph_antitile_stochastic.shadersubgraph
│     ├─ subgraph_distance_normal.shadersubgraph
│     └─ subgraph_overlay_dynamic.shadersubgraph
│
├─ pilot/                           # NEW — orchestration
│  ├─ pilot_mountain.py             # full-biome pilot driver
│  ├─ pilot_grassland.py
│  ├─ acceptance_checks.py          # 42-item contract validator
│  └─ reference_compare.py          # photo-plausibility comparison
│
├─ providers/                       # EXISTING — kept (Hunyuan3D-2)
├─ handlers/                        # EXISTING — terrain_unity_export.py DEPRECATED
├─ terrain_pipeline.py              # EXISTING — kept (orchestrator for 1875 callables)
├─ terrain_water_variants.py        # EXISTING — patched (W-1 fixes; canonical channels only)
├─ terrain_stratigraphy.py          # EXISTING — wired into erosion_taichi
├─ terrain_banded_advanced.py       # EXISTING — finally wired (was A-grade unwired)
└─ ... other existing modules ...
```

### 8.2 — Existing Pipeline Integration

Existing 1875-callable pipeline **stays as the engine**. New modules wrap and consume:

```
Existing pipeline produces:                  New modules consume:
heightmap (post-erosion, masks)        →    chunks/chunk_baker.py
50+ derived channels                   →    foliage/scatter/* (drives placement)
water masks (post W-1 fix)             →    water_v2/* (extends with new semantics)
biome zone IDs                         →    unity_export_v2/splat_layers.py
material zone masks                    →    render_v2/* + unity_export_v2/*
```

Single breaking change to existing pipeline: **W-1 fix removes legacy `water_surface` channel writes** (`terrain_water_variants.py:781,878`). 4 consumers migrate to canonical `water_surface_mask` + `water_surface_elevation_m`.

### 8.3 — Module Dependency Order (bake stage)

```
1. heightmap_dem        →  base heightmap
2. erosion_taichi       →  hydraulic + thermal + flow + stratification
3. terrain_pipeline     →  50+ derived channels (existing)
4. water_v2             →  water_surface_z + masks + waterfall instances
5. foliage/scatter      →  tree/grass/clutter instance lists
6. chunks               →  slice to 8×8, write edge contract
7. unity_export_v2      →  18-file artifact per chunk
8. render_v2            →  QA + hero + traversal images (independent of Unity)
9. pilot/acceptance     →  validate 42-item contract + visual gate
```

### 8.4 — Branch / PR Strategy

Per CLAUDE.md repo rules:

```
Pilot work on focused branches:
  feat/chunks-edge-contract
  feat/erosion-taichi-backend
  feat/foliage-lpy-mtree-stack
  feat/water-w1-fix-+-tidal
  feat/render-v2-aces-rig
  feat/unity-export-v2-aaa-contract
  feat/pilot-mountain
  feat/pilot-grassland

PRs into main, squash merge, all required CI checks pass:
  ci (3.11), ci (3.12), pyright, callable-census, Analyze (python), Analyze (actions)

Worktrees if parallel:
  git worktree add ..\veilbreakers-terrain-<scope> -b feat/<scope> origin/main
```

### 8.5 — Testing Strategy

```
veilbreakers_terrain/tests/
├─ chunks/
│  ├─ test_edge_sharing.py
│  ├─ test_edge_contract_roundtrip.py
│  └─ test_stitch_assertions.py
├─ erosion_taichi/
│  ├─ test_hydraulic_convergence.py
│  ├─ test_thermal_repose.py
│  └─ test_flow_d8_correctness.py
├─ foliage/
│  ├─ test_voronoi_clumping.py
│  ├─ test_exclusion_masks.py
│  ├─ test_vertical_z_trunks.py
│  ├─ test_mother_tree_colonies.py
│  └─ test_desert_turing.py
├─ water_v2/
│  ├─ test_w1_canonical_only.py
│  ├─ test_dual_semantics_killed.py
│  └─ test_tidal_harmonics.py
├─ unity_export_v2/
│  ├─ test_42_item_contract.py
│  ├─ test_macro_uniqueness.py
│  └─ test_navmesh_walkable.py
└─ pilot/
   ├─ test_acceptance_mountain.py
   └─ test_acceptance_grassland.py
```

Sub-agents do NOT run pytest per memory `feedback_no_pytest_in_agents`. Test suite runs only on primary agent or CI.

---

## 9. Migration

### 9.1 — Existing Renders

```
Action: ARCHIVE, do not delete.
Path:   renders/legacy/
Reason: reference for "before/after" comparison + audit history
Files:  all current per-biome Cycles renders + 24-image composite + audit pngs
```

### 9.2 — Existing Biome `.blend` Files

```
Action: ARCHIVE, do not delete.
Path:   output/visual_nodes/legacy/
Reason: audit history + can pull species references from them
Files:  VB_Coastal_V*, VB_Mountain_Forest_v*, VB_Grassland_v*, VB_Correct_Fullsize_*
```

### 9.3 — Existing Build Scripts

```
DEPRECATED (kept until pilot ships, then removed):
  scripts/coastal_build_v3*.py
  scripts/mountain_build_v1_full.py
  scripts/grassland_full_build.py
  scripts/render_*.py (visual only)
  scripts/fix_*_lighting.py
  scripts/create_*biome_*nodes.py
  scripts/send_*_to_blender.py
```

These remain as templates for L-Py/MTree species YAMLs during pilot week 2 work. After pilot acceptance, deletion via single PR.

### 9.4 — Existing Unity Export

```
DEPRECATED:
  handlers/terrain_unity_export.py
Replaced by:
  unity_export_v2/* (full module)
Removed:
  After Unity ingestion of new chunk artifacts is verified in template phase
```

### 9.5 — Channels to Remove from Pipeline

```
REMOVED (W-1 fix + phantom-read sweep):
  Legacy water_surface channel writes (terrain_water_variants.py:781,878)

REMOVED if not wired into chunk_<x>_<y>_water.json:
  waterfall_velocity, mist_fog_volume, wave_amplitude_per_vertex,
  particle_emitter_specs, foam_atlas_path, caustic_atlas_path,
  river_mouth_mask, confluence_foam, delta_fan_direction, shoreline_blend,
  mist_zone_mask, wet_surface_decal
  (per audit: many computed but never consumed)

KEPT AND WIRED (was unwired per audit):
  terrain_banded_advanced.py     → wired into erosion_taichi.stratification
  terrain_stratigraphy.py        → wired (E-2 fix)
  Strahler order                  → wired into water_v2/flow_map_export.py
  flow_direction vertex color    → wired into unity_export_v2/chunk_artifacts.py
  Wetland.kind dataclass field   → emit wetland_class channel
  
KEPT (no change):
  Provider system (Hunyuan3D-2)
  Texturing package
  Most of the 1875-callable channel pipeline
```

### 9.6 — Memory / Storage Implications

```
Per biome bake output:
  18 files × 64 chunks × ~12MB avg = ~13.8 GB per biome
  6 biomes = ~83 GB total

Per biome render output:
  512 PNGs × 4MB avg + 8 hero × 12MB + 4 traversal MP4 × 30MB = ~2.3 GB per biome
  6 biomes = ~14 GB total

Per biome Quixel materials:
  4-8 layers × ~80MB = 320-640 MB per biome
  6 biomes = ~3 GB total

Total project storage: ~100 GB. Significant. Recommend external SSD + LFS for renders.
```

---

## 10. Open Questions / Future Work

These are NOT scope for pilot but are flagged for future phases:

1. **URP migration** — Unity 2026 strategy puts new render features on URP. Treat as separate future project after VeilBreakers v1 ships.
2. **Raytraced GI / RT reflections** — separate pipeline conversation; A+ grade only achievable with this.
3. **Jungle as 7th biome** — currently scoped as wet-zone overrides (option B). If desired post-pilot, add 64 chunks of dedicated jungle biome with cloud-forest aesthetic.
4. **Procedural cave generation** — currently caves are authored static meshes. Procedural cave gen via Voronoi on terrain undercuts is a future phase.
5. **Dynamic weather simulation** — HDRP weather hooks exist; gameplay weather sim (rain accumulation → water_depth changes, snow accumulation → terrain heightmap modulation) is post-ship.
6. **Procedural quest landmarks** — `is_landmark` flag on hero trees provides hooks; quest authoring tooling not in scope.
7. **Multiplayer chunk synchronization** — single-player only for v1. Determinism per chunk supports multiplayer if added later.

---

## Appendix A — 42-Item AAA HDRP Contract Checklist

| # | Item | Mandatory/Polish | Status (target) |
|---|---|---|---|
| 1 | Heightmap (16-bit raw, ≥257² per chunk) | M | ✅ |
| 2 | Neighbor stitching metadata (edges.json) | M | ✅ |
| 3 | Splatmap ≥8 layers (2 RGBA splat textures) | M | ✅ |
| 4 | Per-layer Albedo + Smoothness | M | ✅ |
| 5 | Per-layer Normal map (tangent DX-Y) | M | ✅ |
| 6 | Per-layer Mask map (M/AO/Detail/Smooth RGBA) | M | ✅ |
| 7 | Per-layer Height map (parallax) | M | ✅ |
| 8 | Per-layer UV tiling + rotation | M | ✅ |
| 9 | Macro variation overlay | M | ✅ (per-chunk unique) |
| 10 | Anti-tiling overlay (stochastic + macro) | M | ✅ |
| 11 | Distance-based normal blending | M | ✅ |
| 12 | Triplanar projection blend (slope >45°) | M | ✅ |
| 13 | Terrain holes mask | M | ✅ |
| 14 | Cave/undercut mesh handoff | M (if exists) | ✅ |
| 15 | Detail/micro-variation maps | M | ✅ |
| 16 | Wetness overlay channel | M | ✅ |
| 17 | Snow accumulation overlay | M (winter) | ✅ |
| 18 | Dust/age/footprint overlay | P | ✅ |
| 19 | Per-vertex baked AO | M | ✅ |
| 20 | Per-vertex ambient color tint | P | ✅ |
| 21 | Foliage HISM groups per species | M | ✅ |
| 22 | Foliage per-instance random seed | M | ✅ |
| 23 | Foliage wind metadata UV2/UV3 | M | ✅ |
| 24 | Foliage SSS per leaf material | M | ✅ |
| 25 | Foliage attachment / LOD distance | M | ✅ |
| 26 | Reflection probes placement + extents | M | ✅ |
| 27 | Light probe grid density | M | ✅ |
| 28 | GI lightmap UVs | M | ✅ |
| 29 | Sky occlusion mask | P→M (heavy canopy) | ✅ |
| 30 | Shoreline foam mask | M (water present) | ✅ |
| 31 | Depth-fade / wet-band overlay | M (water present) | ✅ |
| 32 | Volumetric fog density volumes | M | ✅ |
| 33 | Height-fog gradient data | M | ✅ |
| 34 | Decals (moss, scorch, dirt, blood) | M | ✅ |
| 35 | Terrain LOD chain (LOD0/1/2 + macro) | M | ✅ |
| 36 | Streaming addressable bundle deps | M | ✅ |
| 37 | Streaming neighbor pre-fetch hints | M | ✅ |
| 38 | Streaming memory budget per chunk | M | ✅ |
| 39 | Audio zones (reverb, footstep, ambient) | M | ✅ |
| 40 | Navmesh walkable mask | M | ✅ |
| 41 | Navmesh slope/water/cliff exclusion | M | ✅ |
| 42 | Navmesh AI off-mesh links (jump/climb) | P→M | ✅ |

**Pilot acceptance: 40-41 of 42 covered = A- minimum. Stretch: 41-42 of 42 = A.**

---

## Appendix B — Per-Biome Species Inventory (Detailed)

### B.1 — Mountain (pilot biome)

```
Hero (1-3 per chunk where landmark scoring places them):
  - Ancient gnarled alpine oak (300-800 yr, 18-25m, twisted limbs, sparse moss)
  - Weathered fir (giant, 25-30m, wind-sculpted asymmetric crown)

Filler (200-800 per chunk):
  - Alpine pine (15-22m, conifer, 4 age variants)
  - Engelmann spruce (12-18m, dense conical crown)
  - Dwarf juniper (3-6m, gnarled, lower-altitude)
  - Scattered birch (8-12m, white bark, deciduous, in protected pockets)

Subcanopy / shrub:
  - Dwarf willow (3-5m on banks)
  - Mountain alder (4-7m, riparian)
  - Heather (0.3-0.6m, purple/white bloom seasons)
  - Blueberry/bilberry shrub (0.4-0.8m)
  - Dwarf rhododendron (0.5-1.2m)
  - Krummholz pine mats above treeline (sprawling, <1m)

Grass (12-24 baked variants per species):
  - Sheep fescue (Festuca ovina, 10-30cm, silvery-blue tussock, year-round)
  - Alpine bluegrass (Poa alpina, 10-25cm, mat, green→straw)
  - Tufted hair-grass (Deschampsia cespitosa, 30-60cm, riparian/wet zones)

Wildflowers (clustered in moisture pockets):
  - Marsh marigold (Caltha leptosepala, riparian)
  - American bistort (Polygonum bistortoides)
  - Parry primrose (Primula parryi)
  - Arctic gentian (Gentiana algida)

Above treeline (cushion plants only):
  - Moss campion (Silene acaulis, 2-5cm mat)
  - Alpine forget-me-not (Eritrichium nanum)
  - Crowberry, dwarf willow prostrate mats

Ground clutter (5-30/m²):
  - Loose stones (5-30cm)
  - Pinecones, fallen needles
  - Dead branches
  - Lichen-covered boulders (hero-tier rocks at 50-150cm)
```

### B.2 — Grassland (pilot biome)

```
Hero (1-3 per chunk):
  - Lone old oak (the silhouette tree, 20-28m, broad crown, 200+ years)
  - Mature riparian willow (15-22m, weeping form, riverside placement)

Filler (rare in true grassland, 0-30 per chunk):
  - Scattered oak/hawthorn copses (2-4 trees per copse, isolated)
  - Birch in moisture pockets

Tall grass tussock (multi-strata):
  - Big Bluestem (Andropogon gerardii, 1.5-3m, blue-green→copper, signature)
  - Switchgrass (Panicum virgatum, 0.9-1.8m, golden in autumn)
  - Indiangrass (Sorghastrum nutans, 1.2-2m, blue-green→golden)
  - Little Bluestem (Schizachyrium scoparium, 0.5-1.1m, steel-blue→russet)

Mid grass:
  - Side-oats Grama (Bouteloua curtipendula, 0.5-0.8m)
  - Prairie cordgrass (Spartina pectinata, 1-1.5m, wet zones)

Short sward:
  - Buffalo Grass (Bouteloua dactyloides, 0.1-0.2m, mat)
  - Kentucky Bluegrass (Poa pratensis)
  - Prairie Junegrass (Koeleria macrantha)

Wet meadow / riparian:
  - Sedges (Carex spp., 0.4-1.2m, arching tussock)
  - Rushes (Juncus spp., 0.5-1.5m)
  - Cattails (Typha, 1.5-3m at water edge)
  - Reed canary grass (1-2m monoculture stands in disturbed wet areas)

Wildflowers (clustered in moisture pockets):
  - Black-eyed Susan (Rudbeckia hirta)
  - Purple Coneflower (Echinacea purpurea)
  - Blazing Star (Liatris spicata)
  - Wild Bergamot (Monarda fistulosa)
  - Lupine, milkweed, asters, daisy, clover

Riparian (within 15m of water):
  - Alder (Alnus, 8-15m)
  - Willow (Salix, 6-12m)
  - Cottonwood (Populus, 18-25m where deep soil)

Ground clutter (5-30/m²):
  - Small stones, twigs, dead grass tufts
  - Animal scat / clumps (wildlife indicators)
  - Wildflower seed heads
  - Fallen leaves (autumn season)
  - Dust patches on heavily trodden paths
```

### B.3 — Coastal

```
Hero:
  - Sea oak (Quercus virginiana analog, 14-18m, twisted live-oak shape)
  - Weathered cypress/cedar (8-15m, salt-pruned)

Filler:
  - Coastal pine (Pinus species, 15-22m)
  - Gnarled hawthorn (5-8m, near-shore band)
  - Bayberry shrub (1.5-3m)

Grass (NOT continuous cover — isolated tussocks with bare sand between):
  - Marram (Ammophila arenaria/breviligulata, 0.6-1.2m, stiff erect tussock, primary dune)
  - Sea Lymegrass (Leymus mollis, 0.4-0.8m, blue-grey)
  - Salt marsh cordgrass (Spartina alterniflora, 0.3-1.5m, dense sward at low tide)
  - Beach grass varieties

Coastal salt marsh:
  - Glasswort, sea lavender
  - Cordgrass dominant zone

Shrubs:
  - Bayberry (1-2m)
  - Salt-tolerant gorse
  - Sea thrift cushions on cliffs
  - Samphire on rocks

Wet-zone overrides (jungle option B trigger):
  - At TWI > 8.5 + canopy_openness < 0.3, swap to cloud-forest assets
```

### B.4 — Volcanic (post-pilot)

```
Hero (extreme rare):
  - Solitary scorched-bark pine (survivor in protected pockets)
  - Ash-tolerant cypress

Filler (sparse):
  - Stunted juniper (0.5-3m, age-zoned by lava cooling time)
  - Sparse halophyte scrub

Ground:
  - Lava-tube fern (rare oasis species)
  - Scattered hardy grasses
  - Mostly bare lava + ash

Pioneer succession on cooling lava (visual):
  - Lichen → moss → fern → grass → shrub progression
  - Visible across chunks of varying flow age
```

### B.5 — Frozen (post-pilot)

```
Above treeline (most of biome):
  - Dwarf willow (5-15cm prostrate mats)
  - Arctic bilberry, crowberry
  - Cottongrass (Eriophorum)
  - Reindeer lichen (Cladonia) ground cover

Krummholz:
  - Wind-sculpted dwarf pine/spruce in protected pockets
  - Twisted, asymmetric, often dead lower branches

Sedges, mosses everywhere on rocks
No tall trees — scattered isolated dead snags as landmarks
```

### B.6 — Desert (post-pilot, hostile-aesthetic)

```
Hero (defining silhouettes):
  - Boojum tree (Fouquieria columnaris, 5-15m, bone-white trunk, otherworldly)
  - Dragon Blood Tree (Dracaena cinnabari, 3-10m, Socotra umbrella)
  - Bleached dead saguaro husks (woody skeleton 9-15m, more distinctive than live)

Mid (whip-stems and silhouettes):
  - Ocotillo (Fouquieria splendens, 2-6m, 90% leafless)
  - Acacia (4-10m wadi indicator)
  - Tamarisk (4-8m oasis indicator)
  - Mesquite (2-6m thorned, wash indicator, deep tap root)

Shrubs (Turing-spaced, NOT Poisson):
  - Creosote bush (Larrea tridentata, 1-2m, 1.5-3m allelopathic ring)
  - Brittlebush (Encelia farinosa, 0.5-1m, silver-grey)
  - Mormon tea (Ephedra, 0.3-1.2m, leafless jointed stems, alien)
  - Sagebrush (cold desert dominant)
  - Saltbush, greasewood (halophytes on flats)
  - Jojoba (rocky slopes)

Succulents:
  - Prickly pear (0.3-1.5m, pad-clusters, can form impenetrable thickets)
  - Jumping cholla ghost-stands (Cylindropuntia bigelovii, 0.5-3m, pale skeletal)
  - Agave with spent 6m flower spike over dead rosette
  - Desert spoon (Dasylirion wheeleri, 0.8-1.2m bleached straw)
  - Hedgehog cactus (0.1-0.4m)

Dry grasses (sparse):
  - Big galleta (Pleuraphis rigida, 0.3-0.7m)
  - Black grama (Bouteloua eriopoda)
  - Three-awns (Aristida)
  - Needle-and-thread (Hesperostipa comata, dramatic twisted awns)

Spacing patterns (Turing-driven):
  - Tiger bush bands on 3-15% slopes (8-20m wide, 15-40m gaps)
  - Creosote allelopathic rings (1.5-3m exclusion enforced)
  - Wash/wadi attractor (5-15m buffer along D8 drainage)
  - Oasis clusters (rare, extreme-flow-accum threshold)

Surface (material layer, not scatter):
  - Biological soil crust (70-80% surface, dark brown/black)
  - Subtracted by track/path mask exposing pale tan
  - Nebkha sand drift downwind from every obstacle (34° repose, 12× obstacle height)
```

### B.7 — Wet-Zone Overrides (jungle option B)

```
Trigger: (TWI > 8.5) AND (canopy_openness < 0.3) AND biome ∈ {coastal, grassland}

Cloud-forest aesthetic (NO bright Pandora-style):

Emergent (rare, 50-150/km², if present):
  - Ancient gnarled cloud-forest giants 20-35m
  - Trunks 80-100% moss-covered
  - Lichen beards on branches
  - NO buttress roots (cloud forest lacks them)

Canopy (800-1500/km²):
  - Twisted dark-wood broad trees 12-20m
  - Interlocking crowns
  - Moss clumps on every major branch crotch

Understory (3000-6000/km²):
  - Prehistoric ferns 1.5-3m
  - Dark-leaved palms
  - Juvenile gnarled hero species
  - Strangler fig lattice columns (rare hero set pieces)

Shrub (very dense):
  - Giant Heliconia-analog leaves (dark burgundy/black-green)
  - Ground fern mats
  - Scrambling creeper vines

Forest floor (millions, aggressive cull at 15-20m):
  - Bioluminescent emissive mushrooms (emissive sheet + bloom, no RTGI required)
  - Shelf fungi on logs
  - Thick litter
  - Moss-covered rocks

Vine/liana generation:
  - Catenary curves between canopy trees
  - Attach radius 8-20m
  - 15-25% of canopy pairs

Light:
  - 95% canopy occlusion
  - Dappled god-rays through gap-mask holes
  - Mushroom emissive for floor lighting
```

---

## Appendix C — Bibliography / Research Sources

### Heightmap & Erosion
- Mei, X., Decaudin, P., & Hu, B. (2007). "Fast Hydraulic Erosion Simulation and Visualization on GPU." *PG '07*.
- Št'ava, O., Beneš, B., Brisbin, M., & Křivánek, J. (2008). "Interactive Terrain Modeling Using Hydraulic Erosion." *SCA '08*.
- Klausmeier, C. A. (1999). "Regular and Irregular Patterns in Semiarid Vegetation." *Science 284*.
- Rietkerk, M., et al. (2002). "Self-organization of vegetation in arid ecosystems." *American Naturalist*.

### Foliage & Ecosystem
- Simard, S. W. (1997). "Net transfer of carbon between ectomycorrhizal tree species in the field." *Nature*.
- Bridson, R. (2007). "Fast Poisson Disk Sampling in Arbitrary Dimensions." *SIGGRAPH 2007 Sketches*.
- Turing, A. M. (1952). "The Chemical Basis of Morphogenesis."
- Heitz, E., & Neyret, F. (2018). "High-Performance By-Example Noise using a Histogram-Preserving Blending Operator." *I3D 2018* — the stochastic sampling technique for anti-tiling.

### AAA Game GDC / SIGGRAPH Talks
- Wohllaib, E. (2021). "Procedural Grass in Ghost of Tsushima." *GDC 2021* — Voronoi clumping algorithm.
- van Muijden, J. & Sanders, G. (2017/2018). "GPU-Based Procedural Placement in Horizon Zero Dawn / The Vegetation of Horizon Zero Dawn." *GDC 2017/2018*.
- Gollent, M. (2014). "Landscape Creation and Rendering in REDengine 3." *GDC 2014* — Witcher 3 vegetation generator.
- Malan, H. (2022). "Rendering Water in Horizon Forbidden West." *SIGGRAPH 2022 Advances in Real-Time Rendering*.
- Rare. "Visual Adventures on Sea of Thieves." *GDC 2019* + *SIGGRAPH 2018*.
- Crysis. *GPU Gems 3 Ch.16: Vegetation Procedural Animation and Shading in Crysis* (2007).
- Massive Entertainment. "Crafting Pandora's Breathtaking Landscape with Snowdrop." (2023).
- Guerrilla Games. "Adventures with Deferred Texturing in Horizon Forbidden West." (2022).

### Unity / HDRP
- Unity HDRP Terrain Lit Material Documentation (v17.0).
- Unity HDRP Water System Documentation (2022 LTS / 2023.1+).
- Unity HDRP Mask Map and Detail Map Spec.
- Unity Render Pipelines Strategy 2026 announcement.

### Tools
- Taichi Lang Documentation (taichi-lang.org).
- L-Py + PlantGL (FraPy / Inria).
- MTree Blender Add-on Documentation.
- SpeedTree Wind Documentation.
- Quixel Megascans Library (free with Unity).

---

## Appendix D — Glossary

| Term | Meaning |
|---|---|
| TWI | Terrain Wetness Index = ln(upslope_area / tan(slope)). Drives moisture-based vegetation density. |
| D8 | Eight-direction flow routing — each pixel's flow goes to one of 8 neighbors. |
| HISM | Hierarchical Instanced Static Mesh — Unity/Unreal feature for grouping N instances into one cull unit. |
| HDRP | High Definition Render Pipeline — Unity's PBR-focused render pipeline. |
| URP | Universal Render Pipeline — Unity's lighter-weight, mobile-friendly render pipeline. |
| L-Py | Procedural plant modeling library based on L-systems. |
| MTree | Blender modular tree procedural generation add-on. |
| FBM | Fractional Brownian Motion — multi-octave noise. |
| Mei et al. 2007 | Standard reference shallow-water flux solver for hydraulic erosion. |
| Klausmeier-Rietkerk | Reaction-diffusion model for arid vegetation Turing patterns. |
| Voronoi clumping | GoT-specific technique where each Voronoi cell carries dominant grass profile. |
| W-1 | Water dual-semantics bug class identified in audit (W-1A through W-1D). |
| Strahler order | Hierarchical numbering of stream segments in a drainage network. |
| Krummholz | Wind-sculpted dwarf trees at treeline. |
| Tussock | Bunch grass with raised mound + dead culm collar + bare gap around it. |
| Sward | Continuous interlocked rhizome carpet (smooth lawn appearance). |
| Allelopathy | Chemical exclusion zone around a plant (e.g., creosote 1.5–3m ring). |
| Nebkha | Sand shadow dune that accumulates downwind of obstacles. |
| Tessendorf FFT | Standard ocean simulation algorithm (Sea of Thieves baseline). |
| Gerstner waves | Trochoidal wave summation for ocean chop layer. |
| ACES | Academy Color Encoding System — film-industry color pipeline used in shipped AAA. |
| AGX | Modern color view transform shipped in Blender 4.x as alternative to Filmic. |
| OptiX | NVIDIA ray-tracing acceleration API used by Cycles GPU rendering. |

---

**End of design spec. Ready for spec-document-reviewer subagent dispatch and user review.**
