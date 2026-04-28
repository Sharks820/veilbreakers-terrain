# R3 Water Simulation Best Practices
## VeilBreakers Terrain — AAA Research Reference
**Date:** 2026-04-27  
**Scope:** River network simulation, waterfall rendering, water rendering channels, water semantics, delta formation, dark fantasy water, generation checklist

---

## TABLE OF CONTENTS
1. [River Network Simulation](#1-river-network-simulation)
2. [Waterfall Simulation](#2-waterfall-simulation)
3. [Water Rendering](#3-water-rendering)
4. [Water Semantics and Channel Data](#4-water-semantics-and-channel-data)
5. [Delta and River Mouth](#5-delta-and-river-mouth)
6. [Dark Fantasy Water](#6-dark-fantasy-water)
7. [Step-by-Step Water Generation Checklist](#7-step-by-step-water-generation-checklist)
8. [Active Bug Context — Dual Semantics W-1](#8-active-bug-context--dual-semantics-w-1)

---

## 1. River Network Simulation

### 1.1 Flow Direction Algorithms

**D8 (Deterministic Eight-Direction)**  
The foundational algorithm. Each cell assigns its entire flow to the single lowest of its eight neighbors based on steepest descent. Formalized in the late 1980s and still the most widely used.

- Strengths: fast, conceptually simple, good for channel network extraction, preserves watershed boundaries cleanly.
- Weaknesses: produces unrealistic parallel flow lines on hillslopes, over-concentrates flow on divergent terrain.
- Best use: channel extraction, watershed delineation, contributing area for river networks.

Source: [D8 vs D-Infinity — Rivix.com](https://www.rivix.com/Topics/D8_vs_Dinf.php)

**D-Infinity (D∞, Tarboton 1997)**  
Partitions flow between the two steepest downslope neighbors using the actual angle of steepest descent, not just one of eight fixed directions. Computes contributing area as a continuous distribution rather than concentrated paths.

- Strengths: more accurate on hillslopes, avoids parallel-flow artifacts, better for diffuse overland flow.
- Weaknesses: slightly slower, not a complete flow-tube solution, can over-disperse flow in narrow channels.
- Best use: hillslope contributing area, scattered vegetation placement, slope-wetness indices.

Source: [D8 vs D-Infinity — Rivix.com](https://www.rivix.com/Topics/D8_vs_Dinf.php)

**Practical AAA Usage**  
Professional terrain pipelines (World Machine, Gaea, ArcGIS, QGIS) use D8 for channel/river extraction and D∞ for smooth contributing-area rasters used as texture masks. For VeilBreakers:
- Use **D8** for extracting the river network skeleton and computing flow accumulation thresholds.
- Use **D∞** contributing area as the source for the scatter/density mask (wetter hillslopes → more moss, mud, ferns).

Source: [ArcGIS Flow Direction tool — supporting D8, MFD, DINF](https://pro.arcgis.com/en/pro-app/latest/tool-reference/spatial-analyst/flow-direction.htm)

---

### 1.2 Barnes 2014 Priority-Flood Algorithm

**What it is:**  
Published by Richard Barnes, Clarence Lehman, and David Mulla in *Computers & Geosciences* Vol. 62, January 2014. An optimal depression-filling and watershed-labeling algorithm for raster DEMs.

**How it works:**  
Floods the DEM inward from its edges using a **priority queue** (min-heap ordered by elevation). The queue starts populated with all boundary cells. Processing order guarantees that every cell is visited at its minimum possible drainage elevation. The resulting DEM has zero internal depressions — every cell is guaranteed to drain.

Pseudocode (conceptual):
```
PQ ← all boundary cells (min-heap by elevation)
visited ← boundary cells
while PQ not empty:
    cell c ← PQ.pop_min()
    for each neighbor n of c:
        if n not visited:
            n.elevation ← max(n.elevation, c.elevation)
            PQ.push(n)
            visited.add(n)
```

**Complexity:**  
- O(n) for integer DEMs  
- O(n log₂ n) for floating-point DEMs  

This is optimal — matching the lower bound for comparison-based sorting of float data.

**Epsilon gradient trick for flat regions:**  
After depression filling, many cells end up exactly equal in elevation (flat regions). D8 cannot assign flow direction in a flat area. Barnes' companion flat-resolution algorithm solves this by superimposing two gradients:  
1. A gradient **away** from higher surrounding cells (preventing flow back uphill).  
2. A gradient **toward** lower outlet cells (pulling flow to drainage points).

The combination creates convergent, V-shaped drainage patterns in flats rather than the parallel-line artifacts produced by naive epsilon methods (which simply add a tiny constant ε per cell step). The implementation in RichDEM uses C++ `std::nextafter` to produce the smallest representable floating-point difference.

**Where it is used:**  
- RichDEM library (r-barnes/richdem) — the reference C++/Python implementation.
- White-box hydrology tools (TauDEM, SAGA GIS, QGIS GDAL terrain tools).
- Gaea's hydrological preprocessing (documented as "sophisticated algorithms that closely mimic nature" — the industry standard under the hood).
- World Machine's Flow Restructure device uses the same class of algorithm to make artificial terrains "hydrologically valid."

Sources:  
- [Priority-Flood paper on arXiv](https://arxiv.org/abs/1511.04463)  
- [Barnes original PDF](https://rbarnes.org/sci/2014_depressions.pdf)  
- [RichDEM flat resolution documentation](https://richdem.readthedocs.io/en/latest/flat_resolution.html)  
- [GitHub r-barnes/Barnes2013-Depressions](https://github.com/r-barnes/Barnes2013-Depressions)  

---

### 1.3 World Machine and Gaea Flat Region Handling

**World Machine (Flow Restructure device):**  
Artificial terrains (fractal noise, sculpted mountains) routinely contain excessive interior lakes and flat basins where water would pool forever. The Flow Restructure device makes the terrain "hydrologically valid" by ensuring every cell has at least one outlet lower than itself. The designer can then selectively re-add lakes where desired by cutting a small depression.

World Machine's water data type carries three sub-channels: **elevation**, **depth**, and **flow velocity (speed + direction)**. This maps directly to the channel set VeilBreakers needs to export.

Source: [Water in World Machine](https://help.world-machine.com/topic/water/)

**Gaea (River node):**  
Gaea's River node "subtly transforms the terrain to provide unbroken pathways for a river to be generated." This is the epsilon/depression-fill preprocessing step exposed as a user-facing parameter. The node requires only that the terrain have some slopes so water can flow downslope — flat areas are internally corrected.

Gaea 3.0 (late 2025) introduced a new river simulation model combining manual spline guides with automatic meander generation, closer to World Machine's River device.

Sources:  
- [Gaea Rivers documentation](https://docs.quadspinner.com/Reference/Water/Rivers.html)  
- [World Machine Features](https://www.world-machine.com/features.php)  

---

### 1.4 Stream Power Erosion and River Incision

**The Stream Power Law (SPL):**

The erosion rate E at a point in a river is:

```
E = K · A^m · S^n
```

Where:
- `E` = erosion (incision) rate [m/yr]
- `K` = erodibility coefficient (bedrock type, climate — varies orders of magnitude)
- `A` = upstream drainage area [m²] — proxy for discharge
- `S` = local channel slope (dimensionless)
- `m`, `n` = empirical exponents (positive; m/n ≈ 0.5 is the validity constraint)

**What it produces:**  
- High A (large drainage basin) → faster incision → broader, deeper valley.
- High S (steep slope) → faster incision → gorges, waterfalls.
- The law is a 1D advection equation. Perturbations (base-level drops) propagate upstream as **knickpoints** — the mathematical explanation for waterfalls.

**Connection to terrain generation:**  
The 2023 SIGGRAPH paper (Schott et al., "Large-scale Terrain Authoring through Interactive Erosion Simulation") works in the **uplift domain** rather than elevation domain and solves the SPL interactively. Key insight: computing drainage area accurately is the expensive step — they use fast approximations of D8 accumulation per frame to make it interactive.

**VeilBreakers actionable use:**  
- Apply SPL to carve river valleys proportional to contributing area: wider valleys at confluence zones, narrow gorges at headwaters with steep slopes.
- Use the knickpoint propagation logic to automatically place waterfall candidates: any cell where slope exceeds a threshold AND upstream area exceeds a minimum accumulation threshold is a knickpoint candidate.

Sources:  
- [Stream power law — Wikipedia](https://en.wikipedia.org/wiki/Stream_power_law)  
- [Schott et al. 2023 ACM TOG](https://dl.acm.org/doi/10.1145/3592787)  
- [Genevaux et al. 2013 ACM SIGGRAPH — terrain generation via hydrology](https://dl.acm.org/doi/abs/10.1145/2461912.2461996)  

---

## 2. Waterfall Simulation

### 2.1 Waterfall Detection from a Heightmap

**Knickpoints** are the geomorphological term for abrupt gradient discontinuities in a river's longitudinal profile. In a heightmap, they appear as:

1. A cell where the slope angle exceeds a hard threshold (e.g., > 60° effective gradient along the flow path).
2. A cell where the SPL erosion rate would be extremely high — indicating the bedrock has not yet been eroded to equilibrium.
3. Topologically: the first cell downstream where the flow direction drops more than `threshold_height` in fewer than `N` cells.

**Detection algorithm (practical implementation):**
```python
for each river cell c (in downstream order from flow accumulation):
    local_slope = (elevation[c] - elevation[downstream[c]]) / cell_size
    if local_slope > WATERFALL_SLOPE_THRESHOLD:  # e.g. tan(60°) ≈ 1.73
        if flow_accumulation[c] > MIN_WATERFALL_AREA:
            mark c as waterfall_candidate
            # Optionally: check that the drop height exceeds MIN_DROP_HEIGHT
            consecutive_drop = sum elevation loss over next K cells downstream
            if consecutive_drop > MIN_DROP_HEIGHT:  # e.g. 5m
                confirm as waterfall, record apex cell and plunge_pool_cell
```

**In Nick McDonald's procedural hydrology system:**  
Waterfalls emerge naturally from the particle-based simulation — particles following the "descend" algorithm generate rapid elevation loss on steep terrain, and the resulting stream map concentration marks these cells automatically.

Source: [Procedural Hydrology — Nick's Blog](https://nickmcd.me/2020/04/15/procedural-hydrology/)

---

### 2.2 Waterfall Rendering Techniques

**Industry-standard approaches (not mutually exclusive):**

**A. Flow Map Sheets (primary visual layer)**  
A tileable water texture is UV-scrolled along the waterfall face using a flow map. Two UV sets are sampled with a phase offset and blended to eliminate the periodic pop. This is the cheapest, most performant approach and used in virtually every production waterfall (The Witcher 3, Horizon Zero Dawn).

**B. Flipbook Animation (spray / foam / mist)**  
Pre-rendered flipbook sprites (e.g., 8x8 grid = 64 frames) are used for:
- Spray at the lip where water leaves the cliff face.
- Foam and bubbles at the base (plunge pool).
- Mist columns rising from the impact zone.

Flipbooks are authored in Houdini (SideFX) or simulated in Blender and baked to a sprite sheet. They are driven by Niagara (UE5) or VFX Graph (Unity) particle systems.

Source: [Waterfall Thread — Real Time VFX](https://realtimevfx.com/t/waterfall-thread/18621)

**C. Flow Map + Niagara Fluid Data (high-end)**  
UE5: Baked fluid simulation data from Houdini is imported as vector fields. Niagara's "Sample Texture" data interface samples the velocity field per-particle, driving GPU particle masses that represent foam streaks and spray.  
Tutorial: [Driving Niagara with Flowmaps and Baked Fluidsim Data — 80.lv](https://80.lv/articles/tutorial-driving-niagara-with-flowmaps-and-baked-fluidsim-data)

**D. Mesh + Tessellation (waterfall body)**  
A planar mesh or ribbon mesh following the waterfall face is UV-mapped along the fall direction. Normal maps baked from the fluid simulation provide the surface detail at the sheet.

---

### 2.3 Foam at Waterfall Bases

**Unity HDRP:**  
The HDRP water system supports Foam Generators — sphere- or box-shaped volumes placed at the base of a waterfall. The generator stamp foam onto the water surface based on:
- Distance from the generator center (radial falloff).
- Current map influence (foam spreads along the flow direction using the RG channel of the current map).
- Foam texture (user-assigned tiling texture, monochrome).

Programmatic control: Foam generators can be created/moved at runtime via C# script. For a procedural terrain pipeline, place foam generators at each confirmed waterfall knickpoint position using the plunge_pool_cell world coordinates.

Source: [Unity HDRP Water — Capabilities Overview](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@14.0/manual/WaterSystem-Overview.html)

**UE5 Water Plugin:**  
Foam on rivers is velocity-driven. The Shallow Water Equations (SWE) simulation outputs a velocity field; the foam advection system generates and propagates foam based on local velocity magnitude. Higher velocity → more foam generation. At waterfall bases, the velocity field spike from the falling water drives dense foam accumulation.

The Fluid Flux plugin (third-party but widely used in production) implements this correctly with GPU-based SWE.

Source: [Water Plugin Foam on Rivers — Epic Forums](https://forums.unrealengine.com/t/water-plugin-in-ue5-does-anyone-know-how-to-use-the-foam-on-rivers-see-video-linked/688819)

---

## 3. Water Rendering

### 3.1 Unity HDRP Water System

**Surface types and their simulation bands:**

| Surface Type     | Simulation Bands | Foam | Caustics | Current Map | Flow Map |
|------------------|------------------|------|----------|-------------|----------|
| Pool             | 1 (ripples)      | No   | Yes      | Ripples only | No      |
| River            | 2 (agitation + ripples) | Yes | Yes | Agitation + Ripples | Yes |
| Ocean/Sea/Lake   | 3 (2 swells + ripples)  | Yes | Yes | Swell bands | No  |

**Wave simulation:** FFT (Fast Fourier Transform) summing multiple frequency bands. Rivers use the "agitation" band for downstream choppiness and the "ripples" band for fine surface detail.

**Current Map (flow map) — exact channel specification:**
- **R channel:** X component of flow direction (range [0,1] mapped to [-1,+1])
- **G channel:** Z component of flow direction (range [0,1] mapped to [-1,+1])  
- **B channel:** Influence weight of current map (0 = no effect, 1 = full effect)
- **Neutral value:** (1.0, 0.5, 1.0) = flow in +X direction at full influence
- **Format:** Non-sRGB (linear). Import with sRGB unchecked.
- **Author in:** Krita with Tangent Normal brush (Tangent Encoding: R=-X, G=-Y, B=-Z)

The current map drives wave agitation direction, not water mesh displacement. It is distinct from a deformation map.

**Deformation map — channel specification:**
- R+G channels (yellow in Unity's material editor): X and Z displacement of water surface mesh.
- Single-channel texture for vertical (Y) deformation.
- Render texture format for runtime updates: **R16_UNorm**.

**Foam system:**
- Foam generators (runtime spheres/boxes) stamp foam at specified positions.
- Foam mask texture: single-channel (monochrome), attenuates or suppresses foam in specific regions.
- Foam smoothness and amount are per-surface parameters.
- Foam and caustics are monochrome in HDRP — no color tinting without shader modification.
- Caustics do NOT respond to current maps or water masks.

**Caustics:**
- Driven by the ripples simulation band by default.
- You can switch to a larger band (e.g., "Swell First Band") for ocean/river environments.
- Controlled by: Caustics Resolution, Virtual Plane Distance, Absorption Distance.
- Lower Absorption Distance = murkier water = less visible caustics.
- Caustics only render on opaque GameObjects behind the water surface.

Sources:  
- [HDRP Water System Simulation](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@17.1/manual/water-water-system-simulation.html)  
- [HDRP Create a Current](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@17.0/manual/water-create-a-current-in-the-water-system.html)  
- [HDRP Customize Caustics](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@17.0/manual/water-caustics-in-the-water-system.html)  
- [HDRP Deform Water Surface](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@17.0/manual/water-deform-a-water-surface.html)  

---

### 3.2 UE5 Water Plugin

**Architecture:**
- Water Body Actor types: WaterBodyRiver, WaterBodyLake, WaterBodyOcean, WaterBodyCustom.
- Rivers use a **spline-based mesh** with automatic LOD. Not simulation-based by default.
- The Water Plugin's built-in simulation is relatively limited for rivers — most AAA teams replace it with Fluid Flux or a custom SWE simulation.

**Foam on rivers:**
- The native Water Plugin exposes foam via a material parameter on the WaterBodyRiver material.
- Foam is velocity-driven in Fluid Flux: velocity magnitude > threshold → foam generation rate increases.
- Niagara-based foam: Kármán vortex streets (periodic vortex shedding) are baked as flipbook velocity maps and sampled by Niagara GPU particles.

**Caustics:**
- Light Function approach: A panning caustics texture applied to the Directional Light as a light cookie. Cheap, effective for shallow water scenes.
- Chromatic aberration offset: Slightly shift R, G, B panning speeds to get the shimmer quality.
- Compute shader caustics: Some plugins (e.g., water caustics generators) use compute shaders to simulate wave refraction in real time, outputting a Render Texture for the light function.
- HDRP-style: Caustics from the ripple simulation band (same principle as Unity HDRP).

Sources:  
- [UE5 Water System — Foam and Caustics Tutorial](https://dev.epicgames.com/community/learning/tutorials/EL06/unreal-engine-5-water-system-creating-stylized-foam-caustic-beginner-tutorial-part-2)  
- [Mastering Water in Unreal Engine — Yelzkizi](https://yelzkizi.org/water-simulation-in-unreal-engine/)  
- [Realtime Water Shader with Caustics in UE — RealtimeVFX](https://realtimevfx.com/t/realtime-water-shader-with-caustics-and-wet-surface-in-unreal-engine/8734)  

---

### 3.3 Flow Maps: What They Are and How They Are Baked

**Definition:**  
A flow map is a 2D texture where the R channel stores the normalized X component of the water flow velocity vector and the G channel stores the Z (or Y) component. The B channel is often unused or stores flow speed/intensity.

**Standard encoding:**
```
R = (velocity.x / max_speed) * 0.5 + 0.5   # range [0, 1]
G = (velocity.z / max_speed) * 0.5 + 0.5   # range [0, 1]
B = magnitude / max_speed                    # optional speed mask
```
Neutral (no flow) = (0.5, 0.5, *).

**Baking from river simulation:**
1. Run your river simulation (SWE, particle hydrology, or D8 flow accumulation).
2. At each terrain cell that has water coverage, compute the velocity vector from the flow direction and speed.
3. Encode as RG texture at terrain resolution.
4. Apply Gaussian blur (σ ≈ 2–4 cells) to smooth sharp transitions.
5. Export as 16-bit linear PNG or EXR to preserve precision.

**Flow-map advection in shaders:**
Two UV sets are needed. Both scroll along the flow direction encoded in RG, but with a phase offset (typically 0.5). The shader blends between them using a periodic function so the texture loops seamlessly without a visible seam pop.

Source (Godot Waterways plugin — Arnklit — flow/foam map generation reference):  
[GitHub — Arnklit/Waterways](https://github.com/Arnklit/Waterways)

**Foam driven by flow velocity:**
- Foam generation rate scales with |velocity|.
- World Machine's water data outputs flow velocity as a vector map which can be used directly as a flow map.
- At river bends: the outer bank has higher velocity → more foam there.
- At waterfalls: maximum velocity → maximum foam generation.
- In pools/lakes: near-zero velocity → foam accumulates but does not advect (static ring patterns).

Sources:  
- [Developing Next-Gen Water Rendering — 80.lv](https://80.lv/articles/developing-a-next-gen-water-rendering-solution-for-games/)  
- [GPU Gems 1 Ch. 1 — Effective Water Simulation (NVIDIA)](https://developer.nvidia.com/gpugems/gpugems/part-i-natural-effects/chapter-1-effective-water-simulation-physical-models)  

---

### 3.4 Caustics for Shallow Water

**How caustics form:**  
Curved water surfaces act as converging/diverging lenses. Light passing through focuses in bright patterns on the substrate. Only relevant in shallow water (< ~3m depth for realistic scale) — in deep water the pattern dissipates.

**Implementation options (cheapest to most realistic):**

1. **Scrolling caustics texture + light function (UE5):**  
   Apply a grayscale caustics texture as a Directional Light cookie. Pan at two slightly different rates and blend. Add a small chromatic offset (R/G/B panning at subtly different speeds). Depth-fade the strength so it diminishes in deeper water. Cost: very low.

2. **HDRP ripple-band caustics:**  
   HDRP computes caustics automatically from the ripple simulation band — no authoring required. Tune via Caustics Resolution and Virtual Plane Distance. Caustics only appear on opaque geometry. Cost: built-in.

3. **Compute shader caustics generator:**  
   Simulates wave height field on GPU, traces photon paths through refraction, writes a Render Texture. Supports 4+ wave layers, chromatic aberration, directional blur. This Render Texture is then used as a light cookie. Cost: medium (single compute pass).

**Depth gating:**  
Caustics should be conditionally disabled or faded based on water depth:
```hlsl
float causticsMask = saturate(1.0 - waterDepth / CAUSTICS_DEPTH_FADE);
causticsColor *= causticsMask;
```

For dark fantasy corrupted water, reduce or eliminate caustics entirely (murky water does not refract cleanly).

Sources:  
- [Unity HDRP Water Caustics](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@14.0/manual/WaterSystem-caustics.html)  
- [Realtime Caustics techniques — ameye.dev](https://ameye.dev/notes/realtime-caustics/)  
- [UE5 Water & Caustics Tutorial — YouTube](https://www.youtube.com/watch?v=wfNIEkHSfns)  

---

## 4. Water Semantics and Channel Data

### 4.1 The Industry-Standard Channel Set

No single universal standard exists, but the following set is the convergent practice from World Machine, Gaea, GIS pipelines, and engine water systems:

| Channel | Type | Description | Range |
|---------|------|-------------|-------|
| `water_surface_elevation_m` | float32 | Absolute elevation of water surface (WSE) | World units (meters) |
| `water_depth_m` | float32 | Depth from surface to terrain floor | 0–N m |
| `flow_velocity_x` | float32 or [0,1] | X component of flow velocity | m/s or normalized |
| `flow_velocity_z` | float32 or [0,1] | Z component of flow velocity | m/s or normalized |
| `water_mask` | uint8 / bool | Binary wet/dry cell flag | 0 or 1 |
| `foam_mask` | float32 | Foam density at surface | [0, 1] |
| `flow_accumulation` | float32 | Upstream drainage area | cells or m² |

**Critical separation: `water_mask` vs `water_surface_elevation_m`**  
These are semantically distinct and must never be stored in the same channel or conflated:

- `water_mask`: Boolean. Answers "is this cell covered by water?" Used for texture splatting, scatter exclusion, footstep sound switching, gameplay logic. Does not convey how deep or what elevation.
- `water_surface_elevation_m`: Float. Answers "what is the absolute height of the water surface here?" Required for rendering the water plane at the correct world-space position, for buoyancy calculations, and for shader depth computation (`depth = water_surface_elevation - terrain_elevation`).

**The W-1 dual semantics bug in VeilBreakers:**  
If `water_surface_mask` is currently storing a float elevation value in what is semantically named and consumed as a binary mask (or vice versa), this breaks both the terrain exporter (which treats it as 0/1) and the water renderer (which needs the float). The fix is explicit channel separation: generate both outputs independently and pass them via different named outputs.

**World Machine water data channels:**  
World Machine's water data type explicitly carries: elevation, depth, and flow velocity (speed + direction). When exporting for game engines, these are extracted as separate PNG/EXR maps.

Source: [World Machine Water](https://help.world-machine.com/topic/water/)

---

### 4.2 Recommended VeilBreakers Export Schema

```python
WATER_EXPORT_CHANNELS = {
    # Terrain-space data (aligned to heightmap resolution)
    "water_surface_elevation_m":  "float32, EXR, linear",  # absolute WSE
    "water_depth_m":              "float32, EXR, linear",  # terrain to surface
    "water_mask":                 "uint8,   PNG, binary",   # 0 or 255
    "flow_direction_rg":          "uint8,   PNG, linear",   # R=X, G=Z, neutral=(128,128)
    "flow_speed_normalized":      "uint8,   PNG, linear",   # [0,1] normalized speed
    "foam_mask":                  "uint8,   PNG, linear",   # foam density [0,1]
    "flow_accumulation_log":      "float32, EXR, linear",   # log10(accumulation area)
    
    # Engine-specific derived channels (computed at import time)
    # Unity HDRP current map:  RG from flow_direction_rg, B = flow_speed_normalized
    # UE5 Water Material:      RG velocity from flow_direction_rg
    # Foam generator positions: computed from foam_mask > threshold centroids
}
```

Note: `flow_direction_rg` encodes the Unity HDRP current map format directly (neutral = 128, 128 = 0.5, 0.5). No conversion needed if authored at export time.

---

### 4.3 Wave Normals

Wave normals are not typically baked per-cell in procedural terrain pipelines — they are computed in real time by the engine's wave simulation (FFT or sum-of-sines) and added on top of a flat normal map from the flow simulation. However, for static baked water (e.g., frozen lakes, still pools as decals):
- Export a normal map from a Blender fluid sim or Houdini ocean shader.
- Channels: R=X normal, G=Y normal, B=Z normal (standard tangent-space normal map encoding).

---

## 5. Delta and River Mouth

### 5.1 How River Deltas Form

Deltas form when a river carrying sediment enters a standing body of water (lake or sea). Flow velocity drops sharply → sediment deposits → the channel builds a fan-shaped bar. The channel then bifurcates around the bar.

**Key parameters controlling delta type:**
- Fluvial dominance (river energy) → elongated, bird's-foot delta (Mississippi).
- Wave dominance → smooth, arcuate delta (Nile).
- Tide dominance → branching estuarine channels (Ganges-Brahmaputra).

For dark fantasy terrain, fluvial-dominant deltas are most controllable procedurally.

Source: [Modeling River Delta Formation — PNAS](https://www.pnas.org/doi/10.1073/pnas.0705265104)

---

### 5.2 Procedural Delta Algorithm

**Correct fan spread approach:**

1. Identify the river mouth cell (where flow accumulation grid reaches the coastline/lake boundary).
2. Compute a **fan mask** centered on the mouth cell, spread over ±45° of the river's incoming flow direction with radial distance up to `delta_radius`.
3. Within the fan, subdivide into N bifurcating channels (N = 2–5 for stylized) using a branching algorithm:
   ```
   parent_channel → splits at distance d_split from mouth
   each child → slightly diverging direction ±angle_offset
   each child → smaller width = parent_width * width_ratio^depth
   ```
4. Width ratio per bifurcation: empirically ~0.7 (area-preserving branching would be √0.5 ≈ 0.71 per child for 2 children).
5. Continue until channel width < minimum_channel_width or depth > max_depth.

**Hack's Law for width scaling:**  
River width scales with upstream drainage area via:
```
width ∝ A^0.5   (approximate; Hack's exponent h ≈ 0.5–0.6)
```
At the mouth, A is maximum → widest channel. Headwater tributaries have minimum A → narrowest channels. This provides the correct scaling for the entire network from source to delta.

Source: [Hack's Law — Wikipedia](https://en.wikipedia.org/wiki/Hack's_law)

**Hydraulic geometry (Leopold-Maddock 1953):**  
At-a-station hydraulic geometry gives width (w), depth (d), and velocity (v) as power functions of discharge Q:
```
w = a · Q^b      (b ≈ 0.26)
d = c · Q^f      (f ≈ 0.40)
v = k · Q^m      (m ≈ 0.34)
```
Discharge Q scales approximately with drainage area A for a given rainfall regime. Use these exponents to compute width and depth at each river cell from the flow accumulation value.

Source: [Hydraulic Geometry — USGS](https://pubs.usgs.gov/publication/pp252)

---

### 5.3 Delta in VeilBreakers

For a dark fantasy world, the delta mouth is a visually rich area:
- Multiple narrow, slow channels separated by reed-choked mudflats.
- Foam accumulation at channel edges (low velocity, foam pools).
- Shallow water with high turbidity → minimal caustics, strong volumetric depth fog color.
- Corrupted zones: the delta is a natural accumulation point for any upstream corruption.

---

## 6. Dark Fantasy Water

### 6.1 Visual Reference: FromSoftware Poison Swamps

FromSoftware's toxic/corrupted water environments (Dark Souls Blighttown, Elden Ring Swamp of Aeonia, Scarlet Rot pools) establish the industry reference for "corrupted water" in dark fantasy:
- Deep, saturated color (toxic green, blood red, black-purple).
- High opacity / low transparency — objects below surface are invisible or deeply tinted.
- Slow, viscous surface motion — low frequency waves only, no ripples.
- Particle effects: bubbles rising, spores, mist.
- Gameplay: poison/rot status effect buildup.

Sources:  
- [Why FromSoftware's Poison Swamps — CBR](https://www.cbr.com/elden-ring-dark-souls-poison-swamps/)  
- [Elden Ring Shadow of the Erdtree Poison Swamp — Game Rant](https://gamerant.com/elden-ring-shadow-of-the-erdtree-dlc-poison-swamp/)  

---

### 6.2 Corrupted Water Material Properties

**What makes corrupted water look different from clean water:**

| Property | Clean Water | Corrupted Water |
|----------|-------------|-----------------|
| Albedo / tint | Blue-grey, near-clear | Deep green/black/blood-red; near-opaque |
| Transmission | High | Near zero — light absorbed in <0.5m |
| Absorption distance | 5–20m | 0.2–1m |
| Scattering color | Light blue | Desaturated khaki, toxic green, or deep crimson |
| Surface roughness | Low (glossy) | Medium-high (matte, viscous appearance) |
| Foam color | White | Yellow-green, black, or no foam (suppressed) |
| Caustics | Visible, bright | Suppressed or absent (too opaque to refract) |
| Wave frequency | Full spectrum | Low frequency only — suppress ripple band |
| Emissive | None | Faint glow at edges, particle emissions |
| Viscosity cue | Fast currents, sharp eddies | Slow, thick, treacly motion |
| Underwater visibility | Clear to 5m+ | Zero — immediate black fog |

**Unity HDRP Implementation:**
- Absorption Distance → set to 0.3–0.8m (clean water: 10–20m).
- Scattering Color → set to the corruption tint (deep green, blood red).
- Foam → reduce Foam Amount to near zero, or tint the foam mask texture.
- Caustics → disable or reduce Caustics Resolution + increase Virtual Plane Distance.
- Ripples band → set Chaos to maximum (fully non-directional), reduce Ripples Amplitude.
- Water Mask → stamp emissive-glow zones using a Water Decal.

**Additional techniques for dark fantasy water:**
- Add a faint emissive pulse to the water surface using a custom Water Decal shader with time-animated emissive.
- Use particle systems (Niagara / VFX Graph) to add rising bubbles, spores floating at the surface, toxic mist columns.
- For "corrupted veins" in terrain (dark-water rivulets spreading from a corruption source), use a distance-field mask from the corruption epicenter to blend between normal water and corrupted water material parameters.

---

### 6.3 VeilBreakers-Specific Recommendations

Given the dark fantasy setting:
1. Define a `corruption_intensity` float channel (0.0 = clean, 1.0 = fully corrupted). Bake this as a separate terrain mask.
2. In the Unity HDRP material, lerp all water properties based on `corruption_intensity`.
3. Corruption should concentrate downstream — use the flow accumulation raster to drive the corruption spreading algorithm.
4. At corruption level > 0.7: disable caustics, set absorption to 0.3m, emit faint green particle wisps.
5. At corruption level < 0.2: standard water, full caustics, natural blue scattering.

---

## 7. Step-by-Step Water Generation Checklist

This is an ordered pipeline from raw heightmap input to water channels ready for Unity/UE export.

### Phase 1 — Preprocessing (DEM Conditioning)

- [ ] **1.1** Load heightmap as float32 array (world-space elevation in meters).
- [ ] **1.2** Apply depression filling using Barnes 2014 Priority-Flood algorithm.
  - Reference: `richdem.rdPreprocessDEM()` or equivalent.
  - Result: a depression-free DEM where every cell drains.
- [ ] **1.3** Resolve flat regions using Barnes epsilon gradient method.
  - Ensures D8 flow direction can be assigned to all cells, including artificially flattened areas.
  - Result: DEM with imperceptibly small gradients in flat areas.

### Phase 2 — Flow Routing

- [ ] **2.1** Compute D8 flow direction for every cell.
  - Output: `flow_direction_d8` (integer 1–128, or angle).
- [ ] **2.2** Compute D8 flow accumulation (upstream contributing area).
  - Output: `flow_accumulation` (integer cell count or float m²).
- [ ] **2.3** (Optional) Compute D∞ flow accumulation for scatter/biome masks.
  - Output: `flow_accumulation_dinf` (float).

### Phase 3 — River Network Extraction

- [ ] **3.1** Apply threshold to flow accumulation to extract river channels.
  - `river_mask = flow_accumulation > CHANNEL_INITIATION_THRESHOLD`
  - Tune threshold to match desired river density (typical starting value: top 2–5% of accumulation values).
- [ ] **3.2** Compute river width per cell using Leopold-Maddock hydraulic geometry:
  - `width_m = a * (flow_accumulation * cell_area * rainfall_m_yr)^b`  (b ≈ 0.26)
- [ ] **3.3** Compute river depth per cell:
  - `depth_m = c * (discharge)^f`  (f ≈ 0.40)
- [ ] **3.4** Compute water surface elevation per cell:
  - `water_surface_elevation_m = terrain_elevation_m + depth_m`
  - (For rivers this is essentially terrain elevation since rivers are shallow relative to their drainage depth.)

### Phase 4 — Lake and Pool Detection

- [ ] **4.1** Run flood-fill algorithm on depression-unfilled DEM (or intentionally re-carved depressions) to identify closed basins.
- [ ] **4.2** For each basin, compute the spill-point elevation (lowest outlet cell).
- [ ] **4.3** Mark all cells below spill elevation as `lake_mask`.
- [ ] **4.4** Compute lake depth per cell: `lake_depth = spill_elevation - terrain_elevation`.

### Phase 5 — Waterfall Detection

- [ ] **5.1** For each river cell (in downstream order), compute local slope along the flow path.
- [ ] **5.2** Flag as waterfall candidate where:
  - `slope > WATERFALL_SLOPE_THRESHOLD` (e.g., 1.0 m/m = 45°), AND
  - `flow_accumulation > WATERFALL_MIN_AREA`
- [ ] **5.3** Confirm with minimum drop height check (sum elevation loss over next K=5 cells > MIN_DROP_HEIGHT = 3m).
- [ ] **5.4** Record waterfall positions as (apex_cell, plunge_pool_cell, drop_height_m, width_m).

### Phase 6 — Flow Velocity and Direction Maps

- [ ] **6.1** Estimate flow velocity per cell:
  - `velocity = k * discharge^m` (m ≈ 0.34)
  - Or use Manning's equation: `v = (1/n) * R^(2/3) * S^(1/2)` where R ≈ depth, S = slope.
- [ ] **6.2** Convert flow direction (D8 angle) + velocity magnitude to velocity vector (vx, vz).
- [ ] **6.3** Encode as Unity HDRP current map format:
  - `R = vx_normalized * 0.5 + 0.5`
  - `G = vz_normalized * 0.5 + 0.5`  
  - `B = speed_normalized`
  - Export as 8-bit or 16-bit linear PNG (no sRGB).

### Phase 7 — Foam Mask Generation

- [ ] **7.1** Compute foam intensity per cell as a function of flow speed:
  - `foam = saturate((velocity - FOAM_MIN_VELOCITY) / FOAM_RAMP_VELOCITY)`
- [ ] **7.2** Boost foam at waterfall plunge pool cells:
  - `foam[plunge_pool_cell] = 1.0`
- [ ] **7.3** Boost foam at river confluences (cells receiving flow from multiple upstream branches).
- [ ] **7.4** Blur foam mask (Gaussian σ ≈ 3 cells) for smooth transitions.
- [ ] **7.5** Export as `foam_mask.png` (uint8, linear).

### Phase 8 — Delta Formation

- [ ] **8.1** Identify river mouth cells (river_mask cells adjacent to coastline/lake boundary).
- [ ] **8.2** For each mouth, compute fan mask (±45° of incoming flow direction, radial falloff).
- [ ] **8.3** Generate N bifurcating delta channels within the fan (branching tree, width_ratio ≈ 0.71 per bifurcation).
- [ ] **8.4** Add delta channels to river_mask; update width and depth per channel using hydraulic geometry scaled to reduced discharge.

### Phase 9 — Final Channel Export

- [ ] **9.1** Export `water_surface_elevation_m.exr` (float32, linear).
- [ ] **9.2** Export `water_depth_m.exr` (float32, linear).
- [ ] **9.3** Export `water_mask.png` (uint8, 0 or 255).
- [ ] **9.4** Export `current_map.png` (uint8, RG = flow direction, B = speed, linear, NO sRGB).
- [ ] **9.5** Export `foam_mask.png` (uint8, linear).
- [ ] **9.6** Export `waterfall_positions.json` (list of {x, z, drop_height_m, width_m} for runtime foam generator placement).
- [ ] **9.7** Export `flow_accumulation_log.exr` (float32, log10 of accumulation area — useful for scatter/biome masking).
- [ ] **9.8** (If dark fantasy) Export `corruption_intensity.png` (uint8, downstream-flow-weighted corruption mask).

### Phase 10 — Engine Import

**Unity HDRP:**
- [ ] Create WaterSurface of type River for each major waterway.
- [ ] Assign `current_map.png` to the Agitation band (ensure sRGB unchecked).
- [ ] Place WaterFoamGenerator components at each waterfall_positions entry.
- [ ] Assign `foam_mask.png` to suppress foam outside river areas.
- [ ] Configure Caustics from ripple band; reduce Absorption Distance for river murkiness.

**UE5:**
- [ ] Create WaterBodyRiver actors following river spline paths.
- [ ] Import `current_map.png` as a flow velocity texture for the water material.
- [ ] Use `foam_mask.png` in the water material to weight foam opacity.
- [ ] Set up Niagara waterfall FX at each waterfall position using `waterfall_positions.json`.

---

## 8. Active Bug Context — Dual Semantics W-1

The VeilBreakers master guide (2026-04-27) flags W-1 as an active production bug: `water_surface_mask` has dual semantics — it is being used as both a binary presence mask AND as a float elevation value in different parts of the codebase.

**Root cause:**  
The original code likely returned a single water channel and downstream consumers independently interpreted it as [0,1] float elevation or as 0/1 binary mask depending on context. This causes:
- Terrain export to treat a float like 0.73 as "73% wet" instead of "water surface is 0.73m above terrain."
- Rendering code to read a binary 0/1 as "water surface is exactly 0 or 1 meter above terrain," producing flat incorrect water planes.

**Fix strategy:**  
Per the channel schema in Section 4.2, these must be generated and stored in two separate named outputs:
```python
# BAD — dual semantics:
output["water_surface_mask"] = water_elevation_float  # used as both

# GOOD — separated:
output["water_surface_elevation_m"] = water_elevation_float  # float32 WSE
output["water_mask"] = (water_elevation_float > 0).astype(np.uint8) * 255  # binary
```

Any consumer of the old `water_surface_mask` channel must be audited and updated to consume the correct new channel.

---

## Sources

- [Priority-Flood arXiv paper](https://arxiv.org/abs/1511.04463)
- [Barnes 2013 Depressions GitHub](https://github.com/r-barnes/Barnes2013-Depressions)
- [RichDEM flat resolution docs](https://richdem.readthedocs.io/en/latest/flat_resolution.html)
- [D8 vs D-Infinity — Rivix](https://www.rivix.com/Topics/D8_vs_Dinf.php)
- [ArcGIS Flow Direction tool](https://pro.arcgis.com/en/pro-app/latest/tool-reference/spatial-analyst/flow-direction.htm)
- [Stream Power Law — Wikipedia](https://en.wikipedia.org/wiki/Stream_power_law)
- [Schott et al. 2023 — Large-scale Terrain Authoring (ACM TOG)](https://dl.acm.org/doi/10.1145/3592787)
- [Genevaux et al. 2013 — Terrain Generation via Hydrology (SIGGRAPH)](https://dl.acm.org/doi/abs/10.1145/2461912.2461996)
- [Nick McDonald — Procedural Hydrology](https://nickmcd.me/2020/04/15/procedural-hydrology/)
- [World Machine — Water](https://help.world-machine.com/topic/water/)
- [Gaea Rivers documentation](https://docs.quadspinner.com/Reference/Water/Rivers.html)
- [Unity HDRP Water Simulation](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@17.1/manual/water-water-system-simulation.html)
- [Unity HDRP Create a Current](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@17.0/manual/water-create-a-current-in-the-water-system.html)
- [Unity HDRP Caustics](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@17.0/manual/water-caustics-in-the-water-system.html)
- [Unity HDRP Deform Water](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@17.0/manual/water-deform-a-water-surface.html)
- [Unity HDRP Capabilities Overview](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@14.0/manual/WaterSystem-Overview.html)
- [UE5 Water Foam on Rivers — Epic Forums](https://forums.unrealengine.com/t/water-plugin-in-ue5-does-anyone-know-how-to-use-the-foam-on-rivers-see-video-linked/688819)
- [UE5 Water Foam and Caustics Tutorial](https://dev.epicgames.com/community/learning/tutorials/EL06/unreal-engine-5-water-system-creating-stylized-foam-caustic-beginner-tutorial-part-2)
- [Mastering Water in UE — Yelzkizi](https://yelzkizi.org/water-simulation-in-unreal-engine/)
- [Realtime Water Caustics in UE — RealtimeVFX](https://realtimevfx.com/t/realtime-water-shader-with-caustics-and-wet-surface-in-unreal-engine/8734)
- [Next-Gen Water Rendering — 80.lv](https://80.lv/articles/developing-a-next-gen-water-rendering-solution-for-games/)
- [Driving Niagara with Flowmaps — 80.lv](https://80.lv/articles/tutorial-driving-niagara-with-flowmaps-and-baked-fluidsim-data)
- [GPU Gems 1 Ch. 1 — Effective Water Simulation](https://developer.nvidia.com/gpugems/gpugems/part-i-natural-effects/chapter-1-effective-water-simulation-physical-models)
- [Arnklit Waterways — GitHub](https://github.com/Arnklit/Waterways)
- [Fstrugar RiverSim — GitHub](https://github.com/fstrugar/riversim)
- [Waterfall Thread — RealtimeVFX](https://realtimevfx.com/t/waterfall-thread/18621)
- [Hack's Law — Wikipedia](https://en.wikipedia.org/wiki/Hack's_law)
- [USGS Hydraulic Geometry (Leopold-Maddock)](https://pubs.usgs.gov/publication/pp252)
- [Modeling River Delta Formation — PNAS](https://www.pnas.org/doi/10.1073/pnas.0705265104)
- [Realtime Caustics — ameye.dev](https://ameye.dev/notes/realtime-caustics/)
- [Why FromSoftware Loves Poison Swamps — CBR](https://www.cbr.com/elden-ring-dark-souls-poison-swamps/)
- [Elden Ring Shadow of the Erdtree Poison Swamp — Game Rant](https://gamerant.com/elden-ring-shadow-of-the-erdtree-dlc-poison-swamp/)
