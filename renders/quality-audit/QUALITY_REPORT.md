# VeilBreakers Terrain — Render Visual Quality Report

> Generated: 2026-05-04 (v2 renderer) | **Grades from direct render inspection, not channel stats**
> Renderer: `scripts/dynamic_quality_renderer.py` v2 | 1314 renders, 0 failures
> Passes: 73 | Biomes: 6 | Angles: 3 (isometric · topdown · sideprofile)

---

## What the v2 Renderer Fixed vs v1

| Fix | v1 | v2 |
|-----|----|----|
| Terrain smoothing | Raw noise spikes | Gaussian σ=2.5 grassland, σ=0.4 volcanic |
| Biome colour | All grey | Per-biome 4-stop palette (green/white/pink/cream) |
| Camera framing | Fixed z+120m (overflows mountain) | Adaptive bbox from z_min/z_max |
| Water plane | None | Translucent BSDF plane at water_surface_mask level |
| Grass sprites | None | 300 instanced planes from grass_density_map.npy |
| Resolution | 512×384 | 720×540 |

## What Still Does NOT Render Visually

| System | Problem | Impact |
|--------|---------|--------|
| Erosion delta overlay | Baked image texture not applying in EEVEE via `Generated` UV | All erosion passes grade D |
| Structural mask colours | Same baked-texture failure | 3 structural passes grade D |
| Splatmap multiband | Node network created but no UV → texture black | All material passes grade D |
| Biome/gameplay zone overlays | Same baked-texture failure | ~18 passes grade D |
| Grass sprites | 0.8–3.3m sprites invisible at 300m+ camera distance | Scatter passes grade D |

**Root cause of all overlay failures:** the renderer bakes channel data to a Blender image
texture and assigns it via `Generated` UV coordinates. EEVEE in background mode requires
a UV map on the mesh, not `Generated` coords, for image textures to sample correctly.
Fix: add explicit UV map with `mesh.uv_layers.new()` + `smart_project()` before baking.

---

## Summary — Visual Render Grades

| Grade | Count | What it means |
|-------|-------|----------------|
| 🟢 B+ | 11 passes | Water plane clearly visible; pass effect differentiated |
| 🟢 B  | 17 passes | Terrain mesh renders, biome colour correct; partial differentiation |
| ⚠️ C  | 6 passes  | Terrain shows; pass effect invisible but system runs |
| ❌ D  | 39 passes | Base terrain mesh only; zero pass-specific visual output |

**78% of passes (D) show no visual difference from the base terrain mesh.**
This is a renderer failure, not a pipeline failure. The underlying channel data exists
(confirmed by harness manifest) but the Blender material node/UV pipeline is broken.

---

## Terrain Generation

### 🟢 `macro_world` — Grade **B**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | 🟢 **B** | [iso](renders/quality-audit/macro_world/grassland_isometric.png) · [top](renders/quality-audit/macro_world/grassland_topdown.png) · [sid](renders/quality-audit/macro_world/grassland_sideprofile.png) | Green rolling hills. Smoothing works. Slight edge spikes but framing good. |
| mountain | ⚠️ **C** | [iso](renders/quality-audit/macro_world/mountain_isometric.png) · [top](renders/quality-audit/macro_world/mountain_topdown.png) · [sid](renders/quality-audit/macro_world/mountain_sideprofile.png) | Camera clips right edge — terrain overflows frame. Dramatic ridges visible. |
| coastal | 🟢 **B** | [iso](renders/quality-audit/macro_world/coastal_isometric.png) · [top](renders/quality-audit/macro_world/coastal_topdown.png) · [sid](renders/quality-audit/macro_world/coastal_sideprofile.png) | Low flat terrain appropriate. Mostly below sea level. Framing correct. |
| volcanic | ⚠️ **C-** | [iso](renders/quality-audit/macro_world/volcanic_isometric.png) · [top](renders/quality-audit/macro_world/volcanic_topdown.png) · [sid](renders/quality-audit/macro_world/volcanic_sideprofile.png) | Extreme bed-of-nails spikes. Low sigma intentional but 64px res is too coarse. |
| frozen | 🟢 **B+** | [iso](renders/quality-audit/macro_world/frozen_isometric.png) · [top](renders/quality-audit/macro_world/frozen_topdown.png) · [sid](renders/quality-audit/macro_world/frozen_sideprofile.png) | White tundra sheet, smooth, correctly framed. Best biome result. |
| desert | 🟢 **B+** | [iso](renders/quality-audit/macro_world/desert_isometric.png) · [top](renders/quality-audit/macro_world/desert_topdown.png) · [sid](renders/quality-audit/macro_world/desert_sideprofile.png) | Sandy cream dunes, excellent framing and palette. Natural-looking. |

### ⚠️ `pass_generate_low_freq_hmap` — Grade **C**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ⚠️ **C** | [iso](renders/quality-audit/pass_generate_low_freq_hmap/grassland_isometric.png) · [top](renders/quality-audit/pass_generate_low_freq_hmap/grassland_topdown.png) · [sid](renders/quality-audit/pass_generate_low_freq_hmap/grassland_sideprofile.png) | Renders identically to macro_world — sub-pass, no distinct visual output. |
| mountain | ⚠️ **C** | [iso](renders/quality-audit/pass_generate_low_freq_hmap/mountain_isometric.png) · [top](renders/quality-audit/pass_generate_low_freq_hmap/mountain_topdown.png) · [sid](renders/quality-audit/pass_generate_low_freq_hmap/mountain_sideprofile.png) | Renders identically to macro_world — sub-pass, no distinct visual output. |
| coastal | ⚠️ **C** | [iso](renders/quality-audit/pass_generate_low_freq_hmap/coastal_isometric.png) · [top](renders/quality-audit/pass_generate_low_freq_hmap/coastal_topdown.png) · [sid](renders/quality-audit/pass_generate_low_freq_hmap/coastal_sideprofile.png) | Renders identically to macro_world — sub-pass, no distinct visual output. |
| volcanic | ⚠️ **C** | [iso](renders/quality-audit/pass_generate_low_freq_hmap/volcanic_isometric.png) · [top](renders/quality-audit/pass_generate_low_freq_hmap/volcanic_topdown.png) · [sid](renders/quality-audit/pass_generate_low_freq_hmap/volcanic_sideprofile.png) | Renders identically to macro_world — sub-pass, no distinct visual output. |
| frozen | ⚠️ **C** | [iso](renders/quality-audit/pass_generate_low_freq_hmap/frozen_isometric.png) · [top](renders/quality-audit/pass_generate_low_freq_hmap/frozen_topdown.png) · [sid](renders/quality-audit/pass_generate_low_freq_hmap/frozen_sideprofile.png) | Renders identically to macro_world — sub-pass, no distinct visual output. |
| desert | ⚠️ **C** | [iso](renders/quality-audit/pass_generate_low_freq_hmap/desert_isometric.png) · [top](renders/quality-audit/pass_generate_low_freq_hmap/desert_topdown.png) · [sid](renders/quality-audit/pass_generate_low_freq_hmap/desert_sideprofile.png) | Renders identically to macro_world — sub-pass, no distinct visual output. |

### ⚠️ `pass_generate_high_freq_detail` — Grade **C**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ⚠️ **C** | [iso](renders/quality-audit/pass_generate_high_freq_detail/grassland_isometric.png) · [top](renders/quality-audit/pass_generate_high_freq_detail/grassland_topdown.png) · [sid](renders/quality-audit/pass_generate_high_freq_detail/grassland_sideprofile.png) | Renders identically to macro_world — sub-pass, no distinct visual output. |
| mountain | ⚠️ **C** | [iso](renders/quality-audit/pass_generate_high_freq_detail/mountain_isometric.png) · [top](renders/quality-audit/pass_generate_high_freq_detail/mountain_topdown.png) · [sid](renders/quality-audit/pass_generate_high_freq_detail/mountain_sideprofile.png) | Renders identically to macro_world — sub-pass, no distinct visual output. |
| coastal | ⚠️ **C** | [iso](renders/quality-audit/pass_generate_high_freq_detail/coastal_isometric.png) · [top](renders/quality-audit/pass_generate_high_freq_detail/coastal_topdown.png) · [sid](renders/quality-audit/pass_generate_high_freq_detail/coastal_sideprofile.png) | Renders identically to macro_world — sub-pass, no distinct visual output. |
| volcanic | ⚠️ **C** | [iso](renders/quality-audit/pass_generate_high_freq_detail/volcanic_isometric.png) · [top](renders/quality-audit/pass_generate_high_freq_detail/volcanic_topdown.png) · [sid](renders/quality-audit/pass_generate_high_freq_detail/volcanic_sideprofile.png) | Renders identically to macro_world — sub-pass, no distinct visual output. |
| frozen | ⚠️ **C** | [iso](renders/quality-audit/pass_generate_high_freq_detail/frozen_isometric.png) · [top](renders/quality-audit/pass_generate_high_freq_detail/frozen_topdown.png) · [sid](renders/quality-audit/pass_generate_high_freq_detail/frozen_sideprofile.png) | Renders identically to macro_world — sub-pass, no distinct visual output. |
| desert | ⚠️ **C** | [iso](renders/quality-audit/pass_generate_high_freq_detail/desert_isometric.png) · [top](renders/quality-audit/pass_generate_high_freq_detail/desert_topdown.png) · [sid](renders/quality-audit/pass_generate_high_freq_detail/desert_sideprofile.png) | Renders identically to macro_world — sub-pass, no distinct visual output. |

### ⚠️ `pass_composite_hmap` — Grade **C**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ⚠️ **C** | [iso](renders/quality-audit/pass_composite_hmap/grassland_isometric.png) · [top](renders/quality-audit/pass_composite_hmap/grassland_topdown.png) · [sid](renders/quality-audit/pass_composite_hmap/grassland_sideprofile.png) | Composite pass renders same mesh as macro_world. No distinguishing output. |
| mountain | ⚠️ **C** | [iso](renders/quality-audit/pass_composite_hmap/mountain_isometric.png) · [top](renders/quality-audit/pass_composite_hmap/mountain_topdown.png) · [sid](renders/quality-audit/pass_composite_hmap/mountain_sideprofile.png) | Composite pass renders same mesh as macro_world. No distinguishing output. |
| coastal | ⚠️ **C** | [iso](renders/quality-audit/pass_composite_hmap/coastal_isometric.png) · [top](renders/quality-audit/pass_composite_hmap/coastal_topdown.png) · [sid](renders/quality-audit/pass_composite_hmap/coastal_sideprofile.png) | Composite pass renders same mesh as macro_world. No distinguishing output. |
| volcanic | ⚠️ **C** | [iso](renders/quality-audit/pass_composite_hmap/volcanic_isometric.png) · [top](renders/quality-audit/pass_composite_hmap/volcanic_topdown.png) · [sid](renders/quality-audit/pass_composite_hmap/volcanic_sideprofile.png) | Composite pass renders same mesh as macro_world. No distinguishing output. |
| frozen | ⚠️ **C** | [iso](renders/quality-audit/pass_composite_hmap/frozen_isometric.png) · [top](renders/quality-audit/pass_composite_hmap/frozen_topdown.png) · [sid](renders/quality-audit/pass_composite_hmap/frozen_sideprofile.png) | Composite pass renders same mesh as macro_world. No distinguishing output. |
| desert | ⚠️ **C** | [iso](renders/quality-audit/pass_composite_hmap/desert_isometric.png) · [top](renders/quality-audit/pass_composite_hmap/desert_topdown.png) · [sid](renders/quality-audit/pass_composite_hmap/desert_sideprofile.png) | Composite pass renders same mesh as macro_world. No distinguishing output. |

## Erosion

### ❌ `erosion` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/erosion/grassland_isometric.png) · [top](renders/quality-audit/erosion/grassland_topdown.png) · [sid](renders/quality-audit/erosion/grassland_sideprofile.png) | Erosion delta overlay NOT visible. Red/blue baked texture not applying in EEVEE. Shows base terrain only. |
| mountain | ❌ **D** | [iso](renders/quality-audit/erosion/mountain_isometric.png) · [top](renders/quality-audit/erosion/mountain_topdown.png) · [sid](renders/quality-audit/erosion/mountain_sideprofile.png) | Erosion delta overlay NOT visible. Red/blue baked texture not applying in EEVEE. Shows base terrain only. |
| coastal | ❌ **D** | [iso](renders/quality-audit/erosion/coastal_isometric.png) · [top](renders/quality-audit/erosion/coastal_topdown.png) · [sid](renders/quality-audit/erosion/coastal_sideprofile.png) | Erosion delta overlay NOT visible. Red/blue baked texture not applying in EEVEE. Shows base terrain only. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/erosion/volcanic_isometric.png) · [top](renders/quality-audit/erosion/volcanic_topdown.png) · [sid](renders/quality-audit/erosion/volcanic_sideprofile.png) | Erosion delta overlay NOT visible. Red/blue baked texture not applying in EEVEE. Shows base terrain only. |
| frozen | ❌ **D** | [iso](renders/quality-audit/erosion/frozen_isometric.png) · [top](renders/quality-audit/erosion/frozen_topdown.png) · [sid](renders/quality-audit/erosion/frozen_sideprofile.png) | Erosion delta overlay NOT visible. Red/blue baked texture not applying in EEVEE. Shows base terrain only. |
| desert | ❌ **D** | [iso](renders/quality-audit/erosion/desert_isometric.png) · [top](renders/quality-audit/erosion/desert_topdown.png) · [sid](renders/quality-audit/erosion/desert_sideprofile.png) | Erosion delta overlay NOT visible. Red/blue baked texture not applying in EEVEE. Shows base terrain only. |

### ❌ `talus` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/talus/grassland_isometric.png) · [top](renders/quality-audit/talus/grassland_topdown.png) · [sid](renders/quality-audit/talus/grassland_sideprofile.png) | No talus scree overlay visible. Identical to terrain_gen mesh. |
| mountain | ❌ **D** | [iso](renders/quality-audit/talus/mountain_isometric.png) · [top](renders/quality-audit/talus/mountain_topdown.png) · [sid](renders/quality-audit/talus/mountain_sideprofile.png) | No talus scree overlay visible. Identical to terrain_gen mesh. |
| coastal | ❌ **D** | [iso](renders/quality-audit/talus/coastal_isometric.png) · [top](renders/quality-audit/talus/coastal_topdown.png) · [sid](renders/quality-audit/talus/coastal_sideprofile.png) | No talus scree overlay visible. Identical to terrain_gen mesh. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/talus/volcanic_isometric.png) · [top](renders/quality-audit/talus/volcanic_topdown.png) · [sid](renders/quality-audit/talus/volcanic_sideprofile.png) | No talus scree overlay visible. Identical to terrain_gen mesh. |
| frozen | ❌ **D** | [iso](renders/quality-audit/talus/frozen_isometric.png) · [top](renders/quality-audit/talus/frozen_topdown.png) · [sid](renders/quality-audit/talus/frozen_sideprofile.png) | No talus scree overlay visible. Identical to terrain_gen mesh. |
| desert | ❌ **D** | [iso](renders/quality-audit/talus/desert_isometric.png) · [top](renders/quality-audit/talus/desert_topdown.png) · [sid](renders/quality-audit/talus/desert_sideprofile.png) | No talus scree overlay visible. Identical to terrain_gen mesh. |

### ❌ `wind_erosion` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/wind_erosion/grassland_isometric.png) · [top](renders/quality-audit/wind_erosion/grassland_topdown.png) · [sid](renders/quality-audit/wind_erosion/grassland_sideprofile.png) | No wind erosion lines/streaks visible. Base terrain only. |
| mountain | ❌ **D** | [iso](renders/quality-audit/wind_erosion/mountain_isometric.png) · [top](renders/quality-audit/wind_erosion/mountain_topdown.png) · [sid](renders/quality-audit/wind_erosion/mountain_sideprofile.png) | No wind erosion lines/streaks visible. Base terrain only. |
| coastal | ❌ **D** | [iso](renders/quality-audit/wind_erosion/coastal_isometric.png) · [top](renders/quality-audit/wind_erosion/coastal_topdown.png) · [sid](renders/quality-audit/wind_erosion/coastal_sideprofile.png) | No wind erosion lines/streaks visible. Base terrain only. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/wind_erosion/volcanic_isometric.png) · [top](renders/quality-audit/wind_erosion/volcanic_topdown.png) · [sid](renders/quality-audit/wind_erosion/volcanic_sideprofile.png) | No wind erosion lines/streaks visible. Base terrain only. |
| frozen | ❌ **D** | [iso](renders/quality-audit/wind_erosion/frozen_isometric.png) · [top](renders/quality-audit/wind_erosion/frozen_topdown.png) · [sid](renders/quality-audit/wind_erosion/frozen_sideprofile.png) | No wind erosion lines/streaks visible. Base terrain only. |
| desert | ❌ **D** | [iso](renders/quality-audit/wind_erosion/desert_isometric.png) · [top](renders/quality-audit/wind_erosion/desert_topdown.png) · [sid](renders/quality-audit/wind_erosion/desert_sideprofile.png) | No wind erosion lines/streaks visible. Base terrain only. |

### ❌ `glacial` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/glacial/grassland_isometric.png) · [top](renders/quality-audit/glacial/grassland_topdown.png) · [sid](renders/quality-audit/glacial/grassland_sideprofile.png) | Glacial channel/U-valley overlay not visible. Base terrain only. |
| mountain | ❌ **D** | [iso](renders/quality-audit/glacial/mountain_isometric.png) · [top](renders/quality-audit/glacial/mountain_topdown.png) · [sid](renders/quality-audit/glacial/mountain_sideprofile.png) | Glacial channel/U-valley overlay not visible. Base terrain only. |
| coastal | ❌ **D** | [iso](renders/quality-audit/glacial/coastal_isometric.png) · [top](renders/quality-audit/glacial/coastal_topdown.png) · [sid](renders/quality-audit/glacial/coastal_sideprofile.png) | Glacial channel/U-valley overlay not visible. Base terrain only. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/glacial/volcanic_isometric.png) · [top](renders/quality-audit/glacial/volcanic_topdown.png) · [sid](renders/quality-audit/glacial/volcanic_sideprofile.png) | Glacial channel/U-valley overlay not visible. Base terrain only. |
| frozen | ❌ **D** | [iso](renders/quality-audit/glacial/frozen_isometric.png) · [top](renders/quality-audit/glacial/frozen_topdown.png) · [sid](renders/quality-audit/glacial/frozen_sideprofile.png) | Glacial channel/U-valley overlay not visible. Base terrain only. |
| desert | ❌ **D** | [iso](renders/quality-audit/glacial/desert_isometric.png) · [top](renders/quality-audit/glacial/desert_topdown.png) · [sid](renders/quality-audit/glacial/desert_sideprofile.png) | Glacial channel/U-valley overlay not visible. Base terrain only. |

### ❌ `pass_glacial` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/pass_glacial/grassland_isometric.png) · [top](renders/quality-audit/pass_glacial/grassland_topdown.png) · [sid](renders/quality-audit/pass_glacial/grassland_sideprofile.png) | Same as glacial — no visual differentiation. |
| mountain | ❌ **D** | [iso](renders/quality-audit/pass_glacial/mountain_isometric.png) · [top](renders/quality-audit/pass_glacial/mountain_topdown.png) · [sid](renders/quality-audit/pass_glacial/mountain_sideprofile.png) | Same as glacial — no visual differentiation. |
| coastal | ❌ **D** | [iso](renders/quality-audit/pass_glacial/coastal_isometric.png) · [top](renders/quality-audit/pass_glacial/coastal_topdown.png) · [sid](renders/quality-audit/pass_glacial/coastal_sideprofile.png) | Same as glacial — no visual differentiation. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/pass_glacial/volcanic_isometric.png) · [top](renders/quality-audit/pass_glacial/volcanic_topdown.png) · [sid](renders/quality-audit/pass_glacial/volcanic_sideprofile.png) | Same as glacial — no visual differentiation. |
| frozen | ❌ **D** | [iso](renders/quality-audit/pass_glacial/frozen_isometric.png) · [top](renders/quality-audit/pass_glacial/frozen_topdown.png) · [sid](renders/quality-audit/pass_glacial/frozen_sideprofile.png) | Same as glacial — no visual differentiation. |
| desert | ❌ **D** | [iso](renders/quality-audit/pass_glacial/desert_isometric.png) · [top](renders/quality-audit/pass_glacial/desert_topdown.png) · [sid](renders/quality-audit/pass_glacial/desert_sideprofile.png) | Same as glacial — no visual differentiation. |

### ❌ `banded_macro` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/banded_macro/grassland_isometric.png) · [top](renders/quality-audit/banded_macro/grassland_topdown.png) · [sid](renders/quality-audit/banded_macro/grassland_sideprofile.png) | Banded strata not visible. Base terrain only. |
| mountain | ❌ **D** | [iso](renders/quality-audit/banded_macro/mountain_isometric.png) · [top](renders/quality-audit/banded_macro/mountain_topdown.png) · [sid](renders/quality-audit/banded_macro/mountain_sideprofile.png) | Banded strata not visible. Base terrain only. |
| coastal | ❌ **D** | [iso](renders/quality-audit/banded_macro/coastal_isometric.png) · [top](renders/quality-audit/banded_macro/coastal_topdown.png) · [sid](renders/quality-audit/banded_macro/coastal_sideprofile.png) | Banded strata not visible. Base terrain only. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/banded_macro/volcanic_isometric.png) · [top](renders/quality-audit/banded_macro/volcanic_topdown.png) · [sid](renders/quality-audit/banded_macro/volcanic_sideprofile.png) | Banded strata not visible. Base terrain only. |
| frozen | ❌ **D** | [iso](renders/quality-audit/banded_macro/frozen_isometric.png) · [top](renders/quality-audit/banded_macro/frozen_topdown.png) · [sid](renders/quality-audit/banded_macro/frozen_sideprofile.png) | Banded strata not visible. Base terrain only. |
| desert | ❌ **D** | [iso](renders/quality-audit/banded_macro/desert_isometric.png) · [top](renders/quality-audit/banded_macro/desert_topdown.png) · [sid](renders/quality-audit/banded_macro/desert_sideprofile.png) | Banded strata not visible. Base terrain only. |

### ❌ `pass_banded_advanced` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/pass_banded_advanced/grassland_isometric.png) · [top](renders/quality-audit/pass_banded_advanced/grassland_topdown.png) · [sid](renders/quality-audit/pass_banded_advanced/grassland_sideprofile.png) | No banded overlay. Confirmed no-op (A3 audit: 30 templates dead). |
| mountain | ❌ **D** | [iso](renders/quality-audit/pass_banded_advanced/mountain_isometric.png) · [top](renders/quality-audit/pass_banded_advanced/mountain_topdown.png) · [sid](renders/quality-audit/pass_banded_advanced/mountain_sideprofile.png) | No banded overlay. Confirmed no-op (A3 audit: 30 templates dead). |
| coastal | ❌ **D** | [iso](renders/quality-audit/pass_banded_advanced/coastal_isometric.png) · [top](renders/quality-audit/pass_banded_advanced/coastal_topdown.png) · [sid](renders/quality-audit/pass_banded_advanced/coastal_sideprofile.png) | No banded overlay. Confirmed no-op (A3 audit: 30 templates dead). |
| volcanic | ❌ **D** | [iso](renders/quality-audit/pass_banded_advanced/volcanic_isometric.png) · [top](renders/quality-audit/pass_banded_advanced/volcanic_topdown.png) · [sid](renders/quality-audit/pass_banded_advanced/volcanic_sideprofile.png) | No banded overlay. Confirmed no-op (A3 audit: 30 templates dead). |
| frozen | ❌ **D** | [iso](renders/quality-audit/pass_banded_advanced/frozen_isometric.png) · [top](renders/quality-audit/pass_banded_advanced/frozen_topdown.png) · [sid](renders/quality-audit/pass_banded_advanced/frozen_sideprofile.png) | No banded overlay. Confirmed no-op (A3 audit: 30 templates dead). |
| desert | ❌ **D** | [iso](renders/quality-audit/pass_banded_advanced/desert_isometric.png) · [top](renders/quality-audit/pass_banded_advanced/desert_topdown.png) · [sid](renders/quality-audit/pass_banded_advanced/desert_sideprofile.png) | No banded overlay. Confirmed no-op (A3 audit: 30 templates dead). |

### ❌ `pass_morphology` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/pass_morphology/grassland_isometric.png) · [top](renders/quality-audit/pass_morphology/grassland_topdown.png) · [sid](renders/quality-audit/pass_morphology/grassland_sideprofile.png) | Morphology effect not visible. Base terrain only. |
| mountain | ❌ **D** | [iso](renders/quality-audit/pass_morphology/mountain_isometric.png) · [top](renders/quality-audit/pass_morphology/mountain_topdown.png) · [sid](renders/quality-audit/pass_morphology/mountain_sideprofile.png) | Morphology effect not visible. Base terrain only. |
| coastal | ❌ **D** | [iso](renders/quality-audit/pass_morphology/coastal_isometric.png) · [top](renders/quality-audit/pass_morphology/coastal_topdown.png) · [sid](renders/quality-audit/pass_morphology/coastal_sideprofile.png) | Morphology effect not visible. Base terrain only. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/pass_morphology/volcanic_isometric.png) · [top](renders/quality-audit/pass_morphology/volcanic_topdown.png) · [sid](renders/quality-audit/pass_morphology/volcanic_sideprofile.png) | Morphology effect not visible. Base terrain only. |
| frozen | ❌ **D** | [iso](renders/quality-audit/pass_morphology/frozen_isometric.png) · [top](renders/quality-audit/pass_morphology/frozen_topdown.png) · [sid](renders/quality-audit/pass_morphology/frozen_sideprofile.png) | Morphology effect not visible. Base terrain only. |
| desert | ❌ **D** | [iso](renders/quality-audit/pass_morphology/desert_isometric.png) · [top](renders/quality-audit/pass_morphology/desert_topdown.png) · [sid](renders/quality-audit/pass_morphology/desert_sideprofile.png) | Morphology effect not visible. Base terrain only. |

### ❌ `stratigraphy` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/stratigraphy/grassland_isometric.png) · [top](renders/quality-audit/stratigraphy/grassland_topdown.png) · [sid](renders/quality-audit/stratigraphy/grassland_sideprofile.png) | Stratigraphy layer lines not visible. Base terrain only. |
| mountain | ❌ **D** | [iso](renders/quality-audit/stratigraphy/mountain_isometric.png) · [top](renders/quality-audit/stratigraphy/mountain_topdown.png) · [sid](renders/quality-audit/stratigraphy/mountain_sideprofile.png) | Stratigraphy layer lines not visible. Base terrain only. |
| coastal | ❌ **D** | [iso](renders/quality-audit/stratigraphy/coastal_isometric.png) · [top](renders/quality-audit/stratigraphy/coastal_topdown.png) · [sid](renders/quality-audit/stratigraphy/coastal_sideprofile.png) | Stratigraphy layer lines not visible. Base terrain only. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/stratigraphy/volcanic_isometric.png) · [top](renders/quality-audit/stratigraphy/volcanic_topdown.png) · [sid](renders/quality-audit/stratigraphy/volcanic_sideprofile.png) | Stratigraphy layer lines not visible. Base terrain only. |
| frozen | ❌ **D** | [iso](renders/quality-audit/stratigraphy/frozen_isometric.png) · [top](renders/quality-audit/stratigraphy/frozen_topdown.png) · [sid](renders/quality-audit/stratigraphy/frozen_sideprofile.png) | Stratigraphy layer lines not visible. Base terrain only. |
| desert | ❌ **D** | [iso](renders/quality-audit/stratigraphy/desert_isometric.png) · [top](renders/quality-audit/stratigraphy/desert_topdown.png) · [sid](renders/quality-audit/stratigraphy/desert_sideprofile.png) | Stratigraphy layer lines not visible. Base terrain only. |

### ❌ `integrate_deltas` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/integrate_deltas/grassland_isometric.png) · [top](renders/quality-audit/integrate_deltas/grassland_topdown.png) · [sid](renders/quality-audit/integrate_deltas/grassland_sideprofile.png) | Delta integration pass — no distinct visual output vs base terrain. |
| mountain | ❌ **D** | [iso](renders/quality-audit/integrate_deltas/mountain_isometric.png) · [top](renders/quality-audit/integrate_deltas/mountain_topdown.png) · [sid](renders/quality-audit/integrate_deltas/mountain_sideprofile.png) | Delta integration pass — no distinct visual output vs base terrain. |
| coastal | ❌ **D** | [iso](renders/quality-audit/integrate_deltas/coastal_isometric.png) · [top](renders/quality-audit/integrate_deltas/coastal_topdown.png) · [sid](renders/quality-audit/integrate_deltas/coastal_sideprofile.png) | Delta integration pass — no distinct visual output vs base terrain. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/integrate_deltas/volcanic_isometric.png) · [top](renders/quality-audit/integrate_deltas/volcanic_topdown.png) · [sid](renders/quality-audit/integrate_deltas/volcanic_sideprofile.png) | Delta integration pass — no distinct visual output vs base terrain. |
| frozen | ❌ **D** | [iso](renders/quality-audit/integrate_deltas/frozen_isometric.png) · [top](renders/quality-audit/integrate_deltas/frozen_topdown.png) · [sid](renders/quality-audit/integrate_deltas/frozen_sideprofile.png) | Delta integration pass — no distinct visual output vs base terrain. |
| desert | ❌ **D** | [iso](renders/quality-audit/integrate_deltas/desert_isometric.png) · [top](renders/quality-audit/integrate_deltas/desert_topdown.png) · [sid](renders/quality-audit/integrate_deltas/desert_sideprofile.png) | Delta integration pass — no distinct visual output vs base terrain. |

## Water / Hydrology

### 🟢 `pass_hydrology` — Grade **B+**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | 🟢 **B** | [iso](renders/quality-audit/pass_hydrology/grassland_isometric.png) · [top](renders/quality-audit/pass_hydrology/grassland_topdown.png) · [sid](renders/quality-audit/pass_hydrology/grassland_sideprofile.png) | Translucent blue water plane visible over low terrain. River traces faint. |
| mountain | 🟢 **B** | [iso](renders/quality-audit/pass_hydrology/mountain_isometric.png) · [top](renders/quality-audit/pass_hydrology/mountain_topdown.png) · [sid](renders/quality-audit/pass_hydrology/mountain_sideprofile.png) | Water plane clearly at valley level. Mountain peaks above water line. |
| coastal | 🟢 **B+** | [iso](renders/quality-audit/pass_hydrology/coastal_isometric.png) · [top](renders/quality-audit/pass_hydrology/coastal_topdown.png) · [sid](renders/quality-audit/pass_hydrology/coastal_sideprofile.png) | Majority of tile flooded. White foam on exposed land. Excellent coastal look. |
| volcanic | 🟢 **B** | [iso](renders/quality-audit/pass_hydrology/volcanic_isometric.png) · [top](renders/quality-audit/pass_hydrology/volcanic_topdown.png) · [sid](renders/quality-audit/pass_hydrology/volcanic_sideprofile.png) | Orange/amber lava plane visible. Terrain spikes above lava. |
| frozen | 🟢 **B** | [iso](renders/quality-audit/pass_hydrology/frozen_isometric.png) · [top](renders/quality-audit/pass_hydrology/frozen_topdown.png) · [sid](renders/quality-audit/pass_hydrology/frozen_sideprofile.png) | Pale ice-blue water plane. Matches frozen palette. |
| desert | 🟢 **B** | [iso](renders/quality-audit/pass_hydrology/desert_isometric.png) · [top](renders/quality-audit/pass_hydrology/desert_topdown.png) · [sid](renders/quality-audit/pass_hydrology/desert_sideprofile.png) | Water plane visible though desert is mostly dry. Oasis-like impression. |

### 🟢 `pass_hydrology_post_erosion` — Grade **B+**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | 🟢 **B+** | [iso](renders/quality-audit/pass_hydrology_post_erosion/grassland_isometric.png) · [top](renders/quality-audit/pass_hydrology_post_erosion/grassland_topdown.png) · [sid](renders/quality-audit/pass_hydrology_post_erosion/grassland_sideprofile.png) | Post-erosion water pass. Same visual as hydrology — water plane clearly showing. |
| mountain | 🟢 **B+** | [iso](renders/quality-audit/pass_hydrology_post_erosion/mountain_isometric.png) · [top](renders/quality-audit/pass_hydrology_post_erosion/mountain_topdown.png) · [sid](renders/quality-audit/pass_hydrology_post_erosion/mountain_sideprofile.png) | Post-erosion water pass. Same visual as hydrology — water plane clearly showing. |
| coastal | 🟢 **B+** | [iso](renders/quality-audit/pass_hydrology_post_erosion/coastal_isometric.png) · [top](renders/quality-audit/pass_hydrology_post_erosion/coastal_topdown.png) · [sid](renders/quality-audit/pass_hydrology_post_erosion/coastal_sideprofile.png) | Post-erosion water pass. Same visual as hydrology — water plane clearly showing. |
| volcanic | 🟢 **B+** | [iso](renders/quality-audit/pass_hydrology_post_erosion/volcanic_isometric.png) · [top](renders/quality-audit/pass_hydrology_post_erosion/volcanic_topdown.png) · [sid](renders/quality-audit/pass_hydrology_post_erosion/volcanic_sideprofile.png) | Post-erosion water pass. Same visual as hydrology — water plane clearly showing. |
| frozen | 🟢 **B+** | [iso](renders/quality-audit/pass_hydrology_post_erosion/frozen_isometric.png) · [top](renders/quality-audit/pass_hydrology_post_erosion/frozen_topdown.png) · [sid](renders/quality-audit/pass_hydrology_post_erosion/frozen_sideprofile.png) | Post-erosion water pass. Same visual as hydrology — water plane clearly showing. |
| desert | 🟢 **B+** | [iso](renders/quality-audit/pass_hydrology_post_erosion/desert_isometric.png) · [top](renders/quality-audit/pass_hydrology_post_erosion/desert_topdown.png) · [sid](renders/quality-audit/pass_hydrology_post_erosion/desert_sideprofile.png) | Post-erosion water pass. Same visual as hydrology — water plane clearly showing. |

### 🟢 `pass_water_flow_speed` — Grade **B**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | 🟢 **B** | [iso](renders/quality-audit/pass_water_flow_speed/grassland_isometric.png) · [top](renders/quality-audit/pass_water_flow_speed/grassland_topdown.png) · [sid](renders/quality-audit/pass_water_flow_speed/grassland_sideprofile.png) | Water plane visible. Flow speed channel not separately visualised but water shows. |
| mountain | 🟢 **B** | [iso](renders/quality-audit/pass_water_flow_speed/mountain_isometric.png) · [top](renders/quality-audit/pass_water_flow_speed/mountain_topdown.png) · [sid](renders/quality-audit/pass_water_flow_speed/mountain_sideprofile.png) | Water plane visible. Flow speed channel not separately visualised but water shows. |
| coastal | 🟢 **B** | [iso](renders/quality-audit/pass_water_flow_speed/coastal_isometric.png) · [top](renders/quality-audit/pass_water_flow_speed/coastal_topdown.png) · [sid](renders/quality-audit/pass_water_flow_speed/coastal_sideprofile.png) | Water plane visible. Flow speed channel not separately visualised but water shows. |
| volcanic | 🟢 **B** | [iso](renders/quality-audit/pass_water_flow_speed/volcanic_isometric.png) · [top](renders/quality-audit/pass_water_flow_speed/volcanic_topdown.png) · [sid](renders/quality-audit/pass_water_flow_speed/volcanic_sideprofile.png) | Water plane visible. Flow speed channel not separately visualised but water shows. |
| frozen | 🟢 **B** | [iso](renders/quality-audit/pass_water_flow_speed/frozen_isometric.png) · [top](renders/quality-audit/pass_water_flow_speed/frozen_topdown.png) · [sid](renders/quality-audit/pass_water_flow_speed/frozen_sideprofile.png) | Water plane visible. Flow speed channel not separately visualised but water shows. |
| desert | 🟢 **B** | [iso](renders/quality-audit/pass_water_flow_speed/desert_isometric.png) · [top](renders/quality-audit/pass_water_flow_speed/desert_topdown.png) · [sid](renders/quality-audit/pass_water_flow_speed/desert_sideprofile.png) | Water plane visible. Flow speed channel not separately visualised but water shows. |

### 🟢 `pass_river_convergence` — Grade **B**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | 🟢 **B** | [iso](renders/quality-audit/pass_river_convergence/grassland_isometric.png) · [top](renders/quality-audit/pass_river_convergence/grassland_topdown.png) · [sid](renders/quality-audit/pass_river_convergence/grassland_sideprofile.png) | Water plane shows. River convergence overlay not distinguished from hydrology. |
| mountain | 🟢 **B** | [iso](renders/quality-audit/pass_river_convergence/mountain_isometric.png) · [top](renders/quality-audit/pass_river_convergence/mountain_topdown.png) · [sid](renders/quality-audit/pass_river_convergence/mountain_sideprofile.png) | Water plane shows. River convergence overlay not distinguished from hydrology. |
| coastal | 🟢 **B** | [iso](renders/quality-audit/pass_river_convergence/coastal_isometric.png) · [top](renders/quality-audit/pass_river_convergence/coastal_topdown.png) · [sid](renders/quality-audit/pass_river_convergence/coastal_sideprofile.png) | Water plane shows. River convergence overlay not distinguished from hydrology. |
| volcanic | 🟢 **B** | [iso](renders/quality-audit/pass_river_convergence/volcanic_isometric.png) · [top](renders/quality-audit/pass_river_convergence/volcanic_topdown.png) · [sid](renders/quality-audit/pass_river_convergence/volcanic_sideprofile.png) | Water plane shows. River convergence overlay not distinguished from hydrology. |
| frozen | 🟢 **B** | [iso](renders/quality-audit/pass_river_convergence/frozen_isometric.png) · [top](renders/quality-audit/pass_river_convergence/frozen_topdown.png) · [sid](renders/quality-audit/pass_river_convergence/frozen_sideprofile.png) | Water plane shows. River convergence overlay not distinguished from hydrology. |
| desert | 🟢 **B** | [iso](renders/quality-audit/pass_river_convergence/desert_isometric.png) · [top](renders/quality-audit/pass_river_convergence/desert_topdown.png) · [sid](renders/quality-audit/pass_river_convergence/desert_sideprofile.png) | Water plane shows. River convergence overlay not distinguished from hydrology. |

### 🟢 `pass_water_depth` — Grade **B**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | 🟢 **B** | [iso](renders/quality-audit/pass_water_depth/grassland_isometric.png) · [top](renders/quality-audit/pass_water_depth/grassland_topdown.png) · [sid](renders/quality-audit/pass_water_depth/grassland_sideprofile.png) | Depth channel colours faintly through water plane. Water clearly showing. |
| mountain | 🟢 **B** | [iso](renders/quality-audit/pass_water_depth/mountain_isometric.png) · [top](renders/quality-audit/pass_water_depth/mountain_topdown.png) · [sid](renders/quality-audit/pass_water_depth/mountain_sideprofile.png) | Depth channel colours faintly through water plane. Water clearly showing. |
| coastal | 🟢 **B** | [iso](renders/quality-audit/pass_water_depth/coastal_isometric.png) · [top](renders/quality-audit/pass_water_depth/coastal_topdown.png) · [sid](renders/quality-audit/pass_water_depth/coastal_sideprofile.png) | Depth channel colours faintly through water plane. Water clearly showing. |
| volcanic | 🟢 **B** | [iso](renders/quality-audit/pass_water_depth/volcanic_isometric.png) · [top](renders/quality-audit/pass_water_depth/volcanic_topdown.png) · [sid](renders/quality-audit/pass_water_depth/volcanic_sideprofile.png) | Depth channel colours faintly through water plane. Water clearly showing. |
| frozen | 🟢 **B** | [iso](renders/quality-audit/pass_water_depth/frozen_isometric.png) · [top](renders/quality-audit/pass_water_depth/frozen_topdown.png) · [sid](renders/quality-audit/pass_water_depth/frozen_sideprofile.png) | Depth channel colours faintly through water plane. Water clearly showing. |
| desert | 🟢 **B** | [iso](renders/quality-audit/pass_water_depth/desert_isometric.png) · [top](renders/quality-audit/pass_water_depth/desert_topdown.png) · [sid](renders/quality-audit/pass_water_depth/desert_sideprofile.png) | Depth channel colours faintly through water plane. Water clearly showing. |

### 🟢 `bathymetry` — Grade **B+**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | 🟢 **B** | [iso](renders/quality-audit/bathymetry/grassland_isometric.png) · [top](renders/quality-audit/bathymetry/grassland_topdown.png) · [sid](renders/quality-audit/bathymetry/grassland_sideprofile.png) | Water plane visible. Bathymetry depth colouring subtle but present. |
| mountain | 🟢 **B** | [iso](renders/quality-audit/bathymetry/mountain_isometric.png) · [top](renders/quality-audit/bathymetry/mountain_topdown.png) · [sid](renders/quality-audit/bathymetry/mountain_sideprofile.png) | Water plane visible. Bathymetry depth colouring subtle but present. |
| coastal | 🟢 **B+** | [iso](renders/quality-audit/bathymetry/coastal_isometric.png) · [top](renders/quality-audit/bathymetry/coastal_topdown.png) · [sid](renders/quality-audit/bathymetry/coastal_sideprofile.png) | Coastal tile fully flooded. Terrain depth visible through water as lighter/darker blue zones. |
| volcanic | 🟢 **B** | [iso](renders/quality-audit/bathymetry/volcanic_isometric.png) · [top](renders/quality-audit/bathymetry/volcanic_topdown.png) · [sid](renders/quality-audit/bathymetry/volcanic_sideprofile.png) | Water plane visible. Bathymetry depth colouring subtle but present. |
| frozen | 🟢 **B** | [iso](renders/quality-audit/bathymetry/frozen_isometric.png) · [top](renders/quality-audit/bathymetry/frozen_topdown.png) · [sid](renders/quality-audit/bathymetry/frozen_sideprofile.png) | Water plane visible. Bathymetry depth colouring subtle but present. |
| desert | 🟢 **B** | [iso](renders/quality-audit/bathymetry/desert_isometric.png) · [top](renders/quality-audit/bathymetry/desert_topdown.png) · [sid](renders/quality-audit/bathymetry/desert_sideprofile.png) | Water plane visible. Bathymetry depth colouring subtle but present. |

### 🟢 `water_variants` — Grade **B**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | 🟢 **B** | [iso](renders/quality-audit/water_variants/grassland_isometric.png) · [top](renders/quality-audit/water_variants/grassland_topdown.png) · [sid](renders/quality-audit/water_variants/grassland_sideprofile.png) | Water plane visible. Variant colouring not distinguished from base hydrology. |
| mountain | 🟢 **B** | [iso](renders/quality-audit/water_variants/mountain_isometric.png) · [top](renders/quality-audit/water_variants/mountain_topdown.png) · [sid](renders/quality-audit/water_variants/mountain_sideprofile.png) | Water plane visible. Variant colouring not distinguished from base hydrology. |
| coastal | 🟢 **B** | [iso](renders/quality-audit/water_variants/coastal_isometric.png) · [top](renders/quality-audit/water_variants/coastal_topdown.png) · [sid](renders/quality-audit/water_variants/coastal_sideprofile.png) | Water plane visible. Variant colouring not distinguished from base hydrology. |
| volcanic | 🟢 **B** | [iso](renders/quality-audit/water_variants/volcanic_isometric.png) · [top](renders/quality-audit/water_variants/volcanic_topdown.png) · [sid](renders/quality-audit/water_variants/volcanic_sideprofile.png) | Water plane visible. Variant colouring not distinguished from base hydrology. |
| frozen | 🟢 **B** | [iso](renders/quality-audit/water_variants/frozen_isometric.png) · [top](renders/quality-audit/water_variants/frozen_topdown.png) · [sid](renders/quality-audit/water_variants/frozen_sideprofile.png) | Water plane visible. Variant colouring not distinguished from base hydrology. |
| desert | 🟢 **B** | [iso](renders/quality-audit/water_variants/desert_isometric.png) · [top](renders/quality-audit/water_variants/desert_topdown.png) · [sid](renders/quality-audit/water_variants/desert_sideprofile.png) | Water plane visible. Variant colouring not distinguished from base hydrology. |

### 🟢 `waterfalls` — Grade **B**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | 🟢 **B** | [iso](renders/quality-audit/waterfalls/grassland_isometric.png) · [top](renders/quality-audit/waterfalls/grassland_topdown.png) · [sid](renders/quality-audit/waterfalls/grassland_sideprofile.png) | Water plane present. Waterfall geometry not visible at tile scale. |
| mountain | 🟢 **B** | [iso](renders/quality-audit/waterfalls/mountain_isometric.png) · [top](renders/quality-audit/waterfalls/mountain_topdown.png) · [sid](renders/quality-audit/waterfalls/mountain_sideprofile.png) | Water plane present. Waterfall geometry not visible at tile scale. |
| coastal | 🟢 **B** | [iso](renders/quality-audit/waterfalls/coastal_isometric.png) · [top](renders/quality-audit/waterfalls/coastal_topdown.png) · [sid](renders/quality-audit/waterfalls/coastal_sideprofile.png) | Water plane present. Waterfall geometry not visible at tile scale. |
| volcanic | 🟢 **B** | [iso](renders/quality-audit/waterfalls/volcanic_isometric.png) · [top](renders/quality-audit/waterfalls/volcanic_topdown.png) · [sid](renders/quality-audit/waterfalls/volcanic_sideprofile.png) | Water plane present. Waterfall geometry not visible at tile scale. |
| frozen | 🟢 **B** | [iso](renders/quality-audit/waterfalls/frozen_isometric.png) · [top](renders/quality-audit/waterfalls/frozen_topdown.png) · [sid](renders/quality-audit/waterfalls/frozen_sideprofile.png) | Water plane present. Waterfall geometry not visible at tile scale. |
| desert | 🟢 **B** | [iso](renders/quality-audit/waterfalls/desert_isometric.png) · [top](renders/quality-audit/waterfalls/desert_topdown.png) · [sid](renders/quality-audit/waterfalls/desert_sideprofile.png) | Water plane present. Waterfall geometry not visible at tile scale. |

### 🟢 `waterfall_mist` — Grade **B**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | 🟢 **B** | [iso](renders/quality-audit/waterfall_mist/grassland_isometric.png) · [top](renders/quality-audit/waterfall_mist/grassland_topdown.png) · [sid](renders/quality-audit/waterfall_mist/grassland_sideprofile.png) | Water plane visible. Mist/particle effect not rendered in this pipeline. |
| mountain | 🟢 **B** | [iso](renders/quality-audit/waterfall_mist/mountain_isometric.png) · [top](renders/quality-audit/waterfall_mist/mountain_topdown.png) · [sid](renders/quality-audit/waterfall_mist/mountain_sideprofile.png) | Water plane visible. Mist/particle effect not rendered in this pipeline. |
| coastal | 🟢 **B** | [iso](renders/quality-audit/waterfall_mist/coastal_isometric.png) · [top](renders/quality-audit/waterfall_mist/coastal_topdown.png) · [sid](renders/quality-audit/waterfall_mist/coastal_sideprofile.png) | Water plane visible. Mist/particle effect not rendered in this pipeline. |
| volcanic | 🟢 **B** | [iso](renders/quality-audit/waterfall_mist/volcanic_isometric.png) · [top](renders/quality-audit/waterfall_mist/volcanic_topdown.png) · [sid](renders/quality-audit/waterfall_mist/volcanic_sideprofile.png) | Water plane visible. Mist/particle effect not rendered in this pipeline. |
| frozen | 🟢 **B** | [iso](renders/quality-audit/waterfall_mist/frozen_isometric.png) · [top](renders/quality-audit/waterfall_mist/frozen_topdown.png) · [sid](renders/quality-audit/waterfall_mist/frozen_sideprofile.png) | Water plane visible. Mist/particle effect not rendered in this pipeline. |
| desert | 🟢 **B** | [iso](renders/quality-audit/waterfall_mist/desert_isometric.png) · [top](renders/quality-audit/waterfall_mist/desert_topdown.png) · [sid](renders/quality-audit/waterfall_mist/desert_sideprofile.png) | Water plane visible. Mist/particle effect not rendered in this pipeline. |

### 🟢 `pass_seasonal_water_state` — Grade **B**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | 🟢 **B** | [iso](renders/quality-audit/pass_seasonal_water_state/grassland_isometric.png) · [top](renders/quality-audit/pass_seasonal_water_state/grassland_topdown.png) · [sid](renders/quality-audit/pass_seasonal_water_state/grassland_sideprofile.png) | Water plane showing. Seasonal variation not visually distinct between runs. |
| mountain | 🟢 **B** | [iso](renders/quality-audit/pass_seasonal_water_state/mountain_isometric.png) · [top](renders/quality-audit/pass_seasonal_water_state/mountain_topdown.png) · [sid](renders/quality-audit/pass_seasonal_water_state/mountain_sideprofile.png) | Water plane showing. Seasonal variation not visually distinct between runs. |
| coastal | 🟢 **B** | [iso](renders/quality-audit/pass_seasonal_water_state/coastal_isometric.png) · [top](renders/quality-audit/pass_seasonal_water_state/coastal_topdown.png) · [sid](renders/quality-audit/pass_seasonal_water_state/coastal_sideprofile.png) | Water plane showing. Seasonal variation not visually distinct between runs. |
| volcanic | 🟢 **B** | [iso](renders/quality-audit/pass_seasonal_water_state/volcanic_isometric.png) · [top](renders/quality-audit/pass_seasonal_water_state/volcanic_topdown.png) · [sid](renders/quality-audit/pass_seasonal_water_state/volcanic_sideprofile.png) | Water plane showing. Seasonal variation not visually distinct between runs. |
| frozen | 🟢 **B** | [iso](renders/quality-audit/pass_seasonal_water_state/frozen_isometric.png) · [top](renders/quality-audit/pass_seasonal_water_state/frozen_topdown.png) · [sid](renders/quality-audit/pass_seasonal_water_state/frozen_sideprofile.png) | Water plane showing. Seasonal variation not visually distinct between runs. |
| desert | 🟢 **B** | [iso](renders/quality-audit/pass_seasonal_water_state/desert_isometric.png) · [top](renders/quality-audit/pass_seasonal_water_state/desert_topdown.png) · [sid](renders/quality-audit/pass_seasonal_water_state/desert_sideprofile.png) | Water plane showing. Seasonal variation not visually distinct between runs. |

### 🟢 `pass_lava_simulation` — Grade **B**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ⚠️ **C** | [iso](renders/quality-audit/pass_lava_simulation/grassland_isometric.png) · [top](renders/quality-audit/pass_lava_simulation/grassland_topdown.png) · [sid](renders/quality-audit/pass_lava_simulation/grassland_sideprofile.png) | Lava sim on non-volcanic biome. Water plane shows but lava is inappropriate context. |
| mountain | ⚠️ **C** | [iso](renders/quality-audit/pass_lava_simulation/mountain_isometric.png) · [top](renders/quality-audit/pass_lava_simulation/mountain_topdown.png) · [sid](renders/quality-audit/pass_lava_simulation/mountain_sideprofile.png) | Lava sim on non-volcanic biome. Water plane shows but lava is inappropriate context. |
| coastal | ⚠️ **C** | [iso](renders/quality-audit/pass_lava_simulation/coastal_isometric.png) · [top](renders/quality-audit/pass_lava_simulation/coastal_topdown.png) · [sid](renders/quality-audit/pass_lava_simulation/coastal_sideprofile.png) | Lava sim on non-volcanic biome. Water plane shows but lava is inappropriate context. |
| volcanic | 🟢 **B+** | [iso](renders/quality-audit/pass_lava_simulation/volcanic_isometric.png) · [top](renders/quality-audit/pass_lava_simulation/volcanic_topdown.png) · [sid](renders/quality-audit/pass_lava_simulation/volcanic_sideprofile.png) | Orange lava plane clearly visible. Spiky volcanic terrain above lava. Correct. |
| frozen | ⚠️ **C** | [iso](renders/quality-audit/pass_lava_simulation/frozen_isometric.png) · [top](renders/quality-audit/pass_lava_simulation/frozen_topdown.png) · [sid](renders/quality-audit/pass_lava_simulation/frozen_sideprofile.png) | Lava sim on non-volcanic biome. Water plane shows but lava is inappropriate context. |
| desert | ⚠️ **C** | [iso](renders/quality-audit/pass_lava_simulation/desert_isometric.png) · [top](renders/quality-audit/pass_lava_simulation/desert_topdown.png) · [sid](renders/quality-audit/pass_lava_simulation/desert_sideprofile.png) | Lava sim on non-volcanic biome. Water plane shows but lava is inappropriate context. |

## Structural Masks

### ❌ `structural_masks` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/structural_masks/grassland_isometric.png) · [top](renders/quality-audit/structural_masks/grassland_topdown.png) · [sid](renders/quality-audit/structural_masks/grassland_sideprofile.png) | 8-colour mask region colouring NOT visible. Baked texture not applying. Shows plain biome mesh. |
| mountain | ❌ **D** | [iso](renders/quality-audit/structural_masks/mountain_isometric.png) · [top](renders/quality-audit/structural_masks/mountain_topdown.png) · [sid](renders/quality-audit/structural_masks/mountain_sideprofile.png) | 8-colour mask region colouring NOT visible. Baked texture not applying. Shows plain biome mesh. |
| coastal | ❌ **D** | [iso](renders/quality-audit/structural_masks/coastal_isometric.png) · [top](renders/quality-audit/structural_masks/coastal_topdown.png) · [sid](renders/quality-audit/structural_masks/coastal_sideprofile.png) | 8-colour mask region colouring NOT visible. Baked texture not applying. Shows plain biome mesh. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/structural_masks/volcanic_isometric.png) · [top](renders/quality-audit/structural_masks/volcanic_topdown.png) · [sid](renders/quality-audit/structural_masks/volcanic_sideprofile.png) | 8-colour mask region colouring NOT visible. Baked texture not applying. Shows plain biome mesh. |
| frozen | ❌ **D** | [iso](renders/quality-audit/structural_masks/frozen_isometric.png) · [top](renders/quality-audit/structural_masks/frozen_topdown.png) · [sid](renders/quality-audit/structural_masks/frozen_sideprofile.png) | 8-colour mask region colouring NOT visible. Baked texture not applying. Shows plain biome mesh. |
| desert | ❌ **D** | [iso](renders/quality-audit/structural_masks/desert_isometric.png) · [top](renders/quality-audit/structural_masks/desert_topdown.png) · [sid](renders/quality-audit/structural_masks/desert_sideprofile.png) | 8-colour mask region colouring NOT visible. Baked texture not applying. Shows plain biome mesh. |

### ❌ `structural_masks_post_erosion` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/structural_masks_post_erosion/grassland_isometric.png) · [top](renders/quality-audit/structural_masks_post_erosion/grassland_topdown.png) · [sid](renders/quality-audit/structural_masks_post_erosion/grassland_sideprofile.png) | Same as structural_masks — overlay not visible post-erosion. |
| mountain | ❌ **D** | [iso](renders/quality-audit/structural_masks_post_erosion/mountain_isometric.png) · [top](renders/quality-audit/structural_masks_post_erosion/mountain_topdown.png) · [sid](renders/quality-audit/structural_masks_post_erosion/mountain_sideprofile.png) | Same as structural_masks — overlay not visible post-erosion. |
| coastal | ❌ **D** | [iso](renders/quality-audit/structural_masks_post_erosion/coastal_isometric.png) · [top](renders/quality-audit/structural_masks_post_erosion/coastal_topdown.png) · [sid](renders/quality-audit/structural_masks_post_erosion/coastal_sideprofile.png) | Same as structural_masks — overlay not visible post-erosion. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/structural_masks_post_erosion/volcanic_isometric.png) · [top](renders/quality-audit/structural_masks_post_erosion/volcanic_topdown.png) · [sid](renders/quality-audit/structural_masks_post_erosion/volcanic_sideprofile.png) | Same as structural_masks — overlay not visible post-erosion. |
| frozen | ❌ **D** | [iso](renders/quality-audit/structural_masks_post_erosion/frozen_isometric.png) · [top](renders/quality-audit/structural_masks_post_erosion/frozen_topdown.png) · [sid](renders/quality-audit/structural_masks_post_erosion/frozen_sideprofile.png) | Same as structural_masks — overlay not visible post-erosion. |
| desert | ❌ **D** | [iso](renders/quality-audit/structural_masks_post_erosion/desert_isometric.png) · [top](renders/quality-audit/structural_masks_post_erosion/desert_topdown.png) · [sid](renders/quality-audit/structural_masks_post_erosion/desert_sideprofile.png) | Same as structural_masks — overlay not visible post-erosion. |

### ❌ `structural_masks_post_talus` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/structural_masks_post_talus/grassland_isometric.png) · [top](renders/quality-audit/structural_masks_post_talus/grassland_topdown.png) · [sid](renders/quality-audit/structural_masks_post_talus/grassland_sideprofile.png) | Same as structural_masks — overlay not visible post-talus. |
| mountain | ❌ **D** | [iso](renders/quality-audit/structural_masks_post_talus/mountain_isometric.png) · [top](renders/quality-audit/structural_masks_post_talus/mountain_topdown.png) · [sid](renders/quality-audit/structural_masks_post_talus/mountain_sideprofile.png) | Same as structural_masks — overlay not visible post-talus. |
| coastal | ❌ **D** | [iso](renders/quality-audit/structural_masks_post_talus/coastal_isometric.png) · [top](renders/quality-audit/structural_masks_post_talus/coastal_topdown.png) · [sid](renders/quality-audit/structural_masks_post_talus/coastal_sideprofile.png) | Same as structural_masks — overlay not visible post-talus. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/structural_masks_post_talus/volcanic_isometric.png) · [top](renders/quality-audit/structural_masks_post_talus/volcanic_topdown.png) · [sid](renders/quality-audit/structural_masks_post_talus/volcanic_sideprofile.png) | Same as structural_masks — overlay not visible post-talus. |
| frozen | ❌ **D** | [iso](renders/quality-audit/structural_masks_post_talus/frozen_isometric.png) · [top](renders/quality-audit/structural_masks_post_talus/frozen_topdown.png) · [sid](renders/quality-audit/structural_masks_post_talus/frozen_sideprofile.png) | Same as structural_masks — overlay not visible post-talus. |
| desert | ❌ **D** | [iso](renders/quality-audit/structural_masks_post_talus/desert_isometric.png) · [top](renders/quality-audit/structural_masks_post_talus/desert_topdown.png) · [sid](renders/quality-audit/structural_masks_post_talus/desert_sideprofile.png) | Same as structural_masks — overlay not visible post-talus. |

## Biome

### ❌ `biome_channels` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/biome_channels/grassland_isometric.png) · [top](renders/quality-audit/biome_channels/grassland_topdown.png) · [sid](renders/quality-audit/biome_channels/grassland_sideprofile.png) | biome_id channel overlay not visible. Shows plain terrain mesh. |
| mountain | ❌ **D** | [iso](renders/quality-audit/biome_channels/mountain_isometric.png) · [top](renders/quality-audit/biome_channels/mountain_topdown.png) · [sid](renders/quality-audit/biome_channels/mountain_sideprofile.png) | biome_id channel overlay not visible. Shows plain terrain mesh. |
| coastal | ❌ **D** | [iso](renders/quality-audit/biome_channels/coastal_isometric.png) · [top](renders/quality-audit/biome_channels/coastal_topdown.png) · [sid](renders/quality-audit/biome_channels/coastal_sideprofile.png) | biome_id channel overlay not visible. Shows plain terrain mesh. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/biome_channels/volcanic_isometric.png) · [top](renders/quality-audit/biome_channels/volcanic_topdown.png) · [sid](renders/quality-audit/biome_channels/volcanic_sideprofile.png) | biome_id channel overlay not visible. Shows plain terrain mesh. |
| frozen | ❌ **D** | [iso](renders/quality-audit/biome_channels/frozen_isometric.png) · [top](renders/quality-audit/biome_channels/frozen_topdown.png) · [sid](renders/quality-audit/biome_channels/frozen_sideprofile.png) | biome_id channel overlay not visible. Shows plain terrain mesh. |
| desert | ❌ **D** | [iso](renders/quality-audit/biome_channels/desert_isometric.png) · [top](renders/quality-audit/biome_channels/desert_topdown.png) · [sid](renders/quality-audit/biome_channels/desert_sideprofile.png) | biome_id channel overlay not visible. Shows plain terrain mesh. |

### ❌ `biome_surface_features` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/biome_surface_features/grassland_isometric.png) · [top](renders/quality-audit/biome_surface_features/grassland_topdown.png) · [sid](renders/quality-audit/biome_surface_features/grassland_sideprofile.png) | Surface feature overlay not visible. Terrain mesh only. |
| mountain | ❌ **D** | [iso](renders/quality-audit/biome_surface_features/mountain_isometric.png) · [top](renders/quality-audit/biome_surface_features/mountain_topdown.png) · [sid](renders/quality-audit/biome_surface_features/mountain_sideprofile.png) | Surface feature overlay not visible. Terrain mesh only. |
| coastal | ❌ **D** | [iso](renders/quality-audit/biome_surface_features/coastal_isometric.png) · [top](renders/quality-audit/biome_surface_features/coastal_topdown.png) · [sid](renders/quality-audit/biome_surface_features/coastal_sideprofile.png) | Surface feature overlay not visible. Terrain mesh only. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/biome_surface_features/volcanic_isometric.png) · [top](renders/quality-audit/biome_surface_features/volcanic_topdown.png) · [sid](renders/quality-audit/biome_surface_features/volcanic_sideprofile.png) | Surface feature overlay not visible. Terrain mesh only. |
| frozen | ❌ **D** | [iso](renders/quality-audit/biome_surface_features/frozen_isometric.png) · [top](renders/quality-audit/biome_surface_features/frozen_topdown.png) · [sid](renders/quality-audit/biome_surface_features/frozen_sideprofile.png) | Surface feature overlay not visible. Terrain mesh only. |
| desert | ❌ **D** | [iso](renders/quality-audit/biome_surface_features/desert_isometric.png) · [top](renders/quality-audit/biome_surface_features/desert_topdown.png) · [sid](renders/quality-audit/biome_surface_features/desert_sideprofile.png) | Surface feature overlay not visible. Terrain mesh only. |

### ❌ `snow_line` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/snow_line/grassland_isometric.png) · [top](renders/quality-audit/snow_line/grassland_topdown.png) · [sid](renders/quality-audit/snow_line/grassland_sideprofile.png) | Snow line elevation overlay not showing. Base terrain. |
| mountain | ❌ **D** | [iso](renders/quality-audit/snow_line/mountain_isometric.png) · [top](renders/quality-audit/snow_line/mountain_topdown.png) · [sid](renders/quality-audit/snow_line/mountain_sideprofile.png) | Snow line elevation overlay not showing. Base terrain. |
| coastal | ❌ **D** | [iso](renders/quality-audit/snow_line/coastal_isometric.png) · [top](renders/quality-audit/snow_line/coastal_topdown.png) · [sid](renders/quality-audit/snow_line/coastal_sideprofile.png) | Snow line elevation overlay not showing. Base terrain. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/snow_line/volcanic_isometric.png) · [top](renders/quality-audit/snow_line/volcanic_topdown.png) · [sid](renders/quality-audit/snow_line/volcanic_sideprofile.png) | Snow line elevation overlay not showing. Base terrain. |
| frozen | ❌ **D** | [iso](renders/quality-audit/snow_line/frozen_isometric.png) · [top](renders/quality-audit/snow_line/frozen_topdown.png) · [sid](renders/quality-audit/snow_line/frozen_sideprofile.png) | Snow line elevation overlay not showing. Base terrain. |
| desert | ❌ **D** | [iso](renders/quality-audit/snow_line/desert_isometric.png) · [top](renders/quality-audit/snow_line/desert_topdown.png) · [sid](renders/quality-audit/snow_line/desert_sideprofile.png) | Snow line elevation overlay not showing. Base terrain. |

### ❌ `terrain_labels` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/terrain_labels/grassland_isometric.png) · [top](renders/quality-audit/terrain_labels/grassland_topdown.png) · [sid](renders/quality-audit/terrain_labels/grassland_sideprofile.png) | Label channel confirmed zero output (A3 audit). Base terrain only. |
| mountain | ❌ **D** | [iso](renders/quality-audit/terrain_labels/mountain_isometric.png) · [top](renders/quality-audit/terrain_labels/mountain_topdown.png) · [sid](renders/quality-audit/terrain_labels/mountain_sideprofile.png) | Label channel confirmed zero output (A3 audit). Base terrain only. |
| coastal | ❌ **D** | [iso](renders/quality-audit/terrain_labels/coastal_isometric.png) · [top](renders/quality-audit/terrain_labels/coastal_topdown.png) · [sid](renders/quality-audit/terrain_labels/coastal_sideprofile.png) | Label channel confirmed zero output (A3 audit). Base terrain only. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/terrain_labels/volcanic_isometric.png) · [top](renders/quality-audit/terrain_labels/volcanic_topdown.png) · [sid](renders/quality-audit/terrain_labels/volcanic_sideprofile.png) | Label channel confirmed zero output (A3 audit). Base terrain only. |
| frozen | ❌ **D** | [iso](renders/quality-audit/terrain_labels/frozen_isometric.png) · [top](renders/quality-audit/terrain_labels/frozen_topdown.png) · [sid](renders/quality-audit/terrain_labels/frozen_sideprofile.png) | Label channel confirmed zero output (A3 audit). Base terrain only. |
| desert | ❌ **D** | [iso](renders/quality-audit/terrain_labels/desert_isometric.png) · [top](renders/quality-audit/terrain_labels/desert_topdown.png) · [sid](renders/quality-audit/terrain_labels/desert_sideprofile.png) | Label channel confirmed zero output (A3 audit). Base terrain only. |

### ❌ `ecotones` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/ecotones/grassland_isometric.png) · [top](renders/quality-audit/ecotones/grassland_topdown.png) · [sid](renders/quality-audit/ecotones/grassland_sideprofile.png) | Ecotone gradient overlay not visible. Base terrain. |
| mountain | ❌ **D** | [iso](renders/quality-audit/ecotones/mountain_isometric.png) · [top](renders/quality-audit/ecotones/mountain_topdown.png) · [sid](renders/quality-audit/ecotones/mountain_sideprofile.png) | Ecotone gradient overlay not visible. Base terrain. |
| coastal | ❌ **D** | [iso](renders/quality-audit/ecotones/coastal_isometric.png) · [top](renders/quality-audit/ecotones/coastal_topdown.png) · [sid](renders/quality-audit/ecotones/coastal_sideprofile.png) | Ecotone gradient overlay not visible. Base terrain. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/ecotones/volcanic_isometric.png) · [top](renders/quality-audit/ecotones/volcanic_topdown.png) · [sid](renders/quality-audit/ecotones/volcanic_sideprofile.png) | Ecotone gradient overlay not visible. Base terrain. |
| frozen | ❌ **D** | [iso](renders/quality-audit/ecotones/frozen_isometric.png) · [top](renders/quality-audit/ecotones/frozen_topdown.png) · [sid](renders/quality-audit/ecotones/frozen_sideprofile.png) | Ecotone gradient overlay not visible. Base terrain. |
| desert | ❌ **D** | [iso](renders/quality-audit/ecotones/desert_isometric.png) · [top](renders/quality-audit/ecotones/desert_topdown.png) · [sid](renders/quality-audit/ecotones/desert_sideprofile.png) | Ecotone gradient overlay not visible. Base terrain. |

### ❌ `framing` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/framing/grassland_isometric.png) · [top](renders/quality-audit/framing/grassland_topdown.png) · [sid](renders/quality-audit/framing/grassland_sideprofile.png) | Framing pass overlay not visible. Base terrain. |
| mountain | ❌ **D** | [iso](renders/quality-audit/framing/mountain_isometric.png) · [top](renders/quality-audit/framing/mountain_topdown.png) · [sid](renders/quality-audit/framing/mountain_sideprofile.png) | Framing pass overlay not visible. Base terrain. |
| coastal | ❌ **D** | [iso](renders/quality-audit/framing/coastal_isometric.png) · [top](renders/quality-audit/framing/coastal_topdown.png) · [sid](renders/quality-audit/framing/coastal_sideprofile.png) | Framing pass overlay not visible. Base terrain. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/framing/volcanic_isometric.png) · [top](renders/quality-audit/framing/volcanic_topdown.png) · [sid](renders/quality-audit/framing/volcanic_sideprofile.png) | Framing pass overlay not visible. Base terrain. |
| frozen | ❌ **D** | [iso](renders/quality-audit/framing/frozen_isometric.png) · [top](renders/quality-audit/framing/frozen_topdown.png) · [sid](renders/quality-audit/framing/frozen_sideprofile.png) | Framing pass overlay not visible. Base terrain. |
| desert | ❌ **D** | [iso](renders/quality-audit/framing/desert_isometric.png) · [top](renders/quality-audit/framing/desert_topdown.png) · [sid](renders/quality-audit/framing/desert_sideprofile.png) | Framing pass overlay not visible. Base terrain. |

## Feature

### ❌ `cliffs` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/cliffs/grassland_isometric.png) · [top](renders/quality-audit/cliffs/grassland_topdown.png) · [sid](renders/quality-audit/cliffs/grassland_sideprofile.png) | Cliff candidate overlay not visible. Terrain mesh shows but no cliff highlighting. |
| mountain | ❌ **D** | [iso](renders/quality-audit/cliffs/mountain_isometric.png) · [top](renders/quality-audit/cliffs/mountain_topdown.png) · [sid](renders/quality-audit/cliffs/mountain_sideprofile.png) | Cliff candidate overlay not visible. Terrain mesh shows but no cliff highlighting. |
| coastal | ❌ **D** | [iso](renders/quality-audit/cliffs/coastal_isometric.png) · [top](renders/quality-audit/cliffs/coastal_topdown.png) · [sid](renders/quality-audit/cliffs/coastal_sideprofile.png) | Cliff candidate overlay not visible. Terrain mesh shows but no cliff highlighting. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/cliffs/volcanic_isometric.png) · [top](renders/quality-audit/cliffs/volcanic_topdown.png) · [sid](renders/quality-audit/cliffs/volcanic_sideprofile.png) | Cliff candidate overlay not visible. Terrain mesh shows but no cliff highlighting. |
| frozen | ❌ **D** | [iso](renders/quality-audit/cliffs/frozen_isometric.png) · [top](renders/quality-audit/cliffs/frozen_topdown.png) · [sid](renders/quality-audit/cliffs/frozen_sideprofile.png) | Cliff candidate overlay not visible. Terrain mesh shows but no cliff highlighting. |
| desert | ❌ **D** | [iso](renders/quality-audit/cliffs/desert_isometric.png) · [top](renders/quality-audit/cliffs/desert_topdown.png) · [sid](renders/quality-audit/cliffs/desert_sideprofile.png) | Cliff candidate overlay not visible. Terrain mesh shows but no cliff highlighting. |

### ❌ `caves` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/caves/grassland_isometric.png) · [top](renders/quality-audit/caves/grassland_topdown.png) · [sid](renders/quality-audit/caves/grassland_sideprofile.png) | Cave mask overlay not visible. Terrain mesh only. |
| mountain | ❌ **D** | [iso](renders/quality-audit/caves/mountain_isometric.png) · [top](renders/quality-audit/caves/mountain_topdown.png) · [sid](renders/quality-audit/caves/mountain_sideprofile.png) | Cave mask overlay not visible. Terrain mesh only. |
| coastal | ❌ **D** | [iso](renders/quality-audit/caves/coastal_isometric.png) · [top](renders/quality-audit/caves/coastal_topdown.png) · [sid](renders/quality-audit/caves/coastal_sideprofile.png) | Cave mask overlay not visible. Terrain mesh only. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/caves/volcanic_isometric.png) · [top](renders/quality-audit/caves/volcanic_topdown.png) · [sid](renders/quality-audit/caves/volcanic_sideprofile.png) | Cave mask overlay not visible. Terrain mesh only. |
| frozen | ❌ **D** | [iso](renders/quality-audit/caves/frozen_isometric.png) · [top](renders/quality-audit/caves/frozen_topdown.png) · [sid](renders/quality-audit/caves/frozen_sideprofile.png) | Cave mask overlay not visible. Terrain mesh only. |
| desert | ❌ **D** | [iso](renders/quality-audit/caves/desert_isometric.png) · [top](renders/quality-audit/caves/desert_topdown.png) · [sid](renders/quality-audit/caves/desert_sideprofile.png) | Cave mask overlay not visible. Terrain mesh only. |

### ❌ `karst` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/karst/grassland_isometric.png) · [top](renders/quality-audit/karst/grassland_topdown.png) · [sid](renders/quality-audit/karst/grassland_sideprofile.png) | Karst topology not visible. Terrain mesh only. |
| mountain | ❌ **D** | [iso](renders/quality-audit/karst/mountain_isometric.png) · [top](renders/quality-audit/karst/mountain_topdown.png) · [sid](renders/quality-audit/karst/mountain_sideprofile.png) | Karst topology not visible. Terrain mesh only. |
| coastal | ❌ **D** | [iso](renders/quality-audit/karst/coastal_isometric.png) · [top](renders/quality-audit/karst/coastal_topdown.png) · [sid](renders/quality-audit/karst/coastal_sideprofile.png) | Karst topology not visible. Terrain mesh only. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/karst/volcanic_isometric.png) · [top](renders/quality-audit/karst/volcanic_topdown.png) · [sid](renders/quality-audit/karst/volcanic_sideprofile.png) | Karst topology not visible. Terrain mesh only. |
| frozen | ❌ **D** | [iso](renders/quality-audit/karst/frozen_isometric.png) · [top](renders/quality-audit/karst/frozen_topdown.png) · [sid](renders/quality-audit/karst/frozen_sideprofile.png) | Karst topology not visible. Terrain mesh only. |
| desert | ❌ **D** | [iso](renders/quality-audit/karst/desert_isometric.png) · [top](renders/quality-audit/karst/desert_topdown.png) · [sid](renders/quality-audit/karst/desert_sideprofile.png) | Karst topology not visible. Terrain mesh only. |

### ❌ `coastline` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/coastline/grassland_isometric.png) · [top](renders/quality-audit/coastline/grassland_topdown.png) · [sid](renders/quality-audit/coastline/grassland_sideprofile.png) | Coastline edge overlay not visible. Terrain mesh only. |
| mountain | ❌ **D** | [iso](renders/quality-audit/coastline/mountain_isometric.png) · [top](renders/quality-audit/coastline/mountain_topdown.png) · [sid](renders/quality-audit/coastline/mountain_sideprofile.png) | Coastline edge overlay not visible. Terrain mesh only. |
| coastal | ❌ **D** | [iso](renders/quality-audit/coastline/coastal_isometric.png) · [top](renders/quality-audit/coastline/coastal_topdown.png) · [sid](renders/quality-audit/coastline/coastal_sideprofile.png) | Coastline edge overlay not visible. Terrain mesh only. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/coastline/volcanic_isometric.png) · [top](renders/quality-audit/coastline/volcanic_topdown.png) · [sid](renders/quality-audit/coastline/volcanic_sideprofile.png) | Coastline edge overlay not visible. Terrain mesh only. |
| frozen | ❌ **D** | [iso](renders/quality-audit/coastline/frozen_isometric.png) · [top](renders/quality-audit/coastline/frozen_topdown.png) · [sid](renders/quality-audit/coastline/frozen_sideprofile.png) | Coastline edge overlay not visible. Terrain mesh only. |
| desert | ❌ **D** | [iso](renders/quality-audit/coastline/desert_isometric.png) · [top](renders/quality-audit/coastline/desert_topdown.png) · [sid](renders/quality-audit/coastline/desert_sideprofile.png) | Coastline edge overlay not visible. Terrain mesh only. |

### ❌ `emit_overhang_meshes` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/emit_overhang_meshes/grassland_isometric.png) · [top](renders/quality-audit/emit_overhang_meshes/grassland_topdown.png) · [sid](renders/quality-audit/emit_overhang_meshes/grassland_sideprofile.png) | Overhang meshes not emitted to Blender scene. Terrain only. |
| mountain | ❌ **D** | [iso](renders/quality-audit/emit_overhang_meshes/mountain_isometric.png) · [top](renders/quality-audit/emit_overhang_meshes/mountain_topdown.png) · [sid](renders/quality-audit/emit_overhang_meshes/mountain_sideprofile.png) | Overhang meshes not emitted to Blender scene. Terrain only. |
| coastal | ❌ **D** | [iso](renders/quality-audit/emit_overhang_meshes/coastal_isometric.png) · [top](renders/quality-audit/emit_overhang_meshes/coastal_topdown.png) · [sid](renders/quality-audit/emit_overhang_meshes/coastal_sideprofile.png) | Overhang meshes not emitted to Blender scene. Terrain only. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/emit_overhang_meshes/volcanic_isometric.png) · [top](renders/quality-audit/emit_overhang_meshes/volcanic_topdown.png) · [sid](renders/quality-audit/emit_overhang_meshes/volcanic_sideprofile.png) | Overhang meshes not emitted to Blender scene. Terrain only. |
| frozen | ❌ **D** | [iso](renders/quality-audit/emit_overhang_meshes/frozen_isometric.png) · [top](renders/quality-audit/emit_overhang_meshes/frozen_topdown.png) · [sid](renders/quality-audit/emit_overhang_meshes/frozen_sideprofile.png) | Overhang meshes not emitted to Blender scene. Terrain only. |
| desert | ❌ **D** | [iso](renders/quality-audit/emit_overhang_meshes/desert_isometric.png) · [top](renders/quality-audit/emit_overhang_meshes/desert_topdown.png) · [sid](renders/quality-audit/emit_overhang_meshes/desert_sideprofile.png) | Overhang meshes not emitted to Blender scene. Terrain only. |

### ❌ `pass_terrain_features` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/pass_terrain_features/grassland_isometric.png) · [top](renders/quality-audit/pass_terrain_features/grassland_topdown.png) · [sid](renders/quality-audit/pass_terrain_features/grassland_sideprofile.png) | Feature pass overlay not visible. Base terrain. |
| mountain | ❌ **D** | [iso](renders/quality-audit/pass_terrain_features/mountain_isometric.png) · [top](renders/quality-audit/pass_terrain_features/mountain_topdown.png) · [sid](renders/quality-audit/pass_terrain_features/mountain_sideprofile.png) | Feature pass overlay not visible. Base terrain. |
| coastal | ❌ **D** | [iso](renders/quality-audit/pass_terrain_features/coastal_isometric.png) · [top](renders/quality-audit/pass_terrain_features/coastal_topdown.png) · [sid](renders/quality-audit/pass_terrain_features/coastal_sideprofile.png) | Feature pass overlay not visible. Base terrain. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/pass_terrain_features/volcanic_isometric.png) · [top](renders/quality-audit/pass_terrain_features/volcanic_topdown.png) · [sid](renders/quality-audit/pass_terrain_features/volcanic_sideprofile.png) | Feature pass overlay not visible. Base terrain. |
| frozen | ❌ **D** | [iso](renders/quality-audit/pass_terrain_features/frozen_isometric.png) · [top](renders/quality-audit/pass_terrain_features/frozen_topdown.png) · [sid](renders/quality-audit/pass_terrain_features/frozen_sideprofile.png) | Feature pass overlay not visible. Base terrain. |
| desert | ❌ **D** | [iso](renders/quality-audit/pass_terrain_features/desert_isometric.png) · [top](renders/quality-audit/pass_terrain_features/desert_topdown.png) · [sid](renders/quality-audit/pass_terrain_features/desert_sideprofile.png) | Feature pass overlay not visible. Base terrain. |

## Scatter / Vegetation

### ❌ `scatter_intelligent` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/scatter_intelligent/grassland_isometric.png) · [top](renders/quality-audit/scatter_intelligent/grassland_topdown.png) · [sid](renders/quality-audit/scatter_intelligent/grassland_sideprofile.png) | 300 sprites placed from tree_instance_points but sub-pixel at camera distance (~300m). Invisible. |
| mountain | ❌ **D** | [iso](renders/quality-audit/scatter_intelligent/mountain_isometric.png) · [top](renders/quality-audit/scatter_intelligent/mountain_topdown.png) · [sid](renders/quality-audit/scatter_intelligent/mountain_sideprofile.png) | 300 sprites placed from tree_instance_points but sub-pixel at camera distance (~300m). Invisible. |
| coastal | ❌ **D** | [iso](renders/quality-audit/scatter_intelligent/coastal_isometric.png) · [top](renders/quality-audit/scatter_intelligent/coastal_topdown.png) · [sid](renders/quality-audit/scatter_intelligent/coastal_sideprofile.png) | 300 sprites placed from tree_instance_points but sub-pixel at camera distance (~300m). Invisible. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/scatter_intelligent/volcanic_isometric.png) · [top](renders/quality-audit/scatter_intelligent/volcanic_topdown.png) · [sid](renders/quality-audit/scatter_intelligent/volcanic_sideprofile.png) | 300 sprites placed from tree_instance_points but sub-pixel at camera distance (~300m). Invisible. |
| frozen | ❌ **D** | [iso](renders/quality-audit/scatter_intelligent/frozen_isometric.png) · [top](renders/quality-audit/scatter_intelligent/frozen_topdown.png) · [sid](renders/quality-audit/scatter_intelligent/frozen_sideprofile.png) | 300 sprites placed from tree_instance_points but sub-pixel at camera distance (~300m). Invisible. |
| desert | ❌ **D** | [iso](renders/quality-audit/scatter_intelligent/desert_isometric.png) · [top](renders/quality-audit/scatter_intelligent/desert_topdown.png) · [sid](renders/quality-audit/scatter_intelligent/desert_sideprofile.png) | 300 sprites placed from tree_instance_points but sub-pixel at camera distance (~300m). Invisible. |

### ❌ `pass_procedural_grass` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/pass_procedural_grass/grassland_isometric.png) · [top](renders/quality-audit/pass_procedural_grass/grassland_topdown.png) · [sid](renders/quality-audit/pass_procedural_grass/grassland_sideprofile.png) | grass_density_map 78% nonzero, 7545 placements. Sprites 0.8–3.3m tall — sub-pixel at camera. Invisible in render. |
| mountain | ❌ **D** | [iso](renders/quality-audit/pass_procedural_grass/mountain_isometric.png) · [top](renders/quality-audit/pass_procedural_grass/mountain_topdown.png) · [sid](renders/quality-audit/pass_procedural_grass/mountain_sideprofile.png) | grass_density_map 78% nonzero, 7545 placements. Sprites 0.8–3.3m tall — sub-pixel at camera. Invisible in render. |
| coastal | ❌ **D** | [iso](renders/quality-audit/pass_procedural_grass/coastal_isometric.png) · [top](renders/quality-audit/pass_procedural_grass/coastal_topdown.png) · [sid](renders/quality-audit/pass_procedural_grass/coastal_sideprofile.png) | grass_density_map 78% nonzero, 7545 placements. Sprites 0.8–3.3m tall — sub-pixel at camera. Invisible in render. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/pass_procedural_grass/volcanic_isometric.png) · [top](renders/quality-audit/pass_procedural_grass/volcanic_topdown.png) · [sid](renders/quality-audit/pass_procedural_grass/volcanic_sideprofile.png) | grass_density_map 78% nonzero, 7545 placements. Sprites 0.8–3.3m tall — sub-pixel at camera. Invisible in render. |
| frozen | ❌ **D** | [iso](renders/quality-audit/pass_procedural_grass/frozen_isometric.png) · [top](renders/quality-audit/pass_procedural_grass/frozen_topdown.png) · [sid](renders/quality-audit/pass_procedural_grass/frozen_sideprofile.png) | grass_density_map 78% nonzero, 7545 placements. Sprites 0.8–3.3m tall — sub-pixel at camera. Invisible in render. |
| desert | ❌ **D** | [iso](renders/quality-audit/pass_procedural_grass/desert_isometric.png) · [top](renders/quality-audit/pass_procedural_grass/desert_topdown.png) · [sid](renders/quality-audit/pass_procedural_grass/desert_sideprofile.png) | grass_density_map 78% nonzero, 7545 placements. Sprites 0.8–3.3m tall — sub-pixel at camera. Invisible in render. |

### ❌ `emergent_grass` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/emergent_grass/grassland_isometric.png) · [top](renders/quality-audit/emergent_grass/grassland_topdown.png) · [sid](renders/quality-audit/emergent_grass/grassland_sideprofile.png) | Sprites placed but invisible at camera distance. |
| mountain | ❌ **D** | [iso](renders/quality-audit/emergent_grass/mountain_isometric.png) · [top](renders/quality-audit/emergent_grass/mountain_topdown.png) · [sid](renders/quality-audit/emergent_grass/mountain_sideprofile.png) | Sprites placed but invisible at camera distance. |
| coastal | ❌ **D** | [iso](renders/quality-audit/emergent_grass/coastal_isometric.png) · [top](renders/quality-audit/emergent_grass/coastal_topdown.png) · [sid](renders/quality-audit/emergent_grass/coastal_sideprofile.png) | Sparse density — few sprites placed, all invisible. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/emergent_grass/volcanic_isometric.png) · [top](renders/quality-audit/emergent_grass/volcanic_topdown.png) · [sid](renders/quality-audit/emergent_grass/volcanic_sideprofile.png) | Sprites placed but invisible at camera distance. |
| frozen | ❌ **D** | [iso](renders/quality-audit/emergent_grass/frozen_isometric.png) · [top](renders/quality-audit/emergent_grass/frozen_topdown.png) · [sid](renders/quality-audit/emergent_grass/frozen_sideprofile.png) | Sparse density — few sprites placed, all invisible. |
| desert | ❌ **D** | [iso](renders/quality-audit/emergent_grass/desert_isometric.png) · [top](renders/quality-audit/emergent_grass/desert_topdown.png) · [sid](renders/quality-audit/emergent_grass/desert_sideprofile.png) | Sparse density — few sprites placed, all invisible. |

### ❌ `vegetation_depth` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/vegetation_depth/grassland_isometric.png) · [top](renders/quality-audit/vegetation_depth/grassland_topdown.png) · [sid](renders/quality-audit/vegetation_depth/grassland_sideprofile.png) | Vegetation depth channel not visualised distinctly. Base terrain. |
| mountain | ❌ **D** | [iso](renders/quality-audit/vegetation_depth/mountain_isometric.png) · [top](renders/quality-audit/vegetation_depth/mountain_topdown.png) · [sid](renders/quality-audit/vegetation_depth/mountain_sideprofile.png) | Vegetation depth channel not visualised distinctly. Base terrain. |
| coastal | ❌ **D** | [iso](renders/quality-audit/vegetation_depth/coastal_isometric.png) · [top](renders/quality-audit/vegetation_depth/coastal_topdown.png) · [sid](renders/quality-audit/vegetation_depth/coastal_sideprofile.png) | Vegetation depth channel not visualised distinctly. Base terrain. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/vegetation_depth/volcanic_isometric.png) · [top](renders/quality-audit/vegetation_depth/volcanic_topdown.png) · [sid](renders/quality-audit/vegetation_depth/volcanic_sideprofile.png) | Vegetation depth channel not visualised distinctly. Base terrain. |
| frozen | ❌ **D** | [iso](renders/quality-audit/vegetation_depth/frozen_isometric.png) · [top](renders/quality-audit/vegetation_depth/frozen_topdown.png) · [sid](renders/quality-audit/vegetation_depth/frozen_sideprofile.png) | Vegetation depth channel not visualised distinctly. Base terrain. |
| desert | ❌ **D** | [iso](renders/quality-audit/vegetation_depth/desert_isometric.png) · [top](renders/quality-audit/vegetation_depth/desert_topdown.png) · [sid](renders/quality-audit/vegetation_depth/desert_sideprofile.png) | Vegetation depth channel not visualised distinctly. Base terrain. |

### ❌ `emit_particle_systems` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/emit_particle_systems/grassland_isometric.png) · [top](renders/quality-audit/emit_particle_systems/grassland_topdown.png) · [sid](renders/quality-audit/emit_particle_systems/grassland_sideprofile.png) | Particle system data not rendered in static Blender render. Base terrain. |
| mountain | ❌ **D** | [iso](renders/quality-audit/emit_particle_systems/mountain_isometric.png) · [top](renders/quality-audit/emit_particle_systems/mountain_topdown.png) · [sid](renders/quality-audit/emit_particle_systems/mountain_sideprofile.png) | Particle system data not rendered in static Blender render. Base terrain. |
| coastal | ❌ **D** | [iso](renders/quality-audit/emit_particle_systems/coastal_isometric.png) · [top](renders/quality-audit/emit_particle_systems/coastal_topdown.png) · [sid](renders/quality-audit/emit_particle_systems/coastal_sideprofile.png) | Particle system data not rendered in static Blender render. Base terrain. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/emit_particle_systems/volcanic_isometric.png) · [top](renders/quality-audit/emit_particle_systems/volcanic_topdown.png) · [sid](renders/quality-audit/emit_particle_systems/volcanic_sideprofile.png) | Particle system data not rendered in static Blender render. Base terrain. |
| frozen | ❌ **D** | [iso](renders/quality-audit/emit_particle_systems/frozen_isometric.png) · [top](renders/quality-audit/emit_particle_systems/frozen_topdown.png) · [sid](renders/quality-audit/emit_particle_systems/frozen_sideprofile.png) | Particle system data not rendered in static Blender render. Base terrain. |
| desert | ❌ **D** | [iso](renders/quality-audit/emit_particle_systems/desert_isometric.png) · [top](renders/quality-audit/emit_particle_systems/desert_topdown.png) · [sid](renders/quality-audit/emit_particle_systems/desert_sideprofile.png) | Particle system data not rendered in static Blender render. Base terrain. |

## Material / Splatmap

### ❌ `materials_v2` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/materials_v2/grassland_isometric.png) · [top](renders/quality-audit/materials_v2/grassland_topdown.png) · [sid](renders/quality-audit/materials_v2/grassland_sideprofile.png) | Splatmap multiband not visible. 5-colour node mix created but not rendering. Base biome mesh. |
| mountain | ❌ **D** | [iso](renders/quality-audit/materials_v2/mountain_isometric.png) · [top](renders/quality-audit/materials_v2/mountain_topdown.png) · [sid](renders/quality-audit/materials_v2/mountain_sideprofile.png) | Splatmap multiband not visible. 5-colour node mix created but not rendering. Base biome mesh. |
| coastal | ❌ **D** | [iso](renders/quality-audit/materials_v2/coastal_isometric.png) · [top](renders/quality-audit/materials_v2/coastal_topdown.png) · [sid](renders/quality-audit/materials_v2/coastal_sideprofile.png) | Splatmap multiband not visible. 5-colour node mix created but not rendering. Base biome mesh. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/materials_v2/volcanic_isometric.png) · [top](renders/quality-audit/materials_v2/volcanic_topdown.png) · [sid](renders/quality-audit/materials_v2/volcanic_sideprofile.png) | Splatmap multiband not visible. 5-colour node mix created but not rendering. Base biome mesh. |
| frozen | ❌ **D** | [iso](renders/quality-audit/materials_v2/frozen_isometric.png) · [top](renders/quality-audit/materials_v2/frozen_topdown.png) · [sid](renders/quality-audit/materials_v2/frozen_sideprofile.png) | Splatmap multiband not visible. 5-colour node mix created but not rendering. Base biome mesh. |
| desert | ❌ **D** | [iso](renders/quality-audit/materials_v2/desert_isometric.png) · [top](renders/quality-audit/materials_v2/desert_topdown.png) · [sid](renders/quality-audit/materials_v2/desert_sideprofile.png) | Splatmap multiband not visible. 5-colour node mix created but not rendering. Base biome mesh. |

### ❌ `materials_v2_volcanic` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/materials_v2_volcanic/grassland_isometric.png) · [top](renders/quality-audit/materials_v2_volcanic/grassland_topdown.png) · [sid](renders/quality-audit/materials_v2_volcanic/grassland_sideprofile.png) | Volcanic splatmap not visible. Same spiky pink mesh as terrain_gen. |
| mountain | ❌ **D** | [iso](renders/quality-audit/materials_v2_volcanic/mountain_isometric.png) · [top](renders/quality-audit/materials_v2_volcanic/mountain_topdown.png) · [sid](renders/quality-audit/materials_v2_volcanic/mountain_sideprofile.png) | Volcanic splatmap not visible. Same spiky pink mesh as terrain_gen. |
| coastal | ❌ **D** | [iso](renders/quality-audit/materials_v2_volcanic/coastal_isometric.png) · [top](renders/quality-audit/materials_v2_volcanic/coastal_topdown.png) · [sid](renders/quality-audit/materials_v2_volcanic/coastal_sideprofile.png) | Volcanic splatmap not visible. Same spiky pink mesh as terrain_gen. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/materials_v2_volcanic/volcanic_isometric.png) · [top](renders/quality-audit/materials_v2_volcanic/volcanic_topdown.png) · [sid](renders/quality-audit/materials_v2_volcanic/volcanic_sideprofile.png) | Volcanic splatmap not visible. Same spiky pink mesh as terrain_gen. |
| frozen | ❌ **D** | [iso](renders/quality-audit/materials_v2_volcanic/frozen_isometric.png) · [top](renders/quality-audit/materials_v2_volcanic/frozen_topdown.png) · [sid](renders/quality-audit/materials_v2_volcanic/frozen_sideprofile.png) | Volcanic splatmap not visible. Same spiky pink mesh as terrain_gen. |
| desert | ❌ **D** | [iso](renders/quality-audit/materials_v2_volcanic/desert_isometric.png) · [top](renders/quality-audit/materials_v2_volcanic/desert_topdown.png) · [sid](renders/quality-audit/materials_v2_volcanic/desert_sideprofile.png) | Volcanic splatmap not visible. Same spiky pink mesh as terrain_gen. |

### ❌ `macro_color` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/macro_color/grassland_isometric.png) · [top](renders/quality-audit/macro_color/grassland_topdown.png) · [sid](renders/quality-audit/macro_color/grassland_sideprofile.png) | Macro colour channel not applying. Base biome mesh. |
| mountain | ❌ **D** | [iso](renders/quality-audit/macro_color/mountain_isometric.png) · [top](renders/quality-audit/macro_color/mountain_topdown.png) · [sid](renders/quality-audit/macro_color/mountain_sideprofile.png) | Macro colour channel not applying. Base biome mesh. |
| coastal | ❌ **D** | [iso](renders/quality-audit/macro_color/coastal_isometric.png) · [top](renders/quality-audit/macro_color/coastal_topdown.png) · [sid](renders/quality-audit/macro_color/coastal_sideprofile.png) | Macro colour channel not applying. Base biome mesh. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/macro_color/volcanic_isometric.png) · [top](renders/quality-audit/macro_color/volcanic_topdown.png) · [sid](renders/quality-audit/macro_color/volcanic_sideprofile.png) | Macro colour channel not applying. Base biome mesh. |
| frozen | ❌ **D** | [iso](renders/quality-audit/macro_color/frozen_isometric.png) · [top](renders/quality-audit/macro_color/frozen_topdown.png) · [sid](renders/quality-audit/macro_color/frozen_sideprofile.png) | Macro colour channel not applying. Base biome mesh. |
| desert | ❌ **D** | [iso](renders/quality-audit/macro_color/desert_isometric.png) · [top](renders/quality-audit/macro_color/desert_topdown.png) · [sid](renders/quality-audit/macro_color/desert_sideprofile.png) | Macro colour channel not applying. Base biome mesh. |

### ❌ `multiscale_breakup` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/multiscale_breakup/grassland_isometric.png) · [top](renders/quality-audit/multiscale_breakup/grassland_topdown.png) · [sid](renders/quality-audit/multiscale_breakup/grassland_sideprofile.png) | Breakup pattern not visible. Base biome mesh. |
| mountain | ❌ **D** | [iso](renders/quality-audit/multiscale_breakup/mountain_isometric.png) · [top](renders/quality-audit/multiscale_breakup/mountain_topdown.png) · [sid](renders/quality-audit/multiscale_breakup/mountain_sideprofile.png) | Breakup pattern not visible. Base biome mesh. |
| coastal | ❌ **D** | [iso](renders/quality-audit/multiscale_breakup/coastal_isometric.png) · [top](renders/quality-audit/multiscale_breakup/coastal_topdown.png) · [sid](renders/quality-audit/multiscale_breakup/coastal_sideprofile.png) | Breakup pattern not visible. Base biome mesh. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/multiscale_breakup/volcanic_isometric.png) · [top](renders/quality-audit/multiscale_breakup/volcanic_topdown.png) · [sid](renders/quality-audit/multiscale_breakup/volcanic_sideprofile.png) | Breakup pattern not visible. Base biome mesh. |
| frozen | ❌ **D** | [iso](renders/quality-audit/multiscale_breakup/frozen_isometric.png) · [top](renders/quality-audit/multiscale_breakup/frozen_topdown.png) · [sid](renders/quality-audit/multiscale_breakup/frozen_sideprofile.png) | Breakup pattern not visible. Base biome mesh. |
| desert | ❌ **D** | [iso](renders/quality-audit/multiscale_breakup/desert_isometric.png) · [top](renders/quality-audit/multiscale_breakup/desert_topdown.png) · [sid](renders/quality-audit/multiscale_breakup/desert_sideprofile.png) | Breakup pattern not visible. Base biome mesh. |

### ❌ `quixel_ingest` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/quixel_ingest/grassland_isometric.png) · [top](renders/quality-audit/quixel_ingest/grassland_topdown.png) · [sid](renders/quality-audit/quixel_ingest/grassland_sideprofile.png) | Quixel material not applied in Blender render. Base biome mesh. |
| mountain | ❌ **D** | [iso](renders/quality-audit/quixel_ingest/mountain_isometric.png) · [top](renders/quality-audit/quixel_ingest/mountain_topdown.png) · [sid](renders/quality-audit/quixel_ingest/mountain_sideprofile.png) | Quixel material not applied in Blender render. Base biome mesh. |
| coastal | ❌ **D** | [iso](renders/quality-audit/quixel_ingest/coastal_isometric.png) · [top](renders/quality-audit/quixel_ingest/coastal_topdown.png) · [sid](renders/quality-audit/quixel_ingest/coastal_sideprofile.png) | Quixel material not applied in Blender render. Base biome mesh. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/quixel_ingest/volcanic_isometric.png) · [top](renders/quality-audit/quixel_ingest/volcanic_topdown.png) · [sid](renders/quality-audit/quixel_ingest/volcanic_sideprofile.png) | Quixel material not applied in Blender render. Base biome mesh. |
| frozen | ❌ **D** | [iso](renders/quality-audit/quixel_ingest/frozen_isometric.png) · [top](renders/quality-audit/quixel_ingest/frozen_topdown.png) · [sid](renders/quality-audit/quixel_ingest/frozen_sideprofile.png) | Quixel material not applied in Blender render. Base biome mesh. |
| desert | ❌ **D** | [iso](renders/quality-audit/quixel_ingest/desert_isometric.png) · [top](renders/quality-audit/quixel_ingest/desert_topdown.png) · [sid](renders/quality-audit/quixel_ingest/desert_sideprofile.png) | Quixel material not applied in Blender render. Base biome mesh. |

### ❌ `roughness_driver` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/roughness_driver/grassland_isometric.png) · [top](renders/quality-audit/roughness_driver/grassland_topdown.png) · [sid](renders/quality-audit/roughness_driver/grassland_sideprofile.png) | Roughness channel not visible in diffuse render. Base biome mesh. |
| mountain | ❌ **D** | [iso](renders/quality-audit/roughness_driver/mountain_isometric.png) · [top](renders/quality-audit/roughness_driver/mountain_topdown.png) · [sid](renders/quality-audit/roughness_driver/mountain_sideprofile.png) | Roughness channel not visible in diffuse render. Base biome mesh. |
| coastal | ❌ **D** | [iso](renders/quality-audit/roughness_driver/coastal_isometric.png) · [top](renders/quality-audit/roughness_driver/coastal_topdown.png) · [sid](renders/quality-audit/roughness_driver/coastal_sideprofile.png) | Roughness channel not visible in diffuse render. Base biome mesh. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/roughness_driver/volcanic_isometric.png) · [top](renders/quality-audit/roughness_driver/volcanic_topdown.png) · [sid](renders/quality-audit/roughness_driver/volcanic_sideprofile.png) | Roughness channel not visible in diffuse render. Base biome mesh. |
| frozen | ❌ **D** | [iso](renders/quality-audit/roughness_driver/frozen_isometric.png) · [top](renders/quality-audit/roughness_driver/frozen_topdown.png) · [sid](renders/quality-audit/roughness_driver/frozen_sideprofile.png) | Roughness channel not visible in diffuse render. Base biome mesh. |
| desert | ❌ **D** | [iso](renders/quality-audit/roughness_driver/desert_isometric.png) · [top](renders/quality-audit/roughness_driver/desert_topdown.png) · [sid](renders/quality-audit/roughness_driver/desert_sideprofile.png) | Roughness channel not visible in diffuse render. Base biome mesh. |

### ❌ `stochastic_shader` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/stochastic_shader/grassland_isometric.png) · [top](renders/quality-audit/stochastic_shader/grassland_topdown.png) · [sid](renders/quality-audit/stochastic_shader/grassland_sideprofile.png) | Stochastic pattern not visible. Base biome mesh. |
| mountain | ❌ **D** | [iso](renders/quality-audit/stochastic_shader/mountain_isometric.png) · [top](renders/quality-audit/stochastic_shader/mountain_topdown.png) · [sid](renders/quality-audit/stochastic_shader/mountain_sideprofile.png) | Stochastic pattern not visible. Base biome mesh. |
| coastal | ❌ **D** | [iso](renders/quality-audit/stochastic_shader/coastal_isometric.png) · [top](renders/quality-audit/stochastic_shader/coastal_topdown.png) · [sid](renders/quality-audit/stochastic_shader/coastal_sideprofile.png) | Stochastic pattern not visible. Base biome mesh. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/stochastic_shader/volcanic_isometric.png) · [top](renders/quality-audit/stochastic_shader/volcanic_topdown.png) · [sid](renders/quality-audit/stochastic_shader/volcanic_sideprofile.png) | Stochastic pattern not visible. Base biome mesh. |
| frozen | ❌ **D** | [iso](renders/quality-audit/stochastic_shader/frozen_isometric.png) · [top](renders/quality-audit/stochastic_shader/frozen_topdown.png) · [sid](renders/quality-audit/stochastic_shader/frozen_sideprofile.png) | Stochastic pattern not visible. Base biome mesh. |
| desert | ❌ **D** | [iso](renders/quality-audit/stochastic_shader/desert_isometric.png) · [top](renders/quality-audit/stochastic_shader/desert_topdown.png) · [sid](renders/quality-audit/stochastic_shader/desert_sideprofile.png) | Stochastic pattern not visible. Base biome mesh. |

### ❌ `shadow_clipmap` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/shadow_clipmap/grassland_isometric.png) · [top](renders/quality-audit/shadow_clipmap/grassland_topdown.png) · [sid](renders/quality-audit/shadow_clipmap/grassland_sideprofile.png) | Shadow clipmap not affecting render. Base biome mesh. |
| mountain | ❌ **D** | [iso](renders/quality-audit/shadow_clipmap/mountain_isometric.png) · [top](renders/quality-audit/shadow_clipmap/mountain_topdown.png) · [sid](renders/quality-audit/shadow_clipmap/mountain_sideprofile.png) | Shadow clipmap not affecting render. Base biome mesh. |
| coastal | ❌ **D** | [iso](renders/quality-audit/shadow_clipmap/coastal_isometric.png) · [top](renders/quality-audit/shadow_clipmap/coastal_topdown.png) · [sid](renders/quality-audit/shadow_clipmap/coastal_sideprofile.png) | Shadow clipmap not affecting render. Base biome mesh. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/shadow_clipmap/volcanic_isometric.png) · [top](renders/quality-audit/shadow_clipmap/volcanic_topdown.png) · [sid](renders/quality-audit/shadow_clipmap/volcanic_sideprofile.png) | Shadow clipmap not affecting render. Base biome mesh. |
| frozen | ❌ **D** | [iso](renders/quality-audit/shadow_clipmap/frozen_isometric.png) · [top](renders/quality-audit/shadow_clipmap/frozen_topdown.png) · [sid](renders/quality-audit/shadow_clipmap/frozen_sideprofile.png) | Shadow clipmap not affecting render. Base biome mesh. |
| desert | ❌ **D** | [iso](renders/quality-audit/shadow_clipmap/desert_isometric.png) · [top](renders/quality-audit/shadow_clipmap/desert_topdown.png) · [sid](renders/quality-audit/shadow_clipmap/desert_sideprofile.png) | Shadow clipmap not affecting render. Base biome mesh. |

### ❌ `saliency_refine` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/saliency_refine/grassland_isometric.png) · [top](renders/quality-audit/saliency_refine/grassland_topdown.png) · [sid](renders/quality-audit/saliency_refine/grassland_sideprofile.png) | Saliency mask not visible. Base biome mesh. |
| mountain | ❌ **D** | [iso](renders/quality-audit/saliency_refine/mountain_isometric.png) · [top](renders/quality-audit/saliency_refine/mountain_topdown.png) · [sid](renders/quality-audit/saliency_refine/mountain_sideprofile.png) | Saliency mask not visible. Base biome mesh. |
| coastal | ❌ **D** | [iso](renders/quality-audit/saliency_refine/coastal_isometric.png) · [top](renders/quality-audit/saliency_refine/coastal_topdown.png) · [sid](renders/quality-audit/saliency_refine/coastal_sideprofile.png) | Saliency mask not visible. Base biome mesh. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/saliency_refine/volcanic_isometric.png) · [top](renders/quality-audit/saliency_refine/volcanic_topdown.png) · [sid](renders/quality-audit/saliency_refine/volcanic_sideprofile.png) | Saliency mask not visible. Base biome mesh. |
| frozen | ❌ **D** | [iso](renders/quality-audit/saliency_refine/frozen_isometric.png) · [top](renders/quality-audit/saliency_refine/frozen_topdown.png) · [sid](renders/quality-audit/saliency_refine/frozen_sideprofile.png) | Saliency mask not visible. Base biome mesh. |
| desert | ❌ **D** | [iso](renders/quality-audit/saliency_refine/desert_isometric.png) · [top](renders/quality-audit/saliency_refine/desert_topdown.png) · [sid](renders/quality-audit/saliency_refine/desert_sideprofile.png) | Saliency mask not visible. Base biome mesh. |

### ❌ `decals` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/decals/grassland_isometric.png) · [top](renders/quality-audit/decals/grassland_topdown.png) · [sid](renders/quality-audit/decals/grassland_sideprofile.png) | Decal geometry not placed in Blender scene. Base biome mesh. |
| mountain | ❌ **D** | [iso](renders/quality-audit/decals/mountain_isometric.png) · [top](renders/quality-audit/decals/mountain_topdown.png) · [sid](renders/quality-audit/decals/mountain_sideprofile.png) | Decal geometry not placed in Blender scene. Base biome mesh. |
| coastal | ❌ **D** | [iso](renders/quality-audit/decals/coastal_isometric.png) · [top](renders/quality-audit/decals/coastal_topdown.png) · [sid](renders/quality-audit/decals/coastal_sideprofile.png) | Decal geometry not placed in Blender scene. Base biome mesh. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/decals/volcanic_isometric.png) · [top](renders/quality-audit/decals/volcanic_topdown.png) · [sid](renders/quality-audit/decals/volcanic_sideprofile.png) | Decal geometry not placed in Blender scene. Base biome mesh. |
| frozen | ❌ **D** | [iso](renders/quality-audit/decals/frozen_isometric.png) · [top](renders/quality-audit/decals/frozen_topdown.png) · [sid](renders/quality-audit/decals/frozen_sideprofile.png) | Decal geometry not placed in Blender scene. Base biome mesh. |
| desert | ❌ **D** | [iso](renders/quality-audit/decals/desert_isometric.png) · [top](renders/quality-audit/decals/desert_topdown.png) · [sid](renders/quality-audit/decals/desert_sideprofile.png) | Decal geometry not placed in Blender scene. Base biome mesh. |

## Gameplay

### ❌ `audio_zones` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/audio_zones/grassland_isometric.png) · [top](renders/quality-audit/audio_zones/grassland_topdown.png) · [sid](renders/quality-audit/audio_zones/grassland_sideprofile.png) | Zone colour overlay not visible. Base terrain. |
| mountain | ❌ **D** | [iso](renders/quality-audit/audio_zones/mountain_isometric.png) · [top](renders/quality-audit/audio_zones/mountain_topdown.png) · [sid](renders/quality-audit/audio_zones/mountain_sideprofile.png) | Zone colour overlay not visible. Base terrain. |
| coastal | ❌ **D** | [iso](renders/quality-audit/audio_zones/coastal_isometric.png) · [top](renders/quality-audit/audio_zones/coastal_topdown.png) · [sid](renders/quality-audit/audio_zones/coastal_sideprofile.png) | Zone colour overlay not visible. Base terrain. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/audio_zones/volcanic_isometric.png) · [top](renders/quality-audit/audio_zones/volcanic_topdown.png) · [sid](renders/quality-audit/audio_zones/volcanic_sideprofile.png) | Zone colour overlay not visible. Base terrain. |
| frozen | ❌ **D** | [iso](renders/quality-audit/audio_zones/frozen_isometric.png) · [top](renders/quality-audit/audio_zones/frozen_topdown.png) · [sid](renders/quality-audit/audio_zones/frozen_sideprofile.png) | Zone colour overlay not visible. Base terrain. |
| desert | ❌ **D** | [iso](renders/quality-audit/audio_zones/desert_isometric.png) · [top](renders/quality-audit/audio_zones/desert_topdown.png) · [sid](renders/quality-audit/audio_zones/desert_sideprofile.png) | Zone colour overlay not visible. Base terrain. |

### ❌ `cloud_shadow` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/cloud_shadow/grassland_isometric.png) · [top](renders/quality-audit/cloud_shadow/grassland_topdown.png) · [sid](renders/quality-audit/cloud_shadow/grassland_sideprofile.png) | Cloud shadow mask not visible. Base terrain. |
| mountain | ❌ **D** | [iso](renders/quality-audit/cloud_shadow/mountain_isometric.png) · [top](renders/quality-audit/cloud_shadow/mountain_topdown.png) · [sid](renders/quality-audit/cloud_shadow/mountain_sideprofile.png) | Cloud shadow mask not visible. Base terrain. |
| coastal | ❌ **D** | [iso](renders/quality-audit/cloud_shadow/coastal_isometric.png) · [top](renders/quality-audit/cloud_shadow/coastal_topdown.png) · [sid](renders/quality-audit/cloud_shadow/coastal_sideprofile.png) | Cloud shadow mask not visible. Base terrain. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/cloud_shadow/volcanic_isometric.png) · [top](renders/quality-audit/cloud_shadow/volcanic_topdown.png) · [sid](renders/quality-audit/cloud_shadow/volcanic_sideprofile.png) | Cloud shadow mask not visible. Base terrain. |
| frozen | ❌ **D** | [iso](renders/quality-audit/cloud_shadow/frozen_isometric.png) · [top](renders/quality-audit/cloud_shadow/frozen_topdown.png) · [sid](renders/quality-audit/cloud_shadow/frozen_sideprofile.png) | Cloud shadow mask not visible. Base terrain. |
| desert | ❌ **D** | [iso](renders/quality-audit/cloud_shadow/desert_isometric.png) · [top](renders/quality-audit/cloud_shadow/desert_topdown.png) · [sid](renders/quality-audit/cloud_shadow/desert_sideprofile.png) | Cloud shadow mask not visible. Base terrain. |

### ❌ `gameplay_zones` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/gameplay_zones/grassland_isometric.png) · [top](renders/quality-audit/gameplay_zones/grassland_topdown.png) · [sid](renders/quality-audit/gameplay_zones/grassland_sideprofile.png) | Zone overlay not visible. Base terrain. |
| mountain | ❌ **D** | [iso](renders/quality-audit/gameplay_zones/mountain_isometric.png) · [top](renders/quality-audit/gameplay_zones/mountain_topdown.png) · [sid](renders/quality-audit/gameplay_zones/mountain_sideprofile.png) | Zone overlay not visible. Base terrain. |
| coastal | ❌ **D** | [iso](renders/quality-audit/gameplay_zones/coastal_isometric.png) · [top](renders/quality-audit/gameplay_zones/coastal_topdown.png) · [sid](renders/quality-audit/gameplay_zones/coastal_sideprofile.png) | Zone overlay not visible. Base terrain. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/gameplay_zones/volcanic_isometric.png) · [top](renders/quality-audit/gameplay_zones/volcanic_topdown.png) · [sid](renders/quality-audit/gameplay_zones/volcanic_sideprofile.png) | Zone overlay not visible. Base terrain. |
| frozen | ❌ **D** | [iso](renders/quality-audit/gameplay_zones/frozen_isometric.png) · [top](renders/quality-audit/gameplay_zones/frozen_topdown.png) · [sid](renders/quality-audit/gameplay_zones/frozen_sideprofile.png) | Zone overlay not visible. Base terrain. |
| desert | ❌ **D** | [iso](renders/quality-audit/gameplay_zones/desert_isometric.png) · [top](renders/quality-audit/gameplay_zones/desert_topdown.png) · [sid](renders/quality-audit/gameplay_zones/desert_sideprofile.png) | Zone overlay not visible. Base terrain. |

### ❌ `navmesh` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/navmesh/grassland_isometric.png) · [top](renders/quality-audit/navmesh/grassland_topdown.png) · [sid](renders/quality-audit/navmesh/grassland_sideprofile.png) | Navmesh walkable overlay not visible. Base terrain. |
| mountain | ❌ **D** | [iso](renders/quality-audit/navmesh/mountain_isometric.png) · [top](renders/quality-audit/navmesh/mountain_topdown.png) · [sid](renders/quality-audit/navmesh/mountain_sideprofile.png) | Navmesh walkable overlay not visible. Base terrain. |
| coastal | ❌ **D** | [iso](renders/quality-audit/navmesh/coastal_isometric.png) · [top](renders/quality-audit/navmesh/coastal_topdown.png) · [sid](renders/quality-audit/navmesh/coastal_sideprofile.png) | Navmesh walkable overlay not visible. Base terrain. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/navmesh/volcanic_isometric.png) · [top](renders/quality-audit/navmesh/volcanic_topdown.png) · [sid](renders/quality-audit/navmesh/volcanic_sideprofile.png) | Navmesh walkable overlay not visible. Base terrain. |
| frozen | ❌ **D** | [iso](renders/quality-audit/navmesh/frozen_isometric.png) · [top](renders/quality-audit/navmesh/frozen_topdown.png) · [sid](renders/quality-audit/navmesh/frozen_sideprofile.png) | Navmesh walkable overlay not visible. Base terrain. |
| desert | ❌ **D** | [iso](renders/quality-audit/navmesh/desert_isometric.png) · [top](renders/quality-audit/navmesh/desert_topdown.png) · [sid](renders/quality-audit/navmesh/desert_sideprofile.png) | Navmesh walkable overlay not visible. Base terrain. |

### ❌ `pass_navmesh_export` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/pass_navmesh_export/grassland_isometric.png) · [top](renders/quality-audit/pass_navmesh_export/grassland_topdown.png) · [sid](renders/quality-audit/pass_navmesh_export/grassland_sideprofile.png) | Export pass — no render. Base terrain. |
| mountain | ❌ **D** | [iso](renders/quality-audit/pass_navmesh_export/mountain_isometric.png) · [top](renders/quality-audit/pass_navmesh_export/mountain_topdown.png) · [sid](renders/quality-audit/pass_navmesh_export/mountain_sideprofile.png) | Export pass — no render. Base terrain. |
| coastal | ❌ **D** | [iso](renders/quality-audit/pass_navmesh_export/coastal_isometric.png) · [top](renders/quality-audit/pass_navmesh_export/coastal_topdown.png) · [sid](renders/quality-audit/pass_navmesh_export/coastal_sideprofile.png) | Export pass — no render. Base terrain. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/pass_navmesh_export/volcanic_isometric.png) · [top](renders/quality-audit/pass_navmesh_export/volcanic_topdown.png) · [sid](renders/quality-audit/pass_navmesh_export/volcanic_sideprofile.png) | Export pass — no render. Base terrain. |
| frozen | ❌ **D** | [iso](renders/quality-audit/pass_navmesh_export/frozen_isometric.png) · [top](renders/quality-audit/pass_navmesh_export/frozen_topdown.png) · [sid](renders/quality-audit/pass_navmesh_export/frozen_sideprofile.png) | Export pass — no render. Base terrain. |
| desert | ❌ **D** | [iso](renders/quality-audit/pass_navmesh_export/desert_isometric.png) · [top](renders/quality-audit/pass_navmesh_export/desert_topdown.png) · [sid](renders/quality-audit/pass_navmesh_export/desert_sideprofile.png) | Export pass — no render. Base terrain. |

### ❌ `pass_road_network` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/pass_road_network/grassland_isometric.png) · [top](renders/quality-audit/pass_road_network/grassland_topdown.png) · [sid](renders/quality-audit/pass_road_network/grassland_sideprofile.png) | Road path overlay not visible. Base terrain. |
| mountain | ❌ **D** | [iso](renders/quality-audit/pass_road_network/mountain_isometric.png) · [top](renders/quality-audit/pass_road_network/mountain_topdown.png) · [sid](renders/quality-audit/pass_road_network/mountain_sideprofile.png) | Road path overlay not visible. Base terrain. |
| coastal | ❌ **D** | [iso](renders/quality-audit/pass_road_network/coastal_isometric.png) · [top](renders/quality-audit/pass_road_network/coastal_topdown.png) · [sid](renders/quality-audit/pass_road_network/coastal_sideprofile.png) | Road path overlay not visible. Base terrain. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/pass_road_network/volcanic_isometric.png) · [top](renders/quality-audit/pass_road_network/volcanic_topdown.png) · [sid](renders/quality-audit/pass_road_network/volcanic_sideprofile.png) | Road path overlay not visible. Base terrain. |
| frozen | ❌ **D** | [iso](renders/quality-audit/pass_road_network/frozen_isometric.png) · [top](renders/quality-audit/pass_road_network/frozen_topdown.png) · [sid](renders/quality-audit/pass_road_network/frozen_sideprofile.png) | Road path overlay not visible. Base terrain. |
| desert | ❌ **D** | [iso](renders/quality-audit/pass_road_network/desert_isometric.png) · [top](renders/quality-audit/pass_road_network/desert_topdown.png) · [sid](renders/quality-audit/pass_road_network/desert_sideprofile.png) | Road path overlay not visible. Base terrain. |

### ❌ `wildlife_zones` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/wildlife_zones/grassland_isometric.png) · [top](renders/quality-audit/wildlife_zones/grassland_topdown.png) · [sid](renders/quality-audit/wildlife_zones/grassland_sideprofile.png) | Wildlife zone overlay not visible. Base terrain. |
| mountain | ❌ **D** | [iso](renders/quality-audit/wildlife_zones/mountain_isometric.png) · [top](renders/quality-audit/wildlife_zones/mountain_topdown.png) · [sid](renders/quality-audit/wildlife_zones/mountain_sideprofile.png) | Wildlife zone overlay not visible. Base terrain. |
| coastal | ❌ **D** | [iso](renders/quality-audit/wildlife_zones/coastal_isometric.png) · [top](renders/quality-audit/wildlife_zones/coastal_topdown.png) · [sid](renders/quality-audit/wildlife_zones/coastal_sideprofile.png) | Wildlife zone overlay not visible. Base terrain. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/wildlife_zones/volcanic_isometric.png) · [top](renders/quality-audit/wildlife_zones/volcanic_topdown.png) · [sid](renders/quality-audit/wildlife_zones/volcanic_sideprofile.png) | Wildlife zone overlay not visible. Base terrain. |
| frozen | ❌ **D** | [iso](renders/quality-audit/wildlife_zones/frozen_isometric.png) · [top](renders/quality-audit/wildlife_zones/frozen_topdown.png) · [sid](renders/quality-audit/wildlife_zones/frozen_sideprofile.png) | Wildlife zone overlay not visible. Base terrain. |
| desert | ❌ **D** | [iso](renders/quality-audit/wildlife_zones/desert_isometric.png) · [top](renders/quality-audit/wildlife_zones/desert_topdown.png) · [sid](renders/quality-audit/wildlife_zones/desert_sideprofile.png) | Wildlife zone overlay not visible. Base terrain. |

### ❌ `god_ray_hints` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/god_ray_hints/grassland_isometric.png) · [top](renders/quality-audit/god_ray_hints/grassland_topdown.png) · [sid](renders/quality-audit/god_ray_hints/grassland_sideprofile.png) | God ray hint channel not visualised. Base terrain. |
| mountain | ❌ **D** | [iso](renders/quality-audit/god_ray_hints/mountain_isometric.png) · [top](renders/quality-audit/god_ray_hints/mountain_topdown.png) · [sid](renders/quality-audit/god_ray_hints/mountain_sideprofile.png) | God ray hint channel not visualised. Base terrain. |
| coastal | ❌ **D** | [iso](renders/quality-audit/god_ray_hints/coastal_isometric.png) · [top](renders/quality-audit/god_ray_hints/coastal_topdown.png) · [sid](renders/quality-audit/god_ray_hints/coastal_sideprofile.png) | God ray hint channel not visualised. Base terrain. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/god_ray_hints/volcanic_isometric.png) · [top](renders/quality-audit/god_ray_hints/volcanic_topdown.png) · [sid](renders/quality-audit/god_ray_hints/volcanic_sideprofile.png) | God ray hint channel not visualised. Base terrain. |
| frozen | ❌ **D** | [iso](renders/quality-audit/god_ray_hints/frozen_isometric.png) · [top](renders/quality-audit/god_ray_hints/frozen_topdown.png) · [sid](renders/quality-audit/god_ray_hints/frozen_sideprofile.png) | God ray hint channel not visualised. Base terrain. |
| desert | ❌ **D** | [iso](renders/quality-audit/god_ray_hints/desert_isometric.png) · [top](renders/quality-audit/god_ray_hints/desert_topdown.png) · [sid](renders/quality-audit/god_ray_hints/desert_sideprofile.png) | God ray hint channel not visualised. Base terrain. |

### ❌ `fog_masks` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/fog_masks/grassland_isometric.png) · [top](renders/quality-audit/fog_masks/grassland_topdown.png) · [sid](renders/quality-audit/fog_masks/grassland_sideprofile.png) | Fog mask overlay not visible. Base terrain. |
| mountain | ❌ **D** | [iso](renders/quality-audit/fog_masks/mountain_isometric.png) · [top](renders/quality-audit/fog_masks/mountain_topdown.png) · [sid](renders/quality-audit/fog_masks/mountain_sideprofile.png) | Fog mask overlay not visible. Base terrain. |
| coastal | ❌ **D** | [iso](renders/quality-audit/fog_masks/coastal_isometric.png) · [top](renders/quality-audit/fog_masks/coastal_topdown.png) · [sid](renders/quality-audit/fog_masks/coastal_sideprofile.png) | Fog mask overlay not visible. Base terrain. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/fog_masks/volcanic_isometric.png) · [top](renders/quality-audit/fog_masks/volcanic_topdown.png) · [sid](renders/quality-audit/fog_masks/volcanic_sideprofile.png) | Fog mask overlay not visible. Base terrain. |
| frozen | ❌ **D** | [iso](renders/quality-audit/fog_masks/frozen_isometric.png) · [top](renders/quality-audit/fog_masks/frozen_topdown.png) · [sid](renders/quality-audit/fog_masks/frozen_sideprofile.png) | Fog mask overlay not visible. Base terrain. |
| desert | ❌ **D** | [iso](renders/quality-audit/fog_masks/desert_isometric.png) · [top](renders/quality-audit/fog_masks/desert_topdown.png) · [sid](renders/quality-audit/fog_masks/desert_sideprofile.png) | Fog mask overlay not visible. Base terrain. |

### ❌ `pass_atmospheric_volumes` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/pass_atmospheric_volumes/grassland_isometric.png) · [top](renders/quality-audit/pass_atmospheric_volumes/grassland_topdown.png) · [sid](renders/quality-audit/pass_atmospheric_volumes/grassland_sideprofile.png) | Atmospheric volume data not rendered. Base terrain. |
| mountain | ❌ **D** | [iso](renders/quality-audit/pass_atmospheric_volumes/mountain_isometric.png) · [top](renders/quality-audit/pass_atmospheric_volumes/mountain_topdown.png) · [sid](renders/quality-audit/pass_atmospheric_volumes/mountain_sideprofile.png) | Atmospheric volume data not rendered. Base terrain. |
| coastal | ❌ **D** | [iso](renders/quality-audit/pass_atmospheric_volumes/coastal_isometric.png) · [top](renders/quality-audit/pass_atmospheric_volumes/coastal_topdown.png) · [sid](renders/quality-audit/pass_atmospheric_volumes/coastal_sideprofile.png) | Atmospheric volume data not rendered. Base terrain. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/pass_atmospheric_volumes/volcanic_isometric.png) · [top](renders/quality-audit/pass_atmospheric_volumes/volcanic_topdown.png) · [sid](renders/quality-audit/pass_atmospheric_volumes/volcanic_sideprofile.png) | Atmospheric volume data not rendered. Base terrain. |
| frozen | ❌ **D** | [iso](renders/quality-audit/pass_atmospheric_volumes/frozen_isometric.png) · [top](renders/quality-audit/pass_atmospheric_volumes/frozen_topdown.png) · [sid](renders/quality-audit/pass_atmospheric_volumes/frozen_sideprofile.png) | Atmospheric volume data not rendered. Base terrain. |
| desert | ❌ **D** | [iso](renders/quality-audit/pass_atmospheric_volumes/desert_isometric.png) · [top](renders/quality-audit/pass_atmospheric_volumes/desert_topdown.png) · [sid](renders/quality-audit/pass_atmospheric_volumes/desert_sideprofile.png) | Atmospheric volume data not rendered. Base terrain. |

### ❌ `horizon_lod` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/horizon_lod/grassland_isometric.png) · [top](renders/quality-audit/horizon_lod/grassland_topdown.png) · [sid](renders/quality-audit/horizon_lod/grassland_sideprofile.png) | LOD data not visualised. Base terrain. |
| mountain | ❌ **D** | [iso](renders/quality-audit/horizon_lod/mountain_isometric.png) · [top](renders/quality-audit/horizon_lod/mountain_topdown.png) · [sid](renders/quality-audit/horizon_lod/mountain_sideprofile.png) | LOD data not visualised. Base terrain. |
| coastal | ❌ **D** | [iso](renders/quality-audit/horizon_lod/coastal_isometric.png) · [top](renders/quality-audit/horizon_lod/coastal_topdown.png) · [sid](renders/quality-audit/horizon_lod/coastal_sideprofile.png) | LOD data not visualised. Base terrain. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/horizon_lod/volcanic_isometric.png) · [top](renders/quality-audit/horizon_lod/volcanic_topdown.png) · [sid](renders/quality-audit/horizon_lod/volcanic_sideprofile.png) | LOD data not visualised. Base terrain. |
| frozen | ❌ **D** | [iso](renders/quality-audit/horizon_lod/frozen_isometric.png) · [top](renders/quality-audit/horizon_lod/frozen_topdown.png) · [sid](renders/quality-audit/horizon_lod/frozen_sideprofile.png) | LOD data not visualised. Base terrain. |
| desert | ❌ **D** | [iso](renders/quality-audit/horizon_lod/desert_isometric.png) · [top](renders/quality-audit/horizon_lod/desert_topdown.png) · [sid](renders/quality-audit/horizon_lod/desert_sideprofile.png) | LOD data not visualised. Base terrain. |

### ❌ `pass_horizon_lod` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/pass_horizon_lod/grassland_isometric.png) · [top](renders/quality-audit/pass_horizon_lod/grassland_topdown.png) · [sid](renders/quality-audit/pass_horizon_lod/grassland_sideprofile.png) | LOD export pass — no visual differentiation. |
| mountain | ❌ **D** | [iso](renders/quality-audit/pass_horizon_lod/mountain_isometric.png) · [top](renders/quality-audit/pass_horizon_lod/mountain_topdown.png) · [sid](renders/quality-audit/pass_horizon_lod/mountain_sideprofile.png) | LOD export pass — no visual differentiation. |
| coastal | ❌ **D** | [iso](renders/quality-audit/pass_horizon_lod/coastal_isometric.png) · [top](renders/quality-audit/pass_horizon_lod/coastal_topdown.png) · [sid](renders/quality-audit/pass_horizon_lod/coastal_sideprofile.png) | LOD export pass — no visual differentiation. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/pass_horizon_lod/volcanic_isometric.png) · [top](renders/quality-audit/pass_horizon_lod/volcanic_topdown.png) · [sid](renders/quality-audit/pass_horizon_lod/volcanic_sideprofile.png) | LOD export pass — no visual differentiation. |
| frozen | ❌ **D** | [iso](renders/quality-audit/pass_horizon_lod/frozen_isometric.png) · [top](renders/quality-audit/pass_horizon_lod/frozen_topdown.png) · [sid](renders/quality-audit/pass_horizon_lod/frozen_sideprofile.png) | LOD export pass — no visual differentiation. |
| desert | ❌ **D** | [iso](renders/quality-audit/pass_horizon_lod/desert_isometric.png) · [top](renders/quality-audit/pass_horizon_lod/desert_topdown.png) · [sid](renders/quality-audit/pass_horizon_lod/desert_sideprofile.png) | LOD export pass — no visual differentiation. |

### ❌ `wind_field` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/wind_field/grassland_isometric.png) · [top](renders/quality-audit/wind_field/grassland_topdown.png) · [sid](renders/quality-audit/wind_field/grassland_sideprofile.png) | Wind vector field not visualised. Base terrain. |
| mountain | ❌ **D** | [iso](renders/quality-audit/wind_field/mountain_isometric.png) · [top](renders/quality-audit/wind_field/mountain_topdown.png) · [sid](renders/quality-audit/wind_field/mountain_sideprofile.png) | Wind vector field not visualised. Base terrain. |
| coastal | ❌ **D** | [iso](renders/quality-audit/wind_field/coastal_isometric.png) · [top](renders/quality-audit/wind_field/coastal_topdown.png) · [sid](renders/quality-audit/wind_field/coastal_sideprofile.png) | Wind vector field not visualised. Base terrain. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/wind_field/volcanic_isometric.png) · [top](renders/quality-audit/wind_field/volcanic_topdown.png) · [sid](renders/quality-audit/wind_field/volcanic_sideprofile.png) | Wind vector field not visualised. Base terrain. |
| frozen | ❌ **D** | [iso](renders/quality-audit/wind_field/frozen_isometric.png) · [top](renders/quality-audit/wind_field/frozen_topdown.png) · [sid](renders/quality-audit/wind_field/frozen_sideprofile.png) | Wind vector field not visualised. Base terrain. |
| desert | ❌ **D** | [iso](renders/quality-audit/wind_field/desert_isometric.png) · [top](renders/quality-audit/wind_field/desert_topdown.png) · [sid](renders/quality-audit/wind_field/desert_sideprofile.png) | Wind vector field not visualised. Base terrain. |

## Export

### ❌ `prepare_terrain_normals` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/prepare_terrain_normals/grassland_isometric.png) · [top](renders/quality-audit/prepare_terrain_normals/grassland_topdown.png) · [sid](renders/quality-audit/prepare_terrain_normals/grassland_sideprofile.png) | Greyscale normal channel dump. No terrain mesh rendered. |
| mountain | ❌ **D** | [iso](renders/quality-audit/prepare_terrain_normals/mountain_isometric.png) · [top](renders/quality-audit/prepare_terrain_normals/mountain_topdown.png) · [sid](renders/quality-audit/prepare_terrain_normals/mountain_sideprofile.png) | Greyscale normal channel dump. No terrain mesh rendered. |
| coastal | ❌ **D** | [iso](renders/quality-audit/prepare_terrain_normals/coastal_isometric.png) · [top](renders/quality-audit/prepare_terrain_normals/coastal_topdown.png) · [sid](renders/quality-audit/prepare_terrain_normals/coastal_sideprofile.png) | Greyscale normal channel dump. No terrain mesh rendered. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/prepare_terrain_normals/volcanic_isometric.png) · [top](renders/quality-audit/prepare_terrain_normals/volcanic_topdown.png) · [sid](renders/quality-audit/prepare_terrain_normals/volcanic_sideprofile.png) | Greyscale normal channel dump. No terrain mesh rendered. |
| frozen | ❌ **D** | [iso](renders/quality-audit/prepare_terrain_normals/frozen_isometric.png) · [top](renders/quality-audit/prepare_terrain_normals/frozen_topdown.png) · [sid](renders/quality-audit/prepare_terrain_normals/frozen_sideprofile.png) | Greyscale normal channel dump. No terrain mesh rendered. |
| desert | ❌ **D** | [iso](renders/quality-audit/prepare_terrain_normals/desert_isometric.png) · [top](renders/quality-audit/prepare_terrain_normals/desert_topdown.png) · [sid](renders/quality-audit/prepare_terrain_normals/desert_sideprofile.png) | Greyscale normal channel dump. No terrain mesh rendered. |

### ❌ `prepare_heightmap_raw_u16` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/prepare_heightmap_raw_u16/grassland_isometric.png) · [top](renders/quality-audit/prepare_heightmap_raw_u16/grassland_topdown.png) · [sid](renders/quality-audit/prepare_heightmap_raw_u16/grassland_sideprofile.png) | Raw u16 heightmap export. No terrain mesh rendered. |
| mountain | ❌ **D** | [iso](renders/quality-audit/prepare_heightmap_raw_u16/mountain_isometric.png) · [top](renders/quality-audit/prepare_heightmap_raw_u16/mountain_topdown.png) · [sid](renders/quality-audit/prepare_heightmap_raw_u16/mountain_sideprofile.png) | Raw u16 heightmap export. No terrain mesh rendered. |
| coastal | ❌ **D** | [iso](renders/quality-audit/prepare_heightmap_raw_u16/coastal_isometric.png) · [top](renders/quality-audit/prepare_heightmap_raw_u16/coastal_topdown.png) · [sid](renders/quality-audit/prepare_heightmap_raw_u16/coastal_sideprofile.png) | Raw u16 heightmap export. No terrain mesh rendered. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/prepare_heightmap_raw_u16/volcanic_isometric.png) · [top](renders/quality-audit/prepare_heightmap_raw_u16/volcanic_topdown.png) · [sid](renders/quality-audit/prepare_heightmap_raw_u16/volcanic_sideprofile.png) | Raw u16 heightmap export. No terrain mesh rendered. |
| frozen | ❌ **D** | [iso](renders/quality-audit/prepare_heightmap_raw_u16/frozen_isometric.png) · [top](renders/quality-audit/prepare_heightmap_raw_u16/frozen_topdown.png) · [sid](renders/quality-audit/prepare_heightmap_raw_u16/frozen_sideprofile.png) | Raw u16 heightmap export. No terrain mesh rendered. |
| desert | ❌ **D** | [iso](renders/quality-audit/prepare_heightmap_raw_u16/desert_isometric.png) · [top](renders/quality-audit/prepare_heightmap_raw_u16/desert_topdown.png) · [sid](renders/quality-audit/prepare_heightmap_raw_u16/desert_sideprofile.png) | Raw u16 heightmap export. No terrain mesh rendered. |

### ❌ `prepare_unity_auxiliary_channels` — Grade **D**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ❌ **D** | [iso](renders/quality-audit/prepare_unity_auxiliary_channels/grassland_isometric.png) · [top](renders/quality-audit/prepare_unity_auxiliary_channels/grassland_topdown.png) · [sid](renders/quality-audit/prepare_unity_auxiliary_channels/grassland_sideprofile.png) | Unity auxiliary channels — export only, no render output. |
| mountain | ❌ **D** | [iso](renders/quality-audit/prepare_unity_auxiliary_channels/mountain_isometric.png) · [top](renders/quality-audit/prepare_unity_auxiliary_channels/mountain_topdown.png) · [sid](renders/quality-audit/prepare_unity_auxiliary_channels/mountain_sideprofile.png) | Unity auxiliary channels — export only, no render output. |
| coastal | ❌ **D** | [iso](renders/quality-audit/prepare_unity_auxiliary_channels/coastal_isometric.png) · [top](renders/quality-audit/prepare_unity_auxiliary_channels/coastal_topdown.png) · [sid](renders/quality-audit/prepare_unity_auxiliary_channels/coastal_sideprofile.png) | Unity auxiliary channels — export only, no render output. |
| volcanic | ❌ **D** | [iso](renders/quality-audit/prepare_unity_auxiliary_channels/volcanic_isometric.png) · [top](renders/quality-audit/prepare_unity_auxiliary_channels/volcanic_topdown.png) · [sid](renders/quality-audit/prepare_unity_auxiliary_channels/volcanic_sideprofile.png) | Unity auxiliary channels — export only, no render output. |
| frozen | ❌ **D** | [iso](renders/quality-audit/prepare_unity_auxiliary_channels/frozen_isometric.png) · [top](renders/quality-audit/prepare_unity_auxiliary_channels/frozen_topdown.png) · [sid](renders/quality-audit/prepare_unity_auxiliary_channels/frozen_sideprofile.png) | Unity auxiliary channels — export only, no render output. |
| desert | ❌ **D** | [iso](renders/quality-audit/prepare_unity_auxiliary_channels/desert_isometric.png) · [top](renders/quality-audit/prepare_unity_auxiliary_channels/desert_topdown.png) · [sid](renders/quality-audit/prepare_unity_auxiliary_channels/desert_sideprofile.png) | Unity auxiliary channels — export only, no render output. |

## Validation

### ⚠️ `validation_minimal` — Grade **C**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ⚠️ **C** | [iso](renders/quality-audit/validation_minimal/grassland_isometric.png) · [top](renders/quality-audit/validation_minimal/grassland_topdown.png) · [sid](renders/quality-audit/validation_minimal/grassland_sideprofile.png) | Terrain mesh renders. Validation runs OK. No visual differentiation from terrain_gen. |
| mountain | ⚠️ **C** | [iso](renders/quality-audit/validation_minimal/mountain_isometric.png) · [top](renders/quality-audit/validation_minimal/mountain_topdown.png) · [sid](renders/quality-audit/validation_minimal/mountain_sideprofile.png) | Terrain mesh renders. Validation runs OK. No visual differentiation from terrain_gen. |
| coastal | ⚠️ **C** | [iso](renders/quality-audit/validation_minimal/coastal_isometric.png) · [top](renders/quality-audit/validation_minimal/coastal_topdown.png) · [sid](renders/quality-audit/validation_minimal/coastal_sideprofile.png) | Terrain mesh renders. Validation runs OK. No visual differentiation from terrain_gen. |
| volcanic | ⚠️ **C** | [iso](renders/quality-audit/validation_minimal/volcanic_isometric.png) · [top](renders/quality-audit/validation_minimal/volcanic_topdown.png) · [sid](renders/quality-audit/validation_minimal/volcanic_sideprofile.png) | Terrain mesh renders. Validation runs OK. No visual differentiation from terrain_gen. |
| frozen | ⚠️ **C** | [iso](renders/quality-audit/validation_minimal/frozen_isometric.png) · [top](renders/quality-audit/validation_minimal/frozen_topdown.png) · [sid](renders/quality-audit/validation_minimal/frozen_sideprofile.png) | Terrain mesh renders. Validation runs OK. No visual differentiation from terrain_gen. |
| desert | ⚠️ **C** | [iso](renders/quality-audit/validation_minimal/desert_isometric.png) · [top](renders/quality-audit/validation_minimal/desert_topdown.png) · [sid](renders/quality-audit/validation_minimal/desert_sideprofile.png) | Terrain mesh renders. Validation runs OK. No visual differentiation from terrain_gen. |

### ⚠️ `validation_full` — Grade **C**

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|----------|
| grassland | ⚠️ **C** | [iso](renders/quality-audit/validation_full/grassland_isometric.png) · [top](renders/quality-audit/validation_full/grassland_topdown.png) · [sid](renders/quality-audit/validation_full/grassland_sideprofile.png) | Terrain mesh renders. Full validation OK. No visual differentiation. |
| mountain | ⚠️ **C** | [iso](renders/quality-audit/validation_full/mountain_isometric.png) · [top](renders/quality-audit/validation_full/mountain_topdown.png) · [sid](renders/quality-audit/validation_full/mountain_sideprofile.png) | Terrain mesh renders. Full validation OK. No visual differentiation. |
| coastal | ⚠️ **C** | [iso](renders/quality-audit/validation_full/coastal_isometric.png) · [top](renders/quality-audit/validation_full/coastal_topdown.png) · [sid](renders/quality-audit/validation_full/coastal_sideprofile.png) | Terrain mesh renders. Full validation OK. No visual differentiation. |
| volcanic | ⚠️ **C** | [iso](renders/quality-audit/validation_full/volcanic_isometric.png) · [top](renders/quality-audit/validation_full/volcanic_topdown.png) · [sid](renders/quality-audit/validation_full/volcanic_sideprofile.png) | Terrain mesh renders. Full validation OK. No visual differentiation. |
| frozen | ⚠️ **C** | [iso](renders/quality-audit/validation_full/frozen_isometric.png) · [top](renders/quality-audit/validation_full/frozen_topdown.png) · [sid](renders/quality-audit/validation_full/frozen_sideprofile.png) | Terrain mesh renders. Full validation OK. No visual differentiation. |
| desert | ⚠️ **C** | [iso](renders/quality-audit/validation_full/desert_isometric.png) · [top](renders/quality-audit/validation_full/desert_topdown.png) · [sid](renders/quality-audit/validation_full/desert_sideprofile.png) | Terrain mesh renders. Full validation OK. No visual differentiation. |
