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
| Q3 | Vertex resolution | **257 verts/side, 2m grid, ~66k verts/chunk** — 256 cells × 2m = 512m chunk extents; the 257th vert is the shared edge with the neighbor (vert-shared, not duplicated). Edge contract files store 257 entries per side. | Encodes individual rocks, cart ruts, micro-erosion in heightfield itself |
| Q4 | Heightmap source | **Hybrid DEM + procedural detail, Gaea/Houdini-quality bar** | NASA SRTM 30m macro + 3-octave fbm overlay + Taichi erosion + drainage |
| Q5 | Compute backend | **Taichi-CUDA primary; degraded CPU path for dev iteration only, NOT acceptance-grade. Pilot pass requires GPU bake.** | Free MIT license, AAA-grade (Embark, Coalition), 50–200× over NumPy on RTX 4060 Ti. CPU path retained for laptop/dev iteration; pilot acceptance gate cannot pass on CPU per §11.7 #3 (E-3 audit: pure-Python is non-functional at AAA sizes). |
| Q6 | Foliage stack | **MTree filler + L-Py hero + vertical-Z trunks + exclusion masks** | Real branched topology, kills diagonal-tree bug, structurally prevents props-inside-trees |
| Q7 | Grass system | **L-Py blade variants + zonal Voronoi field + 12-24 baked variants per species + 3-tier LOD** | Real grass complaint is field problem (not blade problem); GoT-style Voronoi clumping breaks "one constant height" |
| Q8 | Render contract | **A: three-light + ACES + manual exposure** | AAA-cinematic. Sun key 50° altitude + sky-bounce fill 30% + rim 10%. Filmic+ACES. 95%+ nonblack guarantee. |
| Q9 | Unity import | **C: hybrid Unity Terrain (heightmap+splat) + Addressables prefabs (foliage/water/props)** | Uses both pipeline outputs in their native lossless forms. HDRP committed (verified in code). |
| Q10 | Pilot scope | **Mountain + grassland end-to-end first** | Stresses heightmap (mountain) + foliage (grassland) — exercises ~80% of pipeline surface |
| Q11 | Acceptance gate | **C: functional + visual + reference parity** | A- minimum, A target. Reference-photo plausibility (Carpathians + Yorkshire). Promotion gate to template. |
| Q12 | Runtime water stack | **A: HDRP built-in water (free, native, AAA) + custom waterfall mesh + custom lava emissive** | Unity 2026 strategy: HDRP maintenance mode but still ships free water; URP migration deferred to future project |
| Q13 | Lava treatment | **A: custom emissive surface shader (NOT through water)** | Lava emits light, doesn't refract — water shader produces wrong physics |
| Q14 | Anti-tile / triplanar / macro / distance normals | **[AUTO-APPLIED — Decision 3.2 / pending user override] A: MicroSplat $40 (default) — FREE base + $20 HDRP 2022 module + $20 Mesh Terrains module = $40 total** | Saves ~2 weeks of solo-dev time vs custom HDRP shader graph. Custom HDRP shader graph stack remains an alternative if a specific visual signature is required. HDRP 14 (Unity 2022 LTS) is in maintenance mode per Feb 2026; URP migration via $20 module swap if needed. |
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
│  │ procedur │   │ 2m grid  │   │ hyd+therm│   │ (50+)    │       │
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

**Determinism enforcement:** Determinism is enforced via subprocess byte-identity CI gate per §11.5.4 PR B5-T4 + Fix 1.22's 18-artifact matrix (12 byte-identity + 2 SSIM ≥0.95 for Cycles cross-platform float drift + 1 schema-only for `meta.runtime.json` volatile fields, plus 4 absorbed via `splatmap_*.png` glob expansion = 18 nominal manifest entries). The in-process determinism CI variant is convenience-only and deferred per §11.8 #5 without compromise to this §3.7 pixel-for-pixel promise.

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

### 6.6 — HDRP Shader Stack ([AUTO-APPLIED — Decision 3.2 / pending user override] MicroSplat $40 default; custom HDRP shader graph as alternative)

**Default (recommended): MicroSplat HDRP 2022 + Mesh Terrains modules ($20 + $20 = $40 total; FREE base).** Saves ~2 weeks of solo-dev time vs custom Shader Graph authoring. Provides triplanar, anti-tile, distance-normal blend, dynamic overlay out of the box; HDRP 14 (Unity 2022 LTS) supported; URP migration possible via $20 module swap if needed.

**Alternative (if specific visual signature required): custom HDRP Shader Graph stack ($0).** Layout below; ~12-18 days realistic solo-dev effort:

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

Combined into one `VbTerrainLit.shadergraph` Master node. Anti-tile + triplanar + distance blend + dynamic overlay all in single shader pass.

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

The 42-item AAA HDRP contract is split into two tiers for the pilot acceptance gate to resolve the prior conflict between "all criteria pass" (Section 7.2) and "40-41 of 42" (this section):

- **Mandatory tier (32 items, ALL must pass for A-):** items 1–8 (heightmap+splat+layers), 13 (holes), 19–25 (foliage including UV2/UV3 wind), 26–28 (probes+GI), 30–35 (water masks+fog+decals+terrain LOD), 36–41 (streaming+audio+navmesh walkable+exclusion).
- **Polish tier (10 items, at least 8 must pass for A-, all 10 for A):** items 9–12 (macro variation, anti-tile, distance normal blend, triplanar), 14 (cave mesh handoff — only if caves exist on pilot biomes), 15 (detail maps), 16–18 (wetness/snow/dust overlay), 29 (sky occlusion), 42 (off-mesh links).

| Stage | Mandatory tier | Polish tier | Grade | Cost |
|---|---|---|---|---|
| Current export (no rebuild) | ~3/32 | ~2/10 | F (~10%) | $0 |
| Pilot A- acceptance gate | **32/32 (all)** | ≥ 8/10 | **A-** | $0 |
| Pilot A stretch | **32/32 (all)** | 10/10 | **A** | $0 |
| Beyond | + raytraced GI / RT reflections | n/a | A+ | separate pipeline |

**Pilot pass = 32 mandatory + 8 polish minimum.** [AUTO-APPLIED — Decision 3.2 / pending user override] Default to MicroSplat HDRP 2022 + Mesh Terrains modules ($40 total; saves ~2 weeks solo-dev time); custom HDRP Shader Graph stack remains an alternative if specific visual signature required.

This split resolves the Section 7.2 vs 6.10 contradiction surfaced by the spec-review v2 audit: the "all criteria pass" rule applies to the mandatory tier; the polish tier permits up to 2 deferrals at A- grade. Section 7.2 acceptance criteria are tagged below in v1.1 with their tier membership.

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
- Coastal biome ecology rules (1 PR, ~0.5 day; was §11.4 #59)
- Volcanic biome (2-3 weeks)
- Frozen biome (2-3 weeks)
- Desert biome (3-4 weeks — Turing patterns, biological soil crust, nebkha)
- Wet-zone override assets (jungle option B): 1-2 weeks across coastal + grassland

**Total project: ~8 weeks pilot + ~12-16 weeks template = ~6 months calendar, ~3-4 months active dev.**

### 7.5 — Risk Register

| Risk | Probability | Mitigation |
|---|---|---|
| HDRP Shader Graph blocker on triplanar/anti-tile | 15% | [AUTO-APPLIED — Decision 3.2 / pending user override] Default is now MicroSplat $40 (FREE base + $20 HDRP 2022 + $20 Mesh Terrains). Custom Shader Graph stack is the alternative if specific visual signature required. |
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

# Spec v1.1 Addendum (2026-05-05, post 6-agent strict review)

After the v1.0 spec was committed to PR #25, six adversarial review agents were dispatched in parallel: 3 Opus deep-dives (PR #24 audit, AAA spec vertical depth, AAA spec horizontal coverage) and 3 Sonnet code-clutter audits (scripts/, veilbreakers_terrain/ core, output/renders/docs/CI). All 6 returned. v1.0's verdict from the strictest reviewer: "spec is NOT implementable as-is — AA at most, needs v1.1 to reach AAA bar." This addendum closes the load-bearing BLOCKING gaps and adds the SHIP-BLOCKING runtime contracts that v1.0 implicitly assumed.

---

## 11. Implementation runway — PR plan v3

### 11.0 Preface — v3 vs v2 deltas

§11 v2 (commit `6cee216`, 27 PRs) merged Wave 1-3 findings into a 4-block runway. **§11 v3** consolidates Wave 1-5 (10 reports across cross-PR coherence, CI impact, HDRP shader, Unity-side parity, end-to-end determinism, asset budget, single-chunk re-bake, test infra, doc rot, dependency CVEs). All Wave-3 verifier-discovered cite errors in v2 PRs are corrected here against the V3-forensic ground truth at `.staging/WAVE_1_5_RAW_FINDINGS.md` §A.1.

| Dimension | v2 | v3 |
|---|---|---|
| Total reported findings (Waves 1-5) | 178 | 276 |
| Verified open after Wave-3 forensic re-check | 174 | 263 |
| Unique items mapped to PRs (after dedup) | 132 | 234 |
| PR count | 27 | 114 (91 + 23 net-new from Phase 4: B5-U-NAV (1) + B5-U15-U22 (8 Unity) + B5-C7-C12 (6 channels) + B5-D5-D8 (4 chunks) + B5-T8-T10 (3 tests) + PR #65 (RNG cleanup) = 23 — Phase 4 adds 23 PR rows; was 91 post-Phase-3 with B5-T1b, now 114 post-Phase-4) |
| Block count | 4 | 5 pilot blocks + Block 6 post-pilot maturity (v1.1 batch, per Phase 2 Fix 2.1) |
| Effort (focused, single-engineer days) | 5–7 | **30–45 working days realistic solo (~6-9 weeks calendar) per [AUTO-APPLIED — Decision 3.3 / pending user override]**; prior optimistic 11–14 estimate dropped — assumed 1 PR/hour throughput at 6h focus/day with no review/surprises. Two-engineer estimate dropped (out of scope; would require hiring). |
| Critical-path length | 5 PRs (#1→#2→#3→#4→#5) | 6 PRs (#1→#2→#3→#4→#5b→#11) |
| Cuts surfaced (§11.7) | 0 (all "tagged ✅") | 20 (was 9 post-Phase-3; +11 from Phase 4: APV experimental risk #10, SVT-defer #11, Mesh-shader-defer #12, HLOD-defer #13, Wwise/FMOD-defer #14, save-game-defer #15, no-multi-platform #16, no-DOTS/ECS #17, no-CDN-Addressables #18, no-runtime-telemetry #19, no-path-tracing #20) |
| Open deferrals (§11.8) | 8 | 14 (was 12 pre-Phase-2; +1 grouped refactor entry per Fix 2.3, +1 Block 6 reference per Fix 2.1) |

The headline deltas: (1) cite corrections to 4 v2 PRs against V3 forensic line-cite ground truth; (2) Block 5 added — Unity-side parity + cross-PR coherence + asset-budget hardening + single-chunk re-bake + test infra + deps + doc rot; (3) Issue #27 fix architecture rewritten (generator-stamping per pass, terrain_labels = validator); (4) ~58 production RNG sites (was over-claimed 127); (5) HDRP shader graph stack honest grade F (~10%); (6) `VbTerrainTileMetadata` is 29 fields, not 3-field stub; (7) coverage already 72% (was claimed 40%); (8) `_terrain_world.py:861-869` cite WRONG → real biome collapse at `environment.py:2031`.

### 11.0.1 Source of truth

Every PR row below is sourced from a single-source-of-truth findings package at:

```
docs/superpowers/specs/.staging/WAVE_1_5_RAW_FINDINGS.md
```

That file is the ground truth across 5 sweep waves (3 Opus deep-dives + 3 Sonnet code clutter audits + 11-Opus orphan-pass comb + verifier-3 forensic line-cite re-check + verifier-4 referee + 10 wave-5 reports). Every claim in §11.1-§11.5 has a file:line cite or explicit "verified-false" annotation. The verifier protocol is defined in §11.11.

### 11.0.2 C-1 contradiction resolution

Spec §3 line 124 and §3.7 line 237 use the same word "seed" for two different scopes. v3 resolves with a two-tier seed model amended by PR #4 (carry-amendment) + PR #B5-D1 (chunk_seed module):

```
biome_seed  = hash(biome, version)
              # Pre-slice scope. Drives DEM upscale jitter, fbm
              # overlay basis permutation, hydraulic Mei-2007 rain
              # noise, stratigraphy modulation, drainage carving.
              # Same biome+version → identical merged 4096m field.
              # USE in: heightmap_dem/, erosion_taichi/,
              #         stage 3.4 drainage extraction, stage 3.5
              #         derived-channel pipeline.

chunk_seed  = hash(biome, chunk_x, chunk_y, version)
              # Post-slice scope. Drives foliage scatter Poisson
              # seeds, Voronoi clumping cell jitter, ground-clutter
              # density randomness, edge-thread feature sampling,
              # macro_variation.png unique noise, render camera
              # interesting-direction tiebreakers.
              # USE in: foliage/scatter/, foliage/ecology/,
              #         unity_export_v2/macro_variation_baker.py,
              #         render_v2/ camera scoring.
```

Spec body lines 124 and 237 are amended by **PR #4 (carry-amendment)** to reference both forms explicitly, eliminating the "same word for two scopes" ambiguity. The `chunk_seed` API lands as a concrete `chunks/chunk_seed.py` module via **PR #B5-D1** (single-chunk re-bake architecture).

### 11.0.3 Path-namespace preface

All file paths in §11.1-§11.5 use shorthand for readability. Implementer must resolve shorthand to real path on every PR:

- `handlers/<file>.py` → real path `veilbreakers_terrain/handlers/<file>.py`
- `providers/<file>.py` → real path `veilbreakers_terrain/providers/<file>.py`
- `chunks/<file>.py` → real path `veilbreakers_terrain/chunks/<file>.py` (NEW directory; lands in PR B5-D1)
- `tests/<file>.py` → real path `veilbreakers_terrain/tests/<file>.py`
- `unity_project/Assets/Scripts/<file>.cs` → real path `unity_plugin/<file>.cs` (Editor-side: `unity_plugin/Editor/<file>.cs`)

Path-shorthand-vs-real-location was global doc-rot identified by `CODEX1_CITE_AUDIT.tsv`; this preface unblocks every PR row.

### 11.0.4 Visible-value milestones (solo-dev motivation)

For a solo dev shipping 114 PRs across 30-45 working days, visible-value
checkpoints prevent motivation collapse:

1. **[AUTO-APPLIED — P3-Polish-1] After Block 4 PR #6 (foliage `align_to_normal` fix; PR #6 was moved to Block 4 per Phase 2 Fix 2.2)** + Block 1 PR #6.5 baseline:
   bake 1 chunk of `cliff_talus_apron`. Render preview should show 0
   diagonal trunks at slope > 30°. **Visible win**. Note: re-anchored on
   #6.5 (which IS in Block 1) ensures the SSIM harness lands on the Block 1
   calendar even though the `align_to_normal` flip ships in Block 4.

2. **[AUTO-APPLIED — P3-Polish-2] After Block 2 PR #19** (Mei-2007 Taichi-CUDA hydraulic): bake 1
   chunk of mountain biome. Compare visual heightmap to baseline.
   **Visible win** if erosion looks materially better. Note: <18s on
   RTX 4060 Ti acceptance is local-only per Decision 3.4 — not enforced in CI
   (pilot drops GPU perf gate from required checks).

3. **After Block 2 PR #29** (label-stamping architecture): bake 1
   chunk; verify cliff/water/rock/gravel labels stamp correctly via
   `std(label) > 0`. **Functional win**.

4. **After Block 5a PR B5-U1** (HDRP shader stack — MicroSplat or
   custom): import 1 chunk into Unity. Visual material should look
   AAA-bar in HDRP 2022 LTS. **Major visible win**.

5. **After Block 5a PR B5-U2-U5** (water/holes/edges/decals/foliage):
   full chunk import. End-to-end pilot demo. **Pilot acceptance gate**.

### 11.0.5 Fix 1.0 — Cite-refresh prereq (P0, MUST precede all surgical PRs)

> Renamed from §11.1.0 → §11.0.5 (Fix R8, sort-order cleanup): logically belongs with the other §11.0.X meta sections; §11.1.0 sorts before §11.1 alphabetically. Content unchanged.


Per Codex 1 cite audit (`docs/superpowers/specs/.staging/CODEX1_CITE_AUDIT.tsv`), 22 of 30 sampled file:line cites in §11.1-§11.5 are STALE against `main` HEAD. Without re-anchoring, ~73% of surgical PRs hit "no such code at this line" failures.

**Action**: Single PR (or batched PR-prep step) re-anchors every line cite in §11 v3 against `main` HEAD. Use the TSV as canonical input. Before any surgical PR (#3, #5a/b, #6, #8, #9, #11, #14, #15, #16, #17, #19, #23, #25, #29, #33, #34, #43, #45, #52, #61, #62, #B5-A4, #B5-U4) is opened, re-verify cite via `git show main:<file>` and update the PR row.

**Acceptance**: 0 cite errors when running static check `git show main:<cited_file> | sed -n 'NL,NLp'` against every cite. CI gate added: `scripts/verify_pr_cites.py` walks §11 PR rows and confirms every cite resolves.

**Effort**: M (write the verification script + walk all ~90 PR rows + commit corrected rows).

### 11.1 Block 1 — Immediate blockers (~3 days, 14 PRs)

Pipeline-can-run + perf gate + security baseline. All Block-1 PRs land sequentially (with parallelization after #3 lands) before any pilot code is touched. **Prereq:** §11.0.5 cite-refresh PR has merged.

**Phase 2 Fix 2.2 — Block-1 detrash:** PRs #6 (`align_to_normal` default), #7 (`chunk_world_size` default), #10 (`bytes += scanline` micro-perf) moved to §11.4 (Block 4 polish) per scope-guardian review. They are correctness/polish one-liners, not pipeline blockers. PRs #14 (chunk_seed promotion) + #15 (hash hazard fix, security baseline) remain in Block 1.

| PR # | Title | Files (file:line) | Acceptance | Validation | Effort | Deps |
|------|-------|-------------------|------------|------------|--------|------|
| 1 | chore(repo): gitignore + LFS hygiene | `.gitignore` | • `output/chunks/`, `renders/pilot/`, `*.blend1`, `output/aaa_node_v3/` ignored<br>• `git status` clean after first pilot bake dry-run | `git status --porcelain` empty after `make bake-dry-run` | S | none |
| 2 | chore(deps): pyproject runtime + bake extras + CVE fixes | `pyproject.toml` | • `taichi>=1.7,<2.0`, `rasterio>=1.4`, `PyYAML>=6.0` declared<br>• `Pillow>=10.4` (CVE-2023-50447, CVE-2024-28219)<br>• `[bake]` and `[providers]` extras added (split `[providers]` + `[geo]` extras — absorbs former B5-DEP1)<br>• `pyright==1.1.408` pinned; `numpy<2.0` cap on Blender lane<br>• `gradio_client`, `requests`, `huggingface_hub` declared | `pip install -e ".[bake,providers,geo,dev]"` succeeds; `pip-audit` zero CRITICAL | S | #1 |
| 3 | fix(pipeline): topo-sort consumes `overrides=` to break dual-cycles | `handlers/terrain_pipeline.py:1449-1510` | • Edge `A→B` for channel `c` suppressed when `c in B.overrides_channels`<br>• 6 dual-cycle regression tests pass<br>• `register_default_passes` no longer raises ValueError on full registry load | `pytest tests/test_terrain_pipeline_toposort_overrides.py -k overrides_breaks_cycle` | M | #2 |
| 4 | fix(pipeline): wire 8 orphan passes into `build_default_pass_sequence` + carry C-1 amendment | `handlers/terrain_pipeline.py:169-261`; spec §3 lines 124, 237 (amend to `biome_seed`/`chunk_seed`); 6 missing `register_*_pass` functions across `terrain_cliffs.py`, `terrain_caves.py`, `coastline.py`, `terrain_karst.py`, `terrain_wind_erosion.py`, `terrain_stratigraphy.py` | • (a) Ensure `register_*_pass` exists for each of the 8 orphans (currently only 2 of 8 do — `pass_water_flow_speed`, `pass_river_convergence`); create 6 missing register functions: cliffs, caves, coastline, karst, wind_erosion, stratigraphy.<br>• (b) Call them from `register_default_passes`.<br>• (c) Insert pass names into pass_sequence at the right phase.<br>• `cliffs`, `caves`, `coastline`, `karst`, `wind_erosion`, `stratigraphy`, `pass_water_flow_speed`, `pass_river_convergence` registered in default sequence<br>• `validate_default_pass_sequence` fixture lists all 8<br>• run_pipeline emits `status="ok"` for all 8<br>• Spec body line 124 and 237 amended to two-tier seed prose | `pytest tests/test_pipeline_default_sequence.py::test_orphan_passes_wired` | M | #3 |
| 5a | fix(water): drop legacy `water_surface` channel writes (W-1 step 1) | `handlers/terrain_water_variants.py:781,878` (drop legacy writes); `TerrainMaskStack.set()` guard rejecting legacy name | • `water_surface` no longer emitted from any pass<br>• Stack-set guard raises on legacy name<br>• 12 legacy water_surface test refs deleted | `pytest tests/test_w1_legacy_writes_removed.py` | M | #3 |
| 5b | fix(water): register canonical W-1 channels (`water_surface_mask`/`water_surface_elevation_m`/`water_depth_m`) and migrate 4 consumers | `handlers/terrain_water_variants.py`; consumers `terrain_unity_export.py:2270-2278`, `terrain_navmesh_export.py:201,329`, `detect_wetlands` (re-ordered before bathymetry); `pass_bathymetry`; `compute_riverbed_caustics` | • Single registry file declares all 3 canonical channels<br>• Spec §3.4 line 192 alternate-name vocabulary deleted<br>• 4 named consumers re-route to canonical channels<br>• PR #37 reads `water_surface_mask` produced here | `pytest tests/test_w1_canonical_channels.py`; `pytest tests/test_w1_consumers_migrated.py` | M | #5a |
| ~~6~~ | **MOVED to Block 4 (§11.4) per Phase 2 Fix 2.2** — `align_to_normal` default flip is correctness/polish, not pipeline blocker. See §11.4 PR #6. | (moved) | (moved) | (moved) | (moved) | (moved) |
| 6.5 | feat(tests): render-baseline PNGs + `compare_render_to_golden` SSIM 0.95 wired into CI (subset of B5-T1, baseline + harness only — promoted to Block 1 to unblock PR #6 render-proof acceptance) | `tests/golden_scenarios/{cave_entrance, cliff_talus_apron, deep_lake_basin, waterfall_plunge_pool}/baseline.png` (4 NEW PNGs); `tests/conftest.py` SSIM helper | • 4 baseline PNGs committed<br>• SSIM 0.95 helper wired in `tests/conftest.py`<br>• Remaining test-infra wiring (CI lane, full goldens framework) stays in B5-T1 | `pytest tests/test_golden_scenarios.py::test_baseline_loads`; manual SSIM round-trip | M | #6 (now in Block 4) |
| ~~7~~ | **MOVED to Block 4 (§11.4) per Phase 2 Fix 2.2** — `chunk_world_size` default change is correctness one-liner, not pipeline blocker. See §11.4 PR #7. | (moved) | (moved) | (moved) | (moved) | (moved) |
| 8 | perf(pipeline): replace `deepcopy(mask_stack)` with channel-shallow + height-COW | `handlers/terrain_pipeline.py:940,956` | • `_lightweight_state_copy` lands<br>• Saves ~30s + 4 GB RAM per default-sequence run on 4096²<br>• Identical hashes pre/post | `pytest tests/test_pipeline_performance.py::test_no_deepcopy`; `pytest --benchmark-only --benchmark-compare baseline` | L | none |
| 9 | perf(roads): vectorize `road_network` SDF via scipy EDT | `handlers/road_network.py:1808-1817` | • Triple loop replaced by `scipy.ndimage.distance_transform_edt`<br>• ~1000× speedup verified<br>• Identical road_sdf_dist output | `pytest tests/test_road_network_sdf_correctness.py`; `pytest --benchmark` | M | none |
| ~~10~~ | **MOVED to Block 4 (§11.4) per Phase 2 Fix 2.2** — `bytes += scanline` micro-perf is polish, not pipeline blocker. See §11.4 PR #10. | (moved) | (moved) | (moved) | (moved) | (moved) |
| 11 | sec(providers): `_safe_filename` for path-injection in 3 providers | `providers/meshy_provider.py:216`, `providers/hunyuan3d2_provider.py:274`, `handlers/asset_generation.py:699,706` | • `species_id` sanitized through `_safe_filename`<br>• Path traversal attempts (`../`, absolute paths, NUL) rejected<br>• Output stays inside `dest_dir` | `pytest tests/test_providers_path_safety.py::test_traversal_blocked` | M | none |
| 12 | fix(unity-export): atomic manifest write + temp-dir bundle pattern | `handlers/terrain_unity_export.py:2484-2510` (real `json.dumps(manifest)` site, NOT line 1612 / 1629); also `:2248` and `:2272` plain `write_text` callsites; helper `_atomic_write_json` + `_write_json:787` | • (a) Replace plain `write_text` at `:2248` and `:2272` with `NamedTemporaryFile` + `os.replace` pattern.<br>• (b) Add helper `_atomic_write_json(path, data)` replacing `_write_json:787` plain `write_text`.<br>• (c) Add `tests/test_unity_export_atomicity.py::test_kill_mid_write`.<br>• Write to `*.tmp` then `os.replace`<br>• No half-written `manifest.json` on crash<br>• Atomic across both manifest + import_descriptor | `pytest tests/test_unity_export_atomicity.py::test_kill_mid_write` | M | #5b |
| 13 | sec(data-quality): NaN/Inf sanitization on Unity-export channels (NOT a security PR) | `handlers/terrain_unity_export.py` various pack-points | • All exported channels sanitized: NaN→0, Inf→clamp(±max_value)<br>• Reframed `fix(data-quality)` per V4 referee — these are correctness, not exploit, vectors<br>• Test: synthetic NaN-poisoned stack produces clean output | `pytest tests/test_unity_export_nan_inf_safe.py` | M | #12 |
| 14 | fix(rng): single-source `derive_pass_seed` via chunk_seed module re-export | `chunks/chunk_seed.py` (NEW; co-with #15.5); `handlers/terrain_rng.py` (transition shim that re-exports from chunks/chunk_seed); `handlers/terrain_pipeline.py` (delete duplicate definition; verify line on `main` — current canonical is `:208`) | • (a) Recognize the duplicate-`derive_pass_seed` claim is stale (only existed on a now-discarded spec-branch state; on `main`, `terrain_rng.py` is 43 lines and contains only `make_rng`/`tile_rng`, while `terrain_pipeline.py:208` is the only `derive_pass_seed` definition; per Codex 1 TSV row 14, `terrain_rng.py:45` is OUT_OF_FILE).<br>• (b) PROMOTE the new `chunks/chunk_seed.py` BLAKE2b API as the single source of truth (co-lands with PR #15.5).<br>• (c) Update `handlers/terrain_rng.py` to import + re-export from `chunks/chunk_seed` (transition shim).<br>• (d) Migrate the 100 production + 79 tests RNG sites per ground truth (NOT 47/58 in stale memory).<br>• Only one `derive_pass_seed` in repo (in `chunks/chunk_seed.py`); `git grep -n "def derive_pass_seed"` returns 1 line | `pytest tests/test_derive_pass_seed_unique.py` | S | #15.5 |
| 15 | fix(determinism): replace ALL 4 hash/sum-of-ord/enumeration hazards (scope expanded per Fix 4.12) | `handlers/terrain_cliffs.py:2368` (`hash(...)` cite corrected from `:2397`); `terrain_cliffs.py:1228, :1467` (sum-of-ord hazards, was `:1502` wrong); `terrain_cliffs.py:2620` (cliff_idx enumeration, was `:2650` wrong); `terrain_caves.py:3894` (cave_i enumeration, was `:3889` wrong) | • All 4 hash/sum-of-ord/enumeration hazards replaced with stable cliff world-coords or `biome+chunk_seed` (NOT enumeration index)<br>• Same byte-output across 3 PYTHONHASHSEED values<br>• Cite refresh confirmed (Fix 1.0 prereq) | `pytest tests/test_determinism_hash_seed.py::test_cliff_id_seed`; `pytest tests/test_determinism_hash_seed.py::test_sum_of_ord_replaced`; `pytest tests/test_determinism_hash_seed.py::test_enumeration_index_replaced` | M | #14 |
| 15.5 | feat(chunks): `chunks/chunk_seed.py` module API (promoted from B5-D1 to break PR #18 ↔ B5-D1 cycle; lands first as API-only, then PR #14 migrates) | new `chunks/chunk_seed.py` (NEW) | • BLAKE2b two-tier API per §8.4 of CE Fixes Guide<br>• `biome_seed(biome, version) → int`<br>• `chunk_seed(biome, x, y, version) → int`<br>• Module is API-only here; migration of 100 prod + 79 test sites lands in PR #18 | `pytest tests/test_chunk_seed_module.py` | M | none |

**Block 1 totals: 14 PR groups / 15 active rows (was 17 before Phase 2 Fix 2.2; PRs #6, #7, #10 moved to Block 4 polish — struck rows preserved here for traceability). Counting convention: PR groups treat #5a + #5b as one logical W-1 step split (canonical-channel migration), giving 14 groups across 15 active rows; struck rows are NOT counted as active. ~3 focused days. Critical path: #1 → #2 → #3 → {#4, #5a→#5b}; #6.5 + #8, #9, #11-#15.5 parallelize after #3.** After Block 1: pipeline runs cleanly, 8 orphan passes execute, W-1 dual-semantics extinct, deepcopy eliminated, security baseline, and chunk_seed module API ready for Block 2 RNG migration.

### 11.2 Block 2 — AAA-parity + long-tail correctness (~3 days parallel, 22 PRs)

Foundation correctness, AAA-parity ecology, mask-channel completeness, determinism hardening. Block 2 may begin once Block 1 #3, #4, #5b are merged; PRs #16-#37 are largely independent and parallelize across multiple agents.

| PR # | Title | Files (file:line) | Acceptance | Validation | Effort | Deps |
|------|-------|-------------------|------------|------------|--------|------|
| 16 | feat(stratigraphy): wire `register_stratigraphy_pass` in master_registrar | `handlers/terrain_master_registrar.py` (Bundle I; insert after `register_wind_erosion_pass`); `handlers/terrain_stratigraphy.py` (add `register_stratigraphy_pass` function) | • ADD `register_stratigraphy_pass` function inside the existing `handlers/terrain_master_registrar.py` file (Bundle I; insert after `register_wind_erosion_pass`). Note the file IS 331 LOC on `main`; only the function is missing.<br>• Stratigraphy pass registered<br>• `pass_terrain_stratigraphy` appears in default sequence after Block 1 #4<br>• E-2 stratification delta applied to height (per audit fix at `terrain_stratigraphy.py:1069`) | `pytest tests/test_stratigraphy_registration.py` | M | #4 |
| 17 | fix(morphology): apply `morphology_delta` to `height` in-pass | `handlers/terrain_morphology.py:459-465` | • After `stack.set("morphology_delta", delta, ...)` add `stack.set("height", height + delta, "pass_morphology")`<br>• Pass declares `overrides=("height",)`<br>• 30 dead landform templates now affect heightmap | `pytest tests/test_morphology_height_delta.py` | M | #16 |
| 18 | fix(determinism): migrate 100 production + 79 test = 179 RNG sites to `derive_pass_seed(biome_seed/chunk_seed)` (effort upgraded L → XL per Fix 4.13 — site count was 58 stale; ground-truth 179) | 100 handlers (full list in `.staging/RNG_SITES_47.txt` — file name preserved as identifier; actual content = 179 sites per ground truth) + 79 tests; **NOT 58 nor 127** (Fix 4.11 ground truth correction) | • `git grep -n "random.Random("` returns ≤ 79 (test-only)<br>• Each migrated site tagged with scope (`biome_seed` for pre-slice, `chunk_seed` for post-slice) per C-1<br>• `_FORBIDDEN_RNG_CALLS` extended to `random.choices/choice/randint/shuffle`<br>• `PYTHONHASHSEED=0` set in CI workflow<br>• Consumes `chunk_seed`/`biome_seed` API created in PR #15.5 | `pytest tests/test_rng_migration.py::test_no_bare_random`; `pytest tests/test_pythonhashseed_set.py` | XL | #14, #15, #15.5 |
| 19 | perf(erosion): Numba/Taichi-jit `priority_flood_d8` + `_erode` (E-1, E-3 fix) | `handlers/_water_network.py:580-664` (Numba-jit + pure-Py fallback); `handlers/_terrain_erosion.py:308-487` (Taichi kernel; clamp particle re-injection at boundary) | • (a) FORBID `atomic_add` on float in Mei-2007 hydraulic kernel.<br>• (b) Use integer atomics OR scan-then-reduce per §8.4 Taichi determinism caveat.<br>• (c) Verify same input → same output to 1 ULP across 5 runs on the same GPU.<br>• E-1 erodibility constants are calibrated Mei-2007 (`Kc=0.022`, `Ks=0.012`, `Kd=0.005`, `Ke=0.005`)<br>• E-3 pure-Py loop replaced by Taichi kernel<br>• `--no-numba` switch for golden test<br>• Hydraulic 200-iter on 4096² runs in <18 s on RTX 4060 Ti | `pytest tests/test_erosion_taichi_kernel.py`; `pytest tests/test_erosion_atomic_float_ban.py`; `pytest --benchmark` | L | #2 |
| 20 | fix(unity-export): `_compat` shim for 14 test imports | `handlers/terrain_unity_export.py` (deprecation notices); new `handlers/_compat.py` | • All 14 internal test imports preserved<br>• Deprecation warnings logged but suite stays green<br>• Removable post-pilot | `pytest tests/test_unity_export_compat.py` | S | #5b |
| 21 | fix(pipeline): declare missing `requires_channels` and `overrides=` on 16+ passes | `climate_zone`, `forest_mask`, `canopy_density`, `pass_road_network` (overrides road_mask + height), `quixel_ingest` (overrides macro_color, roughness_variation, terrain_normals, terrain_displacement, terrain_ao — currently only declares `splatmap_weights_layer`), `waterfalls` (overrides `particle_emitter_specs`) | • All 16+ passes declare correct contract<br>• Topo-sort no longer needs override-suppression for these<br>• `check_protocol_adoption.py` registry extended (≥60 of 74 passes) | `pytest tests/test_pass_contracts_declared.py` | L | #3 |
| 22 | fix(test-infra): 4 importlib script-loader landmines + 12 legacy water_surface deletions + `@pytest.mark.slow` | `tests/test_dynamic_quality_truth_gates.py`, `tests/test_visual_render_camera_proof.py`, `tests/test_scene_v3_visual_quality_gate.py` (one more importlib site), `tests/test_callable_orphan_contracts.py:283,290` | • All importlib loaders replaced with regular imports OR test deleted<br>• 12 legacy water_surface refs in tests removed<br>• `@pytest.mark.slow` on tests >2 GB allocation | `pytest tests/` (full suite green) | M | #5b, #20 |
| 23 | fix(env): wrap DAG-escape `road_mask` write closures into registered passes — scope expanded per Fix 4.5 to cover BOTH `_build_road_mask_and_sdf` (V1 verified at `:4630-4689`) AND sister site `_paint_road_mask_on_terrain` (`:5237`) | `handlers/environment.py` — `_build_road_mask_and_sdf` at `:4630-4689` (V1 verified; primary closure) + sister `_paint_road_mask_on_terrain` at `:5237` (Blender-only legacy closures → registered `pass_road_mask_export` + `pass_road_mask_paint`); cite refresh per §11.0.5 prereq (Fix 1.0) | • BOTH closures removed; writes delegated to registered passes<br>• Channel ownership traceable across both sites<br>• Cite refresh confirmed against `main` HEAD (per §11.0.5 prereq) | `pytest tests/test_road_mask_pass.py`; `Grep "road_mask" handlers/environment.py` returns only registered-pass references | M | #21 (cite-refresh per §11.0.5 prereq required before opening this PR; prereq is not a numbered PR — see Fix R9 cleanup) |
| 24 | fix(cliffs): make overhang threshold configurable; CORRECT cite `terrain_cliffs.py:890` | `handlers/terrain_cliffs.py:890` (real `radians(88.0)`); add config `overhang_threshold_deg` defaulting to 88 with docs that 80 = aggressive, 88 = conservative; do NOT use comments-only 60° / 80° (V3 forensic confirms cite `857-858` is WRONG) | • Threshold sourced from intent config<br>• Defaults documented<br>• Regression test asserts no overhang at 89°+ when threshold=88 | `pytest tests/test_overhang_threshold_configurable.py` | M | #21 |
| 25 | fix(world): biome archetype collapse cite correction; CORRECT cite `environment.py:1205` (canonical first occurrence per Codex 1 cite-refresh) | `handlers/environment.py:1205` (canonical first occurrence: `terrain_type = params.get("terrain_type", "mountains")`); +4 sister callsites at `:2020, :2322, :2990, :3043` (verified via `git show main:veilbreakers_terrain/handlers/environment.py | grep -n 'params.get("terrain_type"'`); v2 PR #25 cited `_terrain_world.py:861-869` which is WRONG (that file is 1667 lines and lines 861-869 are seed/needs_generate); cite at `:2031` (per Fix 1.0 / Codex 1 TSV) is also stale — actual canonical is `:1205` | • Default `terrain_type` collapse documented at correct cite (`:1205`)<br>• "mountains" default unchanged for backward-compat; new biome path takes precedence when supplied<br>• 4 sister callsites (`:2020, :2322, :2990, :3043`) flagged for next sweep | `pytest tests/test_biome_collapse_cite.py` | S | none |
| 26 | feat(coastline): rescue PR — Bezier-SDF smooth shorelines (`landform_zones.py` + `shoreline_sdf.py` files do NOT exist on disk) | new `coastal/landform_zones.py`, `coastal/shoreline_sdf.py` (NET-NEW files; only stale `.pyc` artifacts present) | • Bezier-SDF math NEW module<br>• Provides sub-cell-resolution smooth shorelines (NOT a duplicate of grid-binary chunk zone IDs at spec §3.5)<br>• Coastal pilot consumes for `wave_fetch` smoothing | `pytest tests/test_coastal_landform_sdf.py` | M | #5b |
| 27 | feat(scatter): parent-child scatter rules (1 of 2 net-new AAA gaps) | `foliage/scatter/parent_child_rules.py` | • Parent species defines child placement rules (e.g., creosote ring exclusion, mother-tree saplings)<br>• Tree imposters and shrubs are already in spec §4.4 + §4.8 (NOT new) — V4 confirms 4-net-new claim was over-inflated<br>• 4 species pairs configured for pilot biomes | `pytest tests/test_scatter_parent_child.py` | M | (none — PR #27 placement logic is orthogonal to PR #6 `align_to_normal` trunk-rotation default; soft-ordering after #6 if both in flight is preferred so render-proof acceptance of cliff_talus_apron isn't muddied by diagonal-trunk noise, but PR #27 can land first per Phase 2.5 Fix D — #6 now in Block 4 §11.4) |
| 28 | feat(scatter): artist override layer (2 of 2 net-new AAA gaps) | `foliage/scatter/artist_override.py`; `foliage/species_libs/<biome>_overrides.yaml` | • Artist YAML can pin individual hero positions, suppress regions, force species<br>• Loaded after procedural scatter, before exclusion masks<br>• Mountain pilot has 4 hand-pinned heroes in YAML | `pytest tests/test_artist_override_scatter.py`; render-proof: hero positions match YAML | M | #27 |
| 29 | feat(label-stamping): generator-stamping for cliff/water/rock/gravel labels (Issue #27 architectural fix) | `terrain_cliffs.py` stamps `cliff_label`; `terrain_water_variants.py` stamps `water_label`; `terrain_features.py` stamps `rock_label`; `terrain_morphology.py` stamps `gravel_label`. `terrain_pipeline.py:1054` (`pass_compute_terrain_labels` definition; cite corrected per Codex 1 TSV — `:1133-1191` was actually `pass_compute_biome_channels`, a different pass) becomes validator/clamp (verified via `git show main:veilbreakers_terrain/handlers/terrain_pipeline.py | grep -n 'def pass_compute_terrain_labels'` → `1054:def pass_compute_terrain_labels(`) | • Each generator stamps its owned label channel<br>• `pass_compute_terrain_labels` (at `terrain_pipeline.py:1054`) clamps to [0, 1] but does NOT zero-fill when generator stamped<br>• `std(label) > 0` in 100% of pilot chunks<br>• Issue #27 closes; **DO NOT use "synthesize from `slope_deg>60°`" alone — that is a regression per V3 forensic** | `pytest tests/test_terrain_labels_generator_stamped.py::test_std_gt_zero_all_chunks` | L | #4, #16, #17 |
| 30 | fix(waterfalls): foam alpha both factors corrected | `handlers/terrain_waterfalls.py:115` (`prox_ratio` and `speed_ratio` both inverted; correct formula in doc-comment at lines 100-101) | • `prox_ratio = saturate(obstacle_proximity / max(foam_radius, 1e-9))` (drop the `1.0 -`)<br>• `speed_ratio = flow_speed / max(max_foam_speed, 1e-9)` (drop the `1.0 -`)<br>• Foam appears at obstacles with high flow (correct AAA reference) | `pytest tests/test_waterfall_foam_alpha.py::test_high_velocity_at_obstacle_produces_foam` | S | none |
| 31 | fix(macro_color): expand `consumed_channels` to actual reads | `handlers/terrain_macro_color.py:230` (currently `("height",)`; actually reads `biome_id`, `wetness`, `erosion_amount`, `deposition_amount`, `albedo_shift_rgb`, `snow_line_factor`, `strata_cross_section`) | • `consumed_channels=("height", "biome_id", "wetness", "erosion_amount", "deposition_amount", "albedo_shift_rgb", "snow_line_factor", "strata_cross_section")` (8 channels, not 1)<br>• Topo-sort places macro_color after producers of all 8<br>• No silent KeyError on missing channels (all guarded) | `pytest tests/test_macro_color_consumed_channels.py` | M | #21 |
| 32 | fix(macro_color): extend `DARK_FANTASY_PALETTE` to all 14 biomes | `handlers/terrain_macro_color.py:28-37` (currently 8 entries; biomes 8-13 fall through to `pal.get(bid, default_rgb)` to biome-0 umber) | • Add entries for biome IDs 8-13 (volcanic, frozen, desert, jungle_wet, marsh, ash_plain)<br>• Confirm fallback color is documented as biome-0 umber, not grey<br>• 14 entries total, snapshot test asserts hash | `pytest tests/test_dark_fantasy_palette_complete.py` | S | #31 |
| 33 | fix(audio_zones): line-count and Sabine cite correction | spec body where `terrain_audio_zones.py` referenced (real LOC = **1049**, not 989); Sabine reverb cites at lines 539 (cave/2s) and 554 (open-field/0.1-0.3s) | • Spec body line-count text updated<br>• Sabine references correct<br>• Cave reverb consumes cave FBX bounding box per §12.3 contract | `git grep -n "989 lines"`; `pytest tests/test_audio_zones_sabine_cite.py` | S | none |
| 34 | feat(checkpoints): ID-keyed registries on `id(controller)` documented | `handlers/terrain_checkpoints.py:97-102` (`_LABEL_REGISTRY: Dict[int, ...]`, `_AUTOSAVE_CONTROLLERS: Dict[int, bool]`, `_ORIGINAL_RUN_PASS: Dict[int, ...]` all keyed by `id(controller)`) | • Module docstring documents `id(controller)` keying contract<br>• Cleanup hooks unregister entries on controller dispose<br>• Memory-leak test: 1000 dispose cycles → no growth | `pytest tests/test_checkpoint_registry_id_keyed.py` | S | none |
| 35 | fix(except-swallow): demote `bundle_n` post-pipeline error from `log.error` to hard fail | `handlers/terrain_pipeline.py:992-999` (`except Exception: log.error(...)` swallows hard budget violations) | • `bundle_n_post_pipeline_hooks` exception classifies between recoverable and unrecoverable<br>• Budget-violation exceptions raised, not logged-and-swallowed<br>• Test asserts pipeline raises when budget violated | `pytest tests/test_except_swallow_demoted.py::test_budget_violation_raises` | M | #36 |
| 36 | feat(asset-budget): split `splatmap_layer_count` 4→8 (Unity 2022+ HDRP supports 8) | `handlers/terrain_quality_profiles.py:182` (default), `:352`, `:408`, `:464`, `:520` (4 profile instances) + `handlers/terrain_budget_enforcer.py:211` (consumer); fix `default_dark_fantasy_rules` 5-channel emit; fix `build_terrain_aaa_node_v6.py:597-605` silent truncate to RGBA | • All profiles: `splatmap_layer_count = 8`<br>• `default_dark_fantasy_rules` produces 8 channels<br>• v6 lines 597-605 emit `splat_secondary.png` for layers 4-7 (does not truncate)<br>• PR #41 (single-chunk re-bake) verifies splat_secondary persists | `pytest tests/test_splatmap_8_layer.py` | M | #2 |
| 37 | feat(label-stamping): water_label stamping reads `water_surface_mask` from PR #5b | `handlers/terrain_water_variants.py` (water_label stamping); requires `water_surface_mask` channel registered | • `water_label = water_surface_mask` (binary)<br>• Test confirms `std(water_label) > 0` in pilot chunks with rivers/lakes<br>• Validator (#29) does not zero-fill when stamped | `pytest tests/test_water_label_stamping.py` | M | #5b, #29 |

**Block 2 totals: 22 PRs, ~3 days parallelized.** Critical path inside block: #29 (label-stamping architecture) is the longest single PR (L effort) but unblocks Issue #27 closure.

### 11.3 Block 3 — Tile-seam + concurrency + DEM (~2 days, 11 PRs)

Tile-seam contract correctness, concurrency safety in pipeline parallel-merge, DEM ingestion + procedural overlay foundation.

| PR # | Title | Files (file:line) | Acceptance | Validation | Effort | Deps |
|------|-------|-------------------|------------|------------|--------|------|
| 38 | feat(chunks): edge-vert sharing assert (`chunk[i,j].east == chunk[i+1,j].west`) | new `chunks/edge_contract.py`; `tests/test_edge_vert_sharing.py` | • 257-vert edge math validated<br>• Synthetic 8×8 grid passes assertion<br>• Edge tolerance 1e-3m enforced | `pytest tests/test_edge_vert_sharing.py` | M | #4 |
| 39 | feat(chunks): `edges.json` writer + reader + N/S/E/W feature-thread schema | new `chunks/edge_contract.py`; format per spec §6.3 | • `edges.json` round-trip (write→read→assert)<br>• `feature_threads` array supports `kind ∈ {river, ridge, road}`<br>• Schema versioned (`schema_version: 2`) | `pytest tests/test_edges_json_roundtrip.py` | M | #38 |
| 40 | feat(splat): seam re-normalize across chunk boundary (sum-to-1.0) | `unity_export_v2/splat_layers.py` (NEW); after 8-channel splat write | • Each pixel's splat weights sum to 1.0 ± 1e-4<br>• Renormalization happens on slice boundary so no half-blend at edges<br>• Test: 2-chunk synthetic biome shows zero edge popping | `pytest tests/test_splat_seam_renormalize.py` | M | #36 |
| 41 | feat(asset-budget): BC6H/BC7/BC5 compression enforcement | new `unity_export_v2/texture_compression.py` (or extension); selectors: BC6H for HDR, BC7 for albedo, BC5 for tangent-space normals | • Hard validator: any uncompressed PNG path → `BudgetViolation`<br>• Splatmap baked as PNG (not OpenEXR — fix the §6.1 violation)<br>• Per-layer textures BC7-compressed | `pytest tests/test_texture_compression_enforced.py` | M | #36 |
| 42 | feat(asset-budget): missing emitters (`splat_secondary.png`, `holes.png`, `flow_map.png` RG16, `triplanar_mask.png`, `vertex_ao.bin`, per-layer `albedo/normal/mask/height/detail.png`) | new `unity_export_v2/chunk_artifacts.py` extensions | • All 18 manifest artifacts written (not 14 as v6 currently does)<br>• `holes.png` R8, `flow_map.png` RG16, `vertex_ao.bin` baked<br>• Per-chunk file count enforced (≤ 50 per chunk per spec §6.5) | `pytest tests/test_chunk_artifacts_complete_18.py` | L | #36, #41 |
| 43 | fix(asset-budget): `lod_meshes == []` validator + block manifest emission | `vegetation_system.py:1561, :1600` (the actual `lod_meshes` locations on `main` per Codex 1 TSV — `:1284` was stale and pointed to `# Pure-logic spec mode`); `procedural_grass.py:685` (cite corrected from `:720` which was empty line per TSV); new validator | • `lod_meshes == []` raises `LodMeshValidationError`<br>• Manifest emission blocked until LOD chain complete<br>• v6 stub (32×32 controller path) cannot bypass | `pytest tests/test_lod_meshes_validator.py` | M | #36, #35 |
| 44 | feat(unity-export): streaming budget hard cap (2 GB chunk-artifact + per-chunk file count) | `unity_export_v2/chunk_artifacts.py`; reads `meta.json.memory_budget_mb` | • 2 GB hard cap per spec §6.5<br>• Per-chunk file-count cap (≤ 50)<br>• Tested: synthetic over-budget chunk fails fast | `pytest tests/test_streaming_budget_enforced.py` | M | #42 |
| 45 | fix(pipeline): `pass_hydrology` insert cite correction | `handlers/environment.py:2861` (`requested_passes[3:3] = ["pass_hydrology", "erosion"]`) — pre-erosion confirmed; v2 PR #45 cited `2017-2019` which is WRONG (that range is unrelated `requested_biome_name` reads) | • Cite documented<br>• Insert position verified pre-erosion<br>• Test asserts `pass_hydrology` runs before `erosion` in default sequence | `pytest tests/test_pass_hydrology_insert_position.py` | S | #4 |
| 46 | feat(pipeline): Rule-1 gate restored on scene-read (consumes #3 toposort overrides) | new `handlers/_rule1_gate.py`; integrated with `TerrainPassController` | • Rule-1 gate active on scene-read paths<br>• Bypass at v6 controller flagged (audit referenced; PR #36 starts the wider fix)<br>• Toposort respects gate ordering | `pytest tests/test_rule1_gate_active.py` | M | #3 |
| 47 | feat(perf): create `_parallel_merge.py` with thread-safe attribute-bypass write pattern (per §8.4 atomic-float ban) | new `handlers/_parallel_merge.py` (file does NOT exist on `main`; this is a NEW module, not a fix); add explicit `merge_channel(...)` API; the audit-referenced "setattr bypass leak" is a target spec for what the new module must avoid | • New `_parallel_merge.py` module created<br>• No `setattr(stack, key, value)` bypass in module API<br>• Merge respects channel ownership + topo order<br>• Concurrent run produces identical output to serial | `pytest tests/test_parallel_merge_safe.py` | M | #21 |
| 48 | fix(unity-export): consolidate writer edits — explicit dep chain #11 → #12 → #44 → #5b → #48 | `handlers/terrain_unity_export.py` (no new code; reorders metadata population) | • Single canonical channel layout in writer<br>• 29-field `VbTerrainTileMetadata` populated (NOT 3-field stub — memory correction in §11.10)<br>• Writer-edit serialization prevents merge collisions | `pytest tests/test_unity_export_metadata_29_fields.py` | M | #12, #44, #5b |

**Block 3 totals: 11 PRs, ~2 days.** Critical path: #38 → #39 → #40 → {#41, #42, #43, #44, #48}; #45-#47 independent.

### 11.4 Block 4 — Polish + rescue + infra + ecology demoted (~2 days, 12 PRs after Phase 4 fixes)

Per-biome ecology demoted from B1 to B4 polish (P3 severity for dark-fantasy game), rescue PRs, scope-relocation infra. **Phase 2 Fix 2.2** added 3 polish PRs (#6, #7, #10) moved from Block 1; **Phase 2 Fix 2.3** then deferred 5 refactor PRs (#49-#52, #54) to v1.1; **Phase 4 Fix 4.10** added PR #65 (dead-RNG cleanup), leaving Block 4 net at 12 active PRs (13 baseline + 3 added by Fix 2.2 − 5 deferred by Fix 2.3 + 1 added by Fix 4.10 = 12).

| PR # | Title | Files (file:line) | Acceptance | Validation | Effort | Deps |
|------|-------|-------------------|------------|------------|--------|------|
| 6 | fix(foliage): `align_to_normal` default False (kill diagonal-trunk bug) — moved from Block 1 per Phase 2 Fix 2.2 | `handlers/terrain_advanced.py:2652` (`True` → `False`) | • Default kwarg flipped<br>• 0 diagonal trunks in `golden_scenarios/cliff_talus_apron` reference render | `pytest tests/test_align_to_normal_default.py`; manual: render `cliff_talus_apron` and inspect 10 trunks at `slope > 30°` | S | none |
| 7 | fix(chunking): `chunk_world_size` default 512m — moved from Block 1 per Phase 2 Fix 2.2 | `handlers/terrain_chunking.py:100` (`64.0` → `512.0`) | • Default size 512m<br>• 12 callers audited; none broken by default change<br>• Assertion `chunk_world_size in {64, 128, 256, 512}` | `pytest tests/test_chunk_world_size_default.py` | M | none |
| 10 | perf(shadow): `bytes += scanline` → `io.BytesIO()` — moved from Block 1 per Phase 2 Fix 2.2 | `handlers/terrain_shadow_clipmap_bake.py:317-322` | • Use `io.BytesIO()` + write<br>• 64 GB churn → 64 MB churn | `pytest tests/test_shadow_clipmap_bake.py`; manual: `tracemalloc` peak under 100 MB | S | none |
| ~~49~~ | **DEFERRED to v1.1 (post-pilot) per Phase 2 Fix 2.3** — `procedural_meshes.py` relocation (XL refactor, 22,816 LOC) is not pilot-blocking. See §11.8 #13. | (deferred) | (deferred) | (deferred) | (deferred) | (deferred) |
| ~~50~~ | **DEFERRED to v1.1 (post-pilot) per Phase 2 Fix 2.3** — animation-modules relocation (L refactor, ~3K LOC) is not pilot-blocking. See §11.8 #13. | (deferred) | (deferred) | (deferred) | (deferred) | (deferred) |
| ~~51~~ | **DEFERRED to v1.1 (post-pilot) per Phase 2 Fix 2.3** — `terrain_core.py` extraction (M refactor) is not pilot-blocking; PRs #14/#52/#54 dependents folded into deferral. See §11.8 #13. | (deferred) | (deferred) | (deferred) | (deferred) | (deferred) |
| ~~52~~ | **DEFERRED to v1.1 (post-pilot) per Phase 2 Fix 2.3** — `terrain_semantics.py` 82-importer split (L refactor) is not pilot-blocking. See §11.8 #13. | (deferred) | (deferred) | (deferred) | (deferred) | (deferred) |
| ~~53~~ | **DEFERRED to v1.1 (post-pilot)** — environment.py 5-seam split moved out of Block 4 to §11.8. XL refactor is not pilot-blocking; PRs #23/#25/#45 surgical edits would be invalidated by mid-pilot split. See §11.8 #12. | (deferred) | (deferred) | (deferred) | (deferred) | (deferred) |
| ~~54~~ | **DEFERRED to v1.1 (post-pilot) per Phase 2 Fix 2.3** — `terrain_features.py` 9-seam split (XL refactor) is not pilot-blocking. See §11.8 #13. | (deferred) | (deferred) | (deferred) | (deferred) | (deferred) |
| 55 | chore(deletes): locked-list — 47 deprecated scripts + stale audit docs + monolithic `output/visual_nodes/` | `scripts/deprecated/*` (6); 47 deprecated scripts; `terrain_scatter_altitude_safety.py`; `terrain_legacy_bug_fixes.py`; `asset_generation.py` (after replace 1 import); 14 superseded markdown docs (4× `MASTER_AUDIT_V*_2026_04_19.md`, deep_dive_2026_04_20 trio, GLM_IMPLEMENTATION_PLAN, scratch reconstruct files); 5 MB stale audit docs (V2-V5_2026_04_19, deep_dive_2026_04_16/17, R11/R12, m3_verification, manual_review_batches CSVs); 935 MB `output/visual_nodes/*` (8 .blend); ~280 MB `output/aaa_node_v*/scene_v*`; 120 MB `*.blend1` from LFS | • **5,746 LOC + ~1.3 GB reclaimed**<br>• Single PR with locked file list<br>• Run AFTER #56 (vegetation_system defaults fix) to break #55 ↔ #56 cycle | `git ls-files` shows expected delete list; CI green | M | #5b, #2, #11, #56 |
| 56 | fix(vegetation): repair `vegetation_system.py` defaults so #55 can delete safely | `handlers/vegetation_system.py:1561, :1600` (existing `lod_meshes = []` default — cite corrected per Codex 1 TSV; `:1284` was stale and pointed to `# Pure-logic spec mode`) + `:1534` (manifest writer); fix BEFORE #55 deletes file | • Defaults repaired so other callers do not break on delete<br>• 1-step ordering: #56 lands first, then #55 deletes the file<br>• Resolves #56 ↔ #55 cycle from Wave-5 §B.1 | `pytest tests/test_vegetation_defaults_repaired.py` | M | #43 |
| 57 | demote(ecology): per-biome scattering rules (mountain) | `foliage/species_libs/mountain.yaml` + `foliage/scatter/biome_specific/mountain.py` | • Mountain scatter inherits from generic + biome-specific overrides<br>• v2 PR #20 demoted from B1 to B4: dark-fantasy game, P3 polish severity (per V4 referee + user feedback)<br>• References Appendix B.1 species inventory | `pytest tests/test_mountain_ecology.py` | M | #27, #28 |
| 58 | demote(ecology): per-biome scattering rules (grassland) | `foliage/species_libs/grassland.yaml` + `foliage/scatter/biome_specific/grassland.py` | • References Appendix B.2 species inventory<br>• v2 PR #21 demoted from B1 to B4 | `pytest tests/test_grassland_ecology.py` | M | #57 |
| 60 | feat(quixel): linear-space blend verification | `handlers/terrain_quixel_ingest.py:619` (verify `_srgb_to_linear` on albedo); also verify roughness/normal paths linearize | • Quixel materials blend in linear, not sRGB (P0-A4-5 from MASTER 04-27)<br>• Test asserts roughness/normal linearization | `pytest tests/test_quixel_linear_blend.py` | M | #2 |
| 61 | feat(shader): `HistogramPreservingBlend` HLSL implements Heitz/Neyret Eq.8/11 | `terrain_stochastic_shader.py:51-265` (currently URP-tagged at lines 73, 263; rewrite for HDRP correctness — P0-A4-2) | • HLSL implements Eq.8/11 correctly<br>• `terrain_banded_advanced.py:542` no longer hardcodes `variant="classic"`<br>• `intent.stochastic_variant` threaded through (B15-P1-19) | `pytest tests/test_stochastic_shader_heitz_neyret.py` | L | #2 |
| 62 | gate(W-1): verify pass_water_depth skip + close Issue #28 after test passes | `handlers/terrain_pipeline.py:1275-1330` (`pass_water_depth`); skip path at `:1306-1312`; new `tests/test_water_depth_skip.py`; GitHub issue #28 | • (a) Verify `pass_water_depth` skip behavior at `terrain_pipeline.py:1306-1312` is correct (already coded — `if ws_elev is None or height is None: return PassResult(... status="skipped")`)<br>• (b) Add `tests/test_water_depth_skip.py` with happy/none-elevation/none-height cases<br>• (c) Close GitHub issue #28 only after both pass<br>• Producers exist at `terrain_water_variants.py:880` (water_variants writer) and `:1463` (bathymetry) | `pytest tests/test_water_depth_skip.py` | S | #5b, #18 |
| 64 | fix(unity-export): `UNITY_SCALE_FACTOR` 0.85 → 1.0 — character-rig hack incorrectly applied to mesh export per §8.1 Blender→Unity research | `handlers/terrain_unity_export.py:31` (constant); verify `_apply_unity_scale()` callsites at `:39, :41, :42, :331, :1014, :1441, :2171, :2843` (check via `git show main:`) | • Constant changed to 1.0<br>• All 8 callsite line numbers verified against `main` (per Codex 1 cite-refresh)<br>• Bake 1 chunk; verify Unity-side mesh is 1:1 with bake-side<br>• Manual integration: open chunk in Unity, dimensions match Blender bake within 1e-3m tolerance | `pytest tests/test_unity_scale_factor_unity.py`; manual: bake 1 chunk + Unity import dimensions check | S | #12, B5-C2 |
| 65 | chore(rng): delete 2 dead-RNG instantiations (Fix 4.10 — cite-refresh per Fix R1: 3rd site `terrain_materials_v2.py` does NOT contain `_ = _pass_rng` on `main` HEAD; verified via `git show main:veilbreakers_terrain/handlers/terrain_materials_v2.py | grep -n "_pass_rng\|_ = "` returned no matches; worktree may have it but `main` does not) | `terrain_features.py:2182` (`_ = rng  # reserved for future jitter`; verified via `git show main:` grep), `terrain_waterfalls.py:2294` (`_ = np.random.default_rng(derived_seed)`; verified via `git show main:` grep) | • Both dead-RNG instantiations removed (assigned to `_` and never used)<br>• No behavioral change<br>• Reduces RNG-site count noise in PR #18 ground-truth list | `pytest tests/test_dead_rng_cleanup.py`; `Grep "_ = rng\|_ = np.random.default_rng" veilbreakers_terrain/` returns 0 | XS | none |

**Block 4 totals: 12 active PRs (after Phase 2 Fix 2.2 added #6/#7/#10 from Block 1, Phase 2 Fix 2.3 deferred #49/#50/#51/#52/#54 alongside the already-deferred #53, and Phase 4 Fix 4.10 added PR #65 dead-RNG cleanup). Active: #6, #7, #10, #55, #56, #57, #58, #60, #61, #62, #64, #65. ~2 days. PR #53 deferred to v1.1 per Fix 1.6 (see §11.8 #12); PRs #49/#50/#51/#52/#54 deferred to v1.1 per Phase 2 Fix 2.3 (see §11.8 #13). All 6 refactor PRs (#49-#54) now deferred as a single grouped v1.1 entry. #55-#62, #64, #65 plus the migrated #6/#7/#10 polish must land for pilot acceptance.**

### 11.5 Block 5 — Unity-side workstream + cross-cutting hardening (split BY SEVERITY into 5a/5b/6 per Phase 2 Fix 2.1)

Block 5 is a separate workstream from Block 1-4 bake-side PRs. Requires **Unity engineer** + HDRP shader graph development + asset-budget hardening + single-chunk re-bake module + test infra + dependency hardening + doc rot cleanup.

**Phase 2 Fix 2.1 — split BY SEVERITY (NOT wholesale):** R2-Opus-2 flagged the original "wholesale move post-pilot" as a structural error that would defer P0 security PRs. Round-3 corrected this with a 3-way severity split:

- **Block 5a — Pilot-blocking Unity parity** (lands during pilot): the 5 BLOCKING Unity-side gaps from §11.7 #2 — PRs **B5-U1, B5-U2, B5-U3, B5-U4, B5-U5**. Without these, pilot Unity ingestion fails.
- **Block 5b — Pilot-supporting infra** (lands during pilot): B5-U6 through B5-U14 (Unity polish), §11.5.3 single-chunk re-bake (B5-D2/D3/D4), §11.5.5 asset budget hardening (B5-A1/A2/A3/A4), pilot-critical security/serialization items: B5-C2 (`terrain_unity_export.py` writer-edit serialize), B5-C6 (`terrain_pipeline.py` writer-edit serialize); §11.5.4 pilot test items B5-T1 (render goldens framework) + B5-T4 (byte-identity 18 artifacts); §11.5.6 conditional B5-DEP4 + B5-DEP5 (only if §11.7 #3 picks Path 2 / Path 3).
- **Block 6 — Post-pilot maturity** (deferred to v1.1; see §11.6.1): §11.5.2 remaining (B5-C1 channel-naming + YAML lint, B5-C3 cycle-break ordering, B5-C5 channel-registration doc); §11.5.4 test-infra maturity (B5-T2 pytest-benchmark + nightly perf, B5-T3 hypothesis property tests, B5-T5 protocol enforcement 21/74 → 60/74, B5-T6 pytest-rerunfailures + flaky-hunter, B5-T7 PR-fast vs nightly-full CI split); §11.5.6 remaining dependency hardening (B5-DEP2 lockfile, B5-DEP3 dependabot/CodeQL/SHA-pin); §11.5.7 doc rot cleanup (B5-DOC1 archive, B5-DOC2 04-27 supersede banner, B5-DOC3 nonexistent script cites, B5-DOC4 dirty-tree commit). B5-C4 dropped per Fix 1.1.

PR rows in §11.5.1-§11.5.7 carry a **Sub-block** column tagged `5a`, `5b`, or `6`. The annotation does not change PR identity or count; it only routes work to pilot vs post-pilot calendars.

#### 11.5a Pilot-blocking Unity parity (Block 5a — 6 PRs)

These are the 5 BLOCKING gaps from §11.7 #2 — pilot Unity ingestion fails without them.

#### 11.5b Pilot-supporting infra (Block 5b — most of §11.5.1 polish + §11.5.3 + §11.5.5 + pilot-critical §11.5.2/4/6 entries)

Lands alongside Block 5a during the pilot calendar. See sub-block tags in tables below.

#### 11.5.1 Unity-side parity (5 BLOCKING gaps + 9 polish + 9 Phase 4 net-new = B5-U-NAV [navmesh Recast/Detour] + B5-U15 [APV] + B5-U16 [MeshDataArray + Burst] + B5-U17 [DrawInstancedIndirect foliage] + B5-U18 [static batching contract] + B5-U19 [BC7/ASTC compression] + B5-U20 [memory budget enforcer] + B5-U21 [shadow cascade + contact shadows] + B5-U22 [reflection probe placement])

The bake-side PRs in Blocks 1-4 do **NOT** fix any of these. Block 5 is required for Unity ingestion. Sub-block column tags Block 5a (pilot-blocking) vs Block 5b (pilot-supporting).

| PR # | Sub-block | Title | Files (file:line) | Acceptance | Validation | Effort | Deps |
|------|-----------|-------|-------------------|------------|------------|--------|------|
| B5-U1 | 5a | feat(unity): integrate MicroSplat HDRP 2022 + Mesh Terrains ($40, RECOMMENDED) OR author custom HDRP shader graph stack ([AUTO-APPLIED — Decision 3.2 / pending user override]) | (a) MicroSplat path: `unity_project/Assets/MicroSplat/` package + 2 module imports; OR (b) custom path: new `unity_project/Assets/Shaders/{VbTerrainLitTriplanar,AntiTile,DistanceNormal,OverlayDynamic}.shadergraph` + master + 2 subgraphs per spec §6.6 | • EITHER: (a) buy + integrate MicroSplat HDRP 2022 + Mesh Terrains modules ($40, RECOMMENDED — FREE base + $20 + $20; saves ~2 weeks solo-dev time); OR (b) author 4 .shadergraph files from scratch (~12-18 days solo-dev realistic) AND `acceptance_checks.py` validates them<br>• Currently 0 .shadergraph files exist on disk (audit B.3 — F grade ~10%) | Manual: open in Unity 2022 LTS HDRP, MicroSplat layer stack compiles or all 4 .shadergraph files compile; `acceptance_checks.py` exits 0 | XL | none |
| B5-U2 | 5a | feat(unity): instantiate HDRP `WaterSurface` from `water.json` | `unity_project/Assets/Scripts/VbTerrainImporter.cs:1150-1153` (currently logs "raster-backed water mesh creation disabled" + skips); replace with WaterSurface creation per ocean/river/lake interfaces | • `WaterSurface` instantiated for each water body in water.json<br>• Ocean type infinite mesh, Pool type from polyline, River type with currentMap=flow_map.png<br>• Editor smoke-test loads pilot mountain chunk with river → river surface visible | Manual: open Unity, load pilot chunk, river WaterSurface present | L | B5-U1 |
| B5-U3 | 5a | feat(unity): `holes.png` consumer (`terrainData.SetHoles`) | `VbTerrainImporter.cs:1150-1153` adjacent (no `SetHoles` call currently) | • `terrainData.SetHoles(holes_array)` invoked<br>• Mandatory contract item 13 passes<br>• Editor: chunk with cave undercut shows hole | Manual: chunk with cave loads, hole visible | M | B5-U1 |
| B5-U4 | 5a | fix(unity): tangent-space normal Y-flip on import | `VbTerrainImporter.cs:ImportTextureAsset:2097` (currently sets `textureType = NormalMap` but never inverts G channel for OpenGL-Y → DX-Y bake side at `terrain_unity_export.py:334` `_pack_tangent_space_normal_rgba`) | • Importer inverts G channel when `textureType = NormalMap`<br>• OR bake side flips before write<br>• Decision documented in inline comment (Unity wants DX-Y) | Manual: render slope geometry, shading direction matches reference; `pytest tests/test_normal_handedness.py` | M | B5-U1 |
| B5-U5 | 5a | feat(unity): `edges.json` edge-stitch contract (BOTH bake AND Unity sides) | bake: `chunks/edge_contract.py` (PR #39); Unity: `VbChunkLoader.cs` `OnNeighborLoaded` event consumer with 1e-3m height tolerance per §6.3 | • Bake-side emitter (PR #39 covers writer)<br>• Unity-side validator runs on `OnNeighborLoaded`<br>• Mismatch: log error + draw red wireframe (Editor) / log warning + edge-blend smooth (Player) per §13.9<br>• Cross-chunk seam pop eliminated | Manual: 2 chunks load, edge-weld assertion passes; intentionally corrupt one heightmap → assertion fails fast in Editor | L | #39 |
| B5-U6 | 5b | feat(unity): vertex AO from `vertex_ao.bin` to vertex color | `VbChunkLoader.cs` (vertex color attribute on terrain mesh) | • `vertex_ao.bin` read on activate, written to vertex_color.r<br>• Test: ambient-only render shows AO darkening | Manual: render contact shadows | M | #42 |
| B5-U7 | 5b | feat(unity): HDRP `DecalProjector` instantiation from `decals.json` | `VbChunkLoader.cs` (decal projector instantiation) | • `decals.json` parsed<br>• HDRP DecalProjector instantiated per entry<br>• Pool released on chunk unload | Manual: chunk loads with decals, decals visible in render | M | #42 |
| B5-U8 | 5b | feat(unity): bind `flow_map.png` to River `WaterSurface.currentMap` | `VbChunkLoader.cs` (after WaterSurface instantiation) | • `flow_map.png` (RG16) bound as currentMap<br>• River flows in correct direction in Editor preview | Manual: river flow visible | M | B5-U2 |
| B5-U9 | 5b | feat(unity): `caves/*.fbx` import + GameObject child | `VbChunkLoader.cs` (cave mesh handoff) | • If `caves/` directory exists, FBX files imported as GameObject children<br>• Collider + render components attached<br>• Despawn on chunk unload | Manual: chunk with cave loads with cave geometry | M | #42 |
| B5-U10 | 5b | feat(unity): TerrainLayer height + detail PNGs bound (currently ignored) | `VbChunkLoader.cs:terrainLayers binding` (currently TerrainLayer only gets diffuse/normal/mask) | • Per-layer height map and detail map bound to TerrainLayer<br>• Parallax + detail micro-variation visible at close range | Manual: close-up render shows parallax + detail texturing | M | #42 |
| B5-U11 | 5b | feat(unity): real tree prefab loader (replace Capsule placeholder) | `VbChunkLoader.cs:GetOrCreateTreePrefab:2152` (per V1 — cite corrected from `:2229`); see also §11.7 #8 architectural decision (rename `unity_plugin/VbTerrainRuntimeStreamer.cs` → `VbChunkLoader.cs`, OR keep both) | • Loads species prefab from Addressables<br>• Falls back to LOD3 imposter atlas if prefab not found<br>• 4 species loaded for pilot biomes | Manual: pilot chunks render with tree species, NOT capsules | L | #42, #27 |
| B5-U12 | 5b | feat(unity): foliage UV2 (lightmap) + UV3 (Pivot Painter wind) + vertex colors | bake: `foliage/wind_uv_bake.py` (UV2/UV3 channels); Unity: VbFoliageImporter passes through | • UV2 has lightmap UVs; UV3 has wind metadata per SpeedTree convention (`UV2 = (sway_freq, branch_amplitude, leaf_flutter, gust_freq)`, `UV3 = (gust_strength, phase_offset, wind_axis_x, wind_axis_y)`)<br>• Wind animation visible in Editor preview<br>• Lightmaps bake without UV overlap | Manual: GPU instancing wind; lightmap bake | L | #42 |
| B5-U13 | 5b | feat(unity): populate all 29 `VbTerrainTileMetadata` fields end-to-end | `unity_plugin/VbTerrainTileMetadata.cs` (Round-4 truth-table: 29 top-level public declarations = 28 simple scalars/strings + 1 `ChannelBound[]` array of structs; verified via `git show main:unity_plugin/VbTerrainTileMetadata.cs`) | • All 29 fields declared and JSON-deserializable: `WorldId`, `TileX`, `TileY`, `TileSize`, `CellSize`, `HeightMinMeters`, `HeightMaxMeters`, `HeightScaleFactor`, `CoordinateSystem`, `SourceCoordinateSystem`, `ValidationStatus`, `ValidationIssueCount`, `SeamContractWorldId`, `TerrainNormalsFile`, `TerrainNormalMapFile`, `TerrainNormalMapAssetPath`, `NavMeshAreaIdFile`, `NavMeshDataAssetPath`, `BiomeId`, `ClimateZone`, `WaterPresent`, `WaterSurfaceElevationM`, `ScatterCount`, `Lod0DistanceM`, `Lod1DistanceM`, `Lod2DistanceM`, `SnowLineFactor`, `PrimaryBiomeName`, plus `ChannelBounds[]` (inner struct = 3 fields: `Name`, `Min`, `Max`)<br>• Bake-side `meta.json` emits all 29 fields (PR #48 populates)<br>• Schema-versioned migration if older `meta.json` loaded | Manual: load older chunk with v1 meta, migration path runs | L | #48 |
| B5-U14 | 5b | feat(unity): unknown-key warnings on raw manifest sidecars (audio/decals/water JSON) | `VbChunkLoader.cs` schema validators per sidecar | • Currently only descriptor warns; raw sidecars blob-attached without schema validation<br>• Each sidecar has named JSON Schema<br>• Unknown-key warnings logged per file | Manual: corrupt one sidecar JSON, Unity logs warning, doesn't crash | M | B5-U13 |
| B5-U-NAV | 5a | feat(unity): replace `navmesh.json` writer with Recast/Detour `dtNavMesh.bin` emit (Fix 4.1 — V2 BLOCKING gap; navmesh.json is data-only, lacks Recast off-mesh-link/area-cost runtime contract) | bake-side: `handlers/terrain_navmesh_export.py:580-606` (current JSON writer); bake-side wrapper (NEW) at `chunks/navmesh_recast.py` invoking recast4j Java JAR via subprocess (note: PyPI package `recast-navigation-python` does NOT exist per Codex 1) OR Unity-side **DotRecast** (C# NuGet 2026.1.3) post-import — choose either-or in implementation | • Choose path: (a) bake-side recast4j Java subprocess (deterministic; adds JVM dep) OR (b) Unity-side DotRecast post-import (no bake-side dep; runs on import)<br>• Bake 1 chunk; load in Unity; agent pathfinds end-to-end with off-mesh-link traversal<br>• Either-or decision documented in PR description | Manual: load 1 chunk in Unity, NavMeshAgent pathfinds to target across chunk; `pytest tests/test_navmesh_recast_roundtrip.py` (covered by Fix 4.21 / B5-T8) | L | B5-U1 |
| B5-U15 | 5b | feat(unity): APV (Adaptive Probe Volumes) brick streaming per chunk (Fix 4.15 — V3 BLOCKING gap; experimental in HDRP 14 / Unity 2022 LTS — risk documented in §11.7 #10) | HDRP Frame Settings (Project Settings) + `unity_plugin/Editor/VbApvBaker.cs` (NEW Editor-side baker) | • Bake APV brick streaming asset per chunk<br>• Configure HDRP Frame Settings → APV enable<br>• Addressable group `VbTerrain_<biome>_APVCells` per biome<br>• Verify interior shadow lighting NOT flat (e.g., under cave overhang or dense forest)<br>• Risk note: APV in Unity 2022 LTS HDRP 14 is officially experimental — see §11.7 #10 honesty register | Manual: cave/forest interior render shows non-flat indirect lighting; APV authoring shows brick coverage | XL | B5-U1 |
| B5-U16 | 5b | feat(unity): MeshDataArray + Burst chunk import (Fix 4.16 — Burst is NOT optional; required for native chunk import perf) | `unity_plugin/VbTerrainRuntimeStreamer.cs` (or `VbChunkLoader.cs` per Fix 1.8 Option A); use `Mesh.AllocateWritableMeshData` + `Mesh.ApplyAndDisposeWritableMeshData` (Unity 2022.1+; Burst-compatible) | • MeshDataArray native path replaces managed Mesh API<br>• Burst compilation enabled (NOT optional)<br>• Profiler shows chunk import time drops 2-3× vs baseline managed path<br>• Reference: Unity 2022.1+ docs `Mesh.AllocateWritableMeshData` | Manual: profiler diff before/after; `pytest tests/test_chunk_import_perf.py` | L | B5-U1 |
| B5-U17 | 5b | feat(unity): `DrawInstancedIndirect` for foliage (Fix 4.22 — GPU-resident scatter buffer; replaces per-instance GameObject) | `VbChunkLoader.cs` foliage path; new `unity_plugin/VbFoliageInstancedRenderer.cs` | • Foliage rendered via `Graphics.DrawMeshInstancedIndirect`<br>• Scatter buffer GPU-resident per chunk<br>• Frame-time impact <1ms for 100k blades on RTX 4060 Ti | Manual: profiler frame-time for forested chunk under 1ms foliage cost | L | B5-U11 |
| B5-U18 | 5b | feat(unity): static-batching contract for chunk meshes (Fix 4.23) | `VbChunkLoader.cs` per-chunk prop selection logic | • Chunk meshes >64K verts CANNOT static-batch (Unity hard limit)<br>• Per-chunk prop selection respects 64K vert ceiling<br>• Build report shows static-batch eligible vs ineligible chunks | Manual: Unity Build Report static-batch column matches contract | S | B5-U16 |
| B5-U19 | 5b | feat(unity): BC7 desktop / ASTC mobile texture compression configuration (Fix 4.24) | `unity_plugin/Editor/VbTextureCompressionPreset.cs` (NEW); per-platform overrides | • Splatmap PNG → Unity-side BC7 (desktop) or ASTC (mobile)<br>• Per-layer textures BC7 (albedo/mask) / BC5 (normal)<br>• VRAM impact documented in PR description | Manual: build target shows compressed import format; VRAM probe in Profiler | S | B5-U1 |
| B5-U20 | 5b | feat(unity): per-chunk runtime memory budget enforcer (`memory_budget_mb` field) (Fix 4.25) | `VbChunkLoader.cs` budget enforcer; `VbTerrainTileMetadata.cs` add `MemoryBudgetMb` field (now 30 fields total) | • Per-chunk runtime memory tracked at activation<br>• `memory_budget_mb` field consumed; chunk activation fails if violation<br>• Default budget 200 MB (heightmap + textures + meshes + foliage) | Manual: synthetic over-budget chunk fails activation cleanly | M | B5-U13 |
| B5-U21 | 5b | feat(unity): rasterized shadow cascade configuration for 4096m view distance + contact shadows (Fix 4.27) | HDRP Volume profile per biome at `unity_plugin/Settings/<biome>_HDRPVolume.asset` (NEW) | • 4-cascade rasterized shadow config tuned for 4096m view dist<br>• Contact shadows enabled at 5m radius<br>• Cascade boundaries documented per biome | Manual: render distant cliff at 3km — shadow LOD transition not visible | M | B5-U1 |
| B5-U22 | 5b | feat(unity): per-chunk reflection probe auto-placement (Fix 4.28; pairs with APV Fix 4.15) | `unity_plugin/Editor/VbReflectionProbePlacer.cs` (NEW Editor-side baker); per-chunk reflection probe at chunk center, height = max(heightmap) + 5m | • Reflection probe baked per chunk<br>• Probe positioned at chunk-center horizontal, 5m above max heightmap<br>• Wet ground / metallic surface shows correct sky reflection<br>• Pairs with APV (Fix 4.15) for full GI | Manual: render wet road / metallic prop, sky/horizon reflected correctly | M | B5-U1, B5-U15 |

#### 11.5.2 Cross-PR coherence patches (5 PRs base + 6 Phase 4 channel patches = 11 total: B5-C7 corruption_map + B5-C8 weathering_timeline overrides + B5-C9 phantom-channel re-attribution + B5-C10 material_zones + B5-C11 forest_mask + B5-C12 spec §3.4 absent names)

Per Phase 2 Fix 2.1: B5-C2 + B5-C6 are pilot-blocking serialization rules → Block 5b. B5-C3 + B5-C5 are post-pilot maturity → Block 6. **B5-C1 re-tagged 5b per Phase 2.5 Fix B**: ships YAML `safe_load` discipline + CI lint BEFORE PRs #28/#57/#58 introduce artist YAML loaders, which would otherwise create a hostile-YAML RCE attack surface during pilot. Channel-registry vocabulary unification (originally B5-C1's other half) is also pilot-critical (matches Phase 0 Fix 0.13 water-vocabulary unification scope), so both ride together as a single 5b PR.

| PR # | Sub-block | Title | Files (file:line) | Acceptance | Validation | Effort | Deps |
|------|-----------|-------|-------------------|------------|------------|--------|------|
| B5-C1 | 5b | fix(coherence): unify water-channel naming registry + YAML safe_load discipline (re-tagged 5b per Phase 2.5 Fix B — pilot-critical: lands BEFORE #28/#57/#58 YAML loaders) | `handlers/terrain_channel_registry.py` (NEW); spec body §3.4 line 192 alternate names DELETED; `scripts/check_protocol_adoption.py` extension (YAML lint) | • Single registry file declares `water_surface_mask` (binary), `water_surface_elevation_m` (z), `water_depth_m` (delta)<br>• Spec §3.4 line 192 alternate vocab deleted<br>• 3 competing vocabularies converge to 1<br>• #5b implements; #B5-C1 documents the registry<br>• (a) Declare project rule that all YAML in `species_libs/`, `foliage/`, biome configs MUST use `yaml.safe_load` (or `ruamel.yaml.YAML(typ='safe')`)<br>• (b) Add CI lint extending `scripts/check_protocol_adoption.py` that scans for `yaml.load(` without `Loader=SafeLoader` (RCE sink mitigation: PyYAML default `yaml.load` allows `!!python/object/apply` arbitrary code execution; PRs #28 + #57-58 introduce artist YAML overrides) | `pytest tests/test_water_channel_registry.py`; `Grep "yaml.load(" veilbreakers_terrain/` returns 0 results without `Loader=` | M | #5a, #5b |
| B5-C2 | 5b | fix(coherence): serialize `terrain_unity_export.py` writer-edit dep chain | dep ordering (5 PRs touching `terrain_unity_export.py`: #5b/#12/#13/#20/#48) | • PR labels enforce: only one in-flight at a time<br>• `terrain_unity_export.py` not edited by parallel PRs<br>• Merge collisions zero | Repo policy + PR-label CI gate | S | #12, #48 |
| B5-C3 | 6 | fix(coherence): break #56 ↔ #55 cycle (vegetation_system before delete) | dep ordering (#56 lands first; #55 then deletes file) | • Resolution: #55 removes `vegetation_system.py` from delete list, OR<br>• #56 lands before #55 with explicit dep<br>• Wave-5 §B.1 cycle resolved | PR sequencing test | S | #55, #56 |
| ~~B5-C4~~ | — | **DROPPED** — redundant after Fix 1.1 promoted `chunk_seed` API to PR #15.5; PR #18 migration now passes `seed_scope` directly via the new module API. C-1 propagation absorbed into PR #18 acceptance criteria. | — | — | — | — | — |
| B5-C5 | 6 | fix(coherence): register `water_surface_mask` channel (PR #37 reads, no PR creates) | extends PR #5b explicitly | • `water_surface_mask` channel registered in canonical channel set<br>• PR #37 reads it; producer is PR #5b<br>• Documentation explicit | `pytest tests/test_water_surface_mask_registered.py` | S | #5b |
| B5-C6 | 5b | fix(coherence): serialize `terrain_pipeline.py` writer-edit chain (mirrors B5-C2 for the other multi-edit hotspot) | dep ordering (9 PRs touching `terrain_pipeline.py`: #3, #4, #14, #18, #29, #35, #45, #46, #62) | • PR labels enforce only one in-flight at a time across this chain<br>• Declared chain: `#3 → #4 → #14 → #18 → #29 → #35 → #45 → #46 → #62`<br>• `terrain_pipeline.py` not edited by parallel PRs | Repo policy + PR-label CI gate | S | #3, #4, #14 |
| B5-C7 | 5b | chore(channels): `corruption_map` orphan-write cleanup (Fix 4.3) | `handlers/biome_channels.py` (delete `corruption_map` writer; OR wire to `terrain_macro_color` consumer per Codex 3 wiring decision) | • `Grep "corruption_map"` returns zero references OR symmetric reader/writer pair<br>• Orphan-write either eliminated OR consumer wired (decision documented in PR description) | `pytest tests/test_corruption_map_orphan.py`; `Grep "corruption_map" veilbreakers_terrain/` returns 0 OR matched pair | S | #21 |
| B5-C8 | 5b | fix(channels): wrap `weathering_timeline` as registered Pass with `overrides=("wetness",)` (Fix 4.4) | `handlers/terrain_weathering_timeline.py` (currently has NO PassDefinition class per R2-Opus-2; first wrap as registered Pass, then add `overrides=("wetness",)`) | • `terrain_weathering_timeline.py` declares PassDefinition<br>• `overrides=("wetness",)` declared (timeline mutates wetness over geological time)<br>• Pass registered via `register_weathering_timeline_pass`<br>• Topo-sort accepts `wetness` mutation via `overrides=` mechanism (PR #3 prereq) | `pytest tests/test_weathering_timeline_pass.py` | M | #3, #21 |
| B5-C9 | 5b | chore(channels): re-attribute 10 phantom channel reads to actual readers (Fix 4.6 — REPLACES withdrawn `terrain_visual_qa.py` claim per R2-Opus-3) | `docs/superpowers/specs/CHANNEL_GRAPH.md` amendment; canonical readers live in `atmospheric_volumes.py`, `terrain_features.py`, `terrain_decal_placement.py` (NOT `terrain_visual_qa.py` which reads NONE of the 10 channels per R2-Opus-2/3 + Codex 3) | • CHANNEL_GRAPH.md amended to point at correct reader files<br>• 10 channel-read attributions corrected: targets are `atmospheric_volumes.py`, `terrain_features.py`, `terrain_decal_placement.py`<br>• `terrain_visual_qa.py` no longer cited as reader for these channels | `pytest tests/test_channel_graph_attribution.py`; manual review of CHANNEL_GRAPH.md | S | #21 |
| B5-C10 | 5b | fix(channels): `material_zones` — add producer OR remove from `terrain_roughness_driver` consumed_channels (Fix 4.7 — phantom prerequisite) | `handlers/terrain_roughness_driver.py` (consumed_channels) + producer site for `material_zones` (NEW or remove) | • EITHER add `material_zones` producer somewhere upstream of `terrain_roughness_driver`<br>• OR remove `material_zones` from `terrain_roughness_driver.consumed_channels`<br>• Decision documented; no phantom prerequisite remains | `pytest tests/test_material_zones_no_phantom.py` | S | #21 |
| B5-C11 | 5b | fix(channels): `forest_mask` producer — 5 readers, 0 writers (Fix 4.8 — broken consumer chain) | producer site for `forest_mask` (NEW; OR migrate 5 consumers to `detail_density`/canopy-derived masks) | • EITHER add `forest_mask` producer (e.g., from canopy density threshold)<br>• OR migrate 5 consumers to use `detail_density`/canopy-derived masks<br>• Decision documented; no broken consumer chain<br>• 5 reader sites listed in PR description | `pytest tests/test_forest_mask_chain.py` | M | #21 |
| B5-C12 | 5b | fix(channels): 6 spec §3.4 names absent from production (Fix 4.9 — was claimed 5; actual 6 per audit recount) | spec §3.4 (around line 192-209); affected names: `wet_fetch`, `flow_velocity_xy`, `foam_potential`, `waterfall_mask`, `wave_fetch`, `wet_zone_override` | • Either implement 6 missing channels in production OR delete from spec §3.4<br>• Decision per channel documented in PR description (e.g., `wet_zone_override` is jungle-scope; per Q-jungle, keep as future)<br>• Spec §3.4 truth-aligned with production | `Grep "wet_fetch\|flow_velocity_xy\|foam_potential\|waterfall_mask\|wave_fetch\|wet_zone_override" veilbreakers_terrain/` returns matched pairs OR spec deletes | M | #5b, #21 |

#### 11.5.3 Single-chunk re-bake architecture (4 PRs base + 4 Phase 4 = 8 total: B5-D5 chunk_world_size constants + B5-D6 crash-resilient bake + B5-D7 .sha256 sidecar integrity + B5-D8 schema migration framework)

Per Phase 2 Fix 2.1: all single-chunk re-bake PRs are pilot-supporting infra → Block 5b.

| PR # | Sub-block | Title | Files (file:line) | Acceptance | Validation | Effort | Deps |
|------|-----------|-------|-------------------|------------|------------|--------|------|
| ~~B5-D1~~ | — | **PROMOTED to PR #15.5 (Block 1)** — API now lands earlier; downstream migration of 100 prod + 79 test sites in PR #18 | (see PR #15.5) | API-only; migration in PR #18 | (see PR #15.5) | (moved) | (moved) |
| B5-D2 | 5b | feat(chunks): `chunks/cache_invalidator.py` (chunk-grid-aware content-hash + dependency graph) | new `chunks/cache_invalidator.py`; reads `terrain_dirty_tracking.DirtyRegion` | • Content-hash per chunk per channel<br>• Dependency graph: `heightmap → erosion → drainage → splat → foliage`<br>• Edit at one chunk only rebakes affected chunks | `pytest tests/test_cache_invalidator.py` | L | #15.5 |
| B5-D3 | 5b | feat(chunks): watershed-downstream invalidator | extends `chunks/cache_invalidator.py` | • When heightmap edited at chunk (i,j), compute D8 downstream chunk set from cached `flow_direction`<br>• Invalidates `water.json` + `flow_map.png` on those chunks<br>• Test: edit headwaters chunk → all downstream chunks invalidated | `pytest tests/test_watershed_invalidator.py` | M | B5-D2 |
| B5-D4 | 5b | feat(chunks): `chunks/chunk_baker.py` + single-chunk CLI | new `chunks/chunk_baker.py`; CLI `python -m veilbreakers_terrain.bake --biome mountain --chunk 4,4 --reuse-merged-field` | • Halo-aware re-bake (5px halo for foliage exclusion)<br>• CLI works on 1 chunk in <9 min on RTX 4060 Ti<br>• Outputs identical to full-biome slice for the same chunk | Manual: full-biome bake, single-chunk re-bake → byte-identical for unchanged chunks | L | B5-D3 |
| B5-D5 | 5b | feat(chunks): `chunk_world_size=512` enforced; biome-unit constant added (Fix 4.2 — REFRAMES 4096m→512m subchunk rewrite per R2-Opus-3 — no rewrite needed; `chunk_world_size` parametric default already supports this; clarifies biome-unit vs streaming-unit) | `handlers/terrain_chunking.py` constants module; documents biome-unit (4096m, 1 biome) vs streaming-unit (512m, addressable chunks); see also Block 4 §11.4 PR #7 (default change) | • `BIOME_UNIT_M = 4096` constant added (4096m = 1 biome zone, NOT addressable)<br>• `STREAMING_CHUNK_M = 512` constant added (512m = 1 addressable chunk; 64 chunks per biome zone)<br>• PR #7 default change satisfies the parametric path; this PR adds doc/constant clarity<br>• No subchunk rewrite — the parametric `chunk_world_size` already supports the contract | `pytest tests/test_chunking_constants.py` | S | #7 |
| B5-D6 | 5b | feat(chunks): crash-resilient bake with `.partial` → `.done` atomic finish marker (Fix 4.17) | `chunks/chunk_baker.py` (extends PR B5-D4 scaffold); per-chunk lock file + atomic finish marker | • Mid-flight bake kill leaves `.partial` markers on incomplete chunks<br>• CLI `--resume` flag skips chunks with valid `.done` marker<br>• Per-chunk lock file prevents concurrent bake collision<br>• `os.replace(<chunk>.partial, <chunk>.done)` atomic finish | Manual: kill bake mid-flight via SIGKILL; `--resume` succeeds without re-baking completed chunks | M | B5-D4 |
| B5-D7 | 5b | feat(chunks): sidecar `.sha256` files for binary artifact integrity (Fix 4.18 — REFRAMED per R2-Opus-3: sidecar approach, NOT tail-append; PNG IEND chunk + RAW exact-bytes break tail-append schemes) | per-artifact sidecar file `<artifact>.sha256` next to each `.bin` / `.png` / `.raw`; Unity-side reader verifies on load | • Each binary artifact has companion `.sha256` sidecar<br>• Unity-side reader verifies SHA256 on load; reports tampered/corrupted artifacts<br>• Complementary to (NOT redundant with) §3.7 `version_hash` cache key — `version_hash` is content-addressing for cache invalidation; `.sha256` is integrity verification at load<br>• Sidecar approach (not tail-append) preserves PNG IEND chunk + RAW exact-bytes formats | `pytest tests/test_sha256_sidecar_integrity.py`; manual: corrupt 1 byte in chunk artifact, verify Unity load fails | M | B5-D4 |
| B5-D8 | 5b | feat(chunks): asset schema migration framework (Fix 4.19) | `meta.json.schema_version` field + `chunks/schema_migrations/v1_to_v2.py` example migrator + 16-byte binary header on all `.bin` artifacts | • `meta.json.schema_version` field (semver-like)<br>• `chunks/schema_migrations/v1_to_v2.py` example migrator with rollback path<br>• 16-byte binary header on all `.bin` artifacts: `{magic:4, version:u16, flags:u16, reserved:8}` per Witcher 3 / Decima precedent<br>• Bumping schema bumps `version_hash`; older bakes auto-migrate on load | `pytest tests/test_schema_migration.py`; load v1 chunk through v2 migrator → output bit-equal to direct v2 bake | M | B5-D7 |

#### 11.5.4 Test infrastructure (8 PRs core; B5-CI1 conditional; +3 Phase 4 = 11 total core: B5-T8 navmesh round-trip + 100-agent stress + B5-T9 frame-time gates + B5-T10 Burst+IL2CPP build reproducibility)

Per Phase 2 Fix 2.4 (test infra over-engineered): B5-T1 (render goldens framework) + B5-T1b ([AUTO-APPLIED — Phase 3 Theme 3.8 added] forest stratification baseline) + B5-T4 (byte-identity 18 artifacts) are pilot-required → Block 5b. B5-T2 (pytest-benchmark), B5-T3 (hypothesis), B5-T5 (protocol enforcement), B5-T6 (flaky-hunter), B5-T7 (CI fast-lane split) are post-pilot test maturity → Block 6. B5-CI1 conditional → DEFERRED per Decision 3.4 (Path 1 chosen).

| PR # | Sub-block | Title | Files (file:line) | Acceptance | Validation | Effort | Deps |
|------|-----------|-------|-------------------|------------|------------|--------|------|
| B5-T1 | 5b | feat(tests): remaining test-infra wiring after PR #6.5 lands baseline + harness — full goldens framework, `Render-Goldens` CI lane, `terrain_visual_qa.py:706` SSIM hookup | extends PR #6.5 (which committed the 4 baseline PNGs + `tests/conftest.py` SSIM helper); CI step uses `terrain_visual_qa.py:706` SSIM | • SSIM 0.95 threshold enforced in CI lane (PR #6.5 committed PNGs and helper; B5-T1 now wires the CI lane and validator hookup)<br>• `Render-Goldens` lane green<br>• Validator hooked into the now-reachable `terrain_visual_qa.py:706` codepath | `pytest tests/test_golden_scenarios.py`; CI: `Render-Goldens` lane green | M | #6.5, #19, #29 |
| B5-T1b | 5b | feat(tests): `forest_stratification` baseline + render-proof PR (binds §4.4 five-layer stratification to a goldens fixture) | `tests/golden_scenarios/forest_canopy_layered/{closed_canopy.png, open_canopy.png}` (2 NEW baselines); harness reuse from PR #6.5 SSIM helper | • Closed-canopy chunk shows moss-carpet floor + minimal shrub layer (canopy-shaded → shrub-suppressed; ground = bryophyte/moss layer dominant)<br>• Open-canopy chunk shows grass/forb explosion (sun-exposed → understory layer thrives)<br>• PRs #57 (mountain ecology) and #58 (grassland) bind to this baseline as their visual acceptance gate<br>• Closes §4.4 design-lens conf-75 gap (five-layer stratification not bound to any PR) | `pytest tests/test_golden_scenarios.py::test_forest_stratification`; CI: `Render-Goldens` lane green for forest fixtures | S | #6.5, B5-T1 |
| B5-T2 | 6 | feat(tests): `pytest-benchmark` + nightly perf cron | install `pytest-benchmark`; convert 8 ad-hoc `elapsed < N` asserts to `@pytest.mark.benchmark`; new `.github/workflows/perf-nightly.yml` | • All 8 ad-hoc perf asserts converted<br>• Nightly job tracks regression history<br>• Auto-issue on >20% regression | CI: `Perf-Nightly` lane green | M | #2 |
| B5-T3 | 6 | feat(tests): `hypothesis` property tests on channel invariants | install `hypothesis>=6.100`; add `tests/test_channel_invariants.py` | • NaN-free, shape-stable, range-bounded across N=100 seeds<br>• Each registered channel has at least one property test | `pytest tests/test_channel_invariants.py` | M | #2 |
| B5-T4 | 5b | feat(tests): 18-artifact byte-identity matrix (concrete acceptance per Fix 1.22) | `tests/test_phase8_determinism_guardrails.py:53` (currently checks 3 of 18) | • **Byte-identity** (12 artifacts — full bit equality across 2 PYTHONHASHSEED values): `heightmap.bin`, `heightmap.png`, `normalmap.png`, `splatmap_*.png`, `watermap.png`, `macro_variation.png`, `navmesh.png`, `foliage.json`, `decals.json`, `water.json`, `edges.json`, `manifest.json`<br>• **SSIM ≥0.95** (2 artifacts — Cycles cross-platform float drift): `terrain_render_preview.png`, `lighting_validation.png`<br>• **Schema-only** (1 artifact — volatile fields stripped): `meta.runtime.json` (volatile fields like timestamps stripped from byte-identity matched against `meta.json`)<br>• Per §8.4 of CE Fixes Guide; total = 18 artifacts (12 byte + 2 SSIM + 4 absorbed via `splatmap_*.png` glob expansion = 16 base + the 2 SSIM = 18 nominal manifest entries) | `pytest tests/test_phase8_determinism_guardrails.py::test_byte_identity_matrix`; `pytest tests/test_phase8_determinism_guardrails.py::test_ssim_matrix`; `pytest tests/test_phase8_determinism_guardrails.py::test_schema_only` | L | #42 |
| B5-T5 | 6 | feat(tests): protocol enforcement 21/74 → ≥60/74 | `scripts/check_protocol_adoption.py` registry extension; decorate handlers | • At least 60 of 74 passes have protocol enforcement<br>• `check_protocol_adoption.py` gate fails when pass added without protocol<br>• Currently 28% (21/74) | CI: `protocol-adoption` lane green | M | #21 |
| B5-T6 | 6 | feat(tests): `pytest-rerunfailures` + flaky-hunter nightly | install `pytest-rerunfailures>=12.0`; new `.github/workflows/flaky-hunter.yml` | • Tag known-flaky tests with `@pytest.mark.flaky(reruns=3)`<br>• Nightly job rebuilds confidence intervals<br>• Auto-issue on flake-rate >5% | CI: `Flaky-Hunter` lane green | M | B5-T2 |
| B5-T7 | 6 | feat(ci): fast-lane vs nightly-full split | `.github/workflows/python-package.yml` (split into fast PR lane + nightly full-suite); fast lane <5min (lint + smoke); nightly full | • PR lane <5 min wall-clock<br>• Nightly runs full suite + golden + perf + flaky<br>• Existing `--cov-fail-under=72` preserved (memory correction: was claimed 40, real is 72) | CI: `PR-Fast` <5min; `Nightly-Full` runs | M | B5-T1, B5-T2 |
| B5-CI1 | DEFERRED (Path 1 chosen per Decision 3.4) | feat(ci): GitHub-hosted GPU larger runner for nightly perf gate (lands ONLY if §11.7 #3 / honesty register #9 chooses Path 2 or Path 3) | `.github/workflows/perf-nightly-gpu.yml`; `larger_runner: gpu-t4` declarations; budget gate (~$60-70/mo) | **Does not ship in v1 pilot per [AUTO-APPLIED — Decision 3.4 / pending user override] (Path 1 chosen — drop GPU perf gate, use local benchmark + nightly cron compare).** • GPU larger runner provisioned<br>• Perf-Nightly bake runs on T4 GPU<br>• Cost gate enforced | CI: `Perf-Nightly-GPU` lane green | M | B5-T2 |
| B5-T8 | 5b | feat(tests): NavMeshData round-trip + 100-agent stress (Fix 4.21 — companion gate for Fix 4.1 navmesh path) | bake 1 chunk via Fix 4.1 (B5-U-NAV) navmesh path; import via DotRecast or Unity NavMesh; 100-agent stress runner | • Bake 1 chunk via Fix 4.1 navmesh path<br>• Import via DotRecast OR Unity NavMesh (matching B5-U-NAV path choice)<br>• 100-agent stress: off-mesh-link traversal, dynamic obstacle carving, area-cost respect<br>• Memory <8MB per chunk navmesh artifact<br>• Round-trip byte-identity check (bake → import → round-trip serialize) | `pytest tests/test_navmesh_recast_roundtrip.py`; `pytest tests/test_navmesh_100_agent_stress.py` | M | B5-U-NAV |
| B5-T9 | 5b | feat(tests): `Profiler.GetCounterValueAsLong` frame-time gates (Fix 4.26) | Unity-side test harness; `unity_plugin/Tests/PlayMode/VbFrameTimeGates.cs` (NEW) | • Per-chunk frame-time budget enforced (16.6ms = 60fps target on RTX 4060 Ti)<br>• `Profiler.GetCounterValueAsLong` polled at chunk-load + 30 frames after<br>• Per-system gates: foliage <1ms, terrain <2ms, water <1ms, lighting <2ms<br>• Regression budget: nightly compare to prior baseline | Manual: PlayMode test runs in Unity; CI hookup follows §11.7 #3 Path 1 (local-only) | M | B5-U16, B5-T1 |
| B5-T10 | 5b | feat(tests): Burst hash + IL2CPP determinism reproducibility gate (Fix 4.29) | `unity_plugin/Tests/EditMode/VbBuildReproducibility.cs` (NEW); compare-hashes script | • Same Unity version + same source = identical Player build<br>• Burst hash byte-equal across 2 builds on same machine<br>• IL2CPP determinism: same `il2cpp_data/Metadata` hashes across 2 builds<br>• `unity_plugin/Tests/golden_hashes/<unity_version>.json` committed as baseline | Manual: 2 sequential `Build & Run` invocations; SHA256 of Player executable + IL2CPP metadata equal | M | B5-T1 |

#### 11.5.5 Asset budget hardening (4 PRs beyond Block 2 #36)

Per Phase 2 Fix 2.1: all asset-budget PRs are pilot-supporting infra → Block 5b.

| PR # | Sub-block | Title | Files (file:line) | Acceptance | Validation | Effort | Deps |
|------|-----------|-------|-------------------|------------|------------|--------|------|
| B5-A1 | 5b | feat(asset-budget): v6 controller bypass — wire to controller | `scripts/build_terrain_aaa_node_v6.py:187-287` (currently directly invokes `pass_cliffs`, `pass_waterfalls`, `pass_materials` — bypasses `TerrainPassController.run_pipeline`) | • v6 production stack runs through controller<br>• `enforce_budget()` actually fires (currently `validation_full_present: true` is theatre)<br>• Single fix only one of 4 needed (per audit B.6) | `pytest tests/test_v6_controller_wired.py` | L | #36, #43 |
| B5-A2 | 5b | feat(asset-budget): missing emitters — `splat_secondary.png` (layers 4-7), per-layer `albedo/normal/mask/height/detail.png`, `flow_map.png` (RG16), `triplanar_mask.png`, `vertex_ao.bin` | `unity_export_v2/chunk_artifacts.py` extensions | • All emitters in default-sequence Bundle N<br>• 18-artifact manifest contract complete<br>• Already partially in PR #42; this PR closes the gap | `pytest tests/test_emitters_complete.py` | M | #42 |
| B5-A3 | 5b | feat(asset-budget): BC compression hard validator + PNG-not-EXR splatmap | `unity_export_v2/texture_compression.py` (extends PR #41 with hard validator) | • Splatmap baked as PNG (per spec §6.1)<br>• OpenEXR usage flagged by validator<br>• BC6H/BC7/BC5 enforced (PR #41 covers selection; #B5-A3 covers gate) | `pytest tests/test_compression_gate.py` | M | #41 |
| B5-A4 | 5b | feat(asset-budget): `lod_meshes` validator + manifest emission gate | `vegetation_system.py:1561, :1600` (cite corrected per Codex 1 TSV — `:1284` was stale), `procedural_grass.py:685` (cite corrected from `:720`) (PR #43 covers — #B5-A4 closes the manifest-emission gate) | • Manifest emission blocked when any species `lod_meshes == []`<br>• Validator runs before bundle write<br>• PR #43 + #B5-A4 together unblock | `pytest tests/test_lod_meshes_manifest_gate.py` | M | #43, #56 |

#### 11.5.6 Dependency hardening + supply chain (2 PRs core; B5-DEP4/DEP5 conditional)

Per Phase 2 Fix 2.1: B5-DEP2 + B5-DEP3 are post-pilot maturity → Block 6. B5-DEP4 + B5-DEP5 are conditional pilot-supporting → Block 5b only when §11.7 #3 picks Path 2/3.

| PR # | Sub-block | Title | Files (file:line) | Acceptance | Validation | Effort | Deps |
|------|-----------|-------|-------------------|------------|------------|--------|------|
| B5-DEP2 | 6 | sec(deps): lockfile + `bake-env.yml` + `--require-hashes` | new `uv.lock` OR `requirements-lock.txt`; new `bake-env.yml` (Blender 4.5 NumPy 1.24.x compat); CI uses `pip install --require-hashes` | • Lockfile committed<br>• `bake-env.yml` committed<br>• CI install uses `--require-hashes` | CI install green | M | #2 |
| B5-DEP3 | 6 | sec(supply-chain): `.github/dependabot.yml` + SHA-pin Actions + HF Space SHA + CodeQL `security-extended` | new `.github/dependabot.yml` (weekly cadence pip + github-actions); SHA-pin all `actions/*`; pin Hunyuan3D-2 HF Space SHA in `hunyuan3d2_provider.py`; extend `.github/codeql/codeql-config.yml` to `security-extended` + custom CWE-918 SSRF rules for `requests`/`gradio_client` paths | • Dependabot live<br>• All Actions SHA-pinned (verified by CI lint)<br>• HF Space `revision=` capture in provider<br>• CodeQL `security-extended` query suite live (memory was wrong about default-only — already at `security-and-quality`; this upgrades to `security-extended`) | CI: `CodeQL` upgraded; `dependabot.yml` live | M | B5-DEP2 |
| B5-DEP4 | DEFERRED (Path 1 chosen per Decision 3.4) | sec(secrets): secret hygiene baseline (lands ONLY if §11.7 #3 / honesty register #9 chooses Path 2 or Path 3 — needed for runner SSH keys / GHCR PATs) | `.github/workflows/*` review for `${{ secrets }}` exposure; `secret-scanner` pre-commit hook; rotation policy doc | **Does not ship in v1 pilot per [AUTO-APPLIED — Decision 3.4 / pending user override] (Path 1 chosen).** • Zero secrets in workflow logs (gitleaks scan)<br>• Pre-commit hook blocks new secret commits<br>• Rotation policy committed | CI: `secret-scan` green | M | B5-DEP3 |
| B5-DEP5 | DEFERRED (Path 1 chosen per Decision 3.4) | sec(ci): runner isolation rules per harden-runner pattern (lands ONLY if Path 2 or Path 3 from §11.7 #3 / honesty register #9) | `step-security/harden-runner@v2` step on every workflow; egress allow-list; runner-scope token narrowing | **Does not ship in v1 pilot per [AUTO-APPLIED — Decision 3.4 / pending user override] (Path 1 chosen).** • Harden-runner installed on all jobs<br>• Egress allow-list enforced<br>• PR-fork isolation rule: forked PRs get scoped GITHUB_TOKEN, no secret access | CI: harden-runner audit green | M | B5-DEP4 |

#### 11.5.7 Doc rot cleanup (4 PRs)

Per Phase 2 Fix 2.1: all doc-rot PRs are post-pilot maturity → Block 6.

| PR # | Sub-block | Title | Files (file:line) | Acceptance | Validation | Effort | Deps |
|------|-----------|-------|-------------------|------------|------------|--------|------|
| B5-DOC1 | 6 | docs(archive): 14 superseded markdown files → `docs/_archive/2026-04/` | 4× `MASTER_AUDIT_V*_2026_04_19.md`; deep_dive_2026_04_20 trio; `GLM_IMPLEMENTATION_PLAN`; scratch reconstruct files | • Files moved, not deleted<br>• `docs/_archive/2026-04/INDEX.md` lists each with original path | Manual: review archive index | S | #55 |
| B5-DOC2 | 6 | docs(supersede): patch 04-27 master implementation guide with Batch15 ✅ FIXED status + SUPERSEDED-BY banner | `docs/aaa-audit/deep_dive_2026_04_27/master_implementation_guide.md` (top-of-file banner pointing to `docs/aaa-audit/batch15_2026_05_04/MASTER_AUDIT_BATCH15.md`); patch grade table | • Banner SUPERSEDED-BY at top<br>• 5 P0s marked ✅ FIXED: W-1 (`_water_network.py:907-929`, `procedural_grass.py:350-352`, `coastline.py:1242`), E-1 (`_terrain_erosion.py:318`), E-2 (`terrain_stratigraphy.py:1069`), M-3 (`terrain_texture_layer_stack.py:38`), CL-2 (`terrain_cliffs.py:2704-2706`)<br>• Grade table predictions corrected: Water D+→C+, Visual QA F→fixed, AI assets D→live | Manual: review banner; grade table 5 wrong→fixed | M | none |
| B5-DOC3 | 6 | docs(spec-fix): remove 3 nonexistent build script citations from spec body | spec body lines 7 + 27 (currently cite `coastal_build_v3d_vegetation_v2.py`, `mountain_build_v1_full.py`, `grassland_full_build.py` — verified deleted by V3 forensic) | • Lines 7 and 27 reference superseded scripts as historical context only<br>• `CODEBASE_STRUCTURE.md` refreshed post-providers/, post-Batch14 export-wiring, post-`terrain_texture_layer_stack.py` | Manual: review spec body cites | S | none |
| B5-DOC4 | 6 | docs(refresh): commit dirty-tree docs (already modified, not committed) | `docs/BLENDER_AGENT_USAGE_GUIDE.md`, `docs/TERRAIN_CALLABLE_USAGE_GUARDRAIL.md` (per `git status`); add chunk-aware sections to BLENDER guide; add chunk-pass wiring contract to GUARDRAIL | • Both files committed<br>• Chunk-aware sections present<br>• Chunk-pass wiring contract documented | Manual: review docs | S | #4 |

**Block 5 totals (after Phase 2 Fix 2.1 severity split + Phase 2.5 Fix B B5-C1 re-tag + Phase 3 Decision 3.4 deferring B5-CI1/DEP4/DEP5 + Phase 3 Theme 3.8 adding B5-T1b + Phase 4 adding 22 net-new PR rows in Block 5; 23 total Phase 4 PRs counting #65 in Block 4): 49 PR groups (was 27 post-Phase-3) split into Block 5a (6 pilot-blocking Unity parity PRs: B5-U1 through B5-U5 + B5-U-NAV [Fix 4.1]) + Block 5b (pilot-supporting infra: 9 baseline §11.5.1 + 8 Phase 4 §11.5.1 [B5-U15-U22] + B5-C1 + B5-C2 + B5-C6 + 6 Phase 4 §11.5.2 [B5-C7-C12] + 3 of §11.5.3 + 4 Phase 4 §11.5.3 [B5-D5-D8] + 4 of §11.5.5 + B5-T1 + B5-T1b + B5-T4 + 3 Phase 4 §11.5.4 [B5-T8-T10]) + Block 6 (post-pilot maturity: B5-C3 + B5-C5 + B5-T2/T3/T5/T6/T7 + B5-DEP2 + B5-DEP3 + B5-DOC1-4 = 13 deferred = 2+5+2+4) + DEFERRED-by-Decision-3.4 (B5-CI1 + B5-DEP4 + B5-DEP5 do not ship in v1 pilot). Block 5a + Block 5b land during pilot calendar (within the 30-45 working days [Decision 3.3] envelope). Block 6 deferred to v1.1 (see §11.6.1). Phase 4 net-new sub-block tag distribution: 5a = +1 (B5-U-NAV); 5b = +20 (8 §11.5.1 + 6 §11.5.2 + 4 §11.5.3 + 3 §11.5.4 — but adjusted: 21 total Phase 4 rows = 1 for 5a + 20 for 5b).**

### 11.6 Cross-PR dependency graph

```
                                ┌─────────────────────────────┐
                                │  Block 1 — Pipeline Cleanup │
                                └─────────────────────────────┘
                                              │
                       ┌──────────────────────┼─────────────────────┐
                       ▼                      ▼                     ▼
                      #1                    #14                    #6
                       │                      │              [moved to Block 4
                       │                      │               per Fix 2.2;
                       │                      │               preserved here for
                       │                      │               downstream dep
                       │                      │               traceability — see
                       │                      │               §11.4 PR #6]
                       ▼                      ▼
                      #2 ◄──────────────────#15 (PYTHONHASHSEED)
                       │                      │
                       ▼                      │
                      #3 (toposort overrides=)│
                       │                      │
                       ▼                      │
              ┌────────┴───────┐              │
              ▼                ▼              │
             #4              #5a              │
            (orphan         (drop W-1         │
            passes)         legacy)           │
              │                │              │
              ▼                ▼              │
          (parallel)         #5b              │
                          (canonical)         │
                              │               │
                              ▼               │
                            #12 (atomic)─────#13 (NaN/Inf)
                              │
        ┌─────────────────────┼───────────────────┐
        ▼                     ▼                   ▼
     Block 2              Block 3              Block 4
   (parity + long-tail)  (seam + concurrency)  (polish + scope)

#16(stratig)─#17(morph)─#29(label-stamp)─#37(water-label)
   ▲           ▲             ▲                  ▲
   └─#4────────┴─#16─────────┴──#16,#17         └─#5b,#29

#19(taichi)─#21(contracts)─#22(test-infra)
                  │
                  └─#46(rule1)─#47(parallel-merge)

#36(splat 4→8)─#41(BC compress)─#42(emitters)─#44(stream cap)
   │                ▲              ▲
   └────────────────┴──────────────┴──── all consume #36

#11(atomicity)─#44(stream cap)
            └──#48(unity-export consolidation)
   ◄── Fix 1.16: atomicity precedes the 5 PRs touching terrain_unity_export.py

#27(parent-child)─#28(artist override)─#57(mountain ecology)
                                       └─#58(grassland)  [#59 coastal moved to §7.4 post-pilot]

#56(veg defaults)─#55(deletes)  ◄── must land in this order
#43(lod_meshes)──┐
                 ├──#55(deletes vegetation_system.py)  ◄── #43 + B5-A4 edit, then #55 deletes
#B5-A4(lod_gate)─┤
                 └──#56(veg defaults)  ◄── B5-A4→#56 explicit dep edge per Fix 4.14 (B5-A4 + #43 edit vegetation_system.py before #56 repair, all before #55 delete)

#65(dead-RNG cleanup, chore-only)  ◄── Deps: none; leaf node (Phase 4 Fix 4.10; Block 4)

                                ┌────────────────────────────────┐
                                │  Block 5 — Unity workstream    │
                                │  (parallel to Blocks 1-4)      │
                                └────────────────────────────────┘
B5-U1(HDRP shaders OR MicroSplat)─┬─B5-U2(WaterSurface)
                                   ├─B5-U3(holes.png)
                                   ├─B5-U4(normal Y-flip)─B5-U5(edges.json)
                                   ├─B5-U-NAV(navmesh Recast/Detour)─B5-T8(navmesh round-trip + 100-agent stress)
                                   ├─B5-U15(APV brick streaming)─B5-U22(reflection probe)
                                   ├─B5-U16(MeshDataArray + Burst)─B5-U17(DrawInstancedIndirect foliage)─B5-U18(static-batching contract)
                                   ├─B5-U19(BC7/ASTC compression)
                                   └─B5-U21(shadow cascade + contact shadows)
B5-U13(meta 29 fields)─B5-U20(memory budget enforcer)
#15.5(chunk_seed)─B5-D2(cache invalidator)─B5-D3(watershed)─B5-D4(chunk_baker)─B5-D6(crash-resilient bake)─B5-D7(.sha256 sidecars)─B5-D8(schema migration)
#7(chunk_world_size default)─B5-D5(chunking constants)
B5-T1(goldens)─B5-T7(fast-lane)
B5-T1(goldens)─B5-T9(frame-time gates)─B5-T10(Burst+IL2CPP build reproducibility)
#2(CVEs+extras split — absorbed B5-DEP1)─B5-DEP2(lockfile)─B5-DEP3(SHA-pin)
B5-DOC1(archive)─B5-DOC2(04-27 banner)
[Phase 4 channel patches — sub-block 5b]
#21(contracts)─B5-C7(corruption_map cleanup)
#21(contracts)─B5-C8(weathering_timeline overrides)
#21(contracts)─B5-C9(phantom-channel re-attribution)
#21(contracts)─B5-C10(material_zones)
#21(contracts)─B5-C11(forest_mask)
#5b(canonical W-1)+#21─B5-C12(spec §3.4 absent names)
```

**Critical path:** `#1 → #2 → #3 → #5a → #5b → #12 → #36 → #42 → #44` (9 PRs, all M/L/M/M/M/M/M/L/M = ~5 days serial).

**Block 5 critical path (separate workstream):** `B5-U1 → B5-U2 → B5-U5 → B5-T1` (~3-5 days with Unity engineer).

**Calendar minima** [AUTO-APPLIED — Decision 3.3 / pending user override]:
- **Single solo developer realistic: 30-45 working days (~6-9 weeks calendar).** The optimistic 14-day figure assumes 1 PR/hour throughput at 6h focus/day with no review cycles or surprises — not realistic for solo dev. 114 PRs across 5+ blocks at realistic solo throughput (review, debugging, integration, surprise rate ~30%, calendar gaps) lands at 30-45 working days.
- Two-engineer estimate dropped (out of scope; would require hiring).

### 11.6.1 Block 6 — Post-pilot maturity (deferred to v1.1 per Phase 2 Fix 2.1)

Block 6 collects all non-pilot-blocking Block-5 PRs that R2-Opus-2 originally proposed to "wholesale move" post-pilot. Round-3 reframed this as a severity split: pilot-blocking and pilot-supporting items stay in Block 5a/5b, while the items below defer to v1.1 alongside §11.8 #12-#13 refactors.

| Source | PRs in Block 6 | Severity | Why deferred |
|---|---|---|---|
| §11.5.2 Coherence | B5-C3 (#56↔#55 cycle ordering), B5-C5 (channel-registration documentation) | P2 maturity | B5-C1 (channel registry + YAML `safe_load` lint) re-tagged 5b per Phase 2.5 Fix B (lands BEFORE PRs #28/#57/#58 introduce artist YAML loaders — RCE attack surface mitigation). B5-C2 + B5-C6 cover the pilot-critical writer-edit serialization rules in Block 5b. Remaining 2 items are documentation / dep-cycle ordering — non-blocking. |
| §11.5.4 Test infra (Phase 2 Fix 2.4) | B5-T2 (`pytest-benchmark`), B5-T3 (`hypothesis` property tests), B5-T5 (protocol enforcement 21/74 → 60/74), B5-T6 (`pytest-rerunfailures` + flaky-hunter), B5-T7 (CI fast-lane vs nightly-full split) | Test-maturity | B5-T1 (render goldens) + B5-T4 (byte-identity 18 artifacts) cover pilot acceptance. Remaining 5 are over-engineered for pilot per scope-guardian; better as v1.1 hardening once flake/perf baselines are real. |
| §11.5.6 Deps | B5-DEP2 (lockfile + `bake-env.yml` + `--require-hashes`), B5-DEP3 (dependabot + SHA-pin Actions + CodeQL `security-extended`) | Supply-chain hardening | B5-DEP4 + B5-DEP5 land conditionally in 5b only when §11.7 #3 picks Path 2/3 (runner-isolation requires them). Lockfile + dependabot are best-practice hygiene that does not block pilot ingestion. |
| §11.5.7 Doc rot | B5-DOC1 (archive 14 superseded markdown), B5-DOC2 (04-27 SUPERSEDED-BY banner), B5-DOC3 (nonexistent script cite removal), B5-DOC4 (commit dirty-tree docs) | Doc hygiene | None affect pilot bake or pilot Unity ingestion. Cleanup naturally follows pilot ship. |

**Block 6 totals: 13 PRs (2 + 5 + 2 + 4 — after Phase 2.5 Fix B re-tagged B5-C1 to 5b for pilot-RCE mitigation).** Lands as a single v1.1 batch alongside §11.8 #12 (`environment.py` 5-seam split / PR #53) and §11.8 #13 (PRs #49/#50/#51/#52/#54). v1.1 batch effort: ~3-5 focused days post-pilot.

### 11.7 AAA-parity cuts (honesty register)

These are **not deferrals** — they are explicit cuts where the spec was over-claiming what the codebase or v1 pilot delivers. Each cut is acknowledged here so verifiers and the user know the gap is intentional.

1. **[AUTO-APPLIED — Decision 3.2 / pending user override] HDRP shader graph stack — F (~10%) on disk; default mitigation is MicroSplat $40 (FREE base + $20 HDRP 2022 + $20 Mesh Terrains).** Wave-5 §B.3 verified: 0 `.shadergraph` files, 0 `.hlsl`, 0 `.shader`, 0 `.shadersubgraph`, 0 `.mat`. No Unity project exists (no `Assets/`, no `Packages/manifest.json`). All 4 promised variants (`VbTerrainLitTriplanar`, `AntiTile`, `DistanceNormal`, `OverlayDynamic`) + master + 2 subgraphs are absent. Only HLSL is `terrain_stochastic_shader.py:51-265` embedded as Python f-string, **tagged URP not HDRP** (lines 73, 263). `acceptance_checks.py` referenced by spec line 1016 — does not exist. **Block 5 PR #B5-U1 default action: buy + integrate MicroSplat HDRP 2022 + Mesh Terrains modules ($40 total; saves ~2 weeks solo-dev time). Alternative: author 4 .shadergraph files from scratch (~12-18 days realistic solo-dev).** Pilot acceptance gate cannot pass §6.10 polish-tier without one or the other.

2. **Unity-side has 5 BLOCKING gaps that bake-side PRs do NOT fix:**
   - HDRP shader graphs absent (B5-U1)
   - WaterSurfaces stubbed out (`VbTerrainImporter.cs:1150-1153` skip + log) — B5-U2 fixes
   - `holes.png` never read (no `terrainData.SetHoles` call) — B5-U3 fixes
   - Tangent-space normal handedness mismatch (bake emits OpenGL-Y, importer never inverts G) — B5-U4 fixes
   - `edges.json` edge-stitch contract entirely absent both bake AND Unity sides — B5-U5 fixes (paired with bake-side PR #39)
   Pilot Unity ingestion will fail without all 5.

3. **[AUTO-APPLIED — Decision 3.4 / pending user override — Path 1 chosen for v1 pilot]** **Pipeline `<60min/chunk` target requires Taichi-CUDA + GPU runner; no CPU fallback (per spec §11.5.4 PR B5-T2).** Wave-5 §B.2 confirms: bake-venv + Taichi-CUDA perf gate requires self-hosted GPU runner (RTX 4060 Ti). CPU-only path is not viable for AAA-bar erosion (E-3 audit note: pure-Python is non-functional at AAA sizes). v1 pilot acceptance assumes a self-hosted GPU CI runner. CI without GPU runner cannot validate perf budget. **Three paths to resolve (per Fix 1.10 / honesty register #9); Path 1 chosen for v1 pilot per Decision 3.4 (avoids #1 GitHub anti-pattern of self-hosted GPU runner on public repo):**
   - **Path 1 (recommended; chosen for v1 pilot):** drop GPU perf gate from required checks; use local benchmark + nightly cron compare. No additional CI cost. Effect: B5-CI1, B5-DEP4, B5-DEP5 conditional rows do not ship in v1 pilot.
   - **Path 2 (deferred):** GitHub-hosted larger T4 runner ~$60-70/mo nightly bake. Triggers new PR `B5-CI1` (`feat(ci): GitHub-hosted GPU larger runner for nightly perf gate`) in §11.5.4. Also requires `B5-DEP4`/`B5-DEP5` from §11.5.6 (secrets + runner isolation).
   - **Path 3 (deferred):** self-hosted runner. Highest hardening surface; requires `B5-CI1` + `B5-DEP4` + `B5-DEP5`.

4. **Asset budget `enforce_budget()` exists but v6 controller bypass means the live 1024² stack does not enforce — single fix won't reach all artifacts; PR #36 + B5-A1 + B5-A2 + B5-A3 + B5-A4 are 5-PR sequence (NOT 1).** `build_terrain_aaa_node_v6.py:187-287` directly invokes `pass_cliffs`, `pass_waterfalls`, `pass_materials` — bypasses `TerrainPassController.run_pipeline()` at `terrain_pipeline.py:983-991`. The 32×32 stub through controller is theatre (writes `validation_full_present: true` to `BUILD_SUMMARY.json` but skips real budget checks).

5. **[AUTO-APPLIED — Decision 3.1 / pending user override]** **Pilot ship target = A- minimum / A stretch on 42-item HDRP contract (per §6.10 lock).** v1-ship items deferred per §11.8 #1-#14 (raytraced GI, RT reflections, foliage trampling/persistence, in-engine cinematics, accessibility tier, console quality tiers — per Appendix E.3 V2-WORTHY items deferred). The deferrals do **not** undermine the A-/A pilot grade; they document v2 scope. v2 grade target: A+ with raytrace pipeline.

6. **Tree imposters (LOD3) and midground shrubs (Layer 4) are NOT net-new AAA gaps.** v2 PRs #16 + #17 attempted to fix them; CUT in v3 (per V4 referee). Tree imposters already in spec §4.8 LOD3 (line 366); midground shrubs already in spec §4.4 Layer 4 (line 320). **Real net-new = 2 items** (parent-child scatter rules — PR #27; artist override layer — PR #28).

7. **`procedural_meshes.py` (22,816 LOC) relocation to sibling package is scope contamination, not AAA enhancement.** PR #49 relocates with 4-symbol shim to keep callers working. Deletion deferred to v1.1 ship (per v2 §11.5 #7 + V4 referee).

8. **`VbChunkLoader.cs` is unifying name for tile-loader path; `VbTerrainRuntimeStreamer.cs` (284 LOC) exists on `main` as runtime tile-loader.** Architectural decision required: rename + extend → `VbChunkLoader.cs` (Option A, recommended) OR keep `VbTerrainRuntimeStreamer.cs` and create separate `VbChunkLoader.cs` (Option B). **Default to Option A** — single class for tile loading; preserves camera-aware activation/frustum/distance-priority code already in `VbTerrainRuntimeStreamer.cs`. PR B5-U11 cite corrected from `:2229` to `:2152` (actual `GetOrCreateTreePrefab` location per V1).

9. **[AUTO-APPLIED — Decision 3.4 / Path 1 chosen] GPU runner provisioning approach (P1).** Three paths for the perf gate; **Path 1 chosen for v1 pilot** (self-hosted GPU runner on public repo is the #1 GitHub anti-pattern; Path 2 ~$60-70/mo cost not justified for pilot scope):
   - **Path 1 (chosen for v1 pilot):** drop GPU perf gate from required checks; use local benchmark + nightly cron compare. No additional CI cost.
   - **Path 2 (deferred):** GitHub-hosted larger T4 runner ~$60-70/mo nightly bake.
   - **Path 3 (deferred):** self-hosted with full hardening (B5-CI1/DEP4/DEP5). Highest cost + risk.

10. **APV (Adaptive Probe Volumes) experimental status (Fix 4.15 risk).** APV in Unity 2022 LTS HDRP 14 is officially **experimental** per Unity documentation. PR B5-U15 ships APV brick streaming for cave/forest interior shadow lighting; if APV regresses or is removed in a future HDRP point release, fallback path is per-chunk reflection probe (B5-U22) + light-probe groups baked statically. Risk acknowledged.

11. **SVT (Streaming Virtual Texturing) — defer to v2 (Fix 4.30).** 8K detail textures stay uncompressed in v1 pilot. SVT integration would require Unity 6 / HDRP 17 migration and is outside pilot scope.

12. **Mesh Shaders / GPU Mesh LOD — defer until Unity 6 migration (Fix 4.31).** Unity 2022 LTS does not support mesh shaders; deferred until Unity 6 migration phase.

13. **HLOD (Hierarchical LOD) — defer post-pilot (Fix 4.32).** Witcher-3-style chunk clustering for distance >2km; pilot ships flat LOD chain only.

14. **Wwise/FMOD audio integration — defer post-pilot (Fix 4.33).** `audio_zones` data exists in bake output (per spec §12.3) but runtime mixer integration is not in v1 pilot scope.

15. **Save-game serialization vs procedural seed — defer (Fix 4.34).** Spec §12.5 declares "world is fixed across playthroughs by design." Save-game serialization of mutable world state is a v2 concern.

16. **No multi-platform — PC HDRP only (Fix 4.36 / R2-Opus-4 honest cut #1).** No PS5 / XSX / Switch2 in v1; pilot ships PC HDRP exclusively.

17. **No GPU-driven rendering / DOTS / ECS — managed Unity GameObjects only (Fix 4.37 / R2-Opus-4 honest cut #2).** Pilot uses managed `GameObject`/`MonoBehaviour` lifecycle; DOTS / ECS / GPU-driven rendering deferred to v2.

18. **No CDN Addressables / remote bundle hosting (Fix 4.38 / R2-Opus-4 honest cut #3).** Local-only Addressables for v1 pilot; remote-bundle CDN, profile-pack delivery, OTA chunk updates deferred to v2.

19. **No per-chunk audio occlusion / runtime telemetry / crash analytics (Fix 4.39 / R2-Opus-4 honest cut #4).** Per-chunk reflection probes ship via B5-U22; audio occlusion + runtime telemetry + crash analytics deferred. (Localization moved to its own item below per Fix 4.35.)

20. **No path-tracing reference renders — SSIM-only golden baselines (Fix 4.40 / R2-Opus-4 honest cut #5).** SSIM 0.95 against Cycles-rendered baseline PNGs is the only golden-image gate. No path-tracing reference renders for v1; A+ with raytrace pipeline is v2 target per §11.7 #5.

**Localization deferral (Fix 4.35):** Localization deferred post-pilot — chunk names ASCII-only for v1; multi-language UI/asset names tracked in §11.8 deferral list (see #16 below in §11.8).

### 11.8 Open deferrals (post-pilot v2)

These are P0 items that survive into v1 ship. Each gets a future spec doc post-pilot.

1. **Per-playthrough seed model** — DECLARED fixed-world per §12.5; v2 if procedural-replay requested.
2. **Day/night cycle integration** — IN-SCOPE for v1 ship (per §12.1) but separate spec; post-pilot template phase.
3. **Triplanar UV pinstripes, parallel-merge setattr bypass, mask cache OOM (smoothed by `_lightweight_state_copy` but not solved)** — perf items deferred if time-boxed; addressed in part by PR #8 (deepcopy) + PR #47 (parallel-merge).
4. **Pyright-strict reductions**: 977 baseline → 297 `Any` annotations remaining; v1.1 sweep.
5. **In-process determinism CI (P0-I1)** — fix scheduled but not in pilot scope. Subprocess byte-identity test exists for CLI; weakness is 3/18 artifact coverage (PR #B5-T4 closes this). **Note:** Subprocess byte-identity CI gate (Fix 1.22's 18-artifact matrix, PR #B5-T4) is the canonical enforcement for §3.7 determinism promise; in-process gate is convenience-only, deferred without compromise to §3.7 pixel-for-pixel determinism.
6. **L-1/L-3 deprecated billboard-impostor pipeline**: silent ImportError preserved in `environment_scatter.py:78`; replace with N-view Blender bake in pilot Week 2 (separately tracked).
7. **Climate always "temperate"**: per memory; biome grammar features 8/8 still unused; v1.1 cleanup.
8. **Foliage attachment in Unity**: per memory; pilot adds attach pass; v1 ship validates.
9. **Full hydraulic realism** (Stéva 2008 multi-fluid; iceberg modeling for frozen biome) — research-grade additions deferred.
10. **URP migration** — Unity 2026 strategy puts new render features on URP. Treat as separate future project after VeilBreakers v1 ships.
11. **Raytraced GI / RT reflections** — separate pipeline conversation; A+ grade only achievable with this.
12. **`environment.py` 5-seam split (was PR #53)** — defer to v1.1; XL refactor not pilot-blocking; PRs #23/#25/#45 surgical edits would be invalidated by mid-pilot split (per Fix 1.6).
13. **PRs #49-#54: 6 XL/L refactors deferred to v1.1 per Phase 2 Fix 2.3** — `procedural_meshes.py` relocation (#49), animation modules relocation (#50), `terrain_core.py` extraction (#51), `terrain_semantics.py` 82-importer split (#52), `environment.py` 5-seam split (#53; already deferred per Fix 1.6 / item 12 above), `terrain_features.py` 9-seam split (#54). None are pilot-blocking; per §11.4 footer "may slip to v1.1 if Block 4 calendar is tight". Phase 2 Fix 2.3 makes the deferral firm. PRs #20 (compat shim) and #14 (chunk_seed re-export shim) decouple Block 1-3 work from these refactors.
14. **Block 6 (post-pilot maturity) — defined by Phase 2 Fix 2.1** — non-pilot-blocking Block 5 PRs split off as a discrete post-pilot block. See §11.6.1 for the full Block 6 PR list (Block-5.2 coherence remainders, Block-5.4 test-infra maturity, Block-5.6 conditional dependency hardening, Block-5.7 doc rot). Block 6 lands in v1.1 alongside the §11.8 #12-#13 refactors.

### 11.9 Resolution Registry

This section maps every Wave 1-5 finding to its closing PR or §11.7/§11.8 deferral. Group rows by wave for traceability.

#### Wave 1 — Initial 8-Opus orphan-pass + cleanup audit (~25 findings)

| Finding | Cite | Closing PR / Deferral |
|---|---|---|
| 7-8 orphan passes absent from default sequence | `terrain_pipeline.py:169-261` | PR #4 |
| `_toposort_passes` cycle on `height` | `terrain_pipeline.py:1449-1510` | PR #3 |
| `align_to_normal=True` default → diagonal trees | `terrain_advanced.py:2652` | PR #6 |
| `chunk_world_size=64` default | `terrain_chunking.py:100` | PR #7 |
| Deepcopy mask_stack (~30s + 4GB) | `terrain_pipeline.py:940,956` | PR #8 |
| `road_network` SDF triple-loop | `road_network.py:1808-1817` | PR #9 |
| `bytes += scanlines` (64GB churn) | `terrain_shadow_clipmap_bake.py:317-322` | PR #10 |
| Path-injection in providers | `meshy_provider.py:216`, `hunyuan3d2_provider.py:274`, `asset_generation.py:699,706` | PR #11 |
| Atomic write missing on Unity bundle | `terrain_unity_export.py:2484-2510` | PR #12 |
| Stratigraphy never registered | `terrain_master_registrar.py`, `terrain_stratigraphy.py` | PR #16 |
| Morphology delta not applied to height | `terrain_morphology.py:459-465` | PR #17 |
| Procedural_meshes scope contamination (22,816 LOC) | sibling repo move | PR #49 |
| Animation modules scope contamination | sibling repo move | PR #50 |
| terrain_core extraction needed | PassDefinition + derive_pass_seed | PR #51 |
| `terrain_semantics.py` 82 importers split | _types + _semantics | PR #52 |
| `environment.py` 8651 LOC split | 5-seam | PR #53 |
| `terrain_features.py` 9-seam split | per-feature | PR #54 |
| 47 deprecated scripts + audit doc clutter | locked-list | PR #55 |
| Importlib script-loader landmines (4) | tests | PR #22 |
| 12 legacy water_surface test refs | tests | PR #22 |
| Coverage-gate test (handlers without companion test) | new gate | PR #B5-T5 |
| Golden scenarios SHA contract | new test | PR #B5-T1 |
| `pytest-xdist` enabled | python-package.yml | PR #B5-T7 (combined with fast-lane split) |
| `PYTHONHASHSEED=0` in CI | python-package.yml | PR #18 (covered by #15) |
| In-process determinism CI theatre | P0-I1 | §11.8 #5 |

#### Wave 2 — 11-Opus + verifier-3 forensic (~58 findings)

| Finding | Cite | Closing PR / Deferral |
|---|---|---|
| 35 features unlocked by orphan passes | (composite) | PR #4 |
| 17 registered-but-inert passes | overlap with orphans | PR #4 |
| Banded macro placement | (composite) | PR #21 |
| 16+ passes missing `requires_channels` | (multiple) | PR #21 |
| Quixel ingest declares only `splatmap_weights_layer` | overrides incomplete | PR #21 |
| Waterfalls overrides `particle_emitter_specs` | declaration missing | PR #21 |
| RNG count "127 sites" | INFLATED — V3 says ~58 | PR #18 (corrected) |
| `hash(cliff.cliff_id)` PYTHONHASHSEED hazard | `terrain_cliffs.py:2397` | PR #15 |
| W-1 dual-semantics atomic migration | `terrain_water_variants.py:781,878` + 4 consumers | PRs #5a + #5b |
| Manifest atomicity cite WRONG (1612 / 1629) | real cite `terrain_unity_export.py:2484` | PR #12 |
| Overhang threshold cite WRONG (857-858) | real cite `terrain_cliffs.py:890` | PR #24 |
| Biome collapse cite WRONG (`_terrain_world.py:861-869`) | real cite `environment.py:1205` (per Fix 1.17 / Codex 1 cite-refresh; v3 first draft pointed at `:2031` which is also stale; canonical first occurrence is `:1205` with 4 sister callsites at `:2020, :2322, :2990, :3043`) | PR #25 |
| `pass_hydrology` insert cite WRONG (2017-2019) | real cite `environment.py:2861` | PR #45 |
| `derive_pass_seed` two definitions (drift hazard) — STALE per Fix 1.4-CORRECTED: only `terrain_pipeline.py:208` exists on `main`; `terrain_rng.py:45` is OUT_OF_FILE (file is 43 lines and contains only `make_rng`/`tile_rng`); claim was based on a discarded spec-branch state | resolved by promoting `chunks/chunk_seed.py` (PR #15.5) as canonical source + transition shim in `terrain_rng.py` | PR #14 + #15.5 |
| `OMP_NUM_THREADS=1` not pinned | BLAS thread leak | PR #18 |
| `terrain_quixel_ingest.py:874` unsorted iterdir | order-dependent | PR #18 |
| ID-keyed checkpoint registries `id(controller)` | `terrain_checkpoints.py:97-102` | PR #34 |
| Foam alpha INVERTED (both factors) | `terrain_waterfalls.py:115` | PR #30 |
| `consumed_channels=("height",)` actually reads 8 | `terrain_macro_color.py:230` | PR #31 |
| `DARK_FANTASY_PALETTE` covers IDs 0-7 only | `terrain_macro_color.py:28-37` | PR #32 |
| `terrain_audio_zones.py` 989 lines (real 1049) | spec body | PR #33 |
| Sabine cave/2s + open-field/0.1-0.3s cites | `terrain_audio_zones.py:539, :554` | PR #33 |
| terrain_labels std=0 (Issue #27) | architectural — generator-stamping | PR #29 |
| `pass_water_depth` skip behavior (Issue #28) | `terrain_pipeline.py:1275-1330` (skip block at `:1306-1312`; cite refreshed per Phase 0 Fix 0.6 / Phase 1 Fix 1.19) | PR #62 (gated on #5b) |
| 6 v2 PRs verified literal (#3, #4, #15, §11.5 #5, §11.5 #1+#3) | spec lines 1633, 1635, 1648, 1685, 1681, 1683 | (referenced, no new PR) |
| Issue #27 fix architecture (V1 wrong, V2 correct, current zero) | terrain_pipeline.py:1140-1143 docstring | PR #29 |
| Rescue PR C — landform_zones / shoreline_sdf NET-NEW | files don't exist on disk | PR #26 |
| AAA-vs-AA gap = 2 net-new items | parent-child + artist override | PRs #27 + #28 |
| Tree imposters already in spec §4.8 | (CUT — was v2 PR #16) | §11.7 #6 |
| Midground shrubs already in spec §4.4 | (CUT — was v2 PR #17) | §11.7 #6 |
| Per-biome ecology PRs (mountain/grassland) DEMOTE; coastal moved to §7.4 post-pilot | (was v2 PRs #20/#21/#22) | PRs #57/#58 (coastal: §7.4) |
| `_lightweight_state_copy` perf | `terrain_pipeline.py:940,956` | PR #8 |
| Numba/Taichi-jit erosion | `_water_network.py:580-664`, `_terrain_erosion.py:308-487` | PR #19 |
| Three-interpreter split decision | `requires_blender: bool` on `PassDefinition` | (architecture, no single PR; documented in §8) |
| Taichi + Cycles GPU separate processes | (architecture) | (decision documented in §8) |
| L-Py conda-only | docs | (documented in §8) |
| Quixel linear-space blend | `terrain_quixel_ingest.py:619` | PR #60 |
| Heitz/Neyret HLSL Eq.8/11 | `terrain_stochastic_shader.py:51-265` | PR #61 |
| Stochastic shader contrast knob ignored | `terrain_banded_advanced.py:542` | PR #61 |
| Triplanar UV pinstripes | (deferred) | §11.8 #3 |
| Parallel-merge setattr bypass | `_parallel_merge.py` | PR #47 |
| Mask cache OOM | (deferred) | §11.8 #3 |
| Pyright-strict reductions | (deferred) | §11.8 #4 |
| L-1/L-3 deprecated billboard | `environment_scatter.py:78` | §11.8 #6 |
| Climate always "temperate" | (deferred) | §11.8 #7 |
| Foliage attachment in Unity | (deferred) | §11.8 #8 |

#### Wave 3 — Verifier-4 referee (~10 findings)

| Finding | Resolution |
|---|---|
| v3 draft 78% correct | OPTION 1 chosen (revert + clean rewrite) |
| All 4 wrong v2 cites confirmed | PRs #12, #24, #25, #45 use correct cites |
| RNG count V3 = 47 handlers + 11 tests = 58 (or 68 with scripts) | PR #18 |
| Issue #27 fix: V1 wrong, V2 correct on architecture, current zero | PR #29 |
| `landform_zones.py` net-new (files don't exist) | PR #26 |
| AAA-vs-AA gap real net-new = 2 items | PRs #27 + #28 |
| Tree imposters/shrubs already in spec | §11.7 #6 |
| Per-biome ecology demotion | PRs #57/#58 (Block 4); #59 coastal moved to §7.4 post-pilot |
| C-1 contradiction resolution | §11.0.2 + PR #4 (carry-amendment) + #B5-D1 |
| 14 phantom channel reads | (existing v2 PRs cover ~8; rest in §11.8) |

#### Wave 4 — Cross-PR coherence (~25 findings, 9 severe)

| Finding | Cite | Closing PR |
|---|---|---|
| Water-channel naming 3 vocabularies | spec §3.4 line 192 + 209 + §8.2 line 1041 | PR #B5-C1 |
| `terrain_unity_export.py` touched by 5 PRs (#5/#11/#12/#44/#48) | dep chain serialization | PR #B5-C2 |
| #56 ↔ #55 cycle | vegetation defaults vs delete | PR #B5-C3 |
| C-1 amendment not propagated to PR #18 | scope tagging | PR #B5-C4 |
| `water_surface_mask` not registered (PR #37 reads, no producer) | extends PR #5b | PR #B5-C5 |
| #36 missing dep on #40 (splat seam re-normalize) | dep declared | PR #36 + #40 (now explicit) |
| #46 missing dep on #3 (toposort) | dep declared | PR #46 (now explicit) |
| #62 missing dep on #18 (subprocess determinism) | gate added | PR #62 (gated on #5b + #18) |
| #44 + #48 don't list #12 (atomicity) | dep added | PR #B5-C2 |

#### Wave 5 — 10 reports (CI, HDRP, Unity-side, determinism, asset budget, single-chunk, test infra, doc rot, deps, supply chain) (~150 findings)

| Wave-5 report | Closing PRs |
|---|---|
| §B.1 Cross-PR coherence (25 issues) | PRs #B5-C1 through #B5-C5 |
| §B.2 CI pipeline impact (8 changes, +60-100% wall-clock) | PRs #B5-T2, #B5-T6, #B5-T7, #B5-DEP3 |
| §B.3 HDRP shader graph F (~10%) | PR #B5-U1 (+ §11.7 #1 cut) |
| §B.4 Unity-side parity 5 BLOCKING + 9 polish | PRs #B5-U1 through #B5-U14 (+ §11.7 #2 cut) |
| §B.5 End-to-end determinism CLOSE (4 PRs to byte-identical) | PRs #14, #15, #18, #B5-T4 |
| §B.6 Asset budget 1 enforced + 6 paper | PRs #36, #B5-A1, #B5-A2, #B5-A3, #B5-A4, #43 (+ §11.7 #4 cut) |
| §B.7 Single-chunk re-bake DEGRADED but achievable (6 missing modules) | PRs #B5-D1 through #B5-D4 |
| §B.8 Test infrastructure 1,315 tests, 7 gaps | PRs #B5-T1 through #B5-T7 |
| §B.9 Doc rot HIGH severity (220 markdowns, 14 superseded) | PRs #B5-DOC1, #B5-DOC2, #B5-DOC3, #B5-DOC4 |
| §B.10 Dependency CVE + supply chain (8 hardening items) | PRs #2 (CVE+extras absorbed former B5-DEP1), #B5-DEP2, #B5-DEP3 |

**Resolution Registry totals: ~234 unique findings mapped across Waves 1-5 + Phase 4 added 30+ Wave-1+coverage gaps + AAA-readiness gaps mapped (V2's 14 coverage gaps as Fixes 4.1-4.14 and V3's 21 AAA-readiness gaps as Fixes 4.15-4.40 split BLOCKING/KEEP/DEFER). Zero declined integrations — all verified findings have either a PR closing the issue or a §11.7/§11.8 explicit cut/deferral.**

**Phase 4 fix → PR mapping:** Fix 4.1=B5-U-NAV; Fix 4.2=B5-D5; Fix 4.3=B5-C7; Fix 4.4=B5-C8; Fix 4.5=PR #23 acceptance update; Fix 4.6=B5-C9; Fix 4.7=B5-C10; Fix 4.8=B5-C11; Fix 4.9=B5-C12; Fix 4.10=PR #65; Fix 4.11=§11.10 memory item #2 update; Fix 4.12=PR #15 acceptance update; Fix 4.13=PR #18 effort upgrade L→XL; Fix 4.14=B5-A4→#56 dep edge added to §11.6; Fix 4.15=B5-U15; Fix 4.16=B5-U16; Fix 4.17=B5-D6; Fix 4.18=B5-D7; Fix 4.19=B5-D8; Fix 4.20=WITHDRAWN per R2-Opus-3 (HDRP DXR is platform-restricted); Fix 4.21=B5-T8; Fix 4.22=B5-U17; Fix 4.23=B5-U18; Fix 4.24=B5-U19; Fix 4.25=B5-U20; Fix 4.26=B5-T9; Fix 4.27=B5-U21; Fix 4.28=B5-U22; Fix 4.29=B5-T10; Fixes 4.30-4.40 = §11.7 honesty register entries #10-#20 (6 DEFER + 5 R2-Opus-4 honest cuts).

### 11.10 Memory updates (5 stale items + 04-27 SUPERSEDED-BY)

The user's auto-memory at `~/.claude/projects/.../memory/MEMORY.md` has 5 stale items that PR #B5-DOC2 must update (memory file is outside the repo; this is a manual user-edit task, not a PR):

1. **`VbTerrainTileMetadata 3-field stub`** → real value: **29 fields** (28 simple scalars/strings + 1 `ChannelBound[]` array of structs with 3 inner fields). Source: `unity_plugin/VbTerrainTileMetadata.cs` on `main` (Codex 1 ground-truth re-verification, supersedes Wave-5 §B.4 "25 fields").
2. **`127 random.Random sites`** → real value (Fix 4.11 ground-truth correction): **100 handlers + 79 tests = 179 production sites (per `RNG_SITES_47.txt` ground truth; was inflated by stale memory)**. Prior count "47 handlers + 11 tests = 58" was itself stale; the canonical ground-truth list under `.staging/RNG_SITES_47.txt` (file name preserved as identifier) lists 179 sites. The "127" was 65 doc-prose mentions as RNG sites (Wave-3 V3 forensic, finding A.1 #4); the "58" was a partial scan. PR #18 effort upgraded L → XL per Fix 4.13 (was sized for 58).
3. **`coverage floor 40%`** → real value: **72%**. Source: `.github/workflows/python-package.yml:83` (`--cov-fail-under=72`). Memory predates the bump.
4. **`branch protection protected=false`** → real value: **protected=true**. Verified via live GitHub API check (Wave-5 §B.2). 6 required checks live, `enforce_admins=true`, `required_linear_history=true`, `allow_force_pushes=false`. Gap: `required_approving_review_count=0`.
5. **`CodeQL default config only`** → real value: **`security-and-quality` query suite + Python+Actions languages**. Source: `.github/codeql/codeql-config.yml` (Wave-5 §B.10). PR #B5-DEP3 upgrades to `security-extended`.

**04-27 master implementation guide SUPERSEDED-BY banner** — pinned in user memory as IMPORTANT but stale: 5+ P0 blockers listed as ACTIVE that Batch15 (2026-05-04) marks ✅ FIXED:

- W-1 dual-semantics ✅ FIXED at `_water_network.py:907-929`, `procedural_grass.py:350-352`, `coastline.py:1242` (PR #5a + #5b carry the rest)
- E-1 erodibility 1000× ✅ FIXED at `_terrain_erosion.py:318` (PR #19 carries Taichi kernel rewrite)
- E-2 stratigraphy delta ✅ FIXED at `terrain_stratigraphy.py:1069` (PR #16 wires registration)
- M-3 `TerrainTextureLayerStack` "doesn't exist" → it exists at `terrain_texture_layer_stack.py:38`
- CL-2 cliff/talus/strata masks "never rasterized" ✅ FIXED at `terrain_cliffs.py:2704-2706`

Grade table predicted 5/11 wrong: Water D+→C+, Visual QA F→fixed (real PR #B5-T1), AI assets D→live (Hunyuan3D-2 wired), etc. **PR #B5-DOC2 patches the 04-27 guide with SUPERSEDED-BY banner pointing to `docs/aaa-audit/batch15_2026_05_04/MASTER_AUDIT_BATCH15.md`.**

### 11.11 Verification protocol

Each PR's acceptance is checked through **one of three lanes**:

#### 11.11.1 pytest validation lane

For PRs with explicit test commands in the Validation column above. Standard contract:

```
1. Branch off main: git checkout -b <type>/<scope> origin/main
2. Apply PR diff
3. Run: pytest <validation-command>
4. Confirm: green
5. Run: pytest tests/ (full suite)
6. Confirm: 1,315 tests still pass; coverage ≥ 72%
7. Run: python -m pyright (after Block 1 #2 lands)
8. Confirm: no NEW pyright errors
9. Run: ruff check
10. Confirm: clean
11. Push branch + open PR into main
12. CI green: ci (3.11), ci (3.12), pyright, callable-census, Analyze (python), Analyze (actions)
13. After Block 5 PRs land: also gating Render-Goldens, Perf-Nightly, Flaky-Hunter, CodeQL security-extended
```

#### 11.11.2 render-proof validation lane

For PRs whose acceptance depends on visual output (PR #6 vertical trunks, PR #29 label-stamping, PR #B5-T1 goldens, B5-U1 through B5-U14 Unity-side). Contract:

```
1. Run bake on `golden_scenarios/<scenario>` (4 scenarios committed by PR #B5-T1)
2. Capture render proof PNG at `renders/proof/<pr-num>/<scenario>.png`
3. Compare via SSIM 0.95 to `tests/golden_scenarios/<scenario>/baseline.png`
4. Manual visual review on diff > 0.05
5. Render proofs committed to `renders/proof/` (LFS) in same PR
```

PR review checklist for render-proof PRs:
- [ ] Render proof PNGs attached
- [ ] SSIM diff visible (red highlight > 0.05)
- [ ] User-perspective camera (3rd person + crouched) sample present
- [ ] Compared to nearest reference photo (Carpathians for mountain, Yorkshire for grassland)

#### 11.11.3 manual review validation lane

For doc-rot, scope-relocation, and refactor PRs (#49-#54, #B5-DOC1 through #B5-DOC4). Contract:

```
1. Reviewer opens PR diff
2. Confirms no functional change (refactor) OR documents intentional doc updates
3. Cross-references against this §11 table for cite accuracy
4. Verifies SUPERSEDED-BY banners and archive paths
5. Spot-checks 3 of N file moves
6. Approves
```

#### 11.11.4 Sub-agent test execution rule

Per memory `feedback_no_pytest_in_agents`: sub-agents do NOT run pytest. Test suite runs only on primary agent or CI. Verification PRs must be reviewed by primary agent or in CI lane.

#### 11.11.5 Approval gate

After §11 v3 lands in spec, two Opus verifiers run in parallel (coverage + consistency), then Codex CLI does final pass with `gpt-5.5` model. User commits only after all 4 approvals (this author + 2 Opus verifiers + Codex CLI).

### 11.12 Hygiene runway (separate doc)

**[AUTO-APPLIED — Decision 3.5 / pending user override]** Per Round-3 strategic recommendation, the post-pilot Block 6 hygiene PRs are conceptually a **separate maintenance backlog**, NOT pilot scope. The 11 hygiene PRs are:

- **Test infra maturity (5 PRs):** B5-T2 (`pytest-benchmark`), B5-T3 (`hypothesis` property tests), B5-T5 (protocol enforcement 21/74 → 60/74), B5-T6 (`pytest-rerunfailures` + flaky-hunter), B5-T7 (CI fast-lane vs nightly-full split).
- **Dependency hygiene (2 PRs):** B5-DEP2 (lockfile + `bake-env.yml` + `--require-hashes`), B5-DEP3 (dependabot + SHA-pin Actions + CodeQL `security-extended`).
- **Doc rot (4 PRs):** B5-DOC1 (archive 14 superseded markdown), B5-DOC2 (04-27 SUPERSEDED-BY banner), B5-DOC3 (nonexistent script cite removal), B5-DOC4 (commit dirty-tree docs).

None of these connect to the §0 problem statement (terrain bake → Unity HDRP ingestion → A-/A pilot). They are repository-maintenance items that the AAA-audit waves surfaced.

**Recommended:** peel into a separate doc at `docs/superpowers/specs/2026-05-06-repo-hygiene-runway.md` post-pilot. For now they remain in §11.6.1 Block 6 with the deferral marker; the separate-doc move is a v1.1 housekeeping decision and does not block pilot ship.

---

## 12. SHIP-BLOCKING Gaps Identified by Strict Review (Decisions)

Five gaps surfaced by the horizontal-coverage Opus review as SHIP-BLOCKING for a commercial AAA dark-fantasy game. Each is now explicitly resolved as either IN-SCOPE for pilot, IN-SCOPE for v1 ship (post-pilot template phase), or DEFERRED with named follow-up spec.

### 12.1 — Day/Night Cycle Integration

**Status: IN-SCOPE for v1 ship, NOT in pilot.**

Pilot acceptance gate uses single static sun rig at 50° altitude / 145° azimuth (Section 5.1). v1 ship requires dynamic time-of-day:

- HDRP Time-of-Day Volume override curves per-biome
- Sun azimuth animated 0°→360° over game-day cycle (default 24-min real-time = 1 game-day)
- Sun elevation curve per latitude (per-biome `latitude_deg` field added to biome YAML)
- Per-biome ambient color/intensity curves at: dawn (5°), morning (25°), noon (55°), evening (15°), dusk (-2°), night (-30°+ moon)
- HDRP Adaptive Probe Volumes: bake at 4 keyframes (dawn/noon/dusk/night), runtime blend
- Moon: secondary directional light, intensity curve tied to lunar phase (gameplay-driven later)
- Reflection probes use HDRP Realtime mode in dynamic chunks; Baked mode for static cinematic chunks

**Pilot delivery:** Section 5.1 lighting rig validates static look-dev; the day/night extension is a **separate v1-ship spec** scheduled post-pilot template phase (filed as future spec `2026-XX-XX-day-night-cycle-design.md`).

### 12.2 — Save/Load Version Hash Mismatch Behavior

**Status: IN-SCOPE for v1 ship.**

`meta.json.version_hash` is currently produced but the runtime contract for mismatch is unspecified. Locking the contract:

```
On chunk load, compare meta.version_hash vs game_data.expected_version_hash:
  Match → load normally
  Minor version mismatch (same major+minor, different patch) → load with warning logged
  Major+minor mismatch (post-patch save load):
    1. Attempt migration via VbChunkMigrator (per-version migration scripts)
    2. If migration unavailable, prompt player: "World data needs regenerating —
       persistent edits (felled trees, scorch marks) will be lost. Continue?"
    3. On confirm: regenerate chunk from current pipeline; player_state preserved;
       world_state diff (destruction, decals, item drops) discarded with notice
    4. On cancel: revert to last save with matching version
```

Per-version migration scripts live in `veilbreakers_terrain/migrations/v<from>_to_v<to>.py`. This contract added to Section 6 as a new sub-section 6.11 in v2 of the spec.

### 12.3 — Audio Zone Schema (was checked ✅ but never defined)

**Status: IN-SCOPE for pilot — schema locked here.**

`meta.json.audio_zones[]` schema:

```json
{
  "audio_zones": [
    {
      "zone_id": "mountain_alpine_open",
      "aabb": {"min": [-128, 0, -128], "max": [128, 800, 128]},  // chunk-local coords
      "footstep_surface": "rock_loose",   // maps to Unity AudioMixer surface set
      "reverb_preset": "alpine_open",     // maps to HDRP/Unity Reverb Zone preset
      "ambient_loop": "wind_high_alpine", // AudioClip path in Addressables
      "ambient_volume_db": -8.0,
      "wind_intensity_curve_id": "alpine_wind",  // drives runtime wind audio
      "water_proximity": null  // populated to nearest river/lake basin_id if <50m
    }
  ]
}
```

Splat-layer-ID → footstep-surface mapping per biome locked in `species_libs/<biome>.yaml` under `splat_layer_audio_map`:

```yaml
mountain:
  splat_layer_audio_map:
    layer_0: alpine_grass    # alpine_grass splat → grass footstep
    layer_1: forest_soil_dry # forest_soil → dirt footstep
    layer_2: rock_loose      # scree → rock_loose footstep (skitter sound)
    layer_3: rock_solid      # rock → rock_solid footstep
    layer_4: snow_powder     # snow → snow_powder footstep
    ...
```

Cave reverb geometry is the cave FBX bounding box; ambient audio loops are biome-default unless a chunk-level override exists.

### 12.4 — NavMesh Build Trigger + Off-Mesh Link Heuristic

**Status: IN-SCOPE for v1 ship, partial pilot.**

Pilot ships `navmesh.png` walkable mask only (Section 6.1). v1 ship requires:

```
Build trigger:
  Mode A (dev): Unity Editor button "Bake NavMesh from Chunk Walkable Masks"
                runs NavMeshSurface.BuildNavMesh() per chunk, stores in chunk prefab
  Mode B (runtime): NavMeshComponents.NavMeshSurface with `collectObjects=Volume`
                    bakes on chunk load; ~50ms per chunk on RTX 4060 Ti CPU thread

Surrogate stitching across streamed chunks:
  Each chunk's NavMeshData stored in chunk.navmesh_data
  On neighbor load: NavMesh.SetNavMeshData() merges surfaces by edge proximity
  Edge tolerance: 0.5m height, 1.0m horizontal

Off-mesh link generation (heuristic):
  Jump anchors: detected gaps where two walkable regions are within 1-4m horizontal
                AND <2m vertical drop AND no walkable path exists between them.
                Algorithm: erode walkable_mask by 2px to find "ledges"; for each ledge
                pixel, raycast 1-4m perpendicular; if landing pixel walkable, register.
  Climb anchors: detected on cliff faces where walkable_mask transitions to non-walkable
                 with slope > 60° AND height < 4m AND climbable_material flag in splat.
                 Algorithm: scan vertical strips along cliff base; sample every 3m;
                 if grippable splat at top, register climb anchor.
  Fall anchors: walkable_mask edges with >2m drop AND walkable below.

Stored in meta.json.navmesh_hints.{jump_anchors, climb_anchors, fall_anchors}.
Unity NavMeshSurface consumes these as off-mesh links during bake.
```

Pilot: `navmesh.png` only (mandatory tier #40-41). v1 ship: full NavMesh build + off-mesh links (polish tier #42 + new v1-ship spec).

### 12.5 — Per-Playthrough Seed Model (declared intent)

**Status: DECLARED — world is fixed across playthroughs by design.**

VeilBreakers is a story-driven dark-fantasy game; player exploration relies on world consistency for quest design, environmental storytelling, and shared community knowledge. Therefore:

- **`version_hash` deliberately omits per-playthrough seed.** Same chunks for every player.
- New Game+ runs are visually identical to original; only player_state differs.
- Procedural quest content (procgen item drops, dynamic encounters) seeds from `hash(player_id, chunk_id, version)` — playthrough-specific via player_id, world-shared via chunk_id.
- Modding hook: a `world_seed_override` in pyproject.toml debug config allows dev-time variant generation; never exposed to runtime players.

**Spec impact:** none — current `version_hash` is correct as-is. This is a *declaration of intent*, not a design change.

---

## 13. Vertical-Depth Parameter Specifications (closing v1.0 BLOCKING gaps)

The vertical-depth Opus review identified 10 BLOCKING parameter gaps. Each is now specified.

### 13.1 — Mei et al. 2007 Hydraulic Solver Parameters

```
# Mei et al. 2007 shallow-water flux solver — locked parameters
g                = 9.81 m/s²                # gravity
dt               = 0.05 s                    # timestep (CFL-stable for 2m grid + 200 iters)
A                = 4.0 m²                    # virtual pipe cross-section
L                = 2.0 m                     # virtual pipe length (matches grid spacing)
friction         = 0.04                      # bed friction coefficient (Manning-like)
Kc               = 0.022                     # sediment capacity constant
Ks               = 0.012                     # dissolution constant
Kd               = 0.005                     # deposition constant
Ke               = 0.005 m/iter              # evaporation rate
rain_rate        = 0.012 m/iter              # uniform rainfall
n_iterations     = 200
hardness_factor  = per-pixel from terrain_stratigraphy modulation, range [0.4, 1.6]
```

**Rationale:** values calibrated against Št'ava et al. 2008 reference implementation; `Kc=0.022` produces visible river valleys without over-erosion at 200 iter on 4096² grid. CFL stability check: `dt × max_velocity < 0.5 × grid_spacing`; with `g=9.81`, max water depth ~2.4m, max velocity ≈ 5 m/s → `0.05 × 5 = 0.25 < 0.5 × 2 = 1.0` ✅.

### 13.2 — Erosion Re-run State Semantics (Section 3.3c)

**Locked:** stratification re-run **continues** from prior hydraulic state (water depth, sediment) — does NOT reset. The 50 additional iterations apply the modulated erodibility on top of the converged 200-iteration field. Reset would discard physical realism (rivers would re-form, taking another 50+ iter to converge).

### 13.3 — Procedural FBM Specification

```
fbm_overlay(x, y, biome_seed):
  basis        = OpenSimplex2 (deterministic, gradient-noise)
  permutation  = derived from hash(biome_name, version)  # not random
  octaves      = 3
  wavelengths  = [4m, 16m, 64m]
  amplitudes   = [0.5m, 2m, 6m]
  offset       = (0, 0)  # no spatial offset; biome_seed varies basis seed
  modulation   = elevation-conditioned: amplitude *= (1 - smoothstep(elev/300m, 0.7, 1.0))
                 # high-altitude pixels get less procedural noise (snow caps stay smooth)
```

### 13.4 — DEM Void Handling + Datum/Projection

```
DEM source: NASA SRTM 30m, Hgt format, EGM96 geoid datum
Projection: WGS84 lat/lon → local tangent plane Mercator at biome center coordinate
Resampling: cubic Hermite interpolation 30m → 2m
Void handling (SRTM has known voids in steep terrain):
  Step 1: detect voids via SRTM `_NUM` stripe metadata
  Step 2: fill with NASA SRTM Plus (hole-filled variant) where available
  Step 3: remaining voids → bicubic interpolation from 8 nearest valid neighbors
  Step 4: if void cluster > 100 pixels, log warning + flag for manual review
  Step 5: post-fill, apply 3-pixel Gaussian blur in void regions only (hide seams)

Carpathian foothills (Tatry/Bieszczady) — verified void-free in SRTM Plus.
Yorkshire Dales — verified void-free.
Future biomes — void inspection per region before locking reference.
```

### 13.5 — TWI Threshold Calibration to 2m Grid

**Issue:** v1.0 spec §4.5 sets `wet_zone_override` trigger at TWI > 8.5, derived from 30m DEM context. TWI scales with cell area: at 2m resampled grid, the *same physical wetness* corresponds to a different TWI value because `upslope_area` is measured in pixels, and pixel size shrunk 15×.

**Locked recalibration:**
```
TWI_2m = ln(upslope_area_in_pixels × pixel_area_m² / tan(slope))
       = ln(upslope_area_pixels × 4 / tan(slope))   # 4 = (2m)²
       = ln(4) + TWI_baseline_pixels
       ≈ 1.386 + TWI_baseline_pixels

Original 30m: pixel_area = 900 m², so TWI_30m baseline + ln(900) = TWI_30m + 6.802
2m equivalent: TWI_2m baseline + ln(4) = TWI_2m + 1.386
Offset: TWI_30m → TWI_2m: subtract (6.802 - 1.386) = 5.416

Therefore: 30m TWI 8.5 → 2m TWI ≈ 3.08

LOCKED:
  TWI_min = 1.5
  TWI_max = 6.0
  wet_zone_override threshold (formerly "TWI > 8.5"): TWI_2m > 3.0
```

This recalibration is critical. v1.0's "8.5" would have been so high that wet-zone overrides would NEVER trigger in practice on the 2m grid.

### 13.6 — L-Py Grammar Authoring Contract

```
Per-species L-system grammar lives at:
  veilbreakers_terrain/foliage/species_libs/lpy_grammars/<biome>/<species>.lpy

File format (L-Py native):
  # Header metadata
  # species_id: alpine_pine_hero
  # biome: mountain
  # height_range_m: [18, 25]
  # tris_per_lod0: 5000
  # variants_to_bake: 12

  axiom = ...
  derivation_length = ...
  productions = ...
  interpretation = ...

Bake driver: foliage/lpy_hero.py.bake_species_variants(species_id, n_variants=12)
  - For i in range(n_variants):
      seed L-Py global RNG with hash(species_id, i)
      run derivation
      capture mesh as Blender object
      apply biome-bark + leaf material
      export to species library .blend at output/species_libs/<biome>/<species>_v<i>.blend
  - Variant catalog written to species_libs/<biome>/<species>_catalog.json

Hero scoring picks variant_id from `hash(chunk_x, chunk_y, position) % n_variants`.

Grammar authoring effort: ~4-6 hours per hero species; ~2 hours per filler species
(spec Week 2 budget: mountain 2 hero + 4 filler + grassland 2 hero + 4 filler =
12 species × ~3hr avg = ~36 hours total — fits Week 2 with margin)
```

### 13.7 — MTree Headless Parameter File Format

```
MTree is a Blender add-on; we invoke its operators headlessly.

Per-species parameter file:
  veilbreakers_terrain/foliage/species_libs/mtree_params/<biome>/<species>.json

Schema:
  {
    "species_id": "alpine_pine_filler_med",
    "mtree_node_graph": "<JSON serialization of MTree node graph from Blender>",
    "trunk_height_m": 14.5,
    "trunk_radius_m": 0.32,
    "branch_count": 28,
    "leaf_count": 3500,
    "wind_uv_data": {
      "trunk_mass": 0.85, "primary_axis": [0, 0, 1],
      "sway_freq_hz": 0.4, "gust_response": 0.3,
      "leaf_detail_freq_hz": 2.1, "leaf_amplitude_m": 0.08
    },
    "lod_targets": {"lod0_tris": 1800, "lod1_tris": 800, "lod2_tris": 200}
  }

Bake driver: foliage/mtree_filler.py.bake_species(species_id)
  Uses bypass_operator wrapper from MTree addon to invoke node-graph evaluation
  without bpy.context.scene context (headless-clean).
```

### 13.8 — Voronoi Clumping Cell Specification

```
Cell size: 4m × 4m baseline (configurable per-species), produces visible clump structure
           at human-scale viewing distances (3rd-person camera, crouch POV, etc.)

Cell seeding: blue-noise Poisson distribution (Bridson 2007) at radius 4m,
              jittered ±0.8m within cell; deterministic from hash(chunk_x, chunk_y, biome)

Per-cell variance:
  clump_offset       ~ TruncatedNormal(mean=1.0, sigma=0.18, bounds=[0.8, 1.25])
  species_blend      ~ Categorical(species_weights from biome_yaml)
                       1-3 species per cell, weighted; produces species mixing
  density_multiplier ~ Beta(2, 2) ∈ [0, 1.5]   # most cells near 0.75-1.0, occasional gaps
  rotation_y         ~ Uniform(0, 2π)

Edges between cells: smoothstep blend over 0.5m → smooth species transitions
```

### 13.9 — Edge-Weld Assertion Failure Mode (Player Build vs Editor)

```
Editor mode (Debug+Development builds):
  On mismatch: log error to Unity Console, draw red wireframe at bad edge,
               continue loading (do NOT crash) — allows iteration

Player mode (Release builds):
  On minor mismatch (within tolerance × 5):
    log warning to player_log.txt; load with edge-blend smoothing applied
    (interpolates last 4 verts of mismatched edge over neighbor)
  On major mismatch (> tolerance × 5):
    log error to player_log.txt; load chunk anyway with red-shifted debug tint
    on terrain shader (visible-but-not-fatal indicator)
  Never crash. Never block. Never silent — always logged.

Telemetry (post-ship): aggregate edge-weld error counts, surface in dev dashboards
                       so post-patch errors are visible.
```

### 13.10 — Spawn-Safe Fallback Hierarchy

```
chunk_spawn_safe_position determination:
  Priority 1: chunk center if (slope < 25 AND water_depth == 0 AND tree_footprint == 0
                              AND NOT cliff_overhang)
  Priority 2: nearest valid pixel by Euclidean distance from chunk center (search radius 100m)
  Priority 3: if no valid pixel within chunk: emit (chunk_center, valid=false) and log warning
              Unity treats invalid spawn-safe chunks as "no respawn anchor here"
              (e.g., mountain peak chunk, lake-only chunk)
  Priority 4: gameplay layer queries nearest VALID spawn-safe across neighbor chunks
              for fast-travel / respawn fallback
```

---

## 14. Runtime Channel Contracts (per Opus #3 horizontal review recommendation)

The bake side of the spec is at A- quality; this section formalizes the runtime side. Each baked artifact below is paired with its runtime consumer, schema reference, and lifecycle.

| Baked artifact | Runtime consumer | Schema | Lifecycle |
|---|---|---|---|
| `terrain.raw` | Unity Terrain | 16-bit raw, 257² | Load on chunk activate; immutable |
| `splat.png` + `splat_secondary.png` | Unity Terrain alphamap | RGBA 257² × 2 | Load on activate; immutable |
| `holes.png` | Unity Terrain Holes + MeshCollider for hole edges | R8 257² | Load + generate edge collider mesh on activate |
| `layers/<n>_*.png` | Custom HDRP TerrainLit Shader Graph variant | per-layer 4K texture set | Loaded biome-wide once; reused across all chunks |
| `macro_variation.png` | Custom Shader Graph (macro overlay slot) | RGBA 512² unique per chunk | Load on activate; bound to material per-chunk |
| `overlay_dynamic.png` | Custom Shader Graph (overlay_dynamic slot) | RGBA 257² | Load on activate; refreshed when weather state changes |
| `triplanar_mask.png` | Custom Shader Graph (triplanar fade) | R8 257² | Load on activate; static |
| `flow_map.png` | HDRP WaterSurface River type (current map) | RG16 257² | Load on water surface activate |
| `navmesh.png` | NavMeshSurface bake input + off-mesh anchor scoring | R8 257² | Load → bake via NavMeshComponents → discard texture |
| `vertex_ao.bin` | Vertex color attribute on terrain mesh | binary float per vert | Load on activate; immutable |
| `caves/*.fbx` | GameObject children of chunk; collider + render | static mesh | Instantiate on activate; despawn on deactivate |
| `foliage.json` | Addressables prefab instantiation | tree+prop instance list | Instantiate hero/filler trees on activate; pool deactivated |
| `grass.json` | GPU instancing per 32m sub-cell | 30k–80k entries per chunk | Lazy load on player proximity (sub-cell-level streaming) |
| `water.json` | HDRP WaterSurface + custom Waterfall prefabs | rivers/lakes/waterfalls/ocean | Instantiate water bodies on activate |
| `edges.json` | VbChunkLoader stitch assertion + Terrain.SetNeighbors() | N/S/E/W edge structs | Read on neighbor-load events |
| `probes.json` | Reflection Probe + Light Probe placement | placements list | Instantiate on biome activate (zone-level, not chunk-level) |
| `decals.json` | HDRP Decal Projector instantiation | per-chunk decal list | Instantiate on activate; pool deactivated |
| `meta.json` | Per-chunk metadata + audio_zones + navmesh_hints + addressable_deps | structured | Read on activate; drives all of the above |

**Lifecycle events (Unity-side):**
```
OnChunkLoadRequested   → fetch addressable bundle, parse meta.json, schedule load
OnChunkLoadStarted     → background thread reads all artifact files
OnChunkLoadComplete    → main thread: SetHeights, SetAlphamaps, SetHoles, instantiate
                         prefabs, bind shaders, set material parameters, register
                         WaterSurfaces, AudioSources, ReverbZones, NavMesh data
OnNeighborLoaded       → Terrain.SetNeighbors() + edge-weld assertion check + flow continuity check
OnChunkUnloadRequested → reverse all instantiation, release Addressable handles, free GPU buffers
```

---

## Appendix E — Strict-Reviewer Findings Register

This appendix tracks every finding from the 6-agent strict review wave (3 Opus deep-dives + 3 Sonnet code-clutter audits) and its disposition.

### E.1 — Opus PR #24 Audit Verdict

**Verdict: CLOSE-WITHOUT-MERGE with 2 narrow rescue PRs.**

Rescue PR A (small, ~10 files, the only durable contribution):
- `veilbreakers_terrain/handlers/visual_render_camera_proof.py` (deterministic camera-render assertion handler)
- `veilbreakers_terrain/tests/test_visual_render_camera_proof.py`
- `docs/solutions/best-practices/visual-render-camera-proof-2026-05-04.md`
- 7 rows in `GRADES_VERIFIED.csv`

Rescue PR B (optional, ~6 files):
- `veilbreakers_terrain/coastal/{landform_zones,shoreline_sdf}.py` + tests — Bezier-SDF math reusable in chunk-based pipeline

File 2 plausibly-new bugs as GitHub issues: `terrain_labels` (std=0 across all biomes), `pass_water_depth` skip behavior — may not be in the May 3 audit at this precision.

**Reasoning:** PR #24 is a 64×64 toy harness with synthetic-channel pre-population (smoke test, not quality system). 67% of its "6 confirmed bugs" are redundant with the May 3 / Batch 15 audit which already documents them with file:line precision. The PR contradicts itself across commits. CI failures are fixable but fixing CI to merge a system about to be deleted = negative ROI. Net: ~5% useful after rebuild ships; close.

### E.2 — Opus AAA Spec Vertical Depth — 10 BLOCKING Gaps Resolved in v1.1

| Gap | v1.0 state | v1.1 resolution | Section |
|---|---|---|---|
| Mei et al. 2007 hydraulic parameter set | unspecified | locked Kc/Ks/Kd/Ke/A/L/g/dt/friction/rain_rate values | §13.1 |
| Erosion re-run state semantics | ambiguous | continues from prior state (does NOT reset) | §13.2 |
| Chunk extents math (512m vs 514m) | ambiguous | 256 cells × 2m = 512m extents; 257th vert is shared edge | §1 Q3 |
| DEM void handling + datum/projection | silent | SRTM Plus fallback + bicubic + EGM96 → WGS84 → local tangent Mercator | §13.4 |
| TWI 8.5 calibration to 2m grid | wrong scale | recalibrated to TWI_2m > 3.0 (with derivation) | §13.5 |
| L-Py grammar authoring contract | unspecified | per-species `.lpy` file at `species_libs/lpy_grammars/<biome>/`, bake driver, variant catalog | §13.6 |
| MTree bypass_operator parameter file format | unspecified | per-species JSON at `species_libs/mtree_params/<biome>/`, schema locked | §13.7 |
| Voronoi clumping cell size + seed + variance | unspecified | 4m cell, blue-noise Poisson seed, TruncatedNormal variance | §13.8 |
| Edge-weld assertion failure mode in player builds | fail-fast (crash risk) | log + edge-blend smoothing + telemetry (never crash) | §13.9 |
| Section 6.10 vs 7.2 grade conflict | contradictory | mandatory-32 + polish-10 split with explicit pass criteria | §6.10 |

### E.3 — Opus AAA Spec Horizontal Coverage — 5 SHIP-BLOCKING Gaps Resolved

| Gap | Disposition | Section |
|---|---|---|
| Day/night cycle integration | IN-SCOPE for v1 ship (post-pilot template), separate spec | §12.1 |
| Save/load version_hash mismatch | IN-SCOPE for v1 ship; contract locked | §12.2 |
| Audio zone schema | IN-SCOPE for pilot; schema locked here | §12.3 |
| NavMesh build trigger + off-mesh links | partial pilot (mask only); full v1 ship | §12.4 |
| Per-playthrough seed model | DECLARED — world fixed across playthroughs by design | §12.5 |

V2-WORTHY items deferred (acknowledged): foliage interactions (trampling/destruction), terrain persistence, in-engine cinematics, accessibility tier, console quality tiers. Each gets a future spec doc post-pilot.

### E.4 — Sonnet veilbreakers_terrain/ Core Clutter — 8 Surgical PRs Locked

Compatibility grade: **C** — existing structure not hostile, surgical fixes required.

8 critical conflicts with file:line precision (all addressed in §11 PR sequence):
1. `terrain_water_variants.py:781,878` — W-1 legacy writes (PR #3)
2. `terrain_advanced.py:2652` — align_to_normal default True (PR #4)
3. `terrain_morphology.py:459-465` — morphology_delta never applied (PR #7)
4. `terrain_water_variants.py:622-648` — wetland_type discarded (PR #3)
5. `terrain_unity_export.py` — 14 test imports (PR #9)
6. `environment.py:8274` — lazy import will ImportError (PR #9)
7. `terrain_chunking.py:100` — chunk_world_size default 64m (PR #5)
8. `_terrain_erosion.py:308` — E-1 erodibility (replaced by Taichi)

14 phantom channels triaged in §14 runtime contracts (some WIRED, some REMOVED, some KEPT).

Critical unwired: `terrain_stratigraphy.py` has zero `register_*` references in master_registrar — addressed by PR #6.

### E.5 — Sonnet scripts/ Clutter — 47 Deletes + 8 Conflicts

Disposition summary:
- 47 DEPRECATED-DELETE → consolidated into PR #10 (single cleanup PR)
- 8 CONFLICT scripts → PR #10 deletes most; PR #15-17 decouple test imports first
- 29 KEEP scripts → CI gates + asset fetchers + audit tools (no action)
- 7 UNCLEAR → reviewed post-pilot
- 2 DEPRECATED-KEEP-UNTIL-PILOT → marked with header comments

Scripts confirmed as carrying the diagonal-tree bug at exact line numbers: `coastal_build_v3d_vegetation.py:285-392` and `coastal_build_v3d_vegetation_v2.py:360-392` (cited as evidence in spec §0).

### E.6 — Sonnet output/renders/docs/CI Clutter — Repo Storage + CI

Storage:
- ~1.1 GB LFS reclaimable post-pilot (renders/quality-audit, output/visual_nodes, output/aaa_node_v*, output/scene_v*, *.blend1)
- ~50 MB git proper reclaimable (stale audit docs, intermediate spreadsheets)

Critical pre-pilot blocker: `taichi` and `rasterio` missing from `pyproject.toml` — PR #2.

Test landmines: 3 test files import scripts being deleted — PRs #15-17 decouple before deletes.

CI workflows stable: all 10 referenced scripts exist; new chunk-render-proof workflow (PR #20) added.

`.gitignore` gap: `output/aaa_node_v3/` is committed but only v4+ is ignored — PR #1.

### E.7 — Net Effect of Strict Review on Spec

**Lines added in v1.1: ~700.** Spec is now 2300+ lines.

- v1.0 grade per strict reviewer: **AA at most, NOT implementable as-is**
- v1.1 grade target after addendum: **AAA implementable** (close BLOCKING gaps + define runtime contracts + lock cleanup runway)
- Net additions: 4 new sections (11, 12, 13, 14), 1 new appendix (E), parameter tables for hydraulic/L-Py/MTree/Voronoi, runtime channel lifecycle contracts
- 20 PR cleanup runway → ~3-5 days focused work before pilot Week 1

---

**End of design spec v1.1. Ready for re-review by spec-document-reviewer subagent and final user approval.**
