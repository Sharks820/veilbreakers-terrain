# VeilBreakers Materials & Texturing Audit
**Date:** 2026-04-24  
**Reference bar:** Horizon Zero Dawn terrain — height+slope-blended PBR, tiling normal maps, macro-variation  
**Files audited:**
- `scripts/build_scene_v3.py` (lines 279–654)
- `veilbreakers_terrain/handlers/terrain_quality_profiles.py`
- `veilbreakers_terrain/handlers/vertex_paint_live.py`

---

## Grade Summary Table

| Material / System | Grade | Dominant Failure |
|---|---|---|
| Terrain material — overall | **D** | No macro-variation, no tiling normal maps, no vertex-color input, no snow cap |
| Terrain — height blending | C | 5 stops present but no snow cap; wetland/grass stops are opaque flat colors |
| Terrain — slope masking | C | Present but disconnected from roughness correctly; no triplanar UV |
| Terrain — macro-variation | **F** | Zero macro noise node; tiling break completely absent |
| Terrain — micro-detail normals | D | Bump only from a single reused noise node; no tiling rock/grass normal maps |
| Terrain — vertex color override | **F** | Vertex color input not created, not read, not connected anywhere |
| Water material — Fresnel | C | Fresnel present, capped at 0.68 — correct; but Diffuse+Glossy is non-physical |
| Water material — IOR/depth absorption | **F** | No volume absorption, no Principled BSDF transmission; flat Diffuse tint only |
| Water material — surface ripple normal | C | Voronoi "2D" fix applied; but ripple normals feed only a bump node, not Normal input |
| Rock/cliff material | **D** | Single flat-color Principled BSDF; no tiling normal map, no AO moss/weathering |
| Snow material | **F** | No snow material exists at all; high-altitude zone blends into grey stone flat color |
| Beach sand material | D | Flat base color + noise bump; no normal map, no wet-zone roughness variation |
| Tree foliage — pine | C | Subsurface Weight attempted; roughness set; no translucency map |
| Tree bark | D | Flat brown color only; no normal/roughness variation |
| Grass material | D | Flat green Principled BSDF; no normal, no translucency, no alpha |
| Quality profiles — wiring | **F** | `terrain_quality_profiles.py` is entirely unwired from `build_scene_v3.py` |
| Vertex paint — wiring | **F** | `vertex_paint_live.py` functions never called from build_scene_v3.py |
| blend_method=BLEND on Cycles mats | BUG | Lake/River/Waterfall set `blend_method="BLEND"` — EEVEE-only, silent no-op in Cycles |

---

## A. Terrain Material Layers (lines 279–382 build_scene_v3.py)

### What exists
- `ShaderNodeNewGeometry` → `SeparateXYZ` for both Normal and Position — correct sourcing
- Slope mask: `1 - normal.z` fed through `ValToRGB` with two stops at 0.22 / 0.65
- Altitude ramp: `MapRange` 0..320 m → `ValToRGB` with 5 colour stops (wetland, grass, dirt, rock-dirt, stone)
- Rock noise: `ShaderNodeTexNoise` (scale 8, detail 8, roughness 0.65) fed via `MixRGB` for rock albedo variation
- Final blend: slope factor → `MixRGB`(altitude_color, rock_color) → `Base Color`
- Roughness: slope ramp → `ValToRGB` → `Roughness` input (0.65–0.92 range)
- Bump: same noise node → `ShaderNodeBump` (strength 0.45, dist 0.08) → `Normal`

### What is missing vs Horizon Zero Dawn

| Feature | HZD | VeilBreakers | Gap |
|---|---|---|---|
| Snow cap above ~280 m | Yes, separate PBR layer | No — grey stone flat color (#e5:333) | **Missing** |
| Slope mask drives rock | Yes, per-texel | Partial — only albedo, not normal layers | Partial |
| Macro-variation (large albedo noise, ~50–200 m scale) | Yes, breaks tiling | None | **Missing** |
| Tiling rock normal map (6–12 m tile) | Yes | Only procedural bump from one noise | **Missing** |
| Tiling grass normal map | Yes | None | **Missing** |
| Triplanar UV mapping | Yes, prevents UV seams on cliffs | None; geometry uses world-space Position only but no triplanar projector node | **Missing** |
| Vertex color channel to override biome | Yes, hand-paint wetlands/paths | `vertex_paint_live.py` exists but is never read by material | **Missing / Unwired** |
| AO baked or SSAO modulation of surface roughness | Yes | None | **Missing** |

### Grade: D
The slope×altitude structure is a valid skeleton but every surface-quality layer (macro noise, tiling normal, triplanar projection, snow, vertex paint) is absent. Against HZD this is a low-A-title placeholder, not a shippable layer.

---

## B. PBR Completeness

### B.1 Terrain (VB_TerrainPBR — lines 279–382)
- **Albedo:** Procedural colour ramp — no tiling PBR texture. Acceptable for baked-procedural pipeline IF macro noise is added.
- **Normal:** Single noise → Bump only. No tiling rock/grass normal map. Bump distance = 0.08 m — far too small to read at 1024 m tile scale.
- **Roughness:** Slope-driven 0.65–0.92 range. Wet/water zones do NOT lower roughness (water edge should drop to ~0.3). Single direction only.
- **AO:** None connected.
- **Grade: D**

### B.2 Water — Lake / River / Waterfall (lines 388–480)
- **Albedo:** Diffuse node with tint colour. Always visible — intentional anti-mirror fix.
- **Normal:** Voronoi 2D + noise → Bump → fed to Diffuse and Glossy Normal inputs. Voronoi `.voronoi_dimensions = "2D"` fix applied at line 419. Valid.
- **Roughness:** Lake=0.18, River=0.10, Waterfall=default. Reasonable range.
- **AO:** None.
- **Transmission/depth:** Zero. Deep lake is flat-tinted diffuse — no blue-green depth absorption whatsoever.
- **Grade: C−** (Fresnel correct; depth absorption completely missing)

### B.3 Rock (VB_RockMat — lines 914–934)
- **Albedo:** Single flat colour (0.18, 0.15, 0.11). No noise variation per rock.
- **Normal:** None connected. Principled BSDF Normal input is empty.
- **Roughness:** Single value 0.88. No wet-face variation, no moss in concavities.
- **AO:** None.
- **Grade: D**

### B.4 Snow
- **Does not exist.** High-altitude band uses the terrain material's top stop `(0.52, 0.50, 0.48, 1)` — a flat grey stone colour.
- **Grade: F**

### B.5 Beach Sand (VB_BeachSand — lines 634–650)
- **Albedo:** Flat `(0.64, 0.55, 0.36, 1)` + noise bump. No tiling PBR.
- **Normal:** noise → Bump → Normal. Reasonable.
- **Roughness:** 0.91 fixed. Wet shoreline (near LAKE_WATER_LEVEL) should drop to ~0.55.
- **AO:** None.
- **Grade: D**

### B.6 Tree Foliage / Bark (lines 778–841)
- **Pine Foliage / BroadFoliage:** `Subsurface Weight` attempted (0.10/0.12) — correct Blender 4.x parameter. No translucency map; no alpha mask; no normal map.
- **PineBark:** Flat colour + roughness only. No normal.
- **Grade: C** (subsurface partially correct; everything else absent)

### B.7 Grass (VB_GrassMat — lines 984–988)
- Flat green colour, roughness 0.80. No translucency, no alpha, no normal.
- Should use `Alpha` input with a blade mask and `blend_method` = `CLIP` (or Cycles transparent BSDF).
- **Grade: D**

---

## C. Water Material Deep-Dive

### C.1 Fresnel
- `ShaderNodeFresnel` with IOR 1.333 (water, correct) is present. Output is capped at 0.68 via MULTIPLY node before driving `MixShader`. This correctly forces minimum 32% diffuse blue visibility. **Pass.**

### C.2 IOR / Depth Absorption
- **MISSING.** Correct approach for Cycles is `ShaderNodeVolumeAbsorption` connected to `Volume` output of the material Output node, with density driven by a `MapRange` on object-space Z depth. Currently only a Diffuse+Glossy surface shader with no volume. Deep lake water looks opaque-flat-blue.

### C.3 Ripple Normal Map
- `vor.voronoi_dimensions = "2D"` is set at line 419 — confirmed the fix is in place.
- Voronoi `Distance` output + noise `Fac` → mixed → `ShaderNodeBump` → Normal. The ripple only exists as bump; not a dedicated ripple normal map animated with an offset. Static water.
- **Grade: C** — structural fix applied; depth missing; no animation offset

---

## D. Cliff / Rock Material

The `VB_RockMat` used for scattered rocks (lines 914–934):
- Single `Principled BSDF` node, flat colour 0.18/0.15/0.11, roughness 0.88.
- No tiling rock surface normal — rocks will read perfectly smooth under close inspection.
- No AO-driven moss / weathering blend in concavities.
- No variation between the 4 template rock meshes (all share one material).

**Grade: D**

---

## E. Snow Material

Completely absent. The highest altitude color ramp stop (position 0.86–1.00) bleeds from grey stone (0.40, 0.38, 0.36) to a slightly lighter grey. There is no:
- White albedo high stop
- Subsurface scattering (soft snow SSS)
- Sparkle noise (crystalline glint)
- Wet-edge lower roughness at snowmelt transition

**Grade: F**

---

## F. Quality Profiles Wiring Audit

`terrain_quality_profiles.py` defines four canonical tiers (`mobile`, `standard`, `high_fidelity`, `aaa_open_world`) with `texture_resolution` (128→4096), `normal_map_resolution` (128→4096), `roughness_variation_strength` (0.1→0.5), `splatmap_layer_count=4` on all tiers.

**Search result:** `build_scene_v3.py` does not import `terrain_quality_profiles` anywhere. Zero calls to `load_quality_profile()`. None of the profile texture/normal resolution fields are referenced by any material-building function.

**Verdict: Dead/Unwired code.** The profiles exist but the material factory functions in build_scene_v3.py ignore them entirely. `texture_resolution: int = 4096` has no effect on any created material. `roughness_variation_strength` is never applied to the roughness ramp.

**Grade: F (wiring)**

---

## G. Shader Hygiene

| Issue | Location | Severity |
|---|---|---|
| `blend_method = "BLEND"` on Cycles water materials | build_scene_v3.py:513,554,585 | Bug — EEVEE-only; does nothing in Cycles render pipeline |
| `ShaderNodeMixRGB` used instead of `ShaderNodeMix` (type='RGBA') | build_scene_v3.py:351,358,424 | Deprecated in Blender 4.0+; still functional in 4.5 but will warn |
| `mesh.use_auto_smooth` + `mesh.auto_smooth_angle` | build_scene_v3.py:269-270 | Removed in Blender 4.1; wrapped in try/except so non-fatal; use Smooth by Angle modifier instead |
| Roughness input fed a Color socket output | build_scene_v3.py:371 | `rough_ramp.outputs["Color"]` → `Roughness` — color-to-float implicit conversion is fine in Cycles (takes luminance) but fragile; use `Color` → `Separate RGB` → `R` channel |
| Bump Distance = 0.08 m on 1024 m terrain | build_scene_v3.py:378 | Effectively invisible at tile scale; should be 1.0–3.0 m |
| Water Bump Distance = 0.20 m | build_scene_v3.py:430 | Reasonable for ripple scale; OK |
| Noise node `Distortion` key iteration with try/except | build_scene_v3.py:409-415 | Fragile; in Blender 4.5 the key is `Distortion` (capital D); use direct assignment |
| No UV map on terrain mesh | build_scene_v3.py:240-273 | Tiling normal maps are impossible without UVs or triplanar nodes |

---

## Fix Code — Exact Blender Python Implementations

### Fix 1 — Macro-Variation Node (insert before final mix, ~line 357)

Breaks tiling at 200–400 m world scale. Add after `noise_v` is created:

```python
# Macro albedo variation — large-scale noise to break tiling (~200m tile)
macro_noise = nt.nodes.new("ShaderNodeTexNoise")
macro_noise.location = (-1100, -800)
macro_noise.inputs["Scale"].default_value = 0.8   # ~200m at 1024m tile scale
macro_noise.inputs["Detail"].default_value = 4.0
macro_noise.inputs["Roughness"].default_value = 0.5
nt.links.new(geom.outputs["Position"], macro_noise.inputs["Vector"])

macro_ramp = nt.nodes.new("ShaderNodeValToRGB")
macro_ramp.location = (-700, -800)
macro_ramp.color_ramp.elements[0].position = 0.3
macro_ramp.color_ramp.elements[0].color = (0.85, 0.85, 0.85, 1)  # darken
macro_ramp.color_ramp.elements[1].position = 0.7
macro_ramp.color_ramp.elements[1].color = (1.15, 1.15, 1.15, 1)  # lighten (clamped by MixRGB)
nt.links.new(macro_noise.outputs["Fac"], macro_ramp.inputs["Fac"])

# Multiply final albedo by macro variation
macro_mod = nt.nodes.new("ShaderNodeMixRGB")
macro_mod.location = (1200, 100)
macro_mod.blend_type = "MULTIPLY"
macro_mod.inputs["Fac"].default_value = 1.0
# Wire: connect after mix_final is computed
nt.links.new(mix_final.outputs["Color"], macro_mod.inputs["Color1"])
nt.links.new(macro_ramp.outputs["Color"], macro_mod.inputs["Color2"])
nt.links.new(macro_mod.outputs["Color"], bsdf.inputs["Base Color"])
# Remove old direct link: mix_final -> Base Color (must delete before adding)
# Pattern: for lnk in list(nt.links):
#     if lnk.from_node == mix_final and lnk.to_socket == bsdf.inputs["Base Color"]:
#         nt.links.remove(lnk)
```

### Fix 2 — Snow Cap Layer (add after alt_ramp construction, ~line 341)

```python
# Snow: above 260m, driven by altitude and inverted slope (flat faces catch snow)
snow_alt = nt.nodes.new("ShaderNodeMapRange")
snow_alt.location = (-200, 500)
snow_alt.inputs["From Min"].default_value = 260.0
snow_alt.inputs["From Max"].default_value = 290.0
snow_alt.inputs["To Min"].default_value = 0.0
snow_alt.inputs["To Max"].default_value = 1.0
snow_alt.clamp = True
nt.links.new(sep_p.outputs["Z"], snow_alt.inputs["Value"])

# Snow only settles on gentle faces — invert slope (flat=1, wall=0)
snow_slope_inv = nt.nodes.new("ShaderNodeMath")
snow_slope_inv.location = (-200, 350)
snow_slope_inv.operation = "SUBTRACT"
snow_slope_inv.inputs[0].default_value = 1.0
nt.links.new(slope.outputs[0], snow_slope_inv.inputs[1])
snow_slope_mask = nt.nodes.new("ShaderNodeValToRGB")
snow_slope_mask.location = (50, 350)
snow_slope_mask.color_ramp.elements[0].position = 0.50  # starts on moderately flat faces
snow_slope_mask.color_ramp.elements[1].position = 0.80
nt.links.new(snow_slope_inv.outputs[0], snow_slope_mask.inputs["Fac"])

# Combine: altitude AND gentle-slope both required
snow_mask_mult = nt.nodes.new("ShaderNodeMath")
snow_mask_mult.location = (300, 430)
snow_mask_mult.operation = "MULTIPLY"
nt.links.new(snow_alt.outputs["Result"], snow_mask_mult.inputs[0])
nt.links.new(snow_slope_mask.outputs["Color"], snow_mask_mult.inputs[1])  # luminance

# Sparkle noise for crystalline snow quality
sparkle = nt.nodes.new("ShaderNodeTexNoise")
sparkle.location = (300, 650)
sparkle.inputs["Scale"].default_value = 45.0
sparkle.inputs["Detail"].default_value = 16.0
sparkle.inputs["Roughness"].default_value = 0.8
nt.links.new(geom.outputs["Position"], sparkle.inputs["Vector"])

# Snow color: white tinted by sparkle
snow_color_mix = nt.nodes.new("ShaderNodeMixRGB")
snow_color_mix.location = (600, 500)
snow_color_mix.inputs["Color1"].default_value = (0.85, 0.90, 0.95, 1)  # cold white
snow_color_mix.inputs["Color2"].default_value = (0.95, 0.98, 1.00, 1)  # sparkle bright
snow_color_mix.inputs["Fac"].default_value = 0.15
nt.links.new(sparkle.outputs["Fac"], snow_color_mix.inputs["Fac"])

# Mix snow over existing final color
snow_final = nt.nodes.new("ShaderNodeMixRGB")
snow_final.location = (900, 300)
nt.links.new(snow_mask_mult.outputs["Value"], snow_final.inputs["Fac"])
nt.links.new(mix_final.outputs["Color"], snow_final.inputs["Color1"])   # existing terrain
nt.links.new(snow_color_mix.outputs["Color"], snow_final.inputs["Color2"])
# Connect snow_final output to Base Color (and to macro_mod if Fix 1 applied)
nt.links.new(snow_final.outputs["Color"], bsdf.inputs["Base Color"])

# Snow roughness: very low (0.05 = icy) → slightly higher (0.35 = powder)
snow_rough = nt.nodes.new("ShaderNodeMath")
snow_rough.location = (900, 100)
snow_rough.operation = "MULTIPLY"
snow_rough.inputs[1].default_value = 0.15   # snow roughness target
# Lerp existing roughness toward snow_rough by snow_mask
snow_rough_mix = nt.nodes.new("ShaderNodeMixRGB")
snow_rough_mix.location = (1150, 100)
nt.links.new(snow_mask_mult.outputs["Value"], snow_rough_mix.inputs["Fac"])
nt.links.new(rough_ramp.outputs["Color"], snow_rough_mix.inputs["Color1"])
snow_rough_mix.inputs["Color2"].default_value = (0.15, 0.15, 0.15, 1)
nt.links.new(snow_rough_mix.outputs["Color"], bsdf.inputs["Roughness"])

# Snow subsurface scattering
try:
    bsdf.inputs["Subsurface Weight"].default_value = 0.0  # will be overridden per-pixel
    # Note: per-pixel SSS weight requires a MixShader or dedicated snow BSDF
    # For single-BSDF approach set a baseline
    bsdf.inputs["Subsurface Radius"].default_value = (0.8, 0.9, 1.0)  # blue-tinted SSS
except KeyError:
    pass
```

### Fix 3 — Tiling Rock Normal Map (replace bump section, ~lines 374–379)

```python
# Remove single noise-only bump; add layered tiling normals
# Triplanar rock normal (world-space tiling at ~6m)
tex_coord = nt.nodes.new("ShaderNodeTexCoord")
tex_coord.location = (-1400, -400)

# Scale world position for ~6m tile rock grain
rock_scale = nt.nodes.new("ShaderNodeVectorMath")
rock_scale.location = (-1100, -400)
rock_scale.operation = "SCALE"
rock_scale.inputs["Scale"].default_value = 0.167   # 1/6 ≈ 6m tile
nt.links.new(tex_coord.outputs["Object"], rock_scale.inputs["Vector"])

# Rock grain normal (procedural substitute for tiling normal map image)
rock_norm_noise = nt.nodes.new("ShaderNodeTexNoise")
rock_norm_noise.location = (-800, -500)
rock_norm_noise.inputs["Scale"].default_value = 1.0   # already scaled by rock_scale
rock_norm_noise.inputs["Detail"].default_value = 12.0
rock_norm_noise.inputs["Roughness"].default_value = 0.75
nt.links.new(rock_scale.outputs["Vector"], rock_norm_noise.inputs["Vector"])

rock_bump = nt.nodes.new("ShaderNodeBump")
rock_bump.location = (1100, -200)
rock_bump.inputs["Strength"].default_value = 0.80
rock_bump.inputs["Distance"].default_value = 1.5   # readable at terrain scale
nt.links.new(rock_norm_noise.outputs["Fac"], rock_bump.inputs["Height"])

# Grass grain normal (finer scale, lower bump strength)
grass_scale = nt.nodes.new("ShaderNodeVectorMath")
grass_scale.location = (-1100, -700)
grass_scale.operation = "SCALE"
grass_scale.inputs["Scale"].default_value = 0.5   # 2m tile for grass blade detail
nt.links.new(tex_coord.outputs["Object"], grass_scale.inputs["Vector"])

grass_norm_noise = nt.nodes.new("ShaderNodeTexNoise")
grass_norm_noise.location = (-800, -700)
grass_norm_noise.inputs["Scale"].default_value = 1.0
grass_norm_noise.inputs["Detail"].default_value = 10.0
grass_norm_noise.inputs["Roughness"].default_value = 0.45
nt.links.new(grass_scale.outputs["Vector"], grass_norm_noise.inputs["Vector"])

grass_bump = nt.nodes.new("ShaderNodeBump")
grass_bump.location = (1100, -450)
grass_bump.inputs["Strength"].default_value = 0.30
grass_bump.inputs["Distance"].default_value = 0.6
nt.links.new(grass_norm_noise.outputs["Fac"], grass_bump.inputs["Height"])

# Blend rock_bump vs grass_bump by slope factor
normal_mix = nt.nodes.new("ShaderNodeMix")
normal_mix.location = (1350, -300)
normal_mix.data_type = "VECTOR"
nt.links.new(slope_ramp.outputs["Color"], normal_mix.inputs["Factor"])  # high slope = rock
nt.links.new(grass_bump.outputs["Normal"], normal_mix.inputs[4])   # A = grass (flat)
nt.links.new(rock_bump.outputs["Normal"], normal_mix.inputs[5])    # B = rock (steep)
nt.links.new(normal_mix.outputs[1], bsdf.inputs["Normal"])
```

### Fix 4 — Vertex Color Biome Override (add in make_terrain_material after mix_final)

```python
# Read vertex color attribute — painted by vertex_paint_live.py workflow
vcol = nt.nodes.new("ShaderNodeVertexColor")
vcol.location = (600, -200)
vcol.layer_name = "BiomeOverride"   # must match attribute name set in vertex_paint_live

# Use vertex alpha as override mask (1.0 = fully use painted color)
vcol_alpha_sep = nt.nodes.new("ShaderNodeSeparateColor")
vcol_alpha_sep.location = (800, -200)
nt.links.new(vcol.outputs["Color"], vcol_alpha_sep.inputs["Color"])

vcol_mask = nt.nodes.new("ShaderNodeSeparateColor")  # use R channel as mask
vcol_mask.location = (800, -350)
nt.links.new(vcol.outputs["Alpha"], vcol_mask.inputs["Color"])

# Blend painted color over procedural result where alpha > 0
vcol_mix = nt.nodes.new("ShaderNodeMixRGB")
vcol_mix.location = (1100, 200)
nt.links.new(vcol.outputs["Alpha"], vcol_mix.inputs["Fac"])
nt.links.new(mix_final.outputs["Color"], vcol_mix.inputs["Color1"])
nt.links.new(vcol.outputs["Color"], vcol_mix.inputs["Color2"])
# vcol_mix output feeds into macro_mod (Fix 1) or directly to Base Color
nt.links.new(vcol_mix.outputs["Color"], bsdf.inputs["Base Color"])
```

### Fix 5 — Water Depth Volume Absorption

```python
# Add to make_water_material() — after existing shader nodes, before output link

# Volume absorption for depth-dependent color (deep water = darker blue-green)
vol_abs = nt.nodes.new("ShaderNodeVolumeAbsorption")
vol_abs.location = (800, -500)
# Deep water absorbs red/green more than blue
r, g, b = tint[0], tint[1], tint[2]
# Absorption color is complement of desired transmission tint
vol_abs.inputs["Color"].default_value = (
    max(0.0, 1.0 - r * 0.4),   # absorb some red
    max(0.0, 1.0 - g * 0.6),   # absorb more green
    max(0.0, 1.0 - b * 0.9),   # absorb least blue → blue-green transmission
    1.0
)
vol_abs.inputs["Density"].default_value = 0.08   # 0.08/m → fully absorbed ~40m

# Connect volume to material output Volume socket
nt.links.new(vol_abs.outputs["Volume"], out.inputs["Volume"])
```

### Fix 6 — Rock Material with Tiling Normal and Moss Weathering

```python
# Replace the minimal rock_mat creation in scatter_rocks() (~lines 914-935)
def make_rock_material() -> bpy.types.Material:
    mat = bpy.data.materials.new("VB_RockMat")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (1600, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (1300, 0)
    bsdf.inputs["Roughness"].default_value = 0.88

    geom = nt.nodes.new("ShaderNodeNewGeometry")
    geom.location = (-1200, 0)
    tex_coord = nt.nodes.new("ShaderNodeTexCoord")
    tex_coord.location = (-1200, -300)

    # Rock surface noise — tiling at ~0.4m (fine grain visible at close range)
    rock_scale = nt.nodes.new("ShaderNodeVectorMath")
    rock_scale.operation = "SCALE"
    rock_scale.inputs["Scale"].default_value = 2.5   # ~0.4m tile
    rock_scale.location = (-900, -300)
    nt.links.new(tex_coord.outputs["Object"], rock_scale.inputs["Vector"])

    grain_noise = nt.nodes.new("ShaderNodeTexNoise")
    grain_noise.location = (-600, -300)
    grain_noise.inputs["Scale"].default_value = 1.0
    grain_noise.inputs["Detail"].default_value = 14.0
    grain_noise.inputs["Roughness"].default_value = 0.70
    nt.links.new(rock_scale.outputs["Vector"], grain_noise.inputs["Vector"])

    # Albedo: two rock tones mixed by grain noise
    rock_color_mix = nt.nodes.new("ShaderNodeMixRGB")
    rock_color_mix.location = (-200, 300)
    rock_color_mix.inputs["Color1"].default_value = (0.10, 0.09, 0.07, 1)  # dark
    rock_color_mix.inputs["Color2"].default_value = (0.24, 0.20, 0.15, 1)  # light
    nt.links.new(grain_noise.outputs["Fac"], rock_color_mix.inputs["Fac"])

    # Moss/weathering: AO-like concavity approximation via inverted noise at low frequency
    concavity_noise = nt.nodes.new("ShaderNodeTexNoise")
    concavity_noise.location = (-600, 100)
    concavity_noise.inputs["Scale"].default_value = 0.6
    concavity_noise.inputs["Detail"].default_value = 6.0
    concavity_noise.inputs["Roughness"].default_value = 0.55
    nt.links.new(tex_coord.outputs["Object"], concavity_noise.inputs["Vector"])

    # AO from geometry node — approximate
    ao_node = nt.nodes.new("ShaderNodeAmbientOcclusion")
    ao_node.location = (-600, -100)
    ao_node.samples = 8
    ao_node.inside = False
    nt.links.new(geom.outputs["Position"], ao_node.inputs["Normal"])

    # Moss color (dark green) blended by inverted AO (recesses get moss)
    moss_invert = nt.nodes.new("ShaderNodeMath")
    moss_invert.location = (-200, 0)
    moss_invert.operation = "SUBTRACT"
    moss_invert.inputs[0].default_value = 1.0
    nt.links.new(ao_node.outputs["AO"], moss_invert.inputs[1])

    moss_mix = nt.nodes.new("ShaderNodeMixRGB")
    moss_mix.location = (100, 200)
    moss_mix.inputs["Color2"].default_value = (0.04, 0.09, 0.03, 1)  # moss green
    nt.links.new(rock_color_mix.outputs["Color"], moss_mix.inputs["Color1"])
    nt.links.new(moss_invert.outputs["Value"], moss_mix.inputs["Fac"])
    nt.links.new(moss_mix.outputs["Color"], bsdf.inputs["Base Color"])

    # Tiling bump normal
    rock_bump = nt.nodes.new("ShaderNodeBump")
    rock_bump.location = (1000, -200)
    rock_bump.inputs["Strength"].default_value = 1.2
    rock_bump.inputs["Distance"].default_value = 0.05
    nt.links.new(grain_noise.outputs["Fac"], rock_bump.inputs["Height"])
    nt.links.new(rock_bump.outputs["Normal"], bsdf.inputs["Normal"])

    # Roughness: higher in concavities (wet/mossy), lower on exposed faces
    rough_mix = nt.nodes.new("ShaderNodeMixRGB")
    rough_mix.location = (1000, -400)
    rough_mix.inputs["Color1"].default_value = (0.75, 0.75, 0.75, 1)  # exposed rock
    rough_mix.inputs["Color2"].default_value = (0.95, 0.95, 0.95, 1)  # mossy concavity
    nt.links.new(moss_invert.outputs["Value"], rough_mix.inputs["Fac"])
    nt.links.new(rough_mix.outputs["Color"], bsdf.inputs["Roughness"])

    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat
```

### Fix 7 — Quality Profile Wiring in build_scene_v3.py

Add at top of `make_terrain_material()` and relevant functions:

```python
# At module top level — import quality profiles
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from veilbreakers_terrain.handlers.terrain_quality_profiles import load_quality_profile

# In make_terrain_material():
def make_terrain_material(profile_name: str = "aaa_open_world") -> bpy.types.Material:
    profile = load_quality_profile(profile_name)
    # Use profile.texture_resolution, profile.normal_map_resolution, etc.
    # Example: set noise detail level from roughness_variation_strength
    noise_detail = 8.0 + profile.roughness_variation_strength * 8.0   # 8–12 detail
    noise_v.inputs["Detail"].default_value = noise_detail
    # Roughness variation range from profile
    rough_min = 0.50 + (1.0 - profile.roughness_variation_strength) * 0.20
    rough_max = 0.80 + profile.roughness_variation_strength * 0.15
    rough_ramp.color_ramp.elements[0].color = (rough_min,) * 3 + (1,)
    rough_ramp.color_ramp.elements[1].color = (rough_max,) * 3 + (1,)
```

### Fix 8 — blend_method BLEND Bug (lines 512, 554, 585)

Remove or no-op the `blend_method` calls for Cycles — they have no effect and create false expectations:

```python
# Remove these three try blocks entirely, or replace with a comment:
# lake_mat.blend_method = "BLEND"  # REMOVED: EEVEE-only, does nothing in Cycles
# river_mat.blend_method = "BLEND"  # REMOVED
# wf_mat.blend_method = "BLEND"    # REMOVED

# For actual Cycles transparency on waterfall, use a Transparent BSDF mixed by Fresnel:
# transparent = nt.nodes.new("ShaderNodeBsdfTransparent")
# mix_trans = nt.nodes.new("ShaderNodeMixShader")
# mix_trans.inputs["Fac"].default_value = 0.7   # 70% opaque
# nt.links.new(transparent.outputs["BSDF"], mix_trans.inputs[1])
# nt.links.new(mix_dg.outputs["Shader"], mix_trans.inputs[2])
# nt.links.new(mix_trans.outputs["Shader"], out.inputs["Surface"])
```

### Fix 9 — Bump Distance Scale (line 378)

```python
# Change from:
bump.inputs["Distance"].default_value = 0.08   # invisible at 1024m tile
# To:
bump.inputs["Distance"].default_value = 2.0    # readable terrain surface grain
```

### Fix 10 — ShaderNodeMixRGB Deprecation (lines 351, 358, 424)

```python
# Replace ShaderNodeMixRGB with ShaderNodeMix + data_type='RGBA':
rock_mix = nt.nodes.new("ShaderNodeMix")
rock_mix.data_type = "RGBA"
rock_mix.location = (100, 450)
rock_mix.inputs[6].default_value = (0.09, 0.08, 0.06, 1)  # Color1
rock_mix.inputs[7].default_value = (0.20, 0.17, 0.13, 1)  # Color2
nt.links.new(noise_v.outputs["Fac"], rock_mix.inputs["Factor"])
# Output is rock_mix.outputs[2] (Color output for RGBA mode)
```

---

## Vertex Paint Integration Gap

`vertex_paint_live.py` is a complete, tested brush-weight + blend-color system. It provides:
- `compute_paint_weights()` — world-space falloff, 4 modes
- `compute_paint_weights_uv()` — UV-space falloff
- `blend_colors()` / `blend_colors_array()` — RGBA blending, 4 modes, alpha-preserved

**The problem:** None of these functions are called from `build_scene_v3.py`. More critically, the terrain material (`make_terrain_material`) does not include a `ShaderNodeVertexColor` node reading any attribute, so even if vertex paints were applied at the data level, they would not appear in the render.

**Minimum wiring required:**
1. Add `ShaderNodeVertexColor` to terrain material (Fix 4 above)
2. In a Blender modal operator / paint session handler: call `compute_paint_weights()` to get per-vertex weights, call `blend_colors_array()` to compute new RGBA values, then write results to `mesh.color_attributes["BiomeOverride"].data[vi].color`

---

## Priority Fix Order

| Priority | Fix | Impact |
|---|---|---|
| P0 | Fix 8 — remove blend_method=BLEND bug | Silent correctness bug in current renders |
| P0 | Fix 9 — bump distance 0.08 → 2.0 | Terrain reads completely flat at tile scale |
| P0 | Fix 7 — wire quality profiles into material | Entire profile system is dead code |
| P1 | Fix 1 — macro-variation noise | Tiling is visible at any distance without this |
| P1 | Fix 2 — snow cap | High altitude looks like concrete |
| P1 | Fix 5 — water depth volume absorption | Lake reads flat-blue; no depth |
| P1 | Fix 6 — rock material with normal + moss | Rocks look like plastic spheres |
| P1 | Fix 4 — vertex color biome override wiring | vertex_paint_live.py is entirely wasted work |
| P2 | Fix 3 — tiling rock/grass normal layers | Terrain reads as baked-noise flat at close range |
| P2 | Fix 10 — ShaderNodeMixRGB deprecation | Forward-compat issue for Blender 4.6+ |

---

## Overall Assessment vs. Horizon Zero Dawn Bar

HZD terrain uses: triplanar PBR with 5 material layers, per-layer tiling normal maps, height+slope+curvature blending, macro-variation at 3 scales, hand-painted biome splatmaps, physical water with depth scattering, and fully integrated LOD-scaled material variants.

VeilBreakers currently has: the correct **structural skeleton** (slope and altitude drives exist), but zero surface-quality layers. The terrain will render as uniformly-smooth noise-textured geometry with flat color bands. At 10 m viewing distance it will be indistinguishable from a Blender beginner tutorial. Every single material gap listed above would be noticed in a 10-second screenshot by any AAA art director.

No current material passes the HZD reference bar. With the P0+P1 fixes applied, the terrain would reach approximately 60–70% of the HZD quality floor — still requiring tiling PBR texture maps (image files) and real triplanar projection to close the remaining gap.
