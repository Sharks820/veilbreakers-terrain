# R2: AAA Terrain Texture & Material Systems — Best Practices
**VeilBreakers Terrain Generator — Research Document**
**Date: 2026-04-27**
**Scope: Splatmap layering, PBR pipeline, anti-tiling, triplanar, macro variation, dark fantasy palette**

---

## EXECUTIVE SUMMARY

Terrain texturing is the single most visible quality gap between VeilBreakers and AAA titles. The root failures are:
1. Linear alpha blending instead of height-based blending (muddy transitions)
2. No anti-tiling (obvious repeat patterns on large surfaces)
3. No macro variation layer (uniform color across terrain)
4. Missing correct color-space assignment per channel
5. No distance-based LOD for texture sampling

This document covers the techniques used in Horizon Zero Dawn (Guerrilla/DECIMA), The Witcher 3 (CDPR/REDengine 3), Call of Duty (Treyarch), and researched AAA systems (MicroSplat, MegaSplat, Quixel Megascans) to fix each of these problems.

---

## 1. SPLATMAP / TERRAIN TEXTURE LAYERING

### 1.1 Standard Unity/UE Splatmap Baseline (What We Currently Do — Wrong)

Unity terrain stores texture weights in RGBA splatmap textures. Each RGBA channel holds one layer's blend weight (0–1). Four channels = 4 layers per splatmap. Multiple splatmaps give 8, 12, 16+ layers. The blend is a simple linear alpha lerp between layers:

```
final_color = layer0 * splatR + layer1 * splatG + layer2 * splatB + layer3 * splatA
```

**Problem:** Linear blending produces blurry, undefined transitions — mud everywhere. Rock blending into dirt looks like someone smeared paint. This is the most visible quality marker separating AAA terrain from amateur work. UE4/5 documented this as a known limitation of `LB_WeightBlend` mode.

**Source:** https://docs.unrealengine.com/4.26/en-US/BuildingWorlds/Landscape/Materials/

### 1.2 Height-Based Blending — The Correct AAA Approach

Height-based blending uses each texture's own heightmap to modulate where it "wins" in a transition zone. Instead of a smooth gradient between dirt and rock, the rock's high points poke through the dirt naturally. Dirt collects in the rock's low crevices.

**The algorithm (4-texture implementation):**

```hlsl
void applyHeightsToWeights(float4 heights, inout float4 weights) {
    // Scale height influence toward 0 away from each zone's painted area
    heights *= weights;

    // Compute cutoff: only heights within blend range of the maximum matter
    float height_start = max(max(heights.r, heights.g), max(heights.b, heights.a))
                       - _Height_Blend_Range;

    // Zero out heights below the cutoff
    heights = max(heights - height_start, 0.0f);

    // Renormalize so channels still sum to 1.0
    weights.rgba = heights / dot(heights, 1.0f);
}
```

Pack all four heightmaps into a single RGBA texture (one texture tap reads all four). This means two taps total: one for splatmap weights, one for packed heights. Use `_Height_Blend_Range` of 0.1–0.2 for sharp natural transitions.

**Source:** https://gamedev.stackexchange.com/questions/192514/how-to-best-select-a-texture-pair-to-use-in-height-blending-when-using-a-splatma

**UE5 implementation:** `LB_HeightBlend` mode in `LandscapeLayerBlend` node. Note: all-HeightBlend layers can produce black spots if all heights evaluate to zero simultaneously. Fix: set one base layer to `LB_AlphaBlend` as a fallback. UE5 docs recommend this hybrid.

**Unity HDRP limitation:** Unity disables height blending entirely if the terrain has more than 4 layers. Workaround: use first-pass (layers 1–4) with height blending, subsequent passes with alpha blending. MicroSplat bypasses this limitation entirely through custom shader generation.

**Source:** https://medium.com/@sinitsyndev/removing-the-4-layer-limit-for-height-based-blending-in-unity-terrain-urp-c0ba85444f58

### 1.3 MicroSplat — How It Achieves AAA Quality Over Standard Unity Terrain

Jason Booth's MicroSplat (Unity Asset Store) is the standard reference implementation for Unity terrain texturing. Key innovations over Unity's built-in shader:

**Core system:**
- Replaces Unity's terrain shader with a modular code-generated shader
- Height-based blending as default for all layers (not just first 4)
- Packs all textures into Texture2DArrays for single draw call regardless of layer count
- Supports up to 256 textures per terrain (MegaSplat variant) or 32 PBR textures (MicroSplat core)

**Anti-tiling module features:**
- **Detail Noise:** High-frequency noise overlay when close to surface
- **Distance Noise:** Modulates textures at distance with noise to break up patterns
- **Distance Resampling:** Resamples terrain at different scale in the distance
- **Normal Noise:** Blends a second normal map, adding surface variation across the terrain (up to 3 layers of normal noise for complex variation)
- **Texture Clusters:** Expands each of 16 Unity splatmap textures into 3 height-blended variations, giving 48 effective textures. Directly implements Heitz stochastic technique but with height-blend instead of histogram-preserving blend.

**Other modules relevant to VeilBreakers:**
- Tessellation + Parallax Occlusion Mapping (displacement via heightmap)
- Puddles, Streams, Lava & Wetness module
- Runtime Procedural Texturing (height/slope/noise-based auto-texturing)
- Per-texture properties: gradient tint, hue, brightness by terrain height

**Source:** https://assetstore.unity.com/packages/tools/terrain/microsplat-anti-tiling-module-96480
**Source:** https://assetstore.unity.com/packages/tools/terrain/microsplat-texture-clusters-104223

### 1.4 MegaSplat — 256-Texture Index-Based Splatmap

MegaSplat (also Jason Booth) uses a fundamentally different approach: instead of storing blend weights, it stores **texture indices** in the splatmap channels. Two adjacent texture indices + a blend weight allow blending between 256 possible textures.

**Channel packing:**
- **RG channels:** Index of texture A and texture B (0–255 each, stored as byte)
- **B channel:** Blend weight between texture A and B (0–1)
- **A channel:** Additional data (wetness, snow accumulation, etc.)

This means the shader cost is **constant regardless of texture count** — always 2 texture taps (A and B), never N taps for N layers. This is more efficient than standard splatmapping for more than 4 layers.

Height-based blending is the default blend between A and B. The system includes a built-in texture packer that generates missing PBR channels (normal, height, smoothness, AO) from available maps.

**Source:** https://unityassetpack.com/megasplat/ (MegaSplat free download documentation)
**Source:** https://discussions.unity.com/t/megasplat-256-textures-in-one-splat-map-shader/643764

### 1.5 The Witcher 3 (CDPR REDengine 3) — Two-Material System

From Marcin Gollent's GDC 2014 presentation on REDengine 3 landscape rendering for The Witcher 3:

**Terrain texturing approach:**
- Two combined materials: **background** (e.g., rock) + **overlay** (e.g., snow/moss/dirt)
- These two materials are blended using terrain data, not a simple painted splatmap
- Blend sharpness is variable: blurry transitions for mud/ice/dirt, sharp transitions for snow/sand/grass
- **Slope-based damp:** Separates flat-surface artificial materials from sloped natural materials — each behaves differently for optimal visual results
- Tessellation supports maximum factors of 8–16 for console GPUs
- Target: 16384² heightmap resolution, less than 0.5m between terrain vertices

**Why this matters for VeilBreakers:** Rather than painting every layer manually, the REDengine drives texture selection from terrain data (slope, height, water proximity). This is what makes W3 terrain look authored rather than algorithmic.

**Source:** GDC 2014 — "Landscape Creation and Rendering in REDengine 3", Marcin Gollent
**GDC Vault:** https://www.gdcvault.com/play/1020197/Landscape-Creation-and-Rendering-in

---

## 2. PBR TEXTURE PIPELINE

### 2.1 Quixel Megascans Standard Asset — Channel Inventory

Every Megascans surface asset ships with these maps:

| Map | Channels | Purpose |
|-----|----------|---------|
| Albedo / BaseColor | RGB | Surface color with lighting removed |
| Normal | RGB (tangent space) | Surface micro-detail normals |
| Roughness | Grayscale | Light diffusion (0=mirror, 1=matte) |
| Metallic | Grayscale | Metal vs. dielectric (0 or 1 for terrain, never in-between) |
| AO (Ambient Occlusion) | Grayscale | Micro-occlusion for crevices |
| Displacement / Height | Grayscale | Surface height for tessellation/POM |
| Cavity | Grayscale | Fine-detail AO for close-up |

Terrain surfaces are nearly always non-metallic (Metallic = 0). Metallic channel is included but stays black for rock, dirt, moss, wood.

Megascans physical scan resolution: typically 4K (4096×4096) per surface. High-detail surfaces ship at 8K.

**Source:** https://docs.quixel.com/mixer/1/en/topic/channel-specific-controls.html
**Source:** https://docs.quixel.com/mixer/1/en/topic/advanced-texture-setup-for-exports.html

### 2.2 Channel Packing for Runtime Efficiency

The industry standard is to pack multiple grayscale maps into a single RGBA texture to reduce texture sample count. Two common packing strategies:

**ORM Pack (Unreal/Godot standard):**
```
R = Ambient Occlusion
G = Roughness
B = Metallic
A = (unused or displacement)
```

**Terrain3D / Alternate Pack (used by Terrain3D Godot plugin):**
```
Texture 0: RGB = Albedo, A = Height/Displacement
Texture 1: RGB = Normal (OpenGL), A = Roughness
         (AO is encoded into Normal length: scale the normal vector by AO value)
```

This packing strategy reduces a 5-map set (Albedo, Height, Normal, Roughness, AO) to 2 texture taps, halving sample count.

**Source:** https://terrain3d.readthedocs.io/en/latest/docs/texture_prep.html

### 2.3 Color Space Assignments — Critical for Correct PBR

Incorrect color space causes washed-out or overly dark materials. This is a hard rule:

| Map | Color Space | Why |
|-----|-------------|-----|
| Albedo / BaseColor | **sRGB** | Human-perceived color data |
| Emissive | **sRGB** | Color data |
| Specular (if used) | **sRGB** | Color data (confirmed by Polycount community) |
| Normal | **Linear** (non-color) | Vector data — sRGB gamma destroys normal vectors |
| Roughness | **Linear** | Scalar data |
| Metallic | **Linear** | Scalar data |
| AO | **Linear** | Scalar multiplier |
| Displacement / Height | **Linear** | Scalar data |
| Cavity | **Linear** | Scalar data |

**Rule of thumb:** Everything except Albedo/Emissive/Specular is Linear. In Unity: uncheck "sRGB" on all non-color maps. In Blender: mark non-color inputs as "Non-Color" in the Image Texture node.

**Source:** https://polycount.com/discussion/188972/answered-quixel-megascan-textures-to-unity-what-are-the-correct-color-spaces
**Source:** https://docs.quixel.com/mixer/1/en/topic/advanced-texture-setup-for-exports.html

### 2.4 Texel Density for 1km² Terrain Tiles

There is no single "standard" but established AAA ranges based on viewing distance:

- **First-person games (Doom, CoD, Halo):** 10–20 px/cm for hero assets. For terrain, this is impractical at 1km scale; tiling + layering is used instead.
- **Terrain tiling approach:** Use a 4K texture (4096×4096) tiling at 8–16 meter intervals. At 4K tiling every 8m: `4096 / 800cm = ~5.12 px/cm` — equivalent to high-quality hero asset density at ground level.
- **Far-field macro texture:** 2K texture stretched over the full 1km tile (~0.2 px/cm) for color variation only — not detail.
- **Detail map overlay:** Small 256–512px texture tiling at 0.25–0.5m intervals for close-up micro-detail.

**Practical implementation for VeilBreakers:**
- Layer 0 (base detail): 4K texture, 8m tiling scale
- Layer 1 (macro color): 2K texture, 128m tiling scale
- Layer 2 (micro detail close): 512px, 0.5m tiling, fades past 10m

**Source:** https://www.beyondextent.com/deep-dives/deepdive-texeldensity
**Source:** https://polycount.com/discussion/234887/texel-density-standards-for-aaa-first-person-shooter-games

---

## 3. STOCHASTIC / ANTI-TILING TECHNIQUES

### 3.1 Histogram-Preserving Blending (Heitz & Neyret, HPG 2018) — The Gold Standard

**Paper:** "High-Performance By-Example Noise using a Histogram-Preserving Blending Operator" — Eric Heitz and Fabrice Neyret, HPG 2018 (Best Paper Award).
**Source:** https://eheitzresearch.wordpress.com/722-2/

**The problem standard stochastic sampling fails:** Simple stochastic sampling (picking random patches and blending with barycentric weights) causes:
- **Ghosting:** Duplicated features appear faintly
- **Contrast reduction:** Blended regions lose sharpness
- **Color introduction:** New colors appear that don't exist in the input
- The root cause: linear blending convolves histograms, reducing variance

**The histogram-preserving solution — algorithm:**

1. **Preprocessing (offline, once per texture):**
   - Compute the histogram of the input texture
   - Find a "Gaussianization" transformation T(x) that maps the histogram to a Gaussian distribution
   - Store T and its inverse T⁻¹ as lookup tables (LUTs)

2. **Runtime — per fragment shader:**
   ```
   // Partition output space on triangular grid
   // Each triangle vertex gets a random patch from input
   
   // Sample three patches (3 texture taps)
   c0 = sample(input_LUT_T, uv + random_offset_0)  // Gaussianized
   c1 = sample(input_LUT_T, uv + random_offset_1)
   c2 = sample(input_LUT_T, uv + random_offset_2)
   
   // Blend with barycentric weights (w0 + w1 + w2 = 1)
   blended = w0*c0 + w1*c1 + w2*c2
   
   // Restore variance (mean-preserving contrast restoration)
   // For Gaussian: this is a linear scaling around expected value
   restored = mean + (blended - mean) / sqrt(w0² + w1² + w2²)
   
   // Invert Gaussianization
   final = sample(inverse_LUT, restored)
   ```

3. **Practical simplification (GPU Zen 2 — Deliot & Heitz):**
   - Replace the 3D optimal transport solver with three 1D histogram transformations in eigenspace
   - Add a LUT prefiltering algorithm to fix color deviation with mipmapping
   - Enable DXT/BC compressed textures without artifacts
   - Result: preprocessing runs orders of magnitude faster

**Cost:** 3 texture taps instead of 1. On modern GPUs (2023+) this is rarely a bottleneck for terrain.

**Where to get it:**
- Unity Labs open source implementation: https://github.com/UnityLabs/procedural-stochastic-texturing
- Shader toy demo: https://unity-grenoble.github.io/website/demo/2020/10/16/demo-histogram-preserving-blend-synthesis.html
- MicroSplat's Texture Clusters module uses a simplified version with height-blend instead of histogram-preserving blend

**Source:** https://www.jcgt.org/published/0008/04/02/paper.pdf
**Source:** https://eheitzresearch.wordpress.com/738-2/ (GPU Zen 2 chapter with simplifications)

### 3.2 Wang Tiles for Terrain

**Concept (Cohen et al. 2003, GPU Gems 2):** Wang tiles are square tiles where each edge is assigned a "color" (not visual color — just an ID). A valid tiling requires adjacent tiles to share matching edge colors. With 16 tiles (4 sides × 2 colors = 2⁴), you get a non-periodic pattern that eliminates obvious repetition.

**Implementation:**
1. Pack all 16 tile variants into a single atlas texture
2. Precompute an index texture mapping UV coordinates to tile IDs
3. In the shader: look up which tile to use from the index texture, then sample from the atlas

```hlsl
// Given UV coordinate
float2 tileIndex = floor(uv * numTiles);
// Look up which Wang tile to use
float2 tileID = indexTexture.Sample(sampler, tileIndex / numTiles);
// Sample from the atlas at the right tile
float2 inTileUV = frac(uv * numTiles);
float2 atlasUV = (tileID + inTileUV) / 4.0; // 4×4 atlas
return albedoAtlas.Sample(sampler, atlasUV);
```

**Limitation:** Requires pre-authored tile set with matching edges. Less flexible than stochastic sampling but predictable.

**Source:** http://developer.nvidia.com/gpugems/gpugems2/part-ii-shading-lighting-and-shadows/chapter-12-tile-based-texture-mapping

### 3.3 Hex Tiling (Heitz 2018) — Practical and Fast

**Paper:** "Procedural Stochastic Textures by Tiling and Blending" (GPU Zen 2, Thomas Deliot and Eric Heitz)
**Source:** https://eheitzresearch.wordpress.com/738-2/

Hex tiling partitions texture space into hexagonal regions (implemented as adjacent triangles of a hex grid). For each pixel:
1. Determine which hex region it belongs to
2. Fetch textures from the three adjacent triangle vertices (3 taps)
3. Blend using barycentric weights

**Difference from full histogram-preserving:** Hex tiling uses the same grid structure as Heitz & Neyret 2018 but the blending is simpler — some implementations use dithering instead of sampling the texture three times, reducing cost to 1–2 taps.

**For terrain use:**
- Works excellently for chaotic, directionless surfaces: grass, dirt, concrete, gravel
- **Fails for directional textures:** Wood grain, brick patterns, anything with a strong orientation. Use UV offset in discrete steps (e.g., 1/10 increments for a 10-tile surface) to align seams
- Cost: 3 texture taps, but dithered variants need only 1–2

**Practical ArtStation breakdown:** The `Stepped Offsets` variant (Steps_U, Steps_V parameters) ensures grids align correctly when tiling structured patterns.

**Source:** https://www.artstation.com/blogs/haukethiessen/BPb7/cheap-hex-tiling-for-every-occasion

### 3.4 Horizon Zero Dawn — AAA Anti-Tiling in Production

Guerrilla's DECIMA engine (Horizon Zero Dawn) breaks texture repetition through **ecotope-based colorization**. Rather than shader tricks, they solve it at the content layer:

- The world is divided into ecotopes — biome-level zones that define distinct color palettes and asset distributions
- Assets (rocks, vegetation) are colorized per-ecotope, so terrain variation comes from consistent color shifts across the world
- GPU-driven procedural placement ensures no two areas use the exact same asset at the same density
- This is supplemented by the terrain texture being blended with colorization data from the biome map

**Key insight:** The best anti-tiling is not a shader trick — it's visual diversity through variation in what's *on* the terrain (vegetation, debris, decals) breaking up the surface read.

**Source:** https://www.guerrilla-games.com/read/gpu-based-procedural-placement-in-horizon-zero-dawn
**Source:** https://www.slideshare.net/guerrillagames/gpubased-procedural-placement-in-horizon-zero-dawn

### 3.5 Summary: Which Technique to Use When

| Technique | Best For | Taps | Preprocessing |
|-----------|----------|------|---------------|
| Histogram-Preserving (Heitz/Neyret) | All stochastic textures, max quality | 3 | LUT bake needed |
| Hex Tiling (Deliot/Heitz) | Terrain surfaces, good performance | 1–3 | None (or optional LUT) |
| Wang Tiles | Predictable pattern coverage | 1 (atlas) | Tile set authoring |
| Distance Resampling (MicroSplat) | Simple distance-based scale break | 1 extra | None |
| Ecotope Colorization (Guerrilla) | World-scale variation | N/A | World layout authoring |

---

## 4. TRIPLANAR PROJECTION

### 4.1 When to Use Triplanar vs. UV Projection

**Use UV projection** for flat or gently rolling terrain where stretching is not visible. UV terrain textures tile cleanly on horizontal surfaces.

**Use triplanar projection** for:
- Cliff faces (slopes > 45°) where standard UV creates obvious stretching
- Rock formations with complex geometry
- Any terrain feature visible from the side as well as top

Triplanar samples the texture along all three world-space axes (XY, XZ, YZ planes) and blends between them based on the surface normal. Near-vertical normals → use XZ and YZ samples. Near-horizontal → use XY sample.

### 4.2 Performance Cost of Triplanar

Full triplanar = **3 texture samples per texture map** (one per axis) instead of 1. For a PBR material with Albedo + Normal + Roughness:
- Standard UV: 3 taps
- Full triplanar: 9 taps

**Optimization: biplanar for cliffs.** Cliff faces are not seen from below, so the Y plane sample is wasted. Use only X and Z plane samples (2 instead of 3), halving the extra cost. This is documented in the open-source Unity cliff shader.

**Source:** https://github.com/radiatoryang/unity-triplanar-terrain-cliff-shader

### 4.3 UE5 Triplanar — WorldAlignedTexture Node

Unreal Engine 5 provides the `WorldAlignedTexture` and `WorldAlignedNormal` Material Expression nodes. Key considerations from the UE5 deep-dive (80.lv, Dec 2025):

- Default `WorldAlignedTexture` is world-space dependent — moving the terrain moves the projection, causing swimming artifacts
- For predictable results: convert to Local Space projection by using `TransformPosition` and `TransformVector` nodes
- For multi-mesh environments (modular cliffs): use a shared world-space anchor so patterns align across separate meshes
- `WorldAlignedNormal_HighQuality` gives accurate normals at extra cost; use for hero areas only

**Cliff texturing pattern (Unity + UE5):**
```
slope_mask = saturate((dot(world_normal, float3(0,1,0)) - slope_threshold) / blend_width)
cliff_color = triplanar_sample(cliff_texture, world_pos, world_normal)
terrain_color = standard_uv_sample(terrain_texture, uv)
final_color = lerp(cliff_color, terrain_color, slope_mask)
```

**Source:** https://80.lv/articles/ue5-triplanar-deep-dive-from-worldalignedtexture-to-high-quality-normals-part-1

### 4.4 Unity HDRP Triplanar

In HDRP, surface shaders do not exist — use Shader Graph. The `Triplanar` node is available directly in Shader Graph. Important note from community research:

- Do **not** use per-terrain-layer triplanar naively — sample cost multiplies by layer count
- Use a **single cliff texture with triplanar** as the top-level override, masked by slope angle
- MicroSplat's built-in cliff/triplanar module handles this correctly

**Source:** https://discussions.unity.com/t/triplanar-cliff-shading-with-terrains/893850

---

## 5. MACRO VARIATION

### 5.1 What Macro Variation Does and Why It's Non-Negotiable

Without macro variation, terrain textures collapse to a single color from any distance, and close-up tiling is obviously repetitive. AAA terrain always has three distinct scales of visual information:

1. **Micro detail (0–5m):** High-frequency surface texture (pebbles, grass blades, bark chips)
2. **Mid detail (5–50m):** Standard tiling texture (tile size 2–8m)
3. **Macro variation (50m–1km):** Large-scale color and normal variation that breaks the repetition of mid-detail and prevents "wallpaper" terrain

### 5.2 Vista UVs — Activision / Call of Duty Technique (SIGGRAPH 2023)

From Activision's "Large Scale Terrain Rendering" (Advances in Real-Time Rendering 2023):

**Problem:** At distance, all mipmaps collapse to a single color from the high-detail textures, making terrain look flat and uniform.

**Vista UVs solution:**
1. Compute a second set of UVs = original UVs but scaled down (texture zoomed out — lower magnification)
2. Sample albedo and normal again at this macro scale
3. Lerp between regular (detail) contribution and macro contribution based on camera distance
4. Close to camera: detail textures dominant. Far away: macro textures dominant.

```hlsl
float2 detailUV = worldPos.xz / detail_tile_size;
float2 macroUV = worldPos.xz / macro_tile_size;  // much larger: macro_tile_size >> detail_tile_size

float4 detailAlbedo = tex2D(albedoTex, detailUV);
float4 macroAlbedo = tex2D(albedoTex, macroUV);  // same texture, different scale

float distanceFade = saturate((cameraDistance - start_dist) / (end_dist - start_dist));
float4 finalAlbedo = lerp(detailAlbedo, macroAlbedo, distanceFade);
```

**VT incompatibility:** Vista UVs rely on camera distance, but Virtual Texture pages have no camera concept. Activision's fix: translate mip levels to camera distances (mip 0 = 5 feet, each mip doubles distance). Creates discontinuity in mip chain — still being resolved in production.

**Source:** https://advances.realtimerendering.com/s2023/Etienne(ATVI)-Large%20Scale%20Terrain%20Rendering%20with%20notes%20(Advances%202023).pdf (Activision, SIGGRAPH 2023)

### 5.3 UE4 Macro Texture System (UDK, still relevant)

Unreal Engine has had terrain macro textures since UDK. The system:
- Uses a grayscale macro blend mask (128–1024px, tileable)
- Blends between two source textures (e.g., grass + dirt) according to the mask
- Macro texture can be packed 4-into-1 using RGBA channels (4 different blend masks in one texture)
- TexCoord scale: 0.125 (8x) to 0.25 (4x) — controls how large the macro pattern appears on terrain

**Source:** https://docs.unrealengine.com/udk/Three/TerrainAdvancedTextures.html

UE5 still supports this through the `LandscapeLayerBlend` node's weight map blending with low-frequency macro masks.

### 5.4 Open 3D Engine (O3DE) — Macro Material + Detail Material Architecture

O3DE's terrain system separates concerns cleanly and is worth modeling:

**Macro Material:** Low-fidelity color + normal texture applied over the full terrain extent. Used for:
- Color source for terrain beyond detail render distance
- Color variation layered under detail materials to prevent uniformity

**Detail Material:** High-fidelity tiling PBR material, only rendered within a configurable radius from camera. Blended with macro material in-camera-radius to provide color variation as detail textures repeat.

```
Final terrain color = lerp(macro_color, detail_color, detail_blend_factor)
```
where `detail_blend_factor` goes to 0 at max detail render distance.

**Source:** https://docs.o3de.org/docs/user-guide/components/reference/terrain/terrain-macro-material/
**Source:** https://docs.o3de.org/docs/user-guide/components/reference/terrain/terrain-detail-material/

### 5.5 Macro Normal Map

A macro normal map is a low-frequency (large-scale) normal map stretched over the full terrain. It gives the terrain broad lighting variation that makes distant terrain look like it has large-scale shape, without requiring actual high-density geometry at that range.

O3DE notes: "Macro normals must be in world space and generated at the same terrain scale in all dimensions." They are difficult to author correctly and not recommended for typical use — but when done right, they eliminate the "flat plastic" look of low-poly distant terrain.

**Practical approach for VeilBreakers:** Generate the macro normal by blurring the terrain heightmap normals to 1/16th resolution, then use as a low-frequency normal blend at distance.

**Source:** https://docs.o3de.org/docs/user-guide/components/reference/terrain/terrain-macro-material/

### 5.6 Distance-Based Material Blending

The pattern used by UE5 landscape materials:

1. **Near (0–10m from camera):** Full PBR detail — 4K tiling textures, POM displacement, triplanar cliffs
2. **Mid (10–100m):** Standard tiling textures, normal + roughness only, no displacement
3. **Far (100m+):** Macro color texture only, no normal variation from PBR — use macro normal map
4. **Horizon (500m+):** Terrain color blends to atmospheric fog/haze, no texture contribution at all

Camera depth fade or distance scalar controls the LOD transitions. The `PixelDepth` expression in UE5 materials gives per-pixel distance for smooth crossfades.

---

## 6. STEP-BY-STEP TEXTURE PIPELINE CHECKLIST

This is the full ordered checklist from raw Quixel asset to correctly blended terrain material:

### Phase 1: Asset Acquisition & Validation

- [ ] Download Megascans surface assets (prefer 4K for base terrain, 8K for hero areas)
- [ ] Verify all required maps exist: Albedo, Normal, Roughness, AO, Displacement, Metallic (if any)
- [ ] Check Albedo is free of baked lighting (flat-lit appearance without directional shadow)
- [ ] Verify Normal map convention: Quixel exports OpenGL convention (Y+ = up). Unity uses OpenGL. UE5 uses DirectX (flip G channel if using UE5: `Normal_G = 1.0 - source_G`)
- [ ] Verify physical size of scan (printed in Megascans metadata, e.g., "91×91cm") — needed for tiling scale calculation

### Phase 2: Color Space Assignment

- [ ] Import Albedo: mark as **sRGB**
- [ ] Import Normal: mark as **Linear / Non-Color**
- [ ] Import Roughness: mark as **Linear / Non-Color**
- [ ] Import AO: mark as **Linear / Non-Color**
- [ ] Import Displacement: mark as **Linear / Non-Color**
- [ ] Import Metallic: mark as **Linear / Non-Color**

### Phase 3: Channel Packing

- [ ] Create ORM packed texture: R=AO, G=Roughness, B=Metallic
- [ ] Create Height+Albedo packed texture: RGB=Albedo, A=Displacement (for Terrain3D-style packing)
- [ ] Alternatively: create 4-heights packed texture (RGBA = height of each of 4 layers) for height-blend shader
- [ ] Export packed textures at same resolution as source maps

### Phase 4: Terrain Material Setup

- [ ] Set up height-based blending (not alpha blending) — pack 4 height maps into one RGBA texture
- [ ] Configure splatmap: one RGBA texture per 4 layers of blend weights
- [ ] Assign correct tiling scale per layer based on physical scan size (e.g., 91cm scan → tile at 0.91m → 91 tiles per 83m)
- [ ] Enable cliff/slope masking: add slope_mask = dot(normal, up) threshold for triplanar transition

### Phase 5: Anti-Tiling

- [ ] Implement stochastic sampling (hex tiling or histogram-preserving) for all ground-plane textures
- [ ] Implement Distance Resampling: add second UV scale for distant terrain samples
- [ ] Add Normal Noise: blend a secondary normal at 3–5x lower frequency over the primary normal
- [ ] Validate: zoom out to 100–500m and check for visible grid pattern in the texture — if visible, increase randomization
- [ ] Quality check: take a screenshot with color-only view (no lighting), look for obvious grid structure

### Phase 6: Macro Variation Layer

- [ ] Create or obtain a low-frequency color variation texture (512–2K, tileable, subtle hue/brightness variation)
- [ ] Set macro UV scale to 64–256m tiling
- [ ] Blend macro color into detail albedo: `final = lerp(macro, detail, camera_distance_fade)`
- [ ] Optionally add a macro normal at 128–512m scale for distant terrain lighting variation
- [ ] Quality check: fly the camera from 2m altitude to 1km altitude — color should transition smoothly without snapping

### Phase 7: Distance LOD

- [ ] Implement Vista UVs: sample detail texture at both detail scale and 8–16× macro scale, lerp by distance
- [ ] Configure detail render distance (O3DE-style or custom): beyond X meters, detail maps fade out
- [ ] Verify: terrain should look coherent at all distances from ground-level to aerial overview

### Phase 8: Displacement / Tessellation

- [ ] Enable tessellation or POM (Parallax Occlusion Mapping) for close-up hero areas
- [ ] Set tessellation factors: max 8–16 (optimal for console-class GPUs)
- [ ] Per-texture displacement strength controls (MicroSplat pattern): rock = high, dirt = medium, moss = low
- [ ] Fallback shader for beyond tessellation range (flat mesh, normal map only)

### Phase 9: Wetness Integration

- [ ] Implement wetness mask: driven by terrain water level, slope (water pools in low areas), and noise
- [ ] Per-wetness-value modifications:
  - Roughness: decrease by 0.3–0.5 (wet surfaces are smoother)
  - Specular: increase slightly (wet surfaces catch more light)
  - Albedo: darken by 0.1–0.2 (wet surfaces absorb light)
  - Normal: smooth (flatten micro-normals slightly — water fills micro-crevices)
- [ ] Puddle accumulation: use height map to identify low-point crevices where water accumulates
  - Puddle mask = `saturate(wetness_accumulation * height_inverted - threshold)`
  - Puddle roughness: ~0.02–0.05 (near-mirror)
  - Puddle reflections: screen-space or planar reflection

### Phase 10: Quality Validation

- [ ] No visible tile grid at any viewing distance (anti-tiling working)
- [ ] Smooth, natural transitions between terrain layers (height blending working)
- [ ] Terrain does not look uniform from 200m+ (macro variation working)
- [ ] Cliff faces do not show stretched texture (triplanar working)
- [ ] Wetness areas have lowered roughness and puddles in low spots
- [ ] Normal map directions consistent — no backward-lit surfaces
- [ ] Check "dark seams" at terrain tile boundaries (height-blend zero-weight issue)

---

## 7. DARK FANTASY SPECIFIC

### 7.1 Material Palette for Dark Fantasy Terrain

VeilBreakers requires a specific material language that communicates decay, corruption, and supernatural dread. These are the surface types and their PBR parameters:

#### Wet Rock / Stone
- **Albedo:** Dark grey to near-black (HSV: S=0.05–0.10, V=0.10–0.30)
- **Roughness:** 0.6–0.8 dry, 0.15–0.35 wet
- **AO:** High contrast crevice AO — emphasize cracks and fissures
- **Normal intensity:** High — rock surfaces should read strongly even at distance
- **Triplanar:** Required for cliff faces
- **Wetness response:** Strong — dark stone darkens significantly when wet, puddles in natural crevices

#### Dark Soil / Dead Ground
- **Albedo:** Desaturated brown-black (HSV: H=20–30, S=0.1–0.2, V=0.08–0.18)
- **Roughness:** 0.7–0.9 (very matte — compressed organic material)
- **Displacement:** Low frequency undulation (2–4cm variation)
- **Variation:** Mix with fine gravel/pebble overlay using height-blend. Pebbles should "win" on high points of the displacement.
- **Anti-tiling critical:** Dark uniform soil is the worst offender for visible tiling. Apply histogram-preserving blending.

#### Dead / Dry Vegetation (Grass, Leaves)
- **Albedo:** Ochre to tan (HSV: H=30–50, S=0.2–0.4, V=0.3–0.5) — not green
- **Roughness:** 0.75–0.90 (dried organic matter is matte)
- **Normal:** Light — dead vegetation has minimal surface relief
- **Placement:** Height-blend with soil — dead grass on the high points of terrain microdetail, soil in the low

#### Corrupted / Dark Fantasy Stone
This is a fantasy-specific surface requiring creative extension of real-world PBR:
- **Albedo:** Deep purple-grey to void-black with subtle iridescent edge variation (hint of color in specular, not albedo)
- **Roughness:** Varies: 0.2–0.4 for "crystalline" corrupted surfaces, 0.6–0.8 for "necrotic stone"
- **Metallic:** 0 for stone, up to 0.3 for "dark crystal" corruption (metallic without being chrome)
- **Emissive:** Optional low-value emission (0.05–0.15 intensity) in crack channels — drives perception of internal energy without full glow
- **Normal:** High micro-contrast in crack regions (AO channel drives edge wear exaggeration)
- **Cavity map:** Critical — drives subtle self-shadowing of corruption cracks

#### Moss (Living vs. Dead)
- **Living moss:** HSV H=90–120, S=0.4–0.6, V=0.3–0.5, Roughness=0.7–0.85
- **Dead moss:** HSV H=40–70, S=0.1–0.2, V=0.15–0.3, Roughness=0.8–0.95
- **Placement:** Living moss only in water-adjacent areas (slope mask, proximity to water features). Dead moss everywhere else.
- **Height-blend with rock:** Moss collects in low crevices, rock protrudes at high points

### 7.2 Wetness Driven by the Terrain Water System

The terrain water system should write a **wetness scalar field** (0–1) to a render texture or virtual texture channel, sampled by the terrain material shader.

**Wetness generation rules:**
1. **Base wetness from water body proximity:** Cells within X meters of a river/lake/waterfall: wetness = 1
2. **Slope accumulation:** Low-lying areas accumulate water: `wetness_slope = saturate(1.0 - normalized_slope) * base_wet`
3. **Height offset:** Below the water table height + epsilon: wetness = 1 (submerged)
4. **Decay with distance:** Wetness falls off from water source using exponential decay: `wetness = water_proximity_wet * exp(-distance / wet_falloff_radius)`
5. **Noise variation:** Apply medium-frequency Perlin noise (5–15m scale) to prevent sharp wetness boundaries: `wetness = wetness * noise_scale + noise_base`

**Terrain material wetness response (based on Lux Shader documentation):**
```hlsl
// In terrain material shader:
float wet = wetness_field.Sample(sampler, worldXZ / wetness_tile_size);

// Darken albedo (porous materials absorb light when wet)
albedo = lerp(albedo, albedo * 0.7, wet * porosity_map);

// Smooth roughness toward water roughness (0.02)
roughness = lerp(roughness, 0.02, wet * 0.6);

// Smooth normals (water fills micro-crevices)
float3 wetNormal = normalize(lerp(normal, float3(0,0,1), wet * 0.3));

// Puddle accumulation in low spots
float puddle_mask = saturate(wet * (1.0 - height_map) - puddle_threshold);
// Where puddle_mask > 0: override with water surface material (roughness~0.02, flat normal)
```

**Source (Lux Shader wetness model):** https://github.com/larsbertram69/Lux/blob/master/Lux%20Shader/Wetness/_Lux%20Wetness%20Shaders.txt

**MicroSplat integration:** MicroSplat's "Puddles, Streams, Lava & Wetness" module implements this exact flow with:
- `Puddle Accumulation` parameter (driven externally for rain simulation)
- Height-map-driven puddle placement (low terrain points fill first)
- Wetness also affects normal smoothing and albedo darkening

**Source:** https://assetstore.unity.com/packages/tools/terrain/microsplat-ultimate-bundle-180948

### 7.3 Dark Fantasy Specific Shader Patterns

**Corruption spread material blend:**
Use a corruption scalar (0–1) stored in a channel of the wetness/special-effects virtual texture:
```
terrain_color = lerp(normal_terrain, corrupted_terrain, corruption_mask)
```
Corruption mask should follow low terrain (corruption pools in valleys), proximity to corruption sources (handplaced), and organic noise (use FBM noise for natural spread).

**Blood/ichor puddles:** Same as wetness puddles but:
- Albedo: deep red-black (H=0–15, S=0.6–0.8, V=0.05–0.15)
- Roughness: 0.05–0.10 (fresh blood is glossy)
- Normal: flat (liquid surface)
- Drive with separate ichor accumulation mask, not the water system

**Ash/bone ground:**
- Albedo: pale grey-white (V=0.65–0.80, near-desaturated)
- Roughness: 0.85–0.95 (ash is extremely matte)
- Displacement: low, rounded forms (ash settles into smooth blanket)
- Height-blend under larger rocks: ash covers low terrain, rocks poke through

---

## 8. KEY SOURCES

### Primary Research Papers
- Heitz & Neyret 2018 — Histogram-Preserving Blending: https://eheitzresearch.wordpress.com/722-2/
- Deliot & Heitz GPU Zen 2 — Procedural Stochastic Textures: https://eheitzresearch.wordpress.com/738-2/
- JCGT 2019 — HPB extension: https://www.jcgt.org/published/0008/04/02/paper.pdf

### AAA GDC / Conference Material
- CDPR REDengine 3 Landscape (GDC 2014): https://www.gdcvault.com/play/1020197/Landscape-Creation-and-Rendering-in
- Guerrilla / Horizon Zero Dawn GPU Placement (GDC 2017): https://www.gdcvault.com/play/1024120/GPU-Based-Run-Time-Procedural
- Activision COD Terrain (SIGGRAPH 2023): https://advances.realtimerendering.com/s2023/Etienne(ATVI)-Large%20Scale%20Terrain%20Rendering%20with%20notes%20(Advances%202023).pdf
- Activision COD Terrain Virtual Texturing (GDC 2021): https://research.activision.com/publications/2021/09/boots-on-the-ground--the-terrain-of-call-of-duty

### Tools and Implementations
- MicroSplat Anti-Tiling Module: https://assetstore.unity.com/packages/tools/terrain/microsplat-anti-tiling-module-96480
- MicroSplat Texture Clusters: https://assetstore.unity.com/packages/tools/terrain/microsplat-texture-clusters-104223
- MicroSplat Tessellation: https://assetstore.unity.com/packages/tools/terrain/microsplat-tessellation-and-parallax-96484
- MegaSplat (256 texture index-based): https://assetstore.unity.com/packages/tools/terrain/megasplat-76166
- Unity Labs stochastic texturing: https://github.com/UnityLabs/procedural-stochastic-texturing
- Terrain3D Godot channel packing: https://terrain3d.readthedocs.io/en/latest/docs/texture_prep.html
- Lux Shader wetness model: https://github.com/larsbertram69/Lux/blob/master/Lux%20Shader/Wetness/_Lux%20Wetness%20Shaders.txt

### Documentation
- UE4 Landscape Materials (LB_HeightBlend): https://docs.unrealengine.com/4.26/en-US/BuildingWorlds/Landscape/Materials/
- O3DE Terrain Macro Material: https://docs.o3de.org/docs/user-guide/components/reference/terrain/terrain-macro-material/
- O3DE Terrain Detail Material: https://docs.o3de.org/docs/user-guide/components/reference/terrain/terrain-detail-material/
- Quixel Mixer channel controls: https://docs.quixel.com/mixer/1/en/topic/channel-specific-controls.html
- Unity height-blend 4-layer bypass: https://medium.com/@sinitsyndev/removing-the-4-layer-limit-for-height-based-blending-in-unity-terrain-urp-c0ba85444f58
- UE5 Triplanar deep-dive: https://80.lv/articles/ue5-triplanar-deep-dive-from-worldalignedtexture-to-high-quality-normals-part-1
- Unity triplanar cliff shader: https://github.com/radiatoryang/unity-triplanar-terrain-cliff-shader

### Texel Density Reference
- Beyond Extent texel density guide: https://www.beyondextent.com/deep-dives/deepdive-texeldensity
- Polycount AAA FPS texel density discussion: https://polycount.com/discussion/234887/texel-density-standards-for-aaa-first-person-shooter-games

---

## APPENDIX: VEILBREAKERS PRIORITY ACTION ITEMS

Based on this research, the highest-priority improvements for VeilBreakers terrain texturing (in order of visual impact):

1. **CRITICAL — Switch to height-based blending.** Implement the 4-weight HLSL function. Pack heights into RGBA texture. Expected visual improvement: dramatic — transitions from mud to rock, soil to stone will look like REDengine 3 instead of Unity 2018.

2. **CRITICAL — Add macro variation layer.** Implement Vista UVs or a simple macro color texture at 128m tiling. Expected improvement: terrain will no longer look like wallpaper from >50m altitude.

3. **HIGH — Anti-tiling via hex tiling or Distance Resampling.** Implement the Deliot/Heitz hex tiling or MicroSplat's Distance Resampling for all ground-facing terrain layers. Expected improvement: eliminates the most obvious sign of amateur terrain work.

4. **HIGH — Fix color space assignments.** Every non-color map must be Linear. A single wrong color space causes entire PBR system to malfunction.

5. **HIGH — Triplanar for cliffs.** Any terrain slope > 45° needs triplanar. Use biplanar (XZ only) for performance.

6. **MEDIUM — Drive wetness from water system.** Connect water body proximity → wetness scalar → roughness/albedo/puddle in terrain material.

7. **MEDIUM — Dark fantasy palette pass.** Desaturate and darken albedo values. Standard rock is too light and saturated for VeilBreakers' aesthetic. Target: V < 0.30 for stone, V < 0.20 for soil.

8. **LOW — Tessellation for hero areas.** Enable POM or tessellation within 15m of camera for featured terrain zones (entrances, ritual sites, boss arenas).
