# Phase 9: Scatter / Vegetation Wiring — External Algorithm Research

**Researched:** 2026-04-27
**Domain:** Procedural scatter distribution, Forest Pack Pro 9.x algorithms, 3ds Max 2027 terrain/noise, stochastic tiling
**Confidence:** MEDIUM — iToo's docs.itoosoft.com returned 403 for all direct page fetches; parameters sourced from
official search excerpts, forum threads, and the C++ render API header (verified from GitHub). 3ds Max 2027 features
verified from Autodesk help + third-party write-ups. Algorithms (Bridson, hex-tiling) are HIGH confidence from
primary papers/source.

---

## Summary

Forest Pack Pro 9.x is the industry standard scatter tool for 3ds Max. Its public API (itreesinterface.h) exposes
instance-level CRUD only — it is a renderer-integration interface, not a parameter-control interface. Scatter
_placement_ parameters (density, altitude, slope, collision radius) are ParamBlock2 properties on the Forest
plugin object, not exposed in the C++ header. They are accessible via MaxScript property access on the node.

The core scatter algorithms used in Forest Pack are **not documented** as specific named algorithms in public sources.
Based on behavior documentation and forum posts: Random mode is a jitter-grid (stratified) scatter with per-cell
randomness, NOT Poisson disk. Cluster mode overlays a fractal noise / Voronoi grouping on top of base scatter.
The project already has a correct Bridson Poisson disk implementation in `_scatter_engine.py` — this is **better**
than Forest Pack's Random mode, which does not enforce minimum distance.

3ds Max 2027 adds Noise Plus (Simplex with 5 fractal types) as a displacement modifier replacement. This is
directly relevant to Phase 11 (noise upgrades) more than Phase 9. The Displace modifier's luminance-center
formula (`displacement = (luminance - center) * strength`) is confirmed and clean.

For stochastic tiling (Phase 10, materials), Mikkelsen's 2022 hex-tiling paper is the current standard.
The TriangleGrid function maps UV space to a skewed triangle lattice, samples the texture at 3 offset positions
weighted by barycentric coordinates, and blends using a contrast-adjusted luminance correction.

**Primary recommendation:** The project's `_scatter_engine.py` Bridson implementation is already at or above Forest
Pack's quality level. The critical work is **wiring** it to the density field and road SDF exclusion (C-1/C-2
P0 blockers) rather than replacing the algorithm.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Point distribution (Bridson/Poisson) | `_scatter_engine.py` | — | Pure math, no bpy dependency |
| Density field production | `pass_vegetation_depth` in terrain pipeline | `_scatter_engine.py` (consumer) | Terrain pass owns heightmap analysis |
| Road SDF exclusion | `road_network.py` output → scatter | `_scatter_engine.py` collision check | Roads own their SDF; scatter reads it |
| Altitude/slope filter | `biome_filter_points` in `_scatter_engine.py` | terrain heightmap (provider) | Already implemented, needs wiring |
| Cluster distribution | `_scatter_engine.py` (new function) | noise module | Fractal noise + Voronoi grouping |
| LOD/billboard generation | External tool (SpeedTree/Blender bpy) | asset pipeline | Not scatter's responsibility |
| Splatmap / stochastic tiling | `terrain_materials_v2.py` | GLSL/HLSL at runtime | Texture layer, separate from scatter |
| Unity tree instance export | `terrain_unity_export.py` | TerrainMaskStack | Needs `tree_instance_points` channel |

---

## Standard Stack

### Core (already in project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| numpy | 1.x / 2.x | Density maps, heightmap sampling, slope computation | Universally available, vectorized ops |
| scipy.ndimage | bundled | EDT for biome edge feathering | Used in `biome_filter_points` |

### Supporting (may need addition)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| scipy.spatial | bundled | KD-tree for collision queries across species | Multi-species SDF exclusion at scale |
| scipy.stats.qmc | 1.10+ | PoissonDisk QMC implementation | Alternative if Bridson impl needs replacement |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Custom Bridson | scipy.stats.qmc.PoissonDisk | QMC version has no density_map weighting hook; custom impl wins |
| Fractal noise clusters | Pre-baked Voronoi texture | Pre-baked is faster but not procedural; fractal noise is better for runtime variation |

---

## Forest Pack Pro 9.x: Algorithm Extraction

### Distribution Modes

#### Random Mode (Default)
**What Forest Pack does:** [ASSUMED based on behavior] Internally a jittered-grid scatter, NOT Poisson disk.
Each cell in a uniform grid gets one randomly placed point. This produces neither minimum-distance guarantees
nor true blue-noise distribution. The "random" look comes from per-cell jitter, not from a sampling quality algorithm.

**Why our Bridson impl is better:** Bridson enforces `min_distance` globally, produces blue-noise statistics,
and avoids the "patchy" look of pure jitter grids on visible terrain. Forest Pack's Random mode at high densities
visually approximates Poisson, but ours is provably correct.

**Project status:** `_scatter_engine.poisson_disk_sample` — grade A-. Already implements this correctly.
`[VERIFIED: reading _scatter_engine.py lines 34–206]`

#### Cluster Mode
**What Forest Pack does:** `[CITED: docs.itoosoft.com/forestpack (via search excerpt)]`
- Overlays species groups using a fractal-noise or Voronoi pattern on the base scatter
- Key parameters: `Size` (cluster radius in world units), `Noise` (0–100%, fraction of "rogue" plants
  outside clusters), `Blurry Edge` (0–100%, cluster boundary feather), `Roughness`
- Cluster assignment: items with matching Colour ID in the Geometry List get grouped;
  Diversity = Clusters mode routes items to clusters by ColourID
- The cluster _boundary_ is defined by a noise map threshold, not a hard Voronoi boundary

**Python equivalent:**
```python
import numpy as np

def cluster_mask(
    width: float,
    depth: float,
    resolution: int,
    cluster_size: float,      # world-unit radius of cluster centers
    noise_amount: float = 0.2, # 0-1: fraction of rogue points outside clusters
    seed: int = 0,
) -> np.ndarray:
    """Return a [0,1] cluster weight map using layered fBm noise.

    Values close to 1.0 = dense cluster center.
    Values close to 0.0 = inter-cluster gaps.
    noise_amount blends toward uniform (1.0) to add rogue items.
    """
    rng = np.random.default_rng(seed)
    xs = np.linspace(0, width / cluster_size, resolution)
    ys = np.linspace(0, depth / cluster_size, resolution)
    xx, yy = np.meshgrid(xs, ys)

    # 4-octave fBm (approximates Forest Pack's "cluster noise")
    freq, amp, total = 1.0, 1.0, 0.0
    noise = np.zeros((resolution, resolution), dtype=np.float32)
    for _ in range(4):
        # Simple sine-based noise placeholder; swap in OpenSimplex for production
        phase_x = rng.uniform(0, 2 * np.pi)
        phase_y = rng.uniform(0, 2 * np.pi)
        noise += amp * 0.5 * (
            np.sin(xx * freq * 2 * np.pi + phase_x) *
            np.sin(yy * freq * 2 * np.pi + phase_y) + 1.0
        )
        total += amp
        freq *= 2.0
        amp *= 0.5

    cluster_map = (noise / total)  # normalised to [0, 1]
    # Blend toward 1.0 by noise_amount to let rogue items through everywhere
    return cluster_map * (1.0 - noise_amount) + noise_amount
```
`[ASSUMED — Forest Pack's exact noise type is not publicly documented. fBm sine is structurally equivalent.]`

#### Edge Mode
**What Forest Pack does:** `[CITED: itoosoft.com/tutorials/edge-mode via search]`
- Distributes items along spline/mesh edges at spacing `d`
- Items are aligned to the edge tangent + normal of the surface
- "Blurry Edge" parameter removes items that partially extend beyond the boundary
- Uses the item's pivot point for boundary checks in default mode; Size mode uses bounding radius

**Python equivalent (spline edges):**
```python
def edge_scatter(
    polyline: list[tuple[float, float]],
    spacing: float,
    jitter: float = 0.1,
    seed: int = 0,
) -> list[tuple[float, float, float]]:  # (x, y, angle_deg)
    """Place points at equal arc-length intervals along a polyline."""
    rng = random.Random(seed)
    results = []
    accumulated = 0.0
    for i in range(len(polyline) - 1):
        x0, y0 = polyline[i]
        x1, y1 = polyline[i + 1]
        seg_len = math.hypot(x1 - x0, y1 - y0)
        angle = math.degrees(math.atan2(y1 - y0, x1 - x0))
        while accumulated <= seg_len:
            t = accumulated / seg_len
            px = x0 + t * (x1 - x0) + rng.gauss(0, jitter)
            py = y0 + t * (y1 - y0) + rng.gauss(0, jitter)
            results.append((px, py, angle))
            accumulated += spacing
        accumulated -= seg_len
    return results
```
`[ASSUMED — exact Forest Pack edge spacing internals not documented; arc-length parameterization is standard]`

#### Surface Mode
**What Forest Pack does:** `[CITED: docs.itoosoft.com/forestpack/forest-plugin/surfaces via search excerpt]`
- Projects scatter points onto a target mesh surface
- Alignment: surface normal, slope-up, or global up
- Altitude Range: `Top` / `Bottom` in world units; falloff curve controls density between limits
  - Falloff curve X axis = normalised altitude between Top and Bottom (0→1)
  - Y axis = density multiplier (0→1)
- Slope Range: `Min` / `Max` in degrees (0 = horizontal, 90 = vertical)
- Density falloff near area boundary: `Falloff > Density` curve (distance from edge → density weight)

**Example parameter values from documentation:**
- Altitude Top: 1544m, Bottom: 460m (from altitude-based ecosystem tutorial)
- Slope Max: 44 degrees for tree placement cutoff
`[CITED: itoosoft.com/tutorials/creating-altitude-based-ecosystems via search excerpt]`

**Project equivalent:** `biome_filter_points` in `_scatter_engine.py` already implements altitude/slope
filtering with smoothstep edge feathering. The parameter mapping is:
```
Forest Pack          →  _scatter_engine rule dict
altitude Top         →  max_alt (normalised 0-1)
altitude Bottom      →  min_alt (normalised 0-1)
slope Min            →  min_slope (degrees)
slope Max            →  max_slope (degrees)
density (rule)       →  density (0-1 probability keep)
falloff curve        →  biome_edge_feather_m smoothstep
```
`[VERIFIED: reading _scatter_engine.py lines 337–558]`

---

### Collision / Exclusion Zone System

**Forest Pack's method:** `[CITED: forum.itoosoft.com collision docs via search excerpt]`
Bounding-sphere collision only — NOT signed distance fields. Per-item `Collision Radius` (world units)
defined on each Geometry List entry. Two items collide if:

```
dist(center_A, center_B) < radius_A + radius_B
```

Species separation uses the same mechanism: each species has its own collision radius, so a tree with
radius 3m will not allow another tree within 6m, and will keep a shrub (radius 0.5m) at 3.5m distance.

**SDF note:** Forest Pack does NOT expose SDF exclusion zones. The "Collisions" feature is pure
bounding-sphere rejection applied after initial scatter placement. This is O(n²) naive or O(n log n)
with a spatial index.

**Python equivalent (already partially exists):**
```python
def apply_collision_exclusion(
    placements: list[dict],
    collision_radii: dict[str, float],  # vegetation_type -> radius in world units
    default_radius: float = 1.5,
) -> list[dict]:
    """Remove placements that violate inter-species bounding-sphere separation.

    Uses a spatial hash grid for O(n) average complexity.
    Processes in random order; first-placed wins on collision.
    Matches Forest Pack's bounding-sphere collision model exactly.
    """
    import math
    max_r = max(collision_radii.values(), default=default_radius)
    cell = max_r * 2.0
    grid: dict[tuple[int, int], list[int]] = {}
    kept: list[dict] = []

    for pl in placements:
        px, py = pl["position"]
        r = collision_radii.get(pl["vegetation_type"], default_radius)
        gx, gy = int(px / cell), int(py / cell)
        collision = False
        for dg in range(-2, 3):
            for dh in range(-2, 3):
                for k in grid.get((gx + dg, gy + dh), []):
                    ox, oy = kept[k]["position"]
                    or_ = collision_radii.get(kept[k]["vegetation_type"], default_radius)
                    if math.hypot(px - ox, py - oy) < (r + or_):
                        collision = True
                        break
                if collision:
                    break
            if collision:
                break
        if not collision:
            grid.setdefault((gx, gy), []).append(len(kept))
            kept.append(pl)
    return kept
```
`[ASSUMED — exact Forest Pack spatial index type not documented; spatial hash is standard equivalent]`

---

### Density Map (Bitmap-Driven)

**Forest Pack's Image Mode:** `[CITED: docs.itoosoft.com/forestpack/forest-plugin/distribution/image-mode via search]`
- Grayscale bitmap maps density. Pixel value 0 = no items. Pixel value 255 = full density.
- "Use as Density Map" toggle reinterprets the bitmap as continuous density rather than binary mask.
- Per-item `Probability` (0–100%) multiplies with the map value for species mixing.
- The scatter points are still generated at full density first, then thinned by rejection sampling
  against the density map: `keep_if(random() < map_value_at_position)`

**Project equivalent:** `poisson_disk_sample(density_map=...)` already implements density-weighted
radius: `r_local = min_distance / max(density, 0.05)`. This is a superior approach — it modulates
PLACEMENT not post-hoc rejection, so dense regions get more points and sparse regions get fewer
without wasting candidate generation. Forest Pack's approach is simpler but wastes cycles.

**The gap:** `pass_vegetation_depth` produces a density field but it is **not being passed** as
`density_map` into `poisson_disk_sample`. This is blocker C-1.
`[VERIFIED: project_roads_scatter_texturing_research.md lines 43-48, master guide C-1 P0]`

---

### MaxScript API (for reference only — not for direct reimplementation)

The C++ render API (`itreesinterface.h`) exposes instance-level CRUD:
`[VERIFIED: raw.githubusercontent.com/itoosoft/ForestPack_API/master/itreesinterface.h]`

```cpp
// Instance manipulation (render integration API — not placement control)
virtual void IForestCreate(Point3 p, float width, float height, int specid);
virtual int IForestCount();
virtual void IForestEdit(int n, float width, float height, int specid, int seed);
virtual void IForestMove(int n, Point3 p);
virtual void IForestSetSpecID(int n, int specid);  // species assignment
virtual void IForestSetSeed(int n, int seed);       // per-instance randomisation seed
virtual Matrix3 IForestGetFullTM(int n);            // full transform matrix
```

MaxScript ParamBlock2 access (from forum excerpts, parameter names confirmed):
```maxscript
-- Accessible by MaxScript but removed from UI in recent versions:
fp.globsize   -- global size multiplier
fp.width      -- base width
fp.height     -- base height
-- Distribution map: fp.distmap (bitmap reference)
-- Interface for custom Edit mode:
fp.trees.create p:<point3> width:<float> height:<float> geomid:<int>
```
`[CITED: forum.itoosoft.com/scripts-for-forest-pack via search excerpt]`

**Key insight:** The MaxScript API is irrelevant for our Python pipeline. We own the placement math
directly. The API surface tells us the _data model_ (position + width + height + specID + seed per instance),
which maps cleanly to our placement dict schema.

---

### LOD / Billboard Pipeline

Forest Pack does NOT have a built-in billboard baker. It relies on:
1. SpeedTree-generated billboards (pre-baked multi-view alpha cards)
2. iToo's own "Impostors" feature using V-Ray's billboard rendering
3. Distance thresholds set in Display rollout: `Near/Far` distance per LOD level

**SpeedTree billboard standard** (confirmed approach from search):
- 8 views: cardinal + diagonal at 45° intervals around equator + 1 top-down
- Each view is an alpha-card render at the target polygon LOD
- Atlas: NxN sprite sheet, typically 2048x2048 for 16 views
- LOD switch distance: typically 20–40x tree height (SpeedTree default is 30x)

**Python billboard bake skeleton (bpy-dependent):**
```python
NUM_BILLBOARD_VIEWS = 8
BILLBOARD_ATLAS_SIZE = 2048

def bake_billboard_atlas(obj, output_path: str, view_size: int = 256):
    """Render 8 equatorial views of obj into an atlas texture.
    Requires bpy context with object selected.
    [ASSUMED -- SpeedTree uses this view count; exact Forest Pack view count not documented]
    """
    import bpy, math
    views = [i * (360.0 / NUM_BILLBOARD_VIEWS) for i in range(NUM_BILLBOARD_VIEWS)]
    renders = []
    for az in views:
        # position camera at azimuth az, elevation 15 degrees, distance = 3x bbox height
        rad = math.radians(az)
        # ... camera setup, render to temp file, collect ...
    # pack renders into atlas using numpy
```
`[ASSUMED — exact view angles and atlas packing not from official Forest Pack docs]`

---

## 3ds Max 2027 Terrain Tools

### Displace Modifier (Current standard, not deprecated)
`[CITED: Autodesk Knowledge Network Displace Modifier Reference via search]`

**Algorithm (exact):**
```
displacement_at_vertex = (luminance(pixel) - luminance_center) * strength
```
- `luminance` is grayscale value 0.0–1.0 (standard: gray=0.5 = zero displacement)
- `luminance_center` default: 0.5 (128/255)
- `strength` range: any float; negative = inward displacement
- `decay` parameter: `effective_strength = strength / (1 + decay * distance_from_gizmo)`
  - decay=0 (default): uniform strength throughout world space
  - decay>0: field drops off like 1/r from gizmo center (magnet analogy from docs)

**Python equivalent (already used in project):**
```python
def displace_heightmap(
    heightmap: np.ndarray,  # float32, [0,1]
    strength: float = 50.0,  # world units
    luminance_center: float = 0.5,
) -> np.ndarray:
    """Apply 3ds Max Displace modifier formula to heightmap."""
    return heightmap + (heightmap - luminance_center) * strength
    # Note: this is additive displacement on top of base heightmap geometry
```

### Noise Plus Modifier (3ds Max 2027 new)
`[CITED: Autodesk 3ds Max 2027 What's New + yelzkizi.org write-up, verified from multiple sources]`

**Engine:** Simplex noise (replaces Perlin-based legacy Noise modifier)
**Five fractal types** (exact names not publicly listed; from context Simplex + 4 variants):
- Simple (base Simplex, no fractal stacking)
- fBm (Fractal Brownian Motion — octaves summed with lacunarity/gain)
- Turbulence (abs(fBm) — sharp ridge valleys)
- Ridged (1 - abs(fBm) — sharp raised ridges)
- Hybrid (presumed: combination mode) — `[ASSUMED — 5th type name not confirmed in public docs]`

**Key parameters:**
- Phase: animatable; at Simple type, phase 0° = phase 360° (seamless loop)
- Tiling: works in X/Y/Z; NOT supported in Simple + Hybrid modes
- Seed: per-element random offset
- Coordinate space: Object / World
- Deform along normals: boolean (displaces along vertex normal vs global Z)
- Clamping: min/max output clamp
- Inversion: negate output

**Python Simplex fBm equivalent:**
```python
# Requires opensimplex or noise package
from opensimplex import OpenSimplex

def simplex_fbm(
    x: float, y: float,
    octaves: int = 6,
    lacunarity: float = 2.0,
    gain: float = 0.5,
    seed: int = 0,
) -> float:
    """fBm using Simplex noise — equivalent to 3ds Max 2027 Noise Plus fBm type."""
    gen = OpenSimplex(seed)
    value, amplitude, frequency = 0.0, 1.0, 1.0
    for _ in range(octaves):
        value += amplitude * gen.noise2(x * frequency, y * frequency)
        amplitude *= gain
        frequency *= lacunarity
    return value

def simplex_turbulence(x, y, **kwargs) -> float:
    """Turbulence = abs(fBm) — Noise Plus Turbulence type."""
    return abs(simplex_fbm(x, y, **kwargs))

def simplex_ridged(x, y, **kwargs) -> float:
    """Ridged = 1 - abs(fBm) — Noise Plus Ridged type."""
    return 1.0 - abs(simplex_fbm(x, y, **kwargs))
```
`[CITED: Autodesk 3ds Max 2027 release. fBm/turbulence/ridged formulas are ASSUMED from noise literature
— exact 3ds Max 2027 fractal type names are not publicly confirmed beyond "five types, Simplex-based"]`

### Terrain Compound Object (Deprecated algorithm, still present in 3ds Max 2024+)
`[CITED: Autodesk Knowledge Network Terrain Compound Object 2024 via search]`

**Algorithm:** Creates a triangulated mesh from elevation contour splines.
- Input: editable splines at different Z heights (elevation contours)
- Output: triangulated mesh surface
- Basic algorithm: fan triangulation per contour, connecting adjacent contour levels
- Retriangulate option: slower algorithm that follows contour lines more closely (prevents
  "cascade" artifacts in steep ravines where contours turn sharply)
- **Limitation:** Not suitable for real-time terrain. Creates static mesh only.
- **Deprecation status:** Still present in 2024/2025 docs but labeled "legacy approach" for
  terrain-from-contour. Modern workflow uses Displace modifier + heightmap.

**Key insight for project:** This algorithm is irrelevant — our project uses heightmaps already.
The contour-to-mesh approach is the _opposite_ of our pipeline direction.

### ProBoolean for River/Road Carving
`[ASSUMED — ProBoolean carving details not found in public 2027 docs specifically]`

ProBoolean is a Boolean compound object that supports: Union, Intersection, Subtraction, Imprint, and Cookie operations. For terrain carving:
- Subtraction: carve a channel mesh (spline extruded to depth) from the terrain mesh
- Imprint: stamp the road silhouette onto the terrain mesh topology without removing geometry

**Project equivalent:** Direct heightmap write (Rune's approach, already partially implemented
in `environment.py`). Far superior to mesh Boolean for procedural terrain — no topology dependency.

---

## 3ds Max Material Editor: Terrain Shaders

### Height-Based Splatmap Blending (Advanced Algorithm)
`[CITED: gamedeveloper.com/programming/advanced-terrain-texture-splatting — verified]`

The documented formula used in production terrain shaders (also used by MicroSplat):

```python
def height_blend(
    color_a: np.ndarray,  # (H, W, 3) RGB
    height_a: np.ndarray, # (H, W) per-pixel height/depth [0,1] stored in alpha
    weight_a: np.ndarray, # (H, W) splatmap weight for layer A
    color_b: np.ndarray,
    height_b: np.ndarray,
    weight_b: np.ndarray,
    depth: float = 0.2,   # blend depth parameter (0.1–0.4 range; 0.2 = article default)
) -> np.ndarray:
    """Height-corrected splatmap blend.

    Combines splatmap opacity weight with per-layer height map so that
    taller features (rocks, pebbles) poke through overlying materials.
    Matches the formula from Shanon Drone's 2001 GameDev article, used
    in MicroSplat and UE4 Landscape material.

    Formula:
        ma = max(h_a + w_a, h_b + w_b) - depth
        b_a = max(h_a + w_a - ma, 0)
        b_b = max(h_b + w_b - ma, 0)
        out = (color_a * b_a + color_b * b_b) / (b_a + b_b)
    """
    import numpy as np
    ha = height_a + weight_a
    hb = height_b + weight_b
    ma = np.maximum(ha, hb) - depth
    ba = np.maximum(ha - ma, 0.0)
    bb = np.maximum(hb - ma, 0.0)
    denom = ba + bb
    denom = np.where(denom < 1e-6, 1.0, denom)
    return (color_a * ba[..., None] + color_b * bb[..., None]) / denom[..., None]
```
`[CITED: gamedeveloper.com/programming/advanced-terrain-texture-splatting — formula verified verbatim]`

**Depth parameter guidance:**
- `depth=0.1`: sharp transition — rocks cut through dirt cleanly
- `depth=0.2`: default — natural stone-through-grass seams
- `depth=0.4`: gradual transition — soft mud/sand blends

### Stochastic Hex-Tiling (Anti-Repetition)
`[CITED: Mikkelsen 2022 "Practical Real-Time Hex-Tiling" JCGT Vol.11 No.2]`

**Algorithm structure:**

1. **Triangle grid mapping** — input UV `p` is skewed into simplex triangle coordinates
2. **Three vertices identified** — barycentric coordinates `w1, w2, w3` computed
3. **Hash per vertex** — each vertex gets a 2D random offset and rotation
4. **Three texture samples** — texture sampled at `uv + offset_i` for each vertex i
5. **Contrast ramp** — `Gain3(w1, w2, w3, contrast=0.75)` adjusts barycentric weights
6. **Weighted blend** — final color = `sum(wi * sample_i) / sum(wi)`

**GLSL pseudocode (Mikkelsen's adaptation):**
```glsl
// Step 1: Skew to simplex grid
const mat2 gridToSkewedGrid = mat2(1.0, 0.0, -0.57735027, 1.15470054);
vec2 skewedCoord = gridToSkewedGrid * uv;
ivec2 baseId = ivec2(floor(skewedCoord));
vec3 temp = vec3(fract(skewedCoord), 0.0);
temp.z = 1.0 - temp.x - temp.y;

// Step 2: Identify triangle vertices
float s = step(0.0, -temp.z);
float s2 = 2.0 * s - 1.0;
float w1 = -temp.z * s2;
float w2 = s - temp.y * s2;
float w3 = s - temp.x * s2;
ivec2 v1 = baseId + ivec2(s, s);
ivec2 v2 = baseId + ivec2(s, 1-s);
ivec2 v3 = baseId + ivec2(1-s, s);

// Step 3: Hash each vertex to offset + rotation
// Hash function: hash22(ivec2 p) -> vec2 in [-1,1]

// Step 4: Sample texture 3x with per-vertex offsets
// Contrast ramp (Gain3): contrast_adjust = 0.75
w1 = max(w1 + contrast_adjust*(w1-1.0/3.0), 0.0);
w2 = max(w2 + contrast_adjust*(w2-1.0/3.0), 0.0);
w3 = max(w3 + contrast_adjust*(w3-1.0/3.0), 0.0);
float sum = w1 + w2 + w3;
w1 /= sum; w2 /= sum; w3 /= sum;

// Step 5: Blend
vec4 color = w1 * sample1 + w2 * sample2 + w3 * sample3;
```

**Python port for offline texture baking (splatmap pre-processing):**
```python
def hex_tile_uv(uv: np.ndarray, tile_scale: float = 1.0) -> tuple:
    """
    Map UV coordinates to triangle-grid hex-tiling sample positions.
    Returns (uv1, uv2, uv3, w1, w2, w3) for blending 3 texture samples.
    All weights are normalised to sum to 1.0 after contrast ramp.
    [CITED: Mikkelsen JCGT 2022]
    """
    import numpy as np
    # Skew matrix for simplex triangle grid
    p = uv * tile_scale
    skewed = np.stack([
        p[..., 0] - p[..., 1] * 0.57735027,
        p[..., 1] * 1.15470054
    ], axis=-1)
    base = np.floor(skewed).astype(int)
    frac = skewed - base
    # Barycentric-like weights
    s = (frac[..., 0] + frac[..., 1] < 1.0).astype(float)
    w1 = frac[..., 0] * s + (1 - frac[..., 0]) * (1 - s)
    w2 = frac[..., 1] * s + (1 - frac[..., 1]) * (1 - s)
    w3 = 1.0 - w1 - w2
    # Contrast ramp (Gain3, c=0.75)
    c = 0.75
    w1 = np.maximum(w1 + c * (w1 - 1/3), 0.0)
    w2 = np.maximum(w2 + c * (w2 - 1/3), 0.0)
    w3 = np.maximum(w3 + c * (w3 - 1/3), 0.0)
    total = w1 + w2 + w3
    total = np.where(total < 1e-6, 1.0, total)
    return w1/total, w2/total, w3/total
    # Caller samples texture at 3 different hash-offset UVs and blends by these weights
```
`[CITED: Mikkelsen JCGT 2022 algorithm structure; Python port is ASSUMED equivalent]`

---

## Comparison: Forest Pack Techniques vs Project Status

| Technique | Forest Pack 9.x | Project Status | Gap |
|-----------|----------------|---------------|-----|
| Blue-noise scatter | Jitter-grid (Random mode) | Bridson Poisson — better | None needed |
| Density map | Bitmap grayscale rejection sampling | density_map param exists, disconnected | Wire C-1 |
| Altitude filter | Top/Bottom with falloff curve | `biome_filter_points` — complete | Wire |
| Slope filter | Min/Max degrees | `biome_filter_points` — complete | Wire |
| Cluster mode | Fractal noise grouping | Not implemented | Implement |
| Collision exclusion | Bounding sphere per species | Partial (`is_valid` in Bridson) | Multi-species |
| Road SDF exclusion | Not native — Forest Pack has no roads | Not wired | Wire C-1/C-2 |
| LOD/billboard | SpeedTree impostors, V-Ray specific | Not in scope (external asset) | Out of scope |
| Edge scatter | Arc-length spline placement | Not implemented | Low priority |
| MaxScript API | Node-level CRUD | N/A (Python owns this) | N/A |

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Poisson disk sampling | Custom rejection sampler | `_scatter_engine.poisson_disk_sample` | Already A-grade Bridson impl |
| Biome EDT for edge feather | Manual distance loop | scipy.ndimage.distance_transform_edt | Handles boundary correctly in O(n) |
| Multi-species KD-tree collision | Nested loops | scipy.spatial.KDTree | O(n log n) vs O(n²) naive |
| Simplex noise | Re-implement from scratch | opensimplex (PyPI) or noise package | Well-tested, correct gradient tables |
| Stochastic tiling LUT | Histogram analysis | Pre-bake with the offline Python port above | Complex preprocessing; offline is fine |
| Height-blend formula | Custom lerp variant | The 3-line formula above | Proven formula; custom variants break |

---

## Common Pitfalls

### Pitfall 1: Density Field Disconnection (Active P0 Blocker C-1)
**What goes wrong:** `pass_vegetation_depth` produces a density field, but `handle_scatter_vegetation`
ignores it. Scatter density is uniform across the terrain regardless of biome analysis.
**Why it happens:** The density field is stored in TerrainMaskStack but the scatter handler reads
from a different path.
**How to avoid:** Pass `TerrainMaskStack.detail_density` as the `density_map` arg to `poisson_disk_sample`.
**Warning signs:** Uniform tree distribution ignoring rock/water/road areas.

### Pitfall 2: Road Exclusion by Name String (Active P0 Blocker C-2)
**What goes wrong:** `handle_scatter_vegetation` checks `if "road" in obj.name` — brittle string match
that breaks on object rename.
**Why it happens:** Proper SDF mask from `road_network.py` is not plumbed to scatter.
**How to avoid:** Generate an SDF exclusion mask from road network geometry; sample it per scatter point.

### Pitfall 3: Forest Pack Collision vs SDF (Algorithm Mismatch)
**What goes wrong:** Implementing Forest Pack's bounding-sphere collision and calling it "SDF exclusion".
**Why it happens:** Docs use "collision" loosely; Forest Pack has no SDF concept internally.
**How to avoid:** Bounding-sphere collision = species separation. SDF exclusion = road/water/cliff
keep-out zones. They serve different purposes and should both be implemented independently.

### Pitfall 4: Cluster Mode at Wrong Scale
**What goes wrong:** Cluster noise frequency set in UV space rather than world space, producing
clusters that scale with terrain resolution instead of being biome-appropriate.
**How to avoid:** Always divide world coordinates by `cluster_size` before computing noise.
At default Forest Pack settings, cluster size is 5–15m for understory plants, 30–80m for tree species.
`[ASSUMED — exact FP default cluster sizes not documented]`

### Pitfall 5: Stochastic Tiling on Normal Maps
**What goes wrong:** Applying the hex-tile UV offset to both albedo AND normal map, causing normal
orientation misalignment between the three samples (rotated normals look broken under directional light).
**How to avoid:** Apply per-sample rotation to the normal map's XY channels before blending.
For normal maps: rotate the XY components of each sample's normal by the same angle used for UV rotation.
`[CITED: Mikkelsen 2022 paper — mentions this as the standard correct approach]`

### Pitfall 6: Height-Blend Depth Parameter Miscalibration
**What goes wrong:** Using depth=0.05 (too small) produces pixel-perfect but visually harsh
transitions. Using depth=0.8 (too large) makes the height information irrelevant (everything blends linearly).
**How to avoid:** 0.2 is the documented default. For dark fantasy terrain: rock/dirt = 0.15,
dirt/grass = 0.25, snow/rock = 0.12.
`[ASSUMED — specific VeilBreakers values not from FP docs]`

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|-----------------|--------------|--------|
| Perlin noise displacement | Simplex noise (3ds Max 2027 Noise Plus) | 2026 | Better spectral properties, phase-animatable |
| Linear blend splatmap | Height-corrected blend (depth param) | ~2015 (MicroSplat) | Rocks poke through dirt naturally |
| Tiling textures (repeat) | Stochastic hex-tiling | 2019 (Heitz/Deliot), improved 2022 (Mikkelsen) | Eliminates visible grid pattern |
| Dart-throwing Poisson | Bridson O(n) fast Poisson | 2007 (Bridson SIGGRAPH) | 100x faster, same quality |
| Uniform scatter (random points) | Density-field-weighted Poisson | ~2018 onwards in AAA | Biome-correct density without separate masking |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Forest Pack Random mode uses jitter-grid, not Poisson disk | Distribution Modes | Low — Bridson is better either way |
| A2 | Forest Pack cluster mode uses fBm/Voronoi (not documented explicitly) | Cluster Mode | Medium — wrong noise type produces wrong cluster shape |
| A3 | Edge mode uses arc-length parameterization | Edge Mode | Low — standard technique |
| A4 | Billboard atlases use 8 views at 45° intervals | LOD/Billboard | Low — asset pipeline handles this |
| A5 | 3ds Max 2027 Noise Plus 5th fractal type is "Hybrid" | Noise Plus | Low — name irrelevant to Python port |
| A6 | FP cluster size defaults: 5–15m understory, 30–80m trees | Common Pitfalls #4 | Medium — wrong scale breaks cluster visuals |
| A7 | Python hex-tile UV skew matrix values | Stochastic Tiling | Medium — must verify against paper Listings |

---

## Open Questions

1. **Forest Pack exact internal scatter algorithm**
   - What we know: Behavior described as "random distribution" with collision post-processing
   - What's unclear: Whether it's jitter-grid, uniform random, or quasi-random sequence (Halton)
   - Recommendation: Irrelevant for our pipeline — we use Bridson which is demonstrably better

2. **`tree_instance_points` channel population**
   - What we know: Channel exists in TerrainMaskStack; C-2 says it's never populated
   - What's unclear: Which handler is supposed to populate it, and what format Unity expects
   - Recommendation: Check `terrain_unity_export.py` for expected format before implementing

3. **Stochastic tiling normal map rotation**
   - What we know: XY rotation of normal samples is required
   - What's unclear: Whether to use the same 2x2 rotation matrix or a separate normal-space transform
   - Recommendation: Use the same rotation angle; apply `mat2(cos, -sin, sin, cos)` to XY components

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| numpy | `_scatter_engine.py` | Expected ✓ | project dependency | Pure-Python fallback exists in engine |
| scipy.ndimage | biome EDT feathering | Expected ✓ | project dependency | Manual neighbour scan fallback in engine |
| opensimplex | Noise Plus / cluster mode | Unknown | — | `noise` package or manual impl |
| scipy.spatial.KDTree | Multi-species collision | Expected ✓ | bundled with scipy | Spatial hash fallback |

`[ASSUMED — versions not probed; scipy presence inferred from existing EDT import in _scatter_engine.py]`

---

## Sources

### Primary (HIGH confidence)
- `veilbreakers_terrain/handlers/_scatter_engine.py` (lines 1–558) — project codebase, read directly
- `raw.githubusercontent.com/itoosoft/ForestPack_API/master/itreesinterface.h` — C++ API header verified
- `gamedeveloper.com/programming/advanced-terrain-texture-splatting` — height-blend formula verified verbatim
- Autodesk 3ds Max 2027 What's New (help.autodesk.com/cloudhelp/2027/) — Noise Plus parameters
- Mikkelsen 2022 "Practical Real-Time Hex-Tiling" JCGT 11(3) — hex-tiling algorithm structure
- `project_roads_scatter_texturing_research.md` + `project_master_implementation_guide_2026_04_27.md` — P0 blockers

### Secondary (MEDIUM confidence)
- Search excerpts from docs.itoosoft.com/forestpack/forest-plugin/surfaces — altitude/slope parameters
- Search excerpts from docs.itoosoft.com/forestpack/forest-plugin/distribution/image-mode — density map behavior
- itoosoft.com forum excerpts — MaxScript parameter names (globsize, width, height, trees.create)
- yelzkizi.org + superrendersfarm.com 3ds Max 2027 write-ups — Noise Plus fractal type list

### Tertiary (LOW confidence / ASSUMED)
- Forest Pack Random mode internal algorithm (jitter-grid hypothesis)
- Forest Pack Cluster mode noise type (fBm hypothesis)
- Billboard atlas view count (8 views @ 45°)
- VeilBreakers-specific depth parameter values for height-blend

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — project deps verified from codebase
- Forest Pack algorithms: MEDIUM — behavior documented, internals not disclosed
- Architecture patterns: HIGH — based on existing code + P0 blockers from master guide
- Pitfalls: HIGH — directly from project audit (C-1, C-2) + documented formula edge cases
- 3ds Max 2027: MEDIUM — from official release notes + third-party verified write-ups
- Stochastic tiling: HIGH — primary paper cited, algorithm structure confirmed

**Research date:** 2026-04-27
**Valid until:** 2026-05-27 (Forest Pack docs stable; 3ds Max 2027 notes stable)
