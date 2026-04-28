# AAA Terrain Generation Pipeline Best Practices
**Research Date:** 2026-04-27  
**Purpose:** Actionable pipeline architecture guidance for VeilBreakers terrain generator  
**Scope:** Pipeline architecture, heightmap generation, tile/chunk architecture, generation checklist, failure modes

---

## TABLE OF CONTENTS

1. [Terrain Generation Pipeline Architecture](#1-terrain-generation-pipeline-architecture)
2. [Heightmap Generation: Noise, Erosion, and Resolution Standards](#2-heightmap-generation-noise-erosion-and-resolution-standards)
3. [Tile and Chunk Architecture](#3-tile-and-chunk-architecture)
4. [Production Generation Checklist: Noise Seed to Export](#4-production-generation-checklist-noise-seed-to-export)
5. [Known Failure Modes and Artifact Causes](#5-known-failure-modes-and-artifact-causes)

---

## 1. Terrain Generation Pipeline Architecture

### 1.1 World Machine Node Graph Architecture

World Machine uses a three-tier device network paradigm:

- **Generator Devices** — produce base heightfields (Perlin noise, Voronoi, Layout Generator for vector-drawn features, File Input for DEM import)
- **Filter and Combiner Devices** — modify and blend heightfields (erosion, displacement, terrace, blend, etc.)
- **Output Devices** — export heightfields, meshes, bitmaps, and mask layers to disk

Data flows strictly left-to-right through wired connections. Multiple outputs can be extracted from a single graph: a terrain heightfield, a color texture map, and several mask bitmaps (slope mask, altitude mask, water mask) all export from the same project file.

**Key architectural principle:** World Machine worlds describe *operations*, not terrain data. The actual heightfield is produced at build time. This makes the project file a reproducible recipe rather than a stored asset.

Sources:
- [World Machine Device Workspace Documentation](https://help.world-machine.com/topic/devices-and-the-device-workspace/)
- [World Machine File I/O Documentation](https://help.world-machine.com/topic/file-input-and-output/)

### 1.2 Gaea Node Graph Architecture

Gaea structures its graph as physical-process nodes, not abstract mathematical operations. Each node represents a specific geological or hydrological simulation:

- **Shape generators:** Gradient, Mountain, Strata, Dunes, Canyon
- **Erosion simulators (separate nodes per process):**
  - `Erosion` / `Erosion_2` — hydraulic (fluvial)
  - `Thermal` — thermal weathering/talus
  - `Wizard` — combined hydraulic with simplified controls
  - `Debris` — physics-based rock fragment scattering
  - `Wind` — aeolian sand dune formation
- **Hydrology:** River, Lake, Hydrology (outputs rivers/lakes as separate heightfields or meshes; uses Strahler ordering for river hierarchy)
- **Biome/Vegetation:** Vegetation node driven by terrain shape, hydrology data, and climate masks
- **Accumulator:** Collects global masks across multiple simulation passes (total water, fresh water depth, tree density, debris coverage)
- **Portal System:** Allows complex sub-graphs to be defined in separate tabs and recalled anywhere in the main graph (critical for keeping large multi-biome projects organized)

**Canonical pass order in Gaea:**
```
Shape/Noise → Thermal Erosion → Hydraulic Erosion (multi-pass) → 
Hydrology (rivers/lakes) → Sediment/Debris → 
Vegetation node → Altitude/Slope/Flow masks → 
Output (heightfield + splat + masks)
```

The key insight: Gaea's multi-pass erosion deliberately separates hydraulic and thermal, then chains them. A single erosion pass is the hallmark of amateur terrain; production work uses 3+ erosion passes at different scales.

Sources:
- [Gaea Simulations Overview](http://quadspinner.com/Gaea/Simulations)
- [Gaea Erosion Documentation](https://docs.quadspinner.com/Guide/Using-Gaea/Erosion.html)
- [Cinevva Landscape Generation Guide](https://app.cinevva.com/guides/landscape-generation-browser)

### 1.3 Houdini Heightfield Pipeline

Houdini's terrain workflow is explicitly ordered as a sequence of elevation passes, each building on the previous:

**Step 1 — Massing (Low Resolution)**
Use `Heightfield Paint`, `Heightfield Project` (drape 3D geometry), or `Heightfield File` (import 2D image). Establishes macro-scale terrain form.

**Step 2 — Seeding**
Add micro-disturbances via `Heightfield Noise`, `Heightfield Distort by Layer`, or `Heightfield Distort by Noise`. Seeding is not cosmetic — it creates obstacles that force erosion to behave realistically. Without seeding, erosion produces mechanical, uniform channels.

**Step 3 — Lobing**
Apply `Heightfield Erode` with elevated precipitation, high cut angles, and high sediment capacity to carve the primary mass into discrete mountain lobes/sections.

**Step 4 — Remapping**
`Heightfield Remap` compresses elevation vertically, then the massing/seeding/lobing steps repeat on top. This stacks elevation *passes* (foothills below compressed, mountains above), producing multi-scale geological hierarchy that cannot be achieved in a single pass.

**Step 5 — Upsampling**
`Heightfield Resample` doubles resolution. Never jump from low to final resolution in one step — iterate gradually.

**Step 6 — Shaping**
`Heightfield Terrace` and `Heightfield Clip` with masks add geological features (terraces, vertical cliffs, plateaus).

**Step 7 — Re-seeding**
Repeat seeding at the new higher resolution to add finer obstacles for the final erosion pass.

**Step 8 — Full Erosion**
`Heightfield Erode` (or `HF Erode Thermal`, `HF Erode Hydro`, `HF Precipitation` individually). Multiple chained erode nodes at different feature scales. The Erosion Feature Size parameter controls channel width: larger values produce wide valleys and broad slopes; smaller values produce sharp ravines and fine detail. Outputs include eroded `height`, `sediment`, `debris`, `flow`, and `flowdir` layers — all usable downstream for texture synthesis.

**Step 9 — Export**
`Heightfield Scatter` for vegetation/rock point instancing. `Heightfield Quickshade` for preview materials. Export heightfield plus auxiliary layers (sediment, flow, slope) as separate files.

**Critical insight from SideFX:** Build terrain in "Elevation Passes." The elevation-compress-and-stack approach produces terrain with distinct geological scales (micro-features, hills, mountains) that a single noise+erosion pass never achieves.

Sources:
- [SideFX Houdini Terrain Workflow Documentation](https://www.sidefx.com/docs/houdini/model/terrain_workflow.html)
- [HeightField Erode Node Reference](https://www.sidefx.com/docs/houdini/nodes/sop/heightfield_erode.html)

### 1.4 UE5 PCG (Procedural Content Generation) Framework

UE5 PCG does *not* generate the heightmap itself — it operates on existing landscape data to place procedural content. The PCG Graph node types are:

**Data Types:**
- **Surfaces** — Landscape/terrain as 2D spatial data projected to XY plane
- **Point Clouds** — 3D points with position, density (0–1), and custom attributes
- **Splines** — Landscape Spline components for roads, rivers, paths
- **Volumes** — 3D boolean shapes for inclusion/exclusion zones

**Key Node Categories:**
- **Samplers** (generate points): `Surface Sampler` (points on landscape surface), `Volume Sampler`, `Spline Sampler`
- **Filters** (remove points): `Density Filter`, `Bounds Filter`, `Self-Pruning` (prevents overlap)
- **Modifiers** (transform points): `Transform Points`, `Attribute Operation`, `Copy Points`
- **Spawners** (place content): `Static Mesh Spawner`, `Actor Spawner`
- **Hierarchical Generation** — subgraph support for biome-level organization

**Landscape-specific PCG nodes (UE5.5+):**
- `PCGGenerateLandscapeTextures` — generates grass type textures and height maps from the landscape
- `PCGLandscapeData` — samples landscape height, normals, layer weights, and physical materials as point attributes
- Virtual texture sampling of landscape layers available in GPU sampling mode

**PCG pipeline for terrain scatter (canonical order):**
```
Landscape Input → Surface Sampler → Projection (height/normal) → 
Density Filter (slope) → Self-Pruning (bounds) → Transform Points → 
Static Mesh Spawner
```

Sources:
- [UE5.7 PCG Overview](https://dev.epicgames.com/documentation/unreal-engine/procedural-content-generation-overview)
- [PCG Data Types Reference](https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-framework-data-types-reference-in-unreal-engine)
- [PCGGenerateLandscapeTextures API](https://dev.epicgames.com/documentation/en-us/unreal-engine/BlueprintAPI/Utilities/Struct/MakePCGLandscapeDataProps)

### 1.5 Production Studio Pipelines

#### CD Projekt RED — The Witcher 3 (REDengine 3)
From Marcin Gollent's 2014 GDC presentation ("Landscape Creation and Rendering in REDengine 3"):

- **World size:** 35× The Witcher 2. Novigrad city alone is 46×46 tiles.
- **Vertex spacing:** 0.37 cm between terrain vertices in city areas; target was <0.5m globally.
- **Target resolution:** Support for 16384² heightmaps.
- **Terrain texturing:** Two-material system (background material + foreground material), moving away from conventional linear material blends for better visual quality.
- **Vegetation placement:** Hybrid system — offline vegetation generator (simulates water accumulation and sunlight distribution, then places species by light requirement) + runtime on-the-fly distribution. Manual painting masks out procedural placement in special areas.
- **Grass:** Fully procedural instances; no manual placement. Diversity achieved through per-instance variation.
- **LOD:** Terrain shadow casting from huge meshes (like mountains); terrain LOD management described as a separate system.
- **Streaming:** World split into tiles, each tile packaged into a "tome" (via Umbra 3 middleware). Tomes load asynchronously based on camera position and direction. Unused tomes removed to free VRAM.

**Key lesson:** CDPR's vegetation generator explicitly models physical processes (water flow, sunlight shadowing, slope angle) to decide species placement — not just noise-masked density fields.

Source: [GDC Vault: Landscape Creation and Rendering in REDengine 3](https://www.gdcvault.com/play/1020197/Landscape-Creation-and-Rendering-in)

#### Guerrilla Games — Horizon: Zero Dawn
From Jaap van Muijden's 2017 GDC talk ("GPU-Based Run-Time Procedural Placement"):

- **Density map pipeline:** Procedural system generates 2D density maps (64×64 pixels per block), which are discretized into point clouds by compute shaders — not direct object placement.
- **Granularity by asset size:** Large assets (trees) use 128×128m blocks; grasses use 32×32m blocks. Both use 64×64 density resolution per block.
- **Multiple heightmap layers:** Ground heightmap plus separate water surface heightmap. Objects can be placed on terrain, on top of other objects, or on the water surface.
- **Logic graph (density map shader):** Artists define placement rules in a graph editor; this compiles to a GPU compute shader (DENSITYMAP shader) that evaluates world data into the 64×64 density texture.
- **GPU pipeline per layer:**
  ```
  DENSITYMAP shader (64×64 density texture) →
  GENERATE shader (discretize density map into oriented point cloud) →
  PLACEMENT shader (expand points to world matrices with per-object variation) →
  CPU readback (copy to CPU memory for final world integration)
  ```
- **Collision avoidance:** Handled via a separate GPU pass to prevent assets from overlapping.
- **Key insight:** The system is fully runtime — no baked placement data. The entire environment regenerates as the player moves, eliminating placement data storage and streaming entirely.

Source: [GPU-Based Procedural Placement in Horizon Zero Dawn (Guerrilla Games)](https://www.guerrilla-games.com/read/gpu-based-procedural-placement-in-horizon-zero-dawn)

#### Ubisoft — Far Cry 5
From the GDC 2018 "Procedural World Generation of Far Cry 5" talk:

- **Spatial hierarchy:** Map (top level, streaming boundary) → Section (256m × 256m) → Sector (64m × 64m, smallest bake unit)
- **Core pipeline integration:** Houdini Engine as the procedural processing backbone, exchanging data with the proprietary game engine via Python scripts.
- **Inputs to Houdini:** heightmaps, 2D terrain masks, biome painter data, splines/shapes, Houdini geometry from other tools.
- **Outputs from Houdini:** entity point clouds, terrain texture layers, terrain heightmap layers, 2D terrain data, geometry, terrain logic zones.
- **Nightly rebuild:** The *entire game world* is regenerated every night on dedicated build machines. Determinism is mandatory — same inputs produce identical outputs.
- **Tool ecosystem:** Not a single monolithic tool but a chain: terraforming → freshwater definition → cliff generation tool (steep terrain) → biome painter → procedural vegetation generation → points of interest.
- **Biome recipes:** Rule sets that react to physical terrain features (altitude, slope, proximity to water, cliff distance) to determine entity placement.

Source: [GDC 2018 Notes: Procedural World Generation of Far Cry 5](https://tools.engineer/gdc2018-procedural-world-generation-of-far-cry-5)

---

## 2. Heightmap Generation: Noise, Erosion, and Resolution Standards

### 2.1 Standard Noise Functions for AAA Terrain

**Fractal Brownian Motion (fBm)** is the baseline. Standard parameters:
- **Octaves:** 4–8 (more octaves = more detail, diminishing returns above 8)
- **Persistence:** 0.5 (amplitude multiplier per octave; lower = smoother high frequencies)
- **Lacunarity:** 2.0 (frequency multiplier per octave; 2.0 means each octave is twice the frequency)
- **Normalization:** Always normalize by dividing by `maxAmplitude` (sum of all octave amplitudes) to keep output in [-1, 1] regardless of parameters.

**Domain-Warped fBm** is the AAA standard for organic terrain:
```python
# Two separate fBm offsets warp the coordinate space before sampling main fBm
warp_x = fbm(x * 0.5, y * 0.5) * warp_strength
warp_y = fbm(x * 0.5 + 100, y * 0.5 + 100) * warp_strength
height = fbm(x + warp_x, y + warp_y, octaves, persistence, lacunarity)
```
`warp_strength` controls deformation intensity (low = subtle organic flow; high = twisted, tectonically deformed appearance). `No Man's Sky` uses domain warping as the core of its "uber noise" function. Without domain warping, fBm terrain has a recognizable synthetic quality with no directional geological structure.

**Ridge Noise / Ridged Multifractal** for mountain ridges:
```python
# Apply absolute value and invert each octave before combining
layer = abs(coherent_noise(x * frequency, y * frequency))
layer = 1.0 - layer  # invert: valleys become flat, peaks become sharp ridges
```
The `offset` parameter controls peak sharpness. This transforms smooth hills into sharp ridgelines with flattened valleys. Critical for mountain terrain.

**Voronoi Noise** for rocky/cellular features, crack patterns, canyon systems. Not typically used as the primary height generator; used in combination with fBm for feature variation.

**What noise alone cannot produce:** Real erosion fractal patterns. Even 8 octaves of domain-warped fBm lacks the directional structure of real geology (ridge lines, drainage networks, sediment deposits). These patterns only emerge from physical simulation.

Sources:
- [Dandrino: Terrain Erosion 3 Ways](https://github.com/dandrino/terrain-erosion-3-ways)
- [Mountains of Madness: Interactive Terrain Algorithms](https://amanpriyanshu.github.io/The-Mountains-of-Madness/)
- [Cinevva Landscape Generation Guide](https://app.cinevva.com/guides/landscape-generation-browser)

### 2.2 Erosion Algorithms

#### Particle-Based Hydraulic Erosion (Industry Standard for Detail)
Each simulated raindrop particle flows downhill following the heightmap gradient, erodes material based on velocity and slope, carries sediment, and deposits when velocity drops. The emergent effect after 200,000–500,000 particles:
- Carved valleys and river channels
- Ridgelines sharpened by water runoff
- Alluvial fans at the base of slopes
- Sediment deposits in flat areas

**Implementation parameters (Sebastian Lague's reference implementation):**
- Particle inertia (how much particle continues in prior direction vs. gradient direction)
- Erosion radius (area of heightmap affected per particle step)
- Sediment capacity factor (max sediment carried relative to velocity × slope)
- Deposition rate, evaporation rate, erosion rate, min slope

**Scalability:** This is inherently sequential per particle, which limits GPU parallelism. The standard approach is to run 200k–500k particles total.

#### Pipe-Based (Grid-Based) Hydraulic Erosion
Models water as a layer sitting on each cell, flowing to neighbors via "pipes." Better for large-scale river formation; less effective for fine channel detail. More GPU-parallelizable than particle methods.

#### Thermal Erosion (Talus Formation)
For each grid cell pair, compare height difference to neighbors. If the slope exceeds the material's *angle of repose* (talus angle), move material from the high cell to the low cell. Converges in 50–100 iterations.

**Talus angle typical values:**
- Loose sand: ~30–34°
- Gravel/scree: ~35–40°  
- Fractured rock debris: ~40–45°

Thermal erosion alone: softens sharp peaks, builds scree slopes. Always apply *before* hydraulic erosion so hydraulic can carve into realistically collapsed material.

#### Wind Erosion (Aeolian)
Particle-based, analogous to hydraulic. Particles spawn at terrain boundaries, move in wind direction, abrade the terrain (converting height to suspended sediment), and deposit sediment when velocity drops. Creates:
- Barchan (crescent) dunes
- Deflation hollows (windward erosion)
- Sediment accumulation on leeward slopes
- Yardangs (wind-carved ridges aligned with prevailing wind)

Implementation notes from Nick McDonald's blog:
- Spawn particles at terrain *boundary* (important — not random interior positions)
- Time-deferred cascading: material that exceeds angle of repose cascades before next particle step
- Thermal erosion is trivially implementable as a degenerate wind erosion case (abrasive force only, no directional motion)

#### Production Multi-Pass Erosion Order
This is the canonical production sequence (derived from Gaea documentation):

```
Pass 1 — Thermal Erosion
  • Softens initial sharp noise peaks
  • Builds realistic scree/talus slopes
  • Prepares terrain for hydraulic flow

Pass 2 — Hydraulic Erosion, Pass A (Structure-Building)
  • Selective processing: altitude-based
  • High duration (30%), creates initial flow channels
  • Establishes the primary drainage hierarchy

Pass 3 — Hydraulic Erosion, Pass B (Deepening)
  • 100% Downcutting, 100% Base Level
  • Deepens channels everywhere (not selective)
  • Produces strong flow structures globally

Pass 4 — Hydraulic Erosion, Pass C (Refinement)
  • Default settings
  • Homogenizes texture, preserves large-scale features
  • Optional: higher Inhibition value adds more sediment deposits at base

Pass 5 — Wind Erosion (optional, for arid/desert biomes)
  • Apply after hydraulic to form dunes in dry flat areas
  • Saltation process deposits where wind decelerates

Pass 6 — Debris/Scree Simulation (optional)
  • Physics-based rock fragment scattering
  • Applied post-hydraulic to add loose material at cliff bases
```

**Output masks to preserve from erosion:** `flow`, `sediment`, `debris`, `wear`. These become the basis for the terrain splat map (flow → wet/muddy zones; wear → bare rock; deposits/sediment → sandy/silty areas).

Sources:
- [Gaea Erosion Multi-Pass Guide](https://docs.quadspinner.com/Guide/Using-Gaea/Erosion.html)
- [Nick McDonald: Particle Wind Erosion](https://nickmcd.me/2020/11/23/particle-based-wind-erosion/)
- [Nick McDonald: 3D Multi-Layer Terrain and Erosion](https://nickmcd.me/2022/04/15/soilmachine/)
- [Cinevva: Sebastian Lague Hydraulic Erosion](https://app.cinevva.com/guides/landscape-generation-browser)

### 2.3 DEM Resolution Standards for 1km² Game Tiles

| Resolution | Pixel Spacing | Use Case |
|---|---|---|
| 1m | 1 m/pixel | AAA close-detail terrain; maximum practical for games |
| 2m | 2 m/pixel | Standard console terrain tile resolution |
| 5m | 5 m/pixel | Minimum acceptable for believable terrain per UDK docs |
| 10m | 10 m/pixel | Too low for playable areas; "essentially useless" for game detail |
| 30m | 30 m/pixel | ~1 km per 30 texels; only for background/distant terrain |

For a 1km² tile at 1m/pixel resolution: **1024×1024 heightmap** (or 1025×1025 for power-of-two-plus-one terrain mesh compatibility in UE5).

**Engine recommendation (UE5):** Maximum landscape resolution of 8129×8129 at 1m/pixel = ~8.1km² map. For larger worlds, reduce to 2m or 5m per pixel with tiling.

**Precision requirement:** Use **16-bit** heightmaps minimum (65,536 discrete elevation values). For terrain with subtle slopes or large elevation ranges, 16-bit can produce visible stairstepping — normalize output to use the full 0–65535 range, or use 32-bit float (EXR) internally.

Sources:
- [Unreal Engine: Terrains from DEMs](https://docs.unrealengine.com/udk/Three/TerrainsFromDEMs.html)
- [TerraformPro: Resolution & Dimensions](https://terraformpro.com/docs/dtm-resolution)
- [Gaea: Fix Stairstepping](https://docs.quadspinner.com/Guide/Appendix/Fix-Stairstep.html)

### 2.4 Step-by-Step Procedural Generation Order for AAA Results

The following sequence is the synthesis of World Machine, Gaea, and Houdini best practices:

```
Step 1: MACRO SHAPING (Low Resolution, e.g. 512×512)
  Input:  seed, world parameters
  Process: Tectonic layout / continental gradient + low-frequency Voronoi 
           for mountain range placement + Layout/painting for art direction
  Output: Macro heightfield establishing continent/ocean, mountain ranges, plains

Step 2: SEEDING
  Input:  Macro heightfield
  Process: Add domain-warped fBm at medium frequency as micro-disturbances
           (not decorative — required for realistic erosion behavior)
  Output: Slightly disturbed heightfield with erosion obstacles

Step 3: LOBING / FIRST EROSION PASS
  Input:  Seeded heightfield
  Process: High-intensity erosion (high precipitation, high cut angle) to
           break mountain masses into distinct lobes/sub-ranges
  Output: Segmented mountain forms with initial drainage structure

Step 4: ELEVATION COMPRESSION + LAYER STACKING
  Input:  Lobed heightfield
  Process: Remap/compress vertical range, then add new mid-frequency mass 
           on top (foothills, plateaus). Repeat step 2-3 at this scale.
  Output: Multi-scale elevation hierarchy (macro mountains, mid hills, foothills)

Step 5: UPSAMPLING
  Input:  Multi-scale heightfield at low resolution
  Process: Resample to working resolution (e.g. 2048×2048)
  Output: Higher-resolution heightfield ready for detail passes

Step 6: THERMAL EROSION (Pre-Hydraulic)
  Input:  Upsampled heightfield
  Process: 50–100 thermal iterations at talus angle (35–40°)
  Output: Softened peaks, scree slopes, collapsed material at cliff bases

Step 7: HYDRAULIC EROSION — MULTI-PASS (3 passes minimum)
  Input:  Thermally eroded heightfield
  Pass A: Structure-building (altitude-selective, 30% duration)
  Pass B: Channel deepening (100% downcutting)
  Pass C: Refinement (default settings)
  Output: Eroded heightfield + flow mask + sediment mask + wear mask

Step 8: HYDROLOGY
  Input:  Eroded heightfield + flow accumulation from erosion
  Process: River channel extraction (Strahler ordering), lake basin filling,
           channel carving proportional to drainage area
  Output: Updated heightfield with carved river channels + water body masks
          + river width map (from drainage basin size)

Step 9: WIND EROSION (optional, biome-dependent)
  Input:  Hydraulically eroded heightfield (dry/flat zones only)
  Process: Aeolian particle erosion in prevailing wind direction
  Output: Dune features, deflation hollows, wind-carved yardangs

Step 10: DEBRIS / SCREE (optional)
  Input:  Final eroded heightfield
  Process: Physics-based fragment deposition at cliff bases
  Output: Rock debris deposits, loose material slopes

Step 11: BIOME CLASSIFICATION
  Input:  Final heightfield + temperature map + moisture map (includes
          river/lake influence) + slope mask + flow mask
  Process: Combine temperature, moisture, altitude to classify biome per cell.
           Use smooth blending weights at biome boundaries (NOT hard cutoffs).
  Output: Biome ID map + blend weights + per-biome sub-type mask

Step 12: SPLAT MAP GENERATION
  Input:  Heightfield + slope mask + altitude + erosion masks (flow, wear, sediment)
  Process: 
    - Slope-based: grass (<0.3 rad), rock (0.2–0.5 rad), cliff (>0.5 rad)
    - Altitude-based: sand near sea level, grass at mid-altitude, snow above treeline
    - Erosion-based: flow → wet/muddy, wear → bare rock, sediment/deposit → silty sand
    - Blend using smoothstep() at all boundaries (never hard threshold)
  Output: 4-channel RGBA splat map (up to 4 base materials per pixel)
          Additional layers for rock, snow, cliff face materials

Step 13: VEGETATION DENSITY MAPS
  Input:  Biome map + slope + altitude + flow + splat map
  Process: Per-species density field: multiply slope fitness × altitude fitness × 
           moisture fitness × sunlight fitness (slope-derived shadow estimate)
  Output: Per-species density map at 2m resolution (grass) or 4m resolution (trees)

Step 14: TILING / CHUNKING
  Input:  All output layers (heightfield, splat, density maps)
  Process: Slice into tiles with 1-vertex overlap on all edges.
           Export neighbor rows/columns for normal computation.
  Output: Per-tile packages (heightfield + splat + density + normal maps)

Step 15: EXPORT
  Input:  Per-tile packages
  Process: 
    - Heightfield: 16-bit PNG or R16 raw, normalized to full range
    - Splat: 8-bit RGBA PNG or DXT5 compressed
    - Normal map: Generated from heightfield with 1-texel border sampling
    - Density maps: 8-bit per channel
    - Metadata: tile coordinates, world origin, height scale, units per pixel
  Output: Engine-ready terrain packages
```

---

## 3. Tile and Chunk Architecture

### 3.1 Seam Handling Without Visible Popping

**Root cause of seams:** Normal vectors at tile edges are computed only from vertices *within* that tile, ignoring the neighboring tile's geometry. This produces a discontinuous normal at the boundary, creating a visible lighting seam even when the heightfield is geometrically continuous.

**Standard fix:** Generate heightfield data with a 1-texel *border* extending beyond the tile boundaries. Compute normals from this extended buffer, then discard the border. Adjacent tiles now compute normals using the same source heights for edge vertices.

```python
# Generate heightfield for interior (0..N-1) but sample border (−1..N)
for x in range(-1, tile_size + 1):
    for y in range(-1, tile_size + 1):
        positions[x][y] = compute_height(world_x + x, world_y + y)

# Compute normals using full extent (includes border)
for x in range(0, tile_size):
    for y in range(0, tile_size):
        normal = compute_normal_from_neighbors(positions, x, y)
        # Correct because positions[-1], positions[N] etc. are available
```

**Runtime normal seams (Terrain3D case study):** When using `texture()` with `filter_linear` in fragment shaders to read height for normal computation, the GPU interpolates across region/tile boundaries incorrectly. Fix: switch to `texelFetch()` at boundary pixels and do manual interpolation, OR use vertex-height reads (which correctly handle boundaries) rather than fragment-height reads.

**Geometry seams between different LOD tiles:** Use CDLOD geomorphing (see §3.3) or the geometry clipmap transition region approach. Both prevent T-junctions by smoothly morphing vertices rather than stitching.

**Edge caching for chunk-based generation:**
```python
# Cache this chunk's back edge for the next chunk to use as its front edge
edge_cache[chunk_id] = heights[tile_size - 1][:]  # back row

# Next chunk reads front edge from cache, not from re-sampling
if cached_front_edge:
    heights[0][:] = cached_front_edge
    # Only apply detail noise to interior — NOT edge rows
```

Sources:
- [Seamless Heightmaps: Normals at Boundaries](https://jimknopf.bitbucket.io/layercake/tutorial/heightmaps/)
- [Terrain3D: Normal Artifact Along Region Boundaries](https://github.com/TokisanGames/Terrain3D/issues/185)
- [GameDev StackExchange: Seam-Free Tile Normals](https://gamedev.stackexchange.com/questions/112206/removing-seams-between-procedurally-generated-spherical-terrain-tiles)

### 3.2 Standard Chunk Sizes for Open-World Streaming

| Platform | Cell Size | Streaming Radius | Notes |
|---|---|---|---|
| Mobile | 64–128m | 2–3× cell size | Tight memory budget |
| Switch | 128m | 256–384m | 1–1.5 GB RAM budget |
| Base consoles (PS4/XB1) | 256m | 512m | 2–3 GB streaming budget |
| Current-gen (PS5/XSX) | 256–512m | 512m–1km | 4–6 GB streaming budget |
| PC | 512m+ | 1–2km | Scales with VRAM |

**UE5 World Partition:** Divides level into streaming cells. For dense environments: 64m cells. For most open worlds: 128m cells. For sparse wilderness: 256m cells. Cell size should be *at least 2× loading range* so cells are fully loaded before the player reaches them. For fast movement (vehicles, flying): 3–4× cell size.

**Far Cry 5 hierarchy:** Map (streaming boundary) → Section (256m × 256m) → Sector (64m × 64m, smallest bake unit). Terrain sections at 256m squares with 64m granularity for procedural content.

**Horizon Zero Dawn:** Trees placed in 128×128m blocks; grass in 32×32m blocks. Density maps are always 64×64 per block regardless of block size.

Sources:
- [UE5 World Partition Deep Dive](https://www.strayspark.studio/blog/ue5-world-partition-deep-dive-streaming-hlod)
- [Practical Open World Streaming](https://www.slashskill.com/practical-open-world-streaming-approaches-for-all-platforms/)
- [UE5 Landscape Tiling (unrealcode.net)](https://www.unrealcode.net/NaniteLandscapeMaterials5/)

### 3.3 LOD Transition Techniques

#### CDLOD (Continuous Distance-Dependent Level of Detail) — Current Industry Standard
Filip Strugar's 2010 paper. Uses a **quadtree of regular grids** rather than nested rings. LOD selection is based on precise 3D distance from observer to terrain (not 2D distance, which fails at altitude).

**Key mechanism — Geomorphing vertex shader:**
```glsl
// Morph factor: 0 at far end of transition zone, 1 at near end
float morphFactor = smoothstep(lodNear, lodFar, distanceToCamera);
// Blend between fine LOD height and coarse LOD height
float morphedHeight = mix(fineLodHeight, coarseLodHeight, morphFactor);
```

Every vertex morphs individually (not per-chunk/per-node). Each node supports transition between its own LOD and the next larger (coarser) LOD. Result: no stitching meshes, no T-junctions, no visible popping.

**Benefits over geometry clipmaps:**
- Handles altitude correctly (clipmaps don't consider viewer height)
- Cleaner transitions (per-vertex rather than per-node)
- Simpler integration with other game LOD systems

#### Geometry Clipmaps (Still Widely Used)
Nested concentric rings, coarser outward. Standard configuration: n=255, 8 levels. At 1024×768 viewport, triangles are ~5 pixels wide (uniform screen-space size). Transition zone: outer 20% of each ring blends to the next coarser level. Performance: ~87 fps for a 20-billion-sample US terrain grid in 355 MB RAM (circa 2004 hardware).

Limitation: Does not account for viewer altitude — LOD appears too detailed when flying high above terrain, or too coarse in steep valleys.

#### Nanite (UE5) — Virtual Geometry
Nanite breaks meshes into **~128-triangle clusters**, groups clusters into pages, and streams only the pages visible on screen. LOD selection is per-cluster based on **projected screen-space error** (not distance buckets). Key CVars: `r.Nanite.MaxPixelsPerEdge` (controls LOD threshold), `r.Nanite.Streaming.NumInitialRootPages`.

For terrain + Nanite: Nanite handles per-mesh LOD automatically; HLOD handles draw-call merging for entire streaming cells at distance. Use `r.Nanite.MaxPixelsPerEdge` to tune quality vs. performance.

#### HLOD (Hierarchical LOD) with World Partition
When streaming cells are distant: HLOD generates merged, simplified geometry representing the entire cell. For Nanite-enabled content, HLOD focuses on *instance merging* (reducing draw calls) rather than mesh simplification (Nanite already handles that per-cluster).

Sources:
- [CDLOD Paper (Filip Strugar, 2010)](https://aggrobird.com/files/cdlod_latest.pdf)
- [NVIDIA GPU Gems 2: Geometry Clipmaps](https://developer.nvidia.com/gpugems/GPUGems2/gpugems2_chapter02.html)
- [Nanite Streaming and Memory Budgets](https://medium.com/@GroundZer0/nanite-streaming-and-memory-budgets-managing-geometry-at-scale-4c54bfa5d5b1)
- [UE5 World Partition HLOD Deep Dive](https://www.strayspark.studio/blog/ue5-world-partition-deep-dive-streaming-hlod)

---

## 4. Production Generation Checklist: Noise Seed to Engine Export

This is the definitive ordered checklist for a production terrain generator. Each step specifies what it **consumes** and **produces**.

---

### PHASE 0 — Configuration
- [ ] **0.1 Seed and parameters committed to metadata**
  - Consumes: user-specified world config (seed, world size km², climate preset, biome list, target engine)
  - Produces: immutable metadata file (`world_config.json`) for deterministic reproduction

---

### PHASE 1 — Macro Shape
- [ ] **1.1 Tectonic / Continental Layout**
  - Consumes: seed, world size
  - Produces: 512×512 macro heightfield (mountain ranges, ocean basins, plains regions)
  - Method: Low-frequency Voronoi + gradient shaping, or tectonic plate simulation

- [ ] **1.2 Climate Map Generation**
  - Consumes: macro heightfield, latitude gradient
  - Produces: 512×512 temperature map, 512×512 base moisture map
  - Method: Equatorial warm → polar cold gradient; altitude cooling (lapse rate ~6.5°C/1000m)

---

### PHASE 2 — Noise Base
- [ ] **2.1 Domain-Warped fBm**
  - Consumes: macro heightfield, seed
  - Produces: working heightfield at intermediate resolution (1024×1024)
  - Method: fBm (6–8 octaves, persistence 0.5, lacunarity 2.0) + domain warp (warp_strength 0.5–2.0)
  - Ridge noise variant: apply abs() + invert per octave for mountain ridgelines

- [ ] **2.2 Seeding (Disturbance)**
  - Consumes: working heightfield
  - Produces: disturbed heightfield with micro-obstacles
  - Method: Medium-frequency noise disturbance via Heightfield Distort by Noise

---

### PHASE 3 — Erosion
- [ ] **3.1 Thermal Erosion (Pre-Hydraulic)**
  - Consumes: disturbed heightfield
  - Produces: softened heightfield, scree slopes at cliff bases
  - Parameters: 50–100 iterations, talus angle 35–40°

- [ ] **3.2 Hydraulic Erosion Pass A — Structure**
  - Consumes: thermal-eroded heightfield
  - Produces: primary drainage channels, initial ridgeline sharpening
  - Parameters: altitude-selective processing, ~30% duration, moderate precipitation
  - Particle count: 200,000–500,000 droplets

- [ ] **3.3 Hydraulic Erosion Pass B — Deepening**
  - Consumes: Pass A heightfield
  - Produces: deepened channels, stronger drainage hierarchy
  - Parameters: 100% downcutting, 100% base level

- [ ] **3.4 Hydraulic Erosion Pass C — Refinement**
  - Consumes: Pass B heightfield
  - Produces: final eroded heightfield + **flow mask** + **sediment mask** + **wear mask**
  - Parameters: default settings; optionally higher Inhibition for more sediment deposits

- [ ] **3.5 Wind Erosion (biome-conditional: arid/desert only)**
  - Consumes: Post-hydraulic heightfield in dry zones
  - Produces: dune features, deflation hollows + **wind deposit mask**

- [ ] **3.6 Upsampling to Full Resolution**
  - Consumes: 1024×1024 eroded heightfield
  - Produces: 2048×2048 (or 4096×4096) heightfield
  - Method: Bicubic upsampling; follow with re-seeding + one final lightweight erosion pass

---

### PHASE 4 — Hydrology
- [ ] **4.1 Flow Accumulation**
  - Consumes: final heightfield
  - Produces: flow accumulation grid (each cell = total upstream drainage area)
  - Method: D8 (8-direction) or D-infinity flow routing

- [ ] **4.2 River Network Extraction**
  - Consumes: flow accumulation grid
  - Produces: river centerline splines with Strahler order values
  - Method: Threshold flow accumulation → extract channels → Strahler ordering (confluences of equal-order streams increase order); river width ∝ drainage area^0.5

- [ ] **4.3 Channel Carving**
  - Consumes: heightfield + river splines + river width map
  - Produces: updated heightfield with carved river beds
  - Method: Dig channels to minimum depth; smooth banks with distance falloff

- [ ] **4.4 Lake Basin Filling**
  - Consumes: updated heightfield
  - Produces: water body mask, updated heightfield with flat lake surfaces
  - Method: Fill local minima above sea level to their spill point

---

### PHASE 5 — Classification
- [ ] **5.1 Biome Classification**
  - Consumes: heightfield + temperature + moisture (with river/lake influence added) + slope mask
  - Produces: biome ID map + smooth blend weights (NOT hard boundaries)
  - Method: Whittaker biome chart lookup; smooth blending at transitions via smoothstep weights; sub-biome variation using additional noise layer

- [ ] **5.2 Slope and Aspect Masks**
  - Consumes: heightfield
  - Produces: slope angle map (radians), aspect map (cardinal direction of downslope face)
  - Method: Sobel filter (3×3 kernel) on heightfield with correct texel spacing

- [ ] **5.3 Altitude Band Masks**
  - Consumes: heightfield
  - Produces: sea level zone, low zone, mid zone, high zone, snow zone masks (all smoothstep-blended)

---

### PHASE 6 — Material / Splat Map
- [ ] **6.1 Splat Map Generation**
  - Consumes: slope mask + altitude masks + biome map + erosion masks (flow, wear, sediment)
  - Produces: 4-channel RGBA splat map (blend weights for base materials)
  - Rules:
    - flat + low altitude → grass/soil
    - steep slope (>0.3 rad) → rock
    - very steep (>0.5 rad) → cliff face material
    - high altitude + slope → snow with rock blend
    - flow mask → wet/mud layer
    - wear mask → bare rock
    - sediment mask → sand/silt
  - All boundaries: smoothstep blended (20–50m transition width)

- [ ] **6.2 Normal Map Generation**
  - Consumes: heightfield with 1-texel border overlap from neighboring tiles
  - Produces: world-space normal map (RG = XY derivatives, B = Z)
  - Method: Sobel filter using cross-tile border heights; do NOT compute normals from mesh vertices without neighbor data

---

### PHASE 7 — Vegetation / Scatter
- [ ] **7.1 Per-Species Density Maps**
  - Consumes: biome map + slope + altitude + moisture + flow + sunlight estimate (from slope/aspect)
  - Produces: per-species density maps (2m resolution for grass, 4m for trees)
  - Method: Multiply fitness factors: slope_fitness × altitude_fitness × moisture_fitness × light_fitness
  - CDPR-style: simulate water accumulation + solar exposure → place species matching their biological light requirements

- [ ] **7.2 Point Cloud Generation (offline)**
  - Consumes: density maps
  - Produces: positioned + oriented scatter points per species/asset type
  - Method: Poisson disk sampling weighted by density map, OR blue noise filtered by density threshold
  - Minimum separation: asset radius × 2 (prevents overlap)

---

### PHASE 8 — Tiling and Export
- [ ] **8.1 Tile Slicing with Border**
  - Consumes: all output layers at full resolution
  - Produces: per-tile heightfield slices with 1-texel border for seam-free normals
  - Tile size: 256m × 256m (standard) with 1025×1025 vertex grid (UE5 compatible)

- [ ] **8.2 Per-Tile Normal Map Bake**
  - Consumes: per-tile heightfield slice (including border)
  - Produces: per-tile normal map (no seams, because border heights from neighbors are used)

- [ ] **8.3 Heightfield Normalization**
  - Consumes: per-tile heightfield (raw float)
  - Produces: 16-bit PNG normalized to full 0–65535 range + metadata with height_scale value
  - Critical: normalize to full range, NOT to arbitrary max. Prevents stairstepping artifacts.

- [ ] **8.4 Splat Map Export**
  - Consumes: per-tile splat map
  - Produces: 8-bit RGBA PNG; for UE5 use DXT5/BC3 compression

- [ ] **8.5 Metadata Package**
  - Consumes: all per-tile outputs
  - Produces: per-tile JSON (tile XY index, world origin, tile size meters, height_scale, units_per_pixel, biome IDs present, river count)

- [ ] **8.6 Determinism Verification**
  - Produces: SHA256 hash of heightfield output for the same seed
  - Requirement: identical seed + parameters → identical output (same as Far Cry 5 nightly rebuild requirement)

---

## 5. Known Failure Modes and Artifact Causes

### 5.1 Repeated Tiling / Pattern Fatigue

**Cause:** A single texture tile repeating at predictable intervals across large terrain. The pattern becomes subconsciously recognizable at ~3–4 repetitions, especially visible in specular highlights and normal map lighting.

**Symptoms:** Regular diamond or grid pattern visible in terrain materials. Distinctive rock formation or grass cluster appearing every N meters.

**Fixes (in order of effectiveness):**
1. **Hex Grid Tiling:** Procedurally generate a grid of hexagons; each hex gets randomly offset, rotated, and scaled UVs. Requires 9 texture samples per layer (expensive but most effective). Source: Unity Shader Graph Terrain Sample.
2. **Rotation Tiling:** Sample texture twice; second sample is rotated 90° and blended using a large mask. Requires 2× samples per layer.
3. **Stochastic Texture Bombing:** Per-cell random UV offset + rotation + scale. Used in terrain materials for ground cover.
4. **Triplanar Mapping:** Project texture along all three world axes weighted by surface normal. Eliminates UV-based repetition on steep surfaces. Must-have for cliff faces.
5. **Detail texture overlay:** Blend a high-frequency tiling detail texture (e.g., ground pebbles, soil micro-detail) that breaks up the main pattern at close range.

Source: [Unity Shader Graph Terrain Sample: Problems and Solutions](https://docs.unity3d.com/Packages/com.unity.shadergraph@17.5/manual/Shader-Graph-Sample-Terrain-Solutions.html)

### 5.2 Faceted Normals / Lighting Seams

**Root cause A — Missing neighbor data at tile edges:** Normal computation at edge vertices only considers triangles within the tile. The resulting normal vector points "inward" relative to the correct slope, creating a lighting discontinuity at tile boundaries.

**Fix:** Generate heightfield with a 1-texel border extending into neighboring tiles. Compute normals from the extended data. The extra border row is discarded from the output mesh but not from the normal computation.

**Root cause B — Heightmap precision at tile edge in shader:** Fragment shader uses `texture()` with bilinear filtering to read height for dynamic normal computation. The GPU interpolation "bleeds" values incorrectly across region boundaries.

**Fix (Terrain3D solution):** Detect boundary pixels in the fragment shader (when UV mod region_size is near 0 or near region_size). For boundary pixels, switch from fragment-height reads to vertex-height reads (which correctly resolve boundaries). Switch back to fragment reads for interior pixels.

**Root cause C — Triangle orientation inconsistency (quad diagonal):** Heightmap quads triangulated with a single hard-coded diagonal direction produce a recognizable diamond/stripe artifact in lighting because the shared diagonal edge creates asymmetric lighting. 

**Fix A:** Choose the diagonal direction per quad based on which diagonal connects closer heights (adaptive triangulation). Reduces the artifact significantly for undulating terrain.

**Fix B (more robust):** Bake a normal texture from the heightfield offline (using Sobel or cross-gradient method). Sample this normal texture in the fragment shader instead of computing normals from vertex interpolation. Normals stored in textures are not affected by triangle diagonal orientation.

Sources:
- [GameDev StackExchange: Lighting Artifact on Dynamic Terrain Mesh](https://gamedev.stackexchange.com/questions/90177/what-is-the-cause-of-this-lighting-artifact-on-my-dynamic-terrain-mesh)
- [Terrain3D Issue #185: Normal Artifact at Region Boundaries](https://github.com/TokisanGames/Terrain3D/issues/185)
- [Seamless Heightmaps: Boundary Normals](https://jimknopf.bitbucket.io/layercake/tutorial/heightmaps/)

### 5.3 Contour Banding (Stairstepping)

**Cause:** Heightfield stored at insufficient precision relative to the terrain's height range. With a 16-bit heightfield (65,536 values) and a 2500m height range, each step represents ~3.8cm. Gradual slopes below this threshold round to the same integer value, creating flat bands at regular height intervals (contour lines made visible).

**Triggering conditions:**
- 16-bit heightfield with tall terrain (>1000m range)
- Terrain using only a fraction of the 0–65535 value range (e.g., if max terrain height is 200m in a 2500m-range heightfield, only ~5% of precision is used → each step = ~76cm)
- 8-bit intermediate buffers in the generation pipeline

**Fixes:**
1. **Normalize output to full 16-bit range:** Before export, remap heightfield so the minimum elevation → 0 and maximum elevation → 65535. Store the height_scale multiplier in metadata. Prevents wasted precision. (Gaea Build Manager: Output Range = Normalized)
2. **Use 32-bit float (EXR/R32F) internally** during generation; only convert to 16-bit for the final engine export.
3. **Engine-side:** Verify the engine imports the heightfield with the correct height_scale factor to restore proper proportions.

**Related artifact — Sobel filter banding on normal maps:** When computing normals from a low-precision heightfield using a Sobel operator, the discrete height levels produce quantized gradient values → visible bands in the normal map → banding in specular lighting. Fix: compute normals from the 32-bit float heightfield *before* quantizing to 16-bit for export.

Sources:
- [Gaea: Fix Stairstepping](https://docs.quadspinner.com/Guide/Appendix/Fix-Stairstep.html)
- [Three.js Forum: Terrain Height Map Banding](https://discourse.threejs.org/t/terrain-height-map-banding/53849)
- [StackOverflow: Normalmap Generation Banding in GLSL](https://stackoverflow.com/questions/30349413/normalmap-generation-from-heightmap-in-glsl-shader)

### 5.4 LOD Popping

**Cause:** Discrete vertex count change when a terrain mesh switches from one LOD level to another. Vertices snap from their high-LOD positions to interpolated low-LOD positions in a single frame.

**Fixes:**
1. **CDLOD geomorphing:** Blend each vertex's position between LOD levels based on camera distance. The transition is spread over a distance range (the "morph zone"), making the change sub-pixel across multiple frames.
2. **Geometry clipmap transition bands:** The outer 20% of each clipmap ring is a transition zone where elevation values blend between fine and coarse levels.
3. **HLOD crossfade:** Keep the HLOD mesh visible until the high-detail mesh is fully loaded; then alpha-crossfade between them (dither-based or alpha blend). Never abruptly swap.

### 5.5 Missing Geological Structure ("Noise Terrain" Look)

**Cause:** Terrain generated with noise functions (even complex domain-warped fBm) without erosion simulation. Noise terrain lacks:
- Directional ridge lines aligned with erosion flow
- Drainage networks (rivers flowing from high ground to low)
- V-shaped valley cross-sections (hydraulic erosion)
- Talus/scree at cliff bases (thermal erosion)
- Alluvial fans at slope transitions
- Sediment deposits in flat areas

**Symptom:** Terrain looks like a bumpy noise field regardless of resolution. No sense of geological history.

**Fix:** The noise base is merely the starting material. Erosion simulation is non-negotiable for AAA-quality terrain. Minimum viable erosion: thermal (50 iterations) + hydraulic particle erosion (200,000+ particles). The visual difference between eroded and uneroded terrain is immediately apparent and cannot be compensated by texture quality.

### 5.6 Biome Hard Edges

**Cause:** Biome classification using hard thresholds (e.g., temperature > 15°C = forest, ≤ 15°C = tundra). Creates visible straight-line transitions between biomes that match no natural phenomenon.

**Fix:** Use smooth blending weights based on distance from threshold values:
```python
# Temperature range [10, 20] transitions between tundra and forest
forest_weight = smoothstep(10.0, 20.0, temperature)
tundra_weight = 1.0 - forest_weight

# Sub-biome variation adds noise to prevent straight transition lines
forest_weight += fbm(x * 0.01, y * 0.01) * 0.2  # ±10% variation
```
Atherion world gen uses explicit smooth blending weights at biome boundaries.

### 5.7 Vegetation Density Field Disconnect from Terrain

**Cause:** Vegetation placed by a simple noise-based density field with no connection to the actual terrain heightfield, erosion masks, or moisture simulation. Result: trees on cliff faces, vegetation in active river channels, grass at alpine altitudes, no vegetation variation that matches terrain micro-features.

**Fix (CDPR approach):** Vegetation placement must consume at minimum: slope mask (exclude >30° slopes for most species), altitude mask (species-appropriate altitude ranges), water accumulation simulation (moisture-loving species follow flow paths), and sunlight estimate (north-facing slopes darker → different species mix). The density field is the *output* of these multi-factor fitness computations, not a standalone noise layer.

### 5.8 Normal Map Y-Channel Inversion (DX vs. GL Convention)

**Cause:** DirectX uses Y-up normal maps (green channel = up), OpenGL uses Y-down (green channel = down). Some generation tools export one convention; some engines expect the other. Mismatched convention: lighting appears inverted — convex surfaces look concave, creating artificial "seams" at tile boundaries due to reversed lighting directions on adjacent tiles.

**Fix:** In the export pipeline, know the target engine's convention and always flip the green channel if needed. Standard check: a sphere rendered with the normal map should show specular highlight on the *same* side as a direct lighting test.

Source: [AITEXTURED: Why Seams Are Visible](https://aitextured.com/articles/why_seams_are_visible_how_to_remove_tiling_and_how_to_invert_normals_in_pbr_textures.html)

---

## SOURCE REFERENCE LIST

| # | Title | URL |
|---|---|---|
| 1 | Houdini Terrain Workflow (SideFX) | https://www.sidefx.com/docs/houdini/model/terrain_workflow.html |
| 2 | HeightField Erode Node (SideFX) | https://www.sidefx.com/docs/houdini/nodes/sop/heightfield_erode.html |
| 3 | Gaea Simulations Overview | http://quadspinner.com/Gaea/Simulations |
| 4 | Gaea Erosion Documentation | https://docs.quadspinner.com/Guide/Using-Gaea/Erosion.html |
| 5 | Gaea Fix Stairstepping | https://docs.quadspinner.com/Guide/Appendix/Fix-Stairstep.html |
| 6 | World Machine Device Workspace | https://help.world-machine.com/topic/devices-and-the-device-workspace/ |
| 7 | World Machine File I/O | https://help.world-machine.com/topic/file-input-and-output/ |
| 8 | UE5.7 PCG Overview | https://dev.epicgames.com/documentation/unreal-engine/procedural-content-generation-overview |
| 9 | PCG Data Types Reference | https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-framework-data-types-reference-in-unreal-engine |
| 10 | GDC Vault: Landscape Creation in REDengine 3 (CDPR) | https://www.gdcvault.com/play/1020197/Landscape-Creation-and-Rendering-in |
| 11 | GPU-Based Procedural Placement in Horizon Zero Dawn | https://www.guerrilla-games.com/read/gpu-based-procedural-placement-in-horizon-zero-dawn |
| 12 | GDC 2018: Procedural World Gen Far Cry 5 (notes) | https://tools.engineer/gdc2018-procedural-world-generation-of-far-cry-5 |
| 13 | Far Cry 5 Terrain Rendering GDC 2018 | https://drive.google.com/file/d/1H6ouhi96pLg8WDlwXSGHFupPyZDv2MF6/view |
| 14 | CDLOD Paper — Filip Strugar 2010 | https://aggrobird.com/files/cdlod_latest.pdf |
| 15 | Geometry Clipmaps — GPU Gems 2 (NVIDIA) | https://developer.nvidia.com/gpugems/GPUGems2/gpugems2_chapter02.html |
| 16 | UE5 World Partition Deep Dive | https://www.strayspark.studio/blog/ue5-world-partition-deep-dive-streaming-hlod |
| 17 | Practical Open World Streaming | https://www.slashskill.com/practical-open-world-streaming-approaches-for-all-platforms/ |
| 18 | UE5 Landscape Tiling and World Partition | https://www.unrealcode.net/NaniteLandscapeMaterials5/ |
| 19 | Nanite Streaming and Memory Budgets | https://medium.com/@GroundZer0/nanite-streaming-and-memory-budgets-managing-geometry-at-scale-4c54bfa5d5b1 |
| 20 | Cinevva: Landscape Generation Browser | https://app.cinevva.com/guides/landscape-generation-browser |
| 21 | Dandrino: Terrain Erosion 3 Ways | https://github.com/dandrino/terrain-erosion-3-ways |
| 22 | Mountains of Madness: Terrain Algorithms | https://amanpriyanshu.github.io/The-Mountains-of-Madness/ |
| 23 | Nick McDonald: Particle Wind Erosion | https://nickmcd.me/2020/11/23/particle-based-wind-erosion/ |
| 24 | Nick McDonald: 3D Multi-Layer Terrain | https://nickmcd.me/2022/04/15/soilmachine/ |
| 25 | Terrain3D Issue #185: Normal Seams | https://github.com/TokisanGames/Terrain3D/issues/185 |
| 26 | GameDev SE: Lighting Artifact on Terrain | https://gamedev.stackexchange.com/questions/90177/what-is-the-cause-of-this-lighting-artifact-on-my-dynamic-terrain-mesh |
| 27 | GameDev SE: Tile Normal Seams | https://gamedev.stackexchange.com/questions/112206/removing-seams-between-procedurally-generated-spherical-terrain-tiles |
| 28 | Seamless Heightmap Normals | https://jimknopf.bitbucket.io/layercake/tutorial/heightmaps/ |
| 29 | Unity Shader Graph Terrain: Tiling Solutions | https://docs.unity3d.com/Packages/com.unity.shadergraph@17.5/manual/Shader-Graph-Sample-Terrain-Solutions.html |
| 30 | AITEXTURED: Seams, Tiling, Normal Inversion | https://aitextured.com/articles/why_seams_are_visible_how_to_remove_tiling_and_how_to_invert_normals_in_pbr_textures.html |
| 31 | UE Terrains from DEMs | https://docs.unrealengine.com/udk/Three/TerrainsFromDEMs.html |
| 32 | TerraformPro: DTM Resolution | https://terraformpro.com/docs/dtm-resolution |
| 33 | Atherion World Gen Pipeline | https://www.atherion-online.com/en/news/devlog-worldgen-pipeline |
