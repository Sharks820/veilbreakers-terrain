# VeilBreakers Terrain — Dynamic Quality Audit Report

> Generated: 2026-05-04T18:51:16Z  
> Passes audited: **73**  
> Biomes: 6 (grassland, mountain, coastal, volcanic, frozen, desert)  
> Renders per pass: 18 (6 biomes × 3 angles)  
> Total renders analyzed: **1314**

## Summary

| Grade | Count | Pct |
|-------|-------|-----|
| ✅ A — AAA Pass  | 47 | 64% |
| 🟡 B — Near Pass | 10 | 14% |
| ⚠️ C — Warn      | 8 | 11% |
| ❌ D — Fail      | 7 | 10% |
| 💀 F — Hard Fail | 1 | 1% |

**Overall pipeline health: 57 pass / 8 warn / 8 fail (78% pass rate)**

## Terrain Generation Passes

### ✅ `macro_world` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/macro_world/grassland_isometric.png) · [top](renders/quality-audit/macro_world/grassland_topdown.png) · [side](renders/quality-audit/macro_world/grassland_sideprofile.png) | Terrain generation solid: height std=17.3, pixel_std=81.0 |
| mountain | ✅ **A** | [iso](renders/quality-audit/macro_world/mountain_isometric.png) · [top](renders/quality-audit/macro_world/mountain_topdown.png) · [side](renders/quality-audit/macro_world/mountain_sideprofile.png) | Terrain generation solid: height std=67.0, pixel_std=85.0 |
| coastal | ✅ **A** | [iso](renders/quality-audit/macro_world/coastal_isometric.png) · [top](renders/quality-audit/macro_world/coastal_topdown.png) · [side](renders/quality-audit/macro_world/coastal_sideprofile.png) | Terrain generation solid: height std=10.3, pixel_std=78.3 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/macro_world/volcanic_isometric.png) · [top](renders/quality-audit/macro_world/volcanic_topdown.png) · [side](renders/quality-audit/macro_world/volcanic_sideprofile.png) | Terrain generation solid: height std=116.5, pixel_std=79.2 |
| frozen | ✅ **A** | [iso](renders/quality-audit/macro_world/frozen_isometric.png) · [top](renders/quality-audit/macro_world/frozen_topdown.png) · [side](renders/quality-audit/macro_world/frozen_sideprofile.png) | Terrain generation solid: height std=14.5, pixel_std=77.9 |
| desert | ✅ **A** | [iso](renders/quality-audit/macro_world/desert_isometric.png) · [top](renders/quality-audit/macro_world/desert_topdown.png) · [side](renders/quality-audit/macro_world/desert_sideprofile.png) | Terrain generation solid: height std=20.4, pixel_std=78.4 |

### ✅ `pass_composite_hmap` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/pass_composite_hmap/grassland_isometric.png) · [top](renders/quality-audit/pass_composite_hmap/grassland_topdown.png) · [side](renders/quality-audit/pass_composite_hmap/grassland_sideprofile.png) | Terrain generation solid: height std=12.0, pixel_std=82.6 |
| mountain | ✅ **A** | [iso](renders/quality-audit/pass_composite_hmap/mountain_isometric.png) · [top](renders/quality-audit/pass_composite_hmap/mountain_topdown.png) · [side](renders/quality-audit/pass_composite_hmap/mountain_sideprofile.png) | Terrain generation solid: height std=41.0, pixel_std=83.1 |
| coastal | ✅ **A** | [iso](renders/quality-audit/pass_composite_hmap/coastal_isometric.png) · [top](renders/quality-audit/pass_composite_hmap/coastal_topdown.png) · [side](renders/quality-audit/pass_composite_hmap/coastal_sideprofile.png) | Terrain generation solid: height std=10.7, pixel_std=80.5 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/pass_composite_hmap/volcanic_isometric.png) · [top](renders/quality-audit/pass_composite_hmap/volcanic_topdown.png) · [side](renders/quality-audit/pass_composite_hmap/volcanic_sideprofile.png) | Terrain generation solid: height std=69.5, pixel_std=82.6 |
| frozen | ✅ **A** | [iso](renders/quality-audit/pass_composite_hmap/frozen_isometric.png) · [top](renders/quality-audit/pass_composite_hmap/frozen_topdown.png) · [side](renders/quality-audit/pass_composite_hmap/frozen_sideprofile.png) | Terrain generation solid: height std=11.8, pixel_std=81.0 |
| desert | ✅ **A** | [iso](renders/quality-audit/pass_composite_hmap/desert_isometric.png) · [top](renders/quality-audit/pass_composite_hmap/desert_topdown.png) · [side](renders/quality-audit/pass_composite_hmap/desert_sideprofile.png) | Terrain generation solid: height std=14.3, pixel_std=82.2 |

### ✅ `pass_generate_high_freq_detail` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/pass_generate_high_freq_detail/grassland_isometric.png) · [top](renders/quality-audit/pass_generate_high_freq_detail/grassland_topdown.png) · [side](renders/quality-audit/pass_generate_high_freq_detail/grassland_sideprofile.png) | Terrain generation solid: height std=0.0, pixel_std=82.6 |
| mountain | ✅ **A** | [iso](renders/quality-audit/pass_generate_high_freq_detail/mountain_isometric.png) · [top](renders/quality-audit/pass_generate_high_freq_detail/mountain_topdown.png) · [side](renders/quality-audit/pass_generate_high_freq_detail/mountain_sideprofile.png) | Terrain generation solid: height std=0.1, pixel_std=83.1 |
| coastal | ✅ **A** | [iso](renders/quality-audit/pass_generate_high_freq_detail/coastal_isometric.png) · [top](renders/quality-audit/pass_generate_high_freq_detail/coastal_topdown.png) · [side](renders/quality-audit/pass_generate_high_freq_detail/coastal_sideprofile.png) | Terrain generation solid: height std=0.1, pixel_std=80.5 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/pass_generate_high_freq_detail/volcanic_isometric.png) · [top](renders/quality-audit/pass_generate_high_freq_detail/volcanic_topdown.png) · [side](renders/quality-audit/pass_generate_high_freq_detail/volcanic_sideprofile.png) | Terrain generation solid: height std=0.0, pixel_std=82.6 |
| frozen | ✅ **A** | [iso](renders/quality-audit/pass_generate_high_freq_detail/frozen_isometric.png) · [top](renders/quality-audit/pass_generate_high_freq_detail/frozen_topdown.png) · [side](renders/quality-audit/pass_generate_high_freq_detail/frozen_sideprofile.png) | Terrain generation solid: height std=0.0, pixel_std=81.0 |
| desert | ✅ **A** | [iso](renders/quality-audit/pass_generate_high_freq_detail/desert_isometric.png) · [top](renders/quality-audit/pass_generate_high_freq_detail/desert_topdown.png) · [side](renders/quality-audit/pass_generate_high_freq_detail/desert_sideprofile.png) | Terrain generation solid: height std=0.0, pixel_std=82.2 |

### ✅ `pass_generate_low_freq_hmap` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/pass_generate_low_freq_hmap/grassland_isometric.png) · [top](renders/quality-audit/pass_generate_low_freq_hmap/grassland_topdown.png) · [side](renders/quality-audit/pass_generate_low_freq_hmap/grassland_sideprofile.png) | Terrain generation solid: height std=17.3, pixel_std=81.0 |
| mountain | ✅ **A** | [iso](renders/quality-audit/pass_generate_low_freq_hmap/mountain_isometric.png) · [top](renders/quality-audit/pass_generate_low_freq_hmap/mountain_topdown.png) · [side](renders/quality-audit/pass_generate_low_freq_hmap/mountain_sideprofile.png) | Terrain generation solid: height std=67.0, pixel_std=85.0 |
| coastal | ✅ **A** | [iso](renders/quality-audit/pass_generate_low_freq_hmap/coastal_isometric.png) · [top](renders/quality-audit/pass_generate_low_freq_hmap/coastal_topdown.png) · [side](renders/quality-audit/pass_generate_low_freq_hmap/coastal_sideprofile.png) | Terrain generation solid: height std=10.3, pixel_std=78.3 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/pass_generate_low_freq_hmap/volcanic_isometric.png) · [top](renders/quality-audit/pass_generate_low_freq_hmap/volcanic_topdown.png) · [side](renders/quality-audit/pass_generate_low_freq_hmap/volcanic_sideprofile.png) | Terrain generation solid: height std=116.5, pixel_std=79.2 |
| frozen | ✅ **A** | [iso](renders/quality-audit/pass_generate_low_freq_hmap/frozen_isometric.png) · [top](renders/quality-audit/pass_generate_low_freq_hmap/frozen_topdown.png) · [side](renders/quality-audit/pass_generate_low_freq_hmap/frozen_sideprofile.png) | Terrain generation solid: height std=14.5, pixel_std=77.9 |
| desert | ✅ **A** | [iso](renders/quality-audit/pass_generate_low_freq_hmap/desert_isometric.png) · [top](renders/quality-audit/pass_generate_low_freq_hmap/desert_topdown.png) · [side](renders/quality-audit/pass_generate_low_freq_hmap/desert_sideprofile.png) | Terrain generation solid: height std=20.4, pixel_std=78.4 |

## Structural Mask Passes

### ✅ `structural_masks` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/structural_masks/grassland_isometric.png) · [top](renders/quality-audit/structural_masks/grassland_topdown.png) · [side](renders/quality-audit/structural_masks/grassland_sideprofile.png) | Structural masks: 6/8 channels active, avg_std=26.1673 |
| mountain | ✅ **A** | [iso](renders/quality-audit/structural_masks/mountain_isometric.png) · [top](renders/quality-audit/structural_masks/mountain_topdown.png) · [side](renders/quality-audit/structural_masks/mountain_sideprofile.png) | Structural masks: 6/8 channels active, avg_std=16.9179 |
| coastal | ✅ **A** | [iso](renders/quality-audit/structural_masks/coastal_isometric.png) · [top](renders/quality-audit/structural_masks/coastal_topdown.png) · [side](renders/quality-audit/structural_masks/coastal_sideprofile.png) | Structural masks: 6/8 channels active, avg_std=13.5707 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/structural_masks/volcanic_isometric.png) · [top](renders/quality-audit/structural_masks/volcanic_topdown.png) · [side](renders/quality-audit/structural_masks/volcanic_sideprofile.png) | Structural masks: 6/8 channels active, avg_std=30.6745 |
| frozen | ✅ **A** | [iso](renders/quality-audit/structural_masks/frozen_isometric.png) · [top](renders/quality-audit/structural_masks/frozen_topdown.png) · [side](renders/quality-audit/structural_masks/frozen_sideprofile.png) | Structural masks: 6/8 channels active, avg_std=27.9102 |
| desert | ✅ **A** | [iso](renders/quality-audit/structural_masks/desert_isometric.png) · [top](renders/quality-audit/structural_masks/desert_topdown.png) · [side](renders/quality-audit/structural_masks/desert_sideprofile.png) | Structural masks: 6/8 channels active, avg_std=23.5900 |

### ✅ `structural_masks_post_erosion` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/structural_masks_post_erosion/grassland_isometric.png) · [top](renders/quality-audit/structural_masks_post_erosion/grassland_topdown.png) · [side](renders/quality-audit/structural_masks_post_erosion/grassland_sideprofile.png) | Structural masks: 6/8 channels active, avg_std=26.1673 |
| mountain | ✅ **A** | [iso](renders/quality-audit/structural_masks_post_erosion/mountain_isometric.png) · [top](renders/quality-audit/structural_masks_post_erosion/mountain_topdown.png) · [side](renders/quality-audit/structural_masks_post_erosion/mountain_sideprofile.png) | Structural masks: 6/8 channels active, avg_std=16.9179 |
| coastal | ✅ **A** | [iso](renders/quality-audit/structural_masks_post_erosion/coastal_isometric.png) · [top](renders/quality-audit/structural_masks_post_erosion/coastal_topdown.png) · [side](renders/quality-audit/structural_masks_post_erosion/coastal_sideprofile.png) | Structural masks: 6/8 channels active, avg_std=13.5707 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/structural_masks_post_erosion/volcanic_isometric.png) · [top](renders/quality-audit/structural_masks_post_erosion/volcanic_topdown.png) · [side](renders/quality-audit/structural_masks_post_erosion/volcanic_sideprofile.png) | Structural masks: 6/8 channels active, avg_std=30.6745 |
| frozen | ✅ **A** | [iso](renders/quality-audit/structural_masks_post_erosion/frozen_isometric.png) · [top](renders/quality-audit/structural_masks_post_erosion/frozen_topdown.png) · [side](renders/quality-audit/structural_masks_post_erosion/frozen_sideprofile.png) | Structural masks: 6/8 channels active, avg_std=27.9102 |
| desert | ✅ **A** | [iso](renders/quality-audit/structural_masks_post_erosion/desert_isometric.png) · [top](renders/quality-audit/structural_masks_post_erosion/desert_topdown.png) · [side](renders/quality-audit/structural_masks_post_erosion/desert_sideprofile.png) | Structural masks: 6/8 channels active, avg_std=23.5900 |

### ✅ `structural_masks_post_talus` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/structural_masks_post_talus/grassland_isometric.png) · [top](renders/quality-audit/structural_masks_post_talus/grassland_topdown.png) · [side](renders/quality-audit/structural_masks_post_talus/grassland_sideprofile.png) | Structural masks: 6/8 channels active, avg_std=26.1673 |
| mountain | ✅ **A** | [iso](renders/quality-audit/structural_masks_post_talus/mountain_isometric.png) · [top](renders/quality-audit/structural_masks_post_talus/mountain_topdown.png) · [side](renders/quality-audit/structural_masks_post_talus/mountain_sideprofile.png) | Structural masks: 6/8 channels active, avg_std=16.9179 |
| coastal | ✅ **A** | [iso](renders/quality-audit/structural_masks_post_talus/coastal_isometric.png) · [top](renders/quality-audit/structural_masks_post_talus/coastal_topdown.png) · [side](renders/quality-audit/structural_masks_post_talus/coastal_sideprofile.png) | Structural masks: 6/8 channels active, avg_std=13.5707 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/structural_masks_post_talus/volcanic_isometric.png) · [top](renders/quality-audit/structural_masks_post_talus/volcanic_topdown.png) · [side](renders/quality-audit/structural_masks_post_talus/volcanic_sideprofile.png) | Structural masks: 6/8 channels active, avg_std=30.6745 |
| frozen | ✅ **A** | [iso](renders/quality-audit/structural_masks_post_talus/frozen_isometric.png) · [top](renders/quality-audit/structural_masks_post_talus/frozen_topdown.png) · [side](renders/quality-audit/structural_masks_post_talus/frozen_sideprofile.png) | Structural masks: 6/8 channels active, avg_std=27.9102 |
| desert | ✅ **A** | [iso](renders/quality-audit/structural_masks_post_talus/desert_isometric.png) · [top](renders/quality-audit/structural_masks_post_talus/desert_topdown.png) · [side](renders/quality-audit/structural_masks_post_talus/desert_sideprofile.png) | Structural masks: 6/8 channels active, avg_std=23.5900 |

## Erosion & Height-Modifying Passes

### ✅ `banded_macro` — Grade **A**

**Overall:** 5A/1B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/banded_macro/grassland_isometric.png) · [top](renders/quality-audit/banded_macro/grassland_topdown.png) · [side](renders/quality-audit/banded_macro/grassland_sideprofile.png) | Erosion active: 1/1 channels, pixel_std=83.2 |
| mountain | ✅ **A** | [iso](renders/quality-audit/banded_macro/mountain_isometric.png) · [top](renders/quality-audit/banded_macro/mountain_topdown.png) · [side](renders/quality-audit/banded_macro/mountain_sideprofile.png) | Erosion active: 1/1 channels, pixel_std=75.9 |
| coastal | 🟡 **B** | [iso](renders/quality-audit/banded_macro/coastal_isometric.png) · [top](renders/quality-audit/banded_macro/coastal_topdown.png) · [side](renders/quality-audit/banded_macro/coastal_sideprofile.png) | Erosion partial: terrain visible 1/3 angles, pixel_std=76.1 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/banded_macro/volcanic_isometric.png) · [top](renders/quality-audit/banded_macro/volcanic_topdown.png) · [side](renders/quality-audit/banded_macro/volcanic_sideprofile.png) | Erosion active: 1/1 channels, pixel_std=76.1 |
| frozen | ✅ **A** | [iso](renders/quality-audit/banded_macro/frozen_isometric.png) · [top](renders/quality-audit/banded_macro/frozen_topdown.png) · [side](renders/quality-audit/banded_macro/frozen_sideprofile.png) | Erosion active: 1/1 channels, pixel_std=77.1 |
| desert | ✅ **A** | [iso](renders/quality-audit/banded_macro/desert_isometric.png) · [top](renders/quality-audit/banded_macro/desert_topdown.png) · [side](renders/quality-audit/banded_macro/desert_sideprofile.png) | Erosion active: 1/1 channels, pixel_std=76.5 |

### ✅ `erosion` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/erosion/grassland_isometric.png) · [top](renders/quality-audit/erosion/grassland_topdown.png) · [side](renders/quality-audit/erosion/grassland_sideprofile.png) | Erosion active: 7/8 channels, pixel_std=82.6 |
| mountain | ✅ **A** | [iso](renders/quality-audit/erosion/mountain_isometric.png) · [top](renders/quality-audit/erosion/mountain_topdown.png) · [side](renders/quality-audit/erosion/mountain_sideprofile.png) | Erosion active: 8/8 channels, pixel_std=83.1 |
| coastal | ✅ **A** | [iso](renders/quality-audit/erosion/coastal_isometric.png) · [top](renders/quality-audit/erosion/coastal_topdown.png) · [side](renders/quality-audit/erosion/coastal_sideprofile.png) | Erosion active: 7/8 channels, pixel_std=80.5 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/erosion/volcanic_isometric.png) · [top](renders/quality-audit/erosion/volcanic_topdown.png) · [side](renders/quality-audit/erosion/volcanic_sideprofile.png) | Erosion active: 7/8 channels, pixel_std=82.6 |
| frozen | ✅ **A** | [iso](renders/quality-audit/erosion/frozen_isometric.png) · [top](renders/quality-audit/erosion/frozen_topdown.png) · [side](renders/quality-audit/erosion/frozen_sideprofile.png) | Erosion active: 7/8 channels, pixel_std=81.0 |
| desert | ✅ **A** | [iso](renders/quality-audit/erosion/desert_isometric.png) · [top](renders/quality-audit/erosion/desert_topdown.png) · [side](renders/quality-audit/erosion/desert_sideprofile.png) | Erosion active: 7/8 channels, pixel_std=82.2 |

### ❌ `glacial` — Grade **D**

**Overall:** 0F + 5D across biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ❌ **D** | [iso](renders/quality-audit/glacial/grassland_isometric.png) · [top](renders/quality-audit/glacial/grassland_topdown.png) · [side](renders/quality-audit/glacial/grassland_sideprofile.png) | All erosion channels near-zero |
| mountain | ❌ **D** | [iso](renders/quality-audit/glacial/mountain_isometric.png) · [top](renders/quality-audit/glacial/mountain_topdown.png) · [side](renders/quality-audit/glacial/mountain_sideprofile.png) | All erosion channels near-zero |
| coastal | ❌ **D** | [iso](renders/quality-audit/glacial/coastal_isometric.png) · [top](renders/quality-audit/glacial/coastal_topdown.png) · [side](renders/quality-audit/glacial/coastal_sideprofile.png) | All erosion channels near-zero |
| volcanic | ❌ **D** | [iso](renders/quality-audit/glacial/volcanic_isometric.png) · [top](renders/quality-audit/glacial/volcanic_topdown.png) · [side](renders/quality-audit/glacial/volcanic_sideprofile.png) | All erosion channels near-zero |
| frozen | ❌ **D** | [iso](renders/quality-audit/glacial/frozen_isometric.png) · [top](renders/quality-audit/glacial/frozen_topdown.png) · [side](renders/quality-audit/glacial/frozen_sideprofile.png) | All erosion channels near-zero |
| desert | ✅ **A** | [iso](renders/quality-audit/glacial/desert_isometric.png) · [top](renders/quality-audit/glacial/desert_topdown.png) · [side](renders/quality-audit/glacial/desert_sideprofile.png) | Erosion active: 1/2 channels, pixel_std=82.2 |

### ✅ `integrate_deltas` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/integrate_deltas/grassland_isometric.png) · [top](renders/quality-audit/integrate_deltas/grassland_topdown.png) · [side](renders/quality-audit/integrate_deltas/grassland_sideprofile.png) | Erosion active: 1/1 channels, pixel_std=81.0 |
| mountain | ✅ **A** | [iso](renders/quality-audit/integrate_deltas/mountain_isometric.png) · [top](renders/quality-audit/integrate_deltas/mountain_topdown.png) · [side](renders/quality-audit/integrate_deltas/mountain_sideprofile.png) | Erosion active: 1/1 channels, pixel_std=85.0 |
| coastal | ✅ **A** | [iso](renders/quality-audit/integrate_deltas/coastal_isometric.png) · [top](renders/quality-audit/integrate_deltas/coastal_topdown.png) · [side](renders/quality-audit/integrate_deltas/coastal_sideprofile.png) | Erosion active: 1/1 channels, pixel_std=78.3 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/integrate_deltas/volcanic_isometric.png) · [top](renders/quality-audit/integrate_deltas/volcanic_topdown.png) · [side](renders/quality-audit/integrate_deltas/volcanic_sideprofile.png) | Erosion active: 1/1 channels, pixel_std=79.2 |
| frozen | ✅ **A** | [iso](renders/quality-audit/integrate_deltas/frozen_isometric.png) · [top](renders/quality-audit/integrate_deltas/frozen_topdown.png) · [side](renders/quality-audit/integrate_deltas/frozen_sideprofile.png) | Erosion active: 1/1 channels, pixel_std=77.9 |
| desert | ✅ **A** | [iso](renders/quality-audit/integrate_deltas/desert_isometric.png) · [top](renders/quality-audit/integrate_deltas/desert_topdown.png) · [side](renders/quality-audit/integrate_deltas/desert_sideprofile.png) | Erosion active: 1/1 channels, pixel_std=78.4 |

### 💀 `pass_banded_advanced` — Grade **F**

**Overall:** 6/6 biomes hard-fail

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | 💀 **F** | [iso](renders/quality-audit/pass_banded_advanced/grassland_isometric.png) · [top](renders/quality-audit/pass_banded_advanced/grassland_topdown.png) · [side](renders/quality-audit/pass_banded_advanced/grassland_sideprofile.png) | No channels produced |
| mountain | 💀 **F** | [iso](renders/quality-audit/pass_banded_advanced/mountain_isometric.png) · [top](renders/quality-audit/pass_banded_advanced/mountain_topdown.png) · [side](renders/quality-audit/pass_banded_advanced/mountain_sideprofile.png) | No channels produced |
| coastal | 💀 **F** | [iso](renders/quality-audit/pass_banded_advanced/coastal_isometric.png) · [top](renders/quality-audit/pass_banded_advanced/coastal_topdown.png) · [side](renders/quality-audit/pass_banded_advanced/coastal_sideprofile.png) | No channels produced |
| volcanic | 💀 **F** | [iso](renders/quality-audit/pass_banded_advanced/volcanic_isometric.png) · [top](renders/quality-audit/pass_banded_advanced/volcanic_topdown.png) · [side](renders/quality-audit/pass_banded_advanced/volcanic_sideprofile.png) | No channels produced |
| frozen | 💀 **F** | [iso](renders/quality-audit/pass_banded_advanced/frozen_isometric.png) · [top](renders/quality-audit/pass_banded_advanced/frozen_topdown.png) · [side](renders/quality-audit/pass_banded_advanced/frozen_sideprofile.png) | No channels produced |
| desert | 💀 **F** | [iso](renders/quality-audit/pass_banded_advanced/desert_isometric.png) · [top](renders/quality-audit/pass_banded_advanced/desert_topdown.png) · [side](renders/quality-audit/pass_banded_advanced/desert_sideprofile.png) | No channels produced |

### ❌ `pass_glacial` — Grade **D**

**Overall:** 0F + 5D across biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ❌ **D** | [iso](renders/quality-audit/pass_glacial/grassland_isometric.png) · [top](renders/quality-audit/pass_glacial/grassland_topdown.png) · [side](renders/quality-audit/pass_glacial/grassland_sideprofile.png) | All erosion channels near-zero |
| mountain | ❌ **D** | [iso](renders/quality-audit/pass_glacial/mountain_isometric.png) · [top](renders/quality-audit/pass_glacial/mountain_topdown.png) · [side](renders/quality-audit/pass_glacial/mountain_sideprofile.png) | All erosion channels near-zero |
| coastal | ❌ **D** | [iso](renders/quality-audit/pass_glacial/coastal_isometric.png) · [top](renders/quality-audit/pass_glacial/coastal_topdown.png) · [side](renders/quality-audit/pass_glacial/coastal_sideprofile.png) | All erosion channels near-zero |
| volcanic | ❌ **D** | [iso](renders/quality-audit/pass_glacial/volcanic_isometric.png) · [top](renders/quality-audit/pass_glacial/volcanic_topdown.png) · [side](renders/quality-audit/pass_glacial/volcanic_sideprofile.png) | All erosion channels near-zero |
| frozen | ❌ **D** | [iso](renders/quality-audit/pass_glacial/frozen_isometric.png) · [top](renders/quality-audit/pass_glacial/frozen_topdown.png) · [side](renders/quality-audit/pass_glacial/frozen_sideprofile.png) | All erosion channels near-zero |
| desert | ✅ **A** | [iso](renders/quality-audit/pass_glacial/desert_isometric.png) · [top](renders/quality-audit/pass_glacial/desert_topdown.png) · [side](renders/quality-audit/pass_glacial/desert_sideprofile.png) | Erosion active: 1/2 channels, pixel_std=82.2 |

### ❌ `pass_morphology` — Grade **D**

**Overall:** 0F + 6D across biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ❌ **D** | [iso](renders/quality-audit/pass_morphology/grassland_isometric.png) · [top](renders/quality-audit/pass_morphology/grassland_topdown.png) · [side](renders/quality-audit/pass_morphology/grassland_sideprofile.png) | All erosion channels near-zero |
| mountain | ❌ **D** | [iso](renders/quality-audit/pass_morphology/mountain_isometric.png) · [top](renders/quality-audit/pass_morphology/mountain_topdown.png) · [side](renders/quality-audit/pass_morphology/mountain_sideprofile.png) | All erosion channels near-zero |
| coastal | ❌ **D** | [iso](renders/quality-audit/pass_morphology/coastal_isometric.png) · [top](renders/quality-audit/pass_morphology/coastal_topdown.png) · [side](renders/quality-audit/pass_morphology/coastal_sideprofile.png) | All erosion channels near-zero |
| volcanic | ❌ **D** | [iso](renders/quality-audit/pass_morphology/volcanic_isometric.png) · [top](renders/quality-audit/pass_morphology/volcanic_topdown.png) · [side](renders/quality-audit/pass_morphology/volcanic_sideprofile.png) | All erosion channels near-zero |
| frozen | ❌ **D** | [iso](renders/quality-audit/pass_morphology/frozen_isometric.png) · [top](renders/quality-audit/pass_morphology/frozen_topdown.png) · [side](renders/quality-audit/pass_morphology/frozen_sideprofile.png) | All erosion channels near-zero |
| desert | ❌ **D** | [iso](renders/quality-audit/pass_morphology/desert_isometric.png) · [top](renders/quality-audit/pass_morphology/desert_topdown.png) · [side](renders/quality-audit/pass_morphology/desert_sideprofile.png) | All erosion channels near-zero |

### ✅ `stratigraphy` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/stratigraphy/grassland_isometric.png) · [top](renders/quality-audit/stratigraphy/grassland_topdown.png) · [side](renders/quality-audit/stratigraphy/grassland_sideprofile.png) | Erosion active: 8/10 channels, pixel_std=82.6 |
| mountain | ✅ **A** | [iso](renders/quality-audit/stratigraphy/mountain_isometric.png) · [top](renders/quality-audit/stratigraphy/mountain_topdown.png) · [side](renders/quality-audit/stratigraphy/mountain_sideprofile.png) | Erosion active: 8/10 channels, pixel_std=83.1 |
| coastal | ✅ **A** | [iso](renders/quality-audit/stratigraphy/coastal_isometric.png) · [top](renders/quality-audit/stratigraphy/coastal_topdown.png) · [side](renders/quality-audit/stratigraphy/coastal_sideprofile.png) | Erosion active: 8/10 channels, pixel_std=80.5 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/stratigraphy/volcanic_isometric.png) · [top](renders/quality-audit/stratigraphy/volcanic_topdown.png) · [side](renders/quality-audit/stratigraphy/volcanic_sideprofile.png) | Erosion active: 9/10 channels, pixel_std=82.6 |
| frozen | ✅ **A** | [iso](renders/quality-audit/stratigraphy/frozen_isometric.png) · [top](renders/quality-audit/stratigraphy/frozen_topdown.png) · [side](renders/quality-audit/stratigraphy/frozen_sideprofile.png) | Erosion active: 8/10 channels, pixel_std=81.0 |
| desert | ✅ **A** | [iso](renders/quality-audit/stratigraphy/desert_isometric.png) · [top](renders/quality-audit/stratigraphy/desert_topdown.png) · [side](renders/quality-audit/stratigraphy/desert_sideprofile.png) | Erosion active: 9/10 channels, pixel_std=82.2 |

### ✅ `talus` — Grade **A**

**Overall:** 5A/1B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/talus/grassland_isometric.png) · [top](renders/quality-audit/talus/grassland_topdown.png) · [side](renders/quality-audit/talus/grassland_sideprofile.png) | Erosion active: 2/2 channels, pixel_std=85.4 |
| mountain | ✅ **A** | [iso](renders/quality-audit/talus/mountain_isometric.png) · [top](renders/quality-audit/talus/mountain_topdown.png) · [side](renders/quality-audit/talus/mountain_sideprofile.png) | Erosion active: 2/2 channels, pixel_std=78.4 |
| coastal | 🟡 **B** | [iso](renders/quality-audit/talus/coastal_isometric.png) · [top](renders/quality-audit/talus/coastal_topdown.png) · [side](renders/quality-audit/talus/coastal_sideprofile.png) | Erosion partial: terrain visible 1/3 angles, pixel_std=80.8 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/talus/volcanic_isometric.png) · [top](renders/quality-audit/talus/volcanic_topdown.png) · [side](renders/quality-audit/talus/volcanic_sideprofile.png) | Erosion active: 2/2 channels, pixel_std=76.5 |
| frozen | ✅ **A** | [iso](renders/quality-audit/talus/frozen_isometric.png) · [top](renders/quality-audit/talus/frozen_topdown.png) · [side](renders/quality-audit/talus/frozen_sideprofile.png) | Erosion active: 2/2 channels, pixel_std=81.5 |
| desert | ✅ **A** | [iso](renders/quality-audit/talus/desert_isometric.png) · [top](renders/quality-audit/talus/desert_topdown.png) · [side](renders/quality-audit/talus/desert_sideprofile.png) | Erosion active: 2/2 channels, pixel_std=78.3 |

### ✅ `wind_erosion` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/wind_erosion/grassland_isometric.png) · [top](renders/quality-audit/wind_erosion/grassland_topdown.png) · [side](renders/quality-audit/wind_erosion/grassland_sideprofile.png) | Erosion active: 1/1 channels, pixel_std=82.6 |
| mountain | ✅ **A** | [iso](renders/quality-audit/wind_erosion/mountain_isometric.png) · [top](renders/quality-audit/wind_erosion/mountain_topdown.png) · [side](renders/quality-audit/wind_erosion/mountain_sideprofile.png) | Erosion active: 1/1 channels, pixel_std=83.1 |
| coastal | ✅ **A** | [iso](renders/quality-audit/wind_erosion/coastal_isometric.png) · [top](renders/quality-audit/wind_erosion/coastal_topdown.png) · [side](renders/quality-audit/wind_erosion/coastal_sideprofile.png) | Erosion active: 1/1 channels, pixel_std=80.5 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/wind_erosion/volcanic_isometric.png) · [top](renders/quality-audit/wind_erosion/volcanic_topdown.png) · [side](renders/quality-audit/wind_erosion/volcanic_sideprofile.png) | Erosion active: 1/1 channels, pixel_std=82.6 |
| frozen | ✅ **A** | [iso](renders/quality-audit/wind_erosion/frozen_isometric.png) · [top](renders/quality-audit/wind_erosion/frozen_topdown.png) · [side](renders/quality-audit/wind_erosion/frozen_sideprofile.png) | Erosion active: 1/1 channels, pixel_std=81.0 |
| desert | ✅ **A** | [iso](renders/quality-audit/wind_erosion/desert_isometric.png) · [top](renders/quality-audit/wind_erosion/desert_topdown.png) · [side](renders/quality-audit/wind_erosion/desert_sideprofile.png) | Erosion active: 1/1 channels, pixel_std=82.2 |

## Water System Passes

### ✅ `bathymetry` — Grade **A**

**Overall:** 5A/1B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/bathymetry/grassland_isometric.png) · [top](renders/quality-audit/bathymetry/grassland_topdown.png) · [side](renders/quality-audit/bathymetry/grassland_sideprofile.png) | Water pass: 2 active channels, color_sep=14.5 |
| mountain | 🟡 **B** | [iso](renders/quality-audit/bathymetry/mountain_isometric.png) · [top](renders/quality-audit/bathymetry/mountain_topdown.png) · [side](renders/quality-audit/bathymetry/mountain_sideprofile.png) | Water partial: 2 active channels, terrain_count=3/3 |
| coastal | ✅ **A** | [iso](renders/quality-audit/bathymetry/coastal_isometric.png) · [top](renders/quality-audit/bathymetry/coastal_topdown.png) · [side](renders/quality-audit/bathymetry/coastal_sideprofile.png) | Water pass: 2 active channels, color_sep=21.7 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/bathymetry/volcanic_isometric.png) · [top](renders/quality-audit/bathymetry/volcanic_topdown.png) · [side](renders/quality-audit/bathymetry/volcanic_sideprofile.png) | Water pass: 2 active channels, color_sep=11.6 |
| frozen | ✅ **A** | [iso](renders/quality-audit/bathymetry/frozen_isometric.png) · [top](renders/quality-audit/bathymetry/frozen_topdown.png) · [side](renders/quality-audit/bathymetry/frozen_sideprofile.png) | Water pass: 2 active channels, color_sep=18.2 |
| desert | ✅ **A** | [iso](renders/quality-audit/bathymetry/desert_isometric.png) · [top](renders/quality-audit/bathymetry/desert_topdown.png) · [side](renders/quality-audit/bathymetry/desert_sideprofile.png) | Water pass: 2 active channels, color_sep=12.4 |

### ✅ `coastline` — Grade **A**

**Overall:** 5A/1B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/coastline/grassland_isometric.png) · [top](renders/quality-audit/coastline/grassland_topdown.png) · [side](renders/quality-audit/coastline/grassland_sideprofile.png) | Water pass: 3 active channels, color_sep=14.5 |
| mountain | 🟡 **B** | [iso](renders/quality-audit/coastline/mountain_isometric.png) · [top](renders/quality-audit/coastline/mountain_topdown.png) · [side](renders/quality-audit/coastline/mountain_sideprofile.png) | Water partial: 3 active channels, terrain_count=3/3 |
| coastal | ✅ **A** | [iso](renders/quality-audit/coastline/coastal_isometric.png) · [top](renders/quality-audit/coastline/coastal_topdown.png) · [side](renders/quality-audit/coastline/coastal_sideprofile.png) | Water pass: 2 active channels, color_sep=21.7 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/coastline/volcanic_isometric.png) · [top](renders/quality-audit/coastline/volcanic_topdown.png) · [side](renders/quality-audit/coastline/volcanic_sideprofile.png) | Water pass: 3 active channels, color_sep=11.6 |
| frozen | ✅ **A** | [iso](renders/quality-audit/coastline/frozen_isometric.png) · [top](renders/quality-audit/coastline/frozen_topdown.png) · [side](renders/quality-audit/coastline/frozen_sideprofile.png) | Water pass: 3 active channels, color_sep=18.2 |
| desert | ✅ **A** | [iso](renders/quality-audit/coastline/desert_isometric.png) · [top](renders/quality-audit/coastline/desert_topdown.png) · [side](renders/quality-audit/coastline/desert_sideprofile.png) | Water pass: 3 active channels, color_sep=12.4 |

### ✅ `pass_hydrology` — Grade **A**

**Overall:** 5A/1B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/pass_hydrology/grassland_isometric.png) · [top](renders/quality-audit/pass_hydrology/grassland_topdown.png) · [side](renders/quality-audit/pass_hydrology/grassland_sideprofile.png) | Water pass: 2 active channels, color_sep=14.5 |
| mountain | 🟡 **B** | [iso](renders/quality-audit/pass_hydrology/mountain_isometric.png) · [top](renders/quality-audit/pass_hydrology/mountain_topdown.png) · [side](renders/quality-audit/pass_hydrology/mountain_sideprofile.png) | Water partial: 2 active channels, terrain_count=3/3 |
| coastal | ✅ **A** | [iso](renders/quality-audit/pass_hydrology/coastal_isometric.png) · [top](renders/quality-audit/pass_hydrology/coastal_topdown.png) · [side](renders/quality-audit/pass_hydrology/coastal_sideprofile.png) | Water pass: 2 active channels, color_sep=21.7 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/pass_hydrology/volcanic_isometric.png) · [top](renders/quality-audit/pass_hydrology/volcanic_topdown.png) · [side](renders/quality-audit/pass_hydrology/volcanic_sideprofile.png) | Water pass: 2 active channels, color_sep=11.6 |
| frozen | ✅ **A** | [iso](renders/quality-audit/pass_hydrology/frozen_isometric.png) · [top](renders/quality-audit/pass_hydrology/frozen_topdown.png) · [side](renders/quality-audit/pass_hydrology/frozen_sideprofile.png) | Water pass: 2 active channels, color_sep=18.2 |
| desert | ✅ **A** | [iso](renders/quality-audit/pass_hydrology/desert_isometric.png) · [top](renders/quality-audit/pass_hydrology/desert_topdown.png) · [side](renders/quality-audit/pass_hydrology/desert_sideprofile.png) | Water pass: 2 active channels, color_sep=12.4 |

### ✅ `pass_hydrology_post_erosion` — Grade **A**

**Overall:** 5A/1B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/pass_hydrology_post_erosion/grassland_isometric.png) · [top](renders/quality-audit/pass_hydrology_post_erosion/grassland_topdown.png) · [side](renders/quality-audit/pass_hydrology_post_erosion/grassland_sideprofile.png) | Water pass: 2 active channels, color_sep=14.5 |
| mountain | 🟡 **B** | [iso](renders/quality-audit/pass_hydrology_post_erosion/mountain_isometric.png) · [top](renders/quality-audit/pass_hydrology_post_erosion/mountain_topdown.png) · [side](renders/quality-audit/pass_hydrology_post_erosion/mountain_sideprofile.png) | Water partial: 2 active channels, terrain_count=3/3 |
| coastal | ✅ **A** | [iso](renders/quality-audit/pass_hydrology_post_erosion/coastal_isometric.png) · [top](renders/quality-audit/pass_hydrology_post_erosion/coastal_topdown.png) · [side](renders/quality-audit/pass_hydrology_post_erosion/coastal_sideprofile.png) | Water pass: 2 active channels, color_sep=21.7 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/pass_hydrology_post_erosion/volcanic_isometric.png) · [top](renders/quality-audit/pass_hydrology_post_erosion/volcanic_topdown.png) · [side](renders/quality-audit/pass_hydrology_post_erosion/volcanic_sideprofile.png) | Water pass: 2 active channels, color_sep=11.6 |
| frozen | ✅ **A** | [iso](renders/quality-audit/pass_hydrology_post_erosion/frozen_isometric.png) · [top](renders/quality-audit/pass_hydrology_post_erosion/frozen_topdown.png) · [side](renders/quality-audit/pass_hydrology_post_erosion/frozen_sideprofile.png) | Water pass: 2 active channels, color_sep=18.2 |
| desert | ✅ **A** | [iso](renders/quality-audit/pass_hydrology_post_erosion/desert_isometric.png) · [top](renders/quality-audit/pass_hydrology_post_erosion/desert_topdown.png) · [side](renders/quality-audit/pass_hydrology_post_erosion/desert_sideprofile.png) | Water pass: 2 active channels, color_sep=12.4 |

### ✅ `pass_river_convergence` — Grade **A**

**Overall:** 5A/1B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/pass_river_convergence/grassland_isometric.png) · [top](renders/quality-audit/pass_river_convergence/grassland_topdown.png) · [side](renders/quality-audit/pass_river_convergence/grassland_sideprofile.png) | Water pass: 3 active channels, color_sep=14.5 |
| mountain | 🟡 **B** | [iso](renders/quality-audit/pass_river_convergence/mountain_isometric.png) · [top](renders/quality-audit/pass_river_convergence/mountain_topdown.png) · [side](renders/quality-audit/pass_river_convergence/mountain_sideprofile.png) | Water partial: 3 active channels, terrain_count=3/3 |
| coastal | ✅ **A** | [iso](renders/quality-audit/pass_river_convergence/coastal_isometric.png) · [top](renders/quality-audit/pass_river_convergence/coastal_topdown.png) · [side](renders/quality-audit/pass_river_convergence/coastal_sideprofile.png) | Water pass: 3 active channels, color_sep=21.7 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/pass_river_convergence/volcanic_isometric.png) · [top](renders/quality-audit/pass_river_convergence/volcanic_topdown.png) · [side](renders/quality-audit/pass_river_convergence/volcanic_sideprofile.png) | Water pass: 3 active channels, color_sep=11.6 |
| frozen | ✅ **A** | [iso](renders/quality-audit/pass_river_convergence/frozen_isometric.png) · [top](renders/quality-audit/pass_river_convergence/frozen_topdown.png) · [side](renders/quality-audit/pass_river_convergence/frozen_sideprofile.png) | Water pass: 3 active channels, color_sep=18.2 |
| desert | ✅ **A** | [iso](renders/quality-audit/pass_river_convergence/desert_isometric.png) · [top](renders/quality-audit/pass_river_convergence/desert_topdown.png) · [side](renders/quality-audit/pass_river_convergence/desert_sideprofile.png) | Water pass: 3 active channels, color_sep=12.4 |

### ✅ `pass_seasonal_water_state` — Grade **A**

**Overall:** 5A/1B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/pass_seasonal_water_state/grassland_isometric.png) · [top](renders/quality-audit/pass_seasonal_water_state/grassland_topdown.png) · [side](renders/quality-audit/pass_seasonal_water_state/grassland_sideprofile.png) | Water pass: 3 active channels, color_sep=14.5 |
| mountain | 🟡 **B** | [iso](renders/quality-audit/pass_seasonal_water_state/mountain_isometric.png) · [top](renders/quality-audit/pass_seasonal_water_state/mountain_topdown.png) · [side](renders/quality-audit/pass_seasonal_water_state/mountain_sideprofile.png) | Water partial: 3 active channels, terrain_count=3/3 |
| coastal | ✅ **A** | [iso](renders/quality-audit/pass_seasonal_water_state/coastal_isometric.png) · [top](renders/quality-audit/pass_seasonal_water_state/coastal_topdown.png) · [side](renders/quality-audit/pass_seasonal_water_state/coastal_sideprofile.png) | Water pass: 2 active channels, color_sep=21.7 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/pass_seasonal_water_state/volcanic_isometric.png) · [top](renders/quality-audit/pass_seasonal_water_state/volcanic_topdown.png) · [side](renders/quality-audit/pass_seasonal_water_state/volcanic_sideprofile.png) | Water pass: 3 active channels, color_sep=11.6 |
| frozen | ✅ **A** | [iso](renders/quality-audit/pass_seasonal_water_state/frozen_isometric.png) · [top](renders/quality-audit/pass_seasonal_water_state/frozen_topdown.png) · [side](renders/quality-audit/pass_seasonal_water_state/frozen_sideprofile.png) | Water pass: 3 active channels, color_sep=18.2 |
| desert | ✅ **A** | [iso](renders/quality-audit/pass_seasonal_water_state/desert_isometric.png) · [top](renders/quality-audit/pass_seasonal_water_state/desert_topdown.png) · [side](renders/quality-audit/pass_seasonal_water_state/desert_sideprofile.png) | Water pass: 3 active channels, color_sep=12.4 |

### ❌ `pass_water_depth` — Grade **D**

**Overall:** 0F + 6D across biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ❌ **D** | [iso](renders/quality-audit/pass_water_depth/grassland_isometric.png) · [top](renders/quality-audit/pass_water_depth/grassland_topdown.png) · [side](renders/quality-audit/pass_water_depth/grassland_sideprofile.png) | Pass skipped — missing prerequisite channels (never ran) |
| mountain | ❌ **D** | [iso](renders/quality-audit/pass_water_depth/mountain_isometric.png) · [top](renders/quality-audit/pass_water_depth/mountain_topdown.png) · [side](renders/quality-audit/pass_water_depth/mountain_sideprofile.png) | Pass skipped — missing prerequisite channels (never ran) |
| coastal | ❌ **D** | [iso](renders/quality-audit/pass_water_depth/coastal_isometric.png) · [top](renders/quality-audit/pass_water_depth/coastal_topdown.png) · [side](renders/quality-audit/pass_water_depth/coastal_sideprofile.png) | Pass skipped — missing prerequisite channels (never ran) |
| volcanic | ❌ **D** | [iso](renders/quality-audit/pass_water_depth/volcanic_isometric.png) · [top](renders/quality-audit/pass_water_depth/volcanic_topdown.png) · [side](renders/quality-audit/pass_water_depth/volcanic_sideprofile.png) | Pass skipped — missing prerequisite channels (never ran) |
| frozen | ❌ **D** | [iso](renders/quality-audit/pass_water_depth/frozen_isometric.png) · [top](renders/quality-audit/pass_water_depth/frozen_topdown.png) · [side](renders/quality-audit/pass_water_depth/frozen_sideprofile.png) | Pass skipped — missing prerequisite channels (never ran) |
| desert | ❌ **D** | [iso](renders/quality-audit/pass_water_depth/desert_isometric.png) · [top](renders/quality-audit/pass_water_depth/desert_topdown.png) · [side](renders/quality-audit/pass_water_depth/desert_sideprofile.png) | Pass skipped — missing prerequisite channels (never ran) |

### 🟡 `pass_water_flow_speed` — Grade **B**

**Overall:** 0A/6B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | 🟡 **B** | [iso](renders/quality-audit/pass_water_flow_speed/grassland_isometric.png) · [top](renders/quality-audit/pass_water_flow_speed/grassland_topdown.png) · [side](renders/quality-audit/pass_water_flow_speed/grassland_sideprofile.png) | Water partial: 1 active channels, terrain_count=3/3 |
| mountain | 🟡 **B** | [iso](renders/quality-audit/pass_water_flow_speed/mountain_isometric.png) · [top](renders/quality-audit/pass_water_flow_speed/mountain_topdown.png) · [side](renders/quality-audit/pass_water_flow_speed/mountain_sideprofile.png) | Water partial: 1 active channels, terrain_count=3/3 |
| coastal | 🟡 **B** | [iso](renders/quality-audit/pass_water_flow_speed/coastal_isometric.png) · [top](renders/quality-audit/pass_water_flow_speed/coastal_topdown.png) · [side](renders/quality-audit/pass_water_flow_speed/coastal_sideprofile.png) | Water partial: 1 active channels, terrain_count=3/3 |
| volcanic | 🟡 **B** | [iso](renders/quality-audit/pass_water_flow_speed/volcanic_isometric.png) · [top](renders/quality-audit/pass_water_flow_speed/volcanic_topdown.png) · [side](renders/quality-audit/pass_water_flow_speed/volcanic_sideprofile.png) | Water partial: 1 active channels, terrain_count=3/3 |
| frozen | 🟡 **B** | [iso](renders/quality-audit/pass_water_flow_speed/frozen_isometric.png) · [top](renders/quality-audit/pass_water_flow_speed/frozen_topdown.png) · [side](renders/quality-audit/pass_water_flow_speed/frozen_sideprofile.png) | Water partial: 1 active channels, terrain_count=3/3 |
| desert | 🟡 **B** | [iso](renders/quality-audit/pass_water_flow_speed/desert_isometric.png) · [top](renders/quality-audit/pass_water_flow_speed/desert_topdown.png) · [side](renders/quality-audit/pass_water_flow_speed/desert_sideprofile.png) | Water partial: 1 active channels, terrain_count=3/3 |

### ✅ `water_variants` — Grade **A**

**Overall:** 5A/1B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/water_variants/grassland_isometric.png) · [top](renders/quality-audit/water_variants/grassland_topdown.png) · [side](renders/quality-audit/water_variants/grassland_sideprofile.png) | Water pass: 4 active channels, color_sep=14.5 |
| mountain | 🟡 **B** | [iso](renders/quality-audit/water_variants/mountain_isometric.png) · [top](renders/quality-audit/water_variants/mountain_topdown.png) · [side](renders/quality-audit/water_variants/mountain_sideprofile.png) | Water partial: 4 active channels, terrain_count=3/3 |
| coastal | ✅ **A** | [iso](renders/quality-audit/water_variants/coastal_isometric.png) · [top](renders/quality-audit/water_variants/coastal_topdown.png) · [side](renders/quality-audit/water_variants/coastal_sideprofile.png) | Water pass: 4 active channels, color_sep=21.7 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/water_variants/volcanic_isometric.png) · [top](renders/quality-audit/water_variants/volcanic_topdown.png) · [side](renders/quality-audit/water_variants/volcanic_sideprofile.png) | Water pass: 4 active channels, color_sep=11.6 |
| frozen | ✅ **A** | [iso](renders/quality-audit/water_variants/frozen_isometric.png) · [top](renders/quality-audit/water_variants/frozen_topdown.png) · [side](renders/quality-audit/water_variants/frozen_sideprofile.png) | Water pass: 4 active channels, color_sep=18.2 |
| desert | ✅ **A** | [iso](renders/quality-audit/water_variants/desert_isometric.png) · [top](renders/quality-audit/water_variants/desert_topdown.png) · [side](renders/quality-audit/water_variants/desert_sideprofile.png) | Water pass: 4 active channels, color_sep=12.4 |

### 🟡 `waterfall_mist` — Grade **B**

**Overall:** 0A/6B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | 🟡 **B** | [iso](renders/quality-audit/waterfall_mist/grassland_isometric.png) · [top](renders/quality-audit/waterfall_mist/grassland_topdown.png) · [side](renders/quality-audit/waterfall_mist/grassland_sideprofile.png) | Water partial: 1 active channels, terrain_count=3/3 |
| mountain | 🟡 **B** | [iso](renders/quality-audit/waterfall_mist/mountain_isometric.png) · [top](renders/quality-audit/waterfall_mist/mountain_topdown.png) · [side](renders/quality-audit/waterfall_mist/mountain_sideprofile.png) | Water partial: 1 active channels, terrain_count=3/3 |
| coastal | 🟡 **B** | [iso](renders/quality-audit/waterfall_mist/coastal_isometric.png) · [top](renders/quality-audit/waterfall_mist/coastal_topdown.png) · [side](renders/quality-audit/waterfall_mist/coastal_sideprofile.png) | Water partial: 1 active channels, terrain_count=3/3 |
| volcanic | 🟡 **B** | [iso](renders/quality-audit/waterfall_mist/volcanic_isometric.png) · [top](renders/quality-audit/waterfall_mist/volcanic_topdown.png) · [side](renders/quality-audit/waterfall_mist/volcanic_sideprofile.png) | Water partial: 1 active channels, terrain_count=3/3 |
| frozen | 🟡 **B** | [iso](renders/quality-audit/waterfall_mist/frozen_isometric.png) · [top](renders/quality-audit/waterfall_mist/frozen_topdown.png) · [side](renders/quality-audit/waterfall_mist/frozen_sideprofile.png) | Water partial: 1 active channels, terrain_count=3/3 |
| desert | 🟡 **B** | [iso](renders/quality-audit/waterfall_mist/desert_isometric.png) · [top](renders/quality-audit/waterfall_mist/desert_topdown.png) · [side](renders/quality-audit/waterfall_mist/desert_sideprofile.png) | Water partial: 1 active channels, terrain_count=3/3 |

### 🟡 `waterfalls` — Grade **B**

**Overall:** 1A/5B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | 🟡 **B** | [iso](renders/quality-audit/waterfalls/grassland_isometric.png) · [top](renders/quality-audit/waterfalls/grassland_topdown.png) · [side](renders/quality-audit/waterfalls/grassland_sideprofile.png) | Water partial: 1 active channels, terrain_count=3/3 |
| mountain | 🟡 **B** | [iso](renders/quality-audit/waterfalls/mountain_isometric.png) · [top](renders/quality-audit/waterfalls/mountain_topdown.png) · [side](renders/quality-audit/waterfalls/mountain_sideprofile.png) | Water partial: 1 active channels, terrain_count=3/3 |
| coastal | 🟡 **B** | [iso](renders/quality-audit/waterfalls/coastal_isometric.png) · [top](renders/quality-audit/waterfalls/coastal_topdown.png) · [side](renders/quality-audit/waterfalls/coastal_sideprofile.png) | Water partial: 1 active channels, terrain_count=3/3 |
| volcanic | 🟡 **B** | [iso](renders/quality-audit/waterfalls/volcanic_isometric.png) · [top](renders/quality-audit/waterfalls/volcanic_topdown.png) · [side](renders/quality-audit/waterfalls/volcanic_sideprofile.png) | Water partial: 1 active channels, terrain_count=3/3 |
| frozen | ✅ **A** | [iso](renders/quality-audit/waterfalls/frozen_isometric.png) · [top](renders/quality-audit/waterfalls/frozen_topdown.png) · [side](renders/quality-audit/waterfalls/frozen_sideprofile.png) | Water pass: 4 active channels, color_sep=18.2 |
| desert | 🟡 **B** | [iso](renders/quality-audit/waterfalls/desert_isometric.png) · [top](renders/quality-audit/waterfalls/desert_topdown.png) · [side](renders/quality-audit/waterfalls/desert_sideprofile.png) | Water partial: 1 active channels, terrain_count=3/3 |

## Biome Classification Passes

### ✅ `biome_channels` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/biome_channels/grassland_isometric.png) · [top](renders/quality-audit/biome_channels/grassland_topdown.png) · [side](renders/quality-audit/biome_channels/grassland_sideprofile.png) | Biome channels: 1/2 active, coverage=80% |
| mountain | ✅ **A** | [iso](renders/quality-audit/biome_channels/mountain_isometric.png) · [top](renders/quality-audit/biome_channels/mountain_topdown.png) · [side](renders/quality-audit/biome_channels/mountain_sideprofile.png) | Biome channels: 1/2 active, coverage=78% |
| coastal | ✅ **A** | [iso](renders/quality-audit/biome_channels/coastal_isometric.png) · [top](renders/quality-audit/biome_channels/coastal_topdown.png) · [side](renders/quality-audit/biome_channels/coastal_sideprofile.png) | Biome channels: 1/2 active, coverage=78% |
| volcanic | ✅ **A** | [iso](renders/quality-audit/biome_channels/volcanic_isometric.png) · [top](renders/quality-audit/biome_channels/volcanic_topdown.png) · [side](renders/quality-audit/biome_channels/volcanic_sideprofile.png) | Biome channels: 1/2 active, coverage=84% |
| frozen | ✅ **A** | [iso](renders/quality-audit/biome_channels/frozen_isometric.png) · [top](renders/quality-audit/biome_channels/frozen_topdown.png) · [side](renders/quality-audit/biome_channels/frozen_sideprofile.png) | Biome channels: 1/2 active, coverage=73% |
| desert | ✅ **A** | [iso](renders/quality-audit/biome_channels/desert_isometric.png) · [top](renders/quality-audit/biome_channels/desert_topdown.png) · [side](renders/quality-audit/biome_channels/desert_sideprofile.png) | Biome channels: 1/2 active, coverage=72% |

### ✅ `biome_surface_features` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/biome_surface_features/grassland_isometric.png) · [top](renders/quality-audit/biome_surface_features/grassland_topdown.png) · [side](renders/quality-audit/biome_surface_features/grassland_sideprofile.png) | Biome channels: 1/1 active, coverage=100% |
| mountain | ✅ **A** | [iso](renders/quality-audit/biome_surface_features/mountain_isometric.png) · [top](renders/quality-audit/biome_surface_features/mountain_topdown.png) · [side](renders/quality-audit/biome_surface_features/mountain_sideprofile.png) | Biome channels: 1/1 active, coverage=100% |
| coastal | ✅ **A** | [iso](renders/quality-audit/biome_surface_features/coastal_isometric.png) · [top](renders/quality-audit/biome_surface_features/coastal_topdown.png) · [side](renders/quality-audit/biome_surface_features/coastal_sideprofile.png) | Biome channels: 1/1 active, coverage=100% |
| volcanic | ✅ **A** | [iso](renders/quality-audit/biome_surface_features/volcanic_isometric.png) · [top](renders/quality-audit/biome_surface_features/volcanic_topdown.png) · [side](renders/quality-audit/biome_surface_features/volcanic_sideprofile.png) | Biome channels: 1/1 active, coverage=100% |
| frozen | ✅ **A** | [iso](renders/quality-audit/biome_surface_features/frozen_isometric.png) · [top](renders/quality-audit/biome_surface_features/frozen_topdown.png) · [side](renders/quality-audit/biome_surface_features/frozen_sideprofile.png) | Biome channels: 1/1 active, coverage=100% |
| desert | ✅ **A** | [iso](renders/quality-audit/biome_surface_features/desert_isometric.png) · [top](renders/quality-audit/biome_surface_features/desert_topdown.png) · [side](renders/quality-audit/biome_surface_features/desert_sideprofile.png) | Biome channels: 1/1 active, coverage=100% |

### ✅ `ecotones` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/ecotones/grassland_isometric.png) · [top](renders/quality-audit/ecotones/grassland_topdown.png) · [side](renders/quality-audit/ecotones/grassland_sideprofile.png) | Biome channels: 2/2 active, coverage=100% |
| mountain | ✅ **A** | [iso](renders/quality-audit/ecotones/mountain_isometric.png) · [top](renders/quality-audit/ecotones/mountain_topdown.png) · [side](renders/quality-audit/ecotones/mountain_sideprofile.png) | Biome channels: 2/2 active, coverage=100% |
| coastal | ✅ **A** | [iso](renders/quality-audit/ecotones/coastal_isometric.png) · [top](renders/quality-audit/ecotones/coastal_topdown.png) · [side](renders/quality-audit/ecotones/coastal_sideprofile.png) | Biome channels: 2/2 active, coverage=100% |
| volcanic | ✅ **A** | [iso](renders/quality-audit/ecotones/volcanic_isometric.png) · [top](renders/quality-audit/ecotones/volcanic_topdown.png) · [side](renders/quality-audit/ecotones/volcanic_sideprofile.png) | Biome channels: 2/2 active, coverage=100% |
| frozen | ✅ **A** | [iso](renders/quality-audit/ecotones/frozen_isometric.png) · [top](renders/quality-audit/ecotones/frozen_topdown.png) · [side](renders/quality-audit/ecotones/frozen_sideprofile.png) | Biome channels: 2/2 active, coverage=100% |
| desert | ✅ **A** | [iso](renders/quality-audit/ecotones/desert_isometric.png) · [top](renders/quality-audit/ecotones/desert_topdown.png) · [side](renders/quality-audit/ecotones/desert_sideprofile.png) | Biome channels: 2/2 active, coverage=100% |

### ✅ `snow_line` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/snow_line/grassland_isometric.png) · [top](renders/quality-audit/snow_line/grassland_topdown.png) · [side](renders/quality-audit/snow_line/grassland_sideprofile.png) | Biome channels: 1/1 active, coverage=100% |
| mountain | ✅ **A** | [iso](renders/quality-audit/snow_line/mountain_isometric.png) · [top](renders/quality-audit/snow_line/mountain_topdown.png) · [side](renders/quality-audit/snow_line/mountain_sideprofile.png) | Biome channels: 1/1 active, coverage=100% |
| coastal | ✅ **A** | [iso](renders/quality-audit/snow_line/coastal_isometric.png) · [top](renders/quality-audit/snow_line/coastal_topdown.png) · [side](renders/quality-audit/snow_line/coastal_sideprofile.png) | Biome channels: 1/1 active, coverage=100% |
| volcanic | ✅ **A** | [iso](renders/quality-audit/snow_line/volcanic_isometric.png) · [top](renders/quality-audit/snow_line/volcanic_topdown.png) · [side](renders/quality-audit/snow_line/volcanic_sideprofile.png) | Biome channels: 1/1 active, coverage=100% |
| frozen | ✅ **A** | [iso](renders/quality-audit/snow_line/frozen_isometric.png) · [top](renders/quality-audit/snow_line/frozen_topdown.png) · [side](renders/quality-audit/snow_line/frozen_sideprofile.png) | Biome channels: 1/1 active, coverage=100% |
| desert | ✅ **A** | [iso](renders/quality-audit/snow_line/desert_isometric.png) · [top](renders/quality-audit/snow_line/desert_topdown.png) · [side](renders/quality-audit/snow_line/desert_sideprofile.png) | Biome channels: 1/1 active, coverage=100% |

### ❌ `terrain_labels` — Grade **D**

**Overall:** 0F + 6D across biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ❌ **D** | [iso](renders/quality-audit/terrain_labels/grassland_isometric.png) · [top](renders/quality-audit/terrain_labels/grassland_topdown.png) · [side](renders/quality-audit/terrain_labels/grassland_sideprofile.png) | All biome channels near-zero |
| mountain | ❌ **D** | [iso](renders/quality-audit/terrain_labels/mountain_isometric.png) · [top](renders/quality-audit/terrain_labels/mountain_topdown.png) · [side](renders/quality-audit/terrain_labels/mountain_sideprofile.png) | All biome channels near-zero |
| coastal | ❌ **D** | [iso](renders/quality-audit/terrain_labels/coastal_isometric.png) · [top](renders/quality-audit/terrain_labels/coastal_topdown.png) · [side](renders/quality-audit/terrain_labels/coastal_sideprofile.png) | All biome channels near-zero |
| volcanic | ❌ **D** | [iso](renders/quality-audit/terrain_labels/volcanic_isometric.png) · [top](renders/quality-audit/terrain_labels/volcanic_topdown.png) · [side](renders/quality-audit/terrain_labels/volcanic_sideprofile.png) | All biome channels near-zero |
| frozen | ❌ **D** | [iso](renders/quality-audit/terrain_labels/frozen_isometric.png) · [top](renders/quality-audit/terrain_labels/frozen_topdown.png) · [side](renders/quality-audit/terrain_labels/frozen_sideprofile.png) | All biome channels near-zero |
| desert | ❌ **D** | [iso](renders/quality-audit/terrain_labels/desert_isometric.png) · [top](renders/quality-audit/terrain_labels/desert_topdown.png) · [side](renders/quality-audit/terrain_labels/desert_sideprofile.png) | All biome channels near-zero |

## Feature Generation Passes

### ⚠️ `caves` — Grade **C**

**Overall:** 0A/0B/6C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ⚠️ **C** | [iso](renders/quality-audit/caves/grassland_isometric.png) · [top](renders/quality-audit/caves/grassland_topdown.png) · [side](renders/quality-audit/caves/grassland_sideprofile.png) | Feature terrain visible 3/3 but effect limited |
| mountain | ⚠️ **C** | [iso](renders/quality-audit/caves/mountain_isometric.png) · [top](renders/quality-audit/caves/mountain_topdown.png) · [side](renders/quality-audit/caves/mountain_sideprofile.png) | Feature terrain visible 3/3 but effect limited |
| coastal | ⚠️ **C** | [iso](renders/quality-audit/caves/coastal_isometric.png) · [top](renders/quality-audit/caves/coastal_topdown.png) · [side](renders/quality-audit/caves/coastal_sideprofile.png) | Feature terrain visible 3/3 but effect limited |
| volcanic | ⚠️ **C** | [iso](renders/quality-audit/caves/volcanic_isometric.png) · [top](renders/quality-audit/caves/volcanic_topdown.png) · [side](renders/quality-audit/caves/volcanic_sideprofile.png) | Feature terrain visible 3/3 but effect limited |
| frozen | ⚠️ **C** | [iso](renders/quality-audit/caves/frozen_isometric.png) · [top](renders/quality-audit/caves/frozen_topdown.png) · [side](renders/quality-audit/caves/frozen_sideprofile.png) | Feature terrain visible 3/3 but effect limited |
| desert | ⚠️ **C** | [iso](renders/quality-audit/caves/desert_isometric.png) · [top](renders/quality-audit/caves/desert_topdown.png) · [side](renders/quality-audit/caves/desert_sideprofile.png) | Feature terrain visible 3/3 but effect limited |

### 🟡 `cliffs` — Grade **B**

**Overall:** 0A/6B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | 🟡 **B** | [iso](renders/quality-audit/cliffs/grassland_isometric.png) · [top](renders/quality-audit/cliffs/grassland_topdown.png) · [side](renders/quality-audit/cliffs/grassland_sideprofile.png) | Feature pass: terrain visible 3/3, 4 active channels |
| mountain | 🟡 **B** | [iso](renders/quality-audit/cliffs/mountain_isometric.png) · [top](renders/quality-audit/cliffs/mountain_topdown.png) · [side](renders/quality-audit/cliffs/mountain_sideprofile.png) | Feature pass: terrain visible 3/3, 3 active channels |
| coastal | 🟡 **B** | [iso](renders/quality-audit/cliffs/coastal_isometric.png) · [top](renders/quality-audit/cliffs/coastal_topdown.png) · [side](renders/quality-audit/cliffs/coastal_sideprofile.png) | Feature pass: terrain visible 3/3, 4 active channels |
| volcanic | 🟡 **B** | [iso](renders/quality-audit/cliffs/volcanic_isometric.png) · [top](renders/quality-audit/cliffs/volcanic_topdown.png) · [side](renders/quality-audit/cliffs/volcanic_sideprofile.png) | Feature pass: terrain visible 3/3, 3 active channels |
| frozen | 🟡 **B** | [iso](renders/quality-audit/cliffs/frozen_isometric.png) · [top](renders/quality-audit/cliffs/frozen_topdown.png) · [side](renders/quality-audit/cliffs/frozen_sideprofile.png) | Feature pass: terrain visible 3/3, 4 active channels |
| desert | 🟡 **B** | [iso](renders/quality-audit/cliffs/desert_isometric.png) · [top](renders/quality-audit/cliffs/desert_topdown.png) · [side](renders/quality-audit/cliffs/desert_sideprofile.png) | Feature pass: terrain visible 3/3, 4 active channels |

### ⚠️ `emit_overhang_meshes` — Grade **C**

**Overall:** 0A/0B/6C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ⚠️ **C** | [iso](renders/quality-audit/emit_overhang_meshes/grassland_isometric.png) · [top](renders/quality-audit/emit_overhang_meshes/grassland_topdown.png) · [side](renders/quality-audit/emit_overhang_meshes/grassland_sideprofile.png) | No channels produced — feature pass may be emit-only (check Unity side) |
| mountain | ⚠️ **C** | [iso](renders/quality-audit/emit_overhang_meshes/mountain_isometric.png) · [top](renders/quality-audit/emit_overhang_meshes/mountain_topdown.png) · [side](renders/quality-audit/emit_overhang_meshes/mountain_sideprofile.png) | No channels produced — feature pass may be emit-only (check Unity side) |
| coastal | ⚠️ **C** | [iso](renders/quality-audit/emit_overhang_meshes/coastal_isometric.png) · [top](renders/quality-audit/emit_overhang_meshes/coastal_topdown.png) · [side](renders/quality-audit/emit_overhang_meshes/coastal_sideprofile.png) | No channels produced — feature pass may be emit-only (check Unity side) |
| volcanic | ⚠️ **C** | [iso](renders/quality-audit/emit_overhang_meshes/volcanic_isometric.png) · [top](renders/quality-audit/emit_overhang_meshes/volcanic_topdown.png) · [side](renders/quality-audit/emit_overhang_meshes/volcanic_sideprofile.png) | No channels produced — feature pass may be emit-only (check Unity side) |
| frozen | ⚠️ **C** | [iso](renders/quality-audit/emit_overhang_meshes/frozen_isometric.png) · [top](renders/quality-audit/emit_overhang_meshes/frozen_topdown.png) · [side](renders/quality-audit/emit_overhang_meshes/frozen_sideprofile.png) | No channels produced — feature pass may be emit-only (check Unity side) |
| desert | ⚠️ **C** | [iso](renders/quality-audit/emit_overhang_meshes/desert_isometric.png) · [top](renders/quality-audit/emit_overhang_meshes/desert_topdown.png) · [side](renders/quality-audit/emit_overhang_meshes/desert_sideprofile.png) | No channels produced — feature pass may be emit-only (check Unity side) |

### 🟡 `framing` — Grade **B**

**Overall:** 0A/5B/1C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | 🟡 **B** | [iso](renders/quality-audit/framing/grassland_isometric.png) · [top](renders/quality-audit/framing/grassland_topdown.png) · [side](renders/quality-audit/framing/grassland_sideprofile.png) | Feature pass: terrain visible 2/3, 1 active channels |
| mountain | 🟡 **B** | [iso](renders/quality-audit/framing/mountain_isometric.png) · [top](renders/quality-audit/framing/mountain_topdown.png) · [side](renders/quality-audit/framing/mountain_sideprofile.png) | Feature pass: terrain visible 3/3, 1 active channels |
| coastal | ⚠️ **C** | [iso](renders/quality-audit/framing/coastal_isometric.png) · [top](renders/quality-audit/framing/coastal_topdown.png) · [side](renders/quality-audit/framing/coastal_sideprofile.png) | Feature terrain visible 1/3 but effect limited |
| volcanic | 🟡 **B** | [iso](renders/quality-audit/framing/volcanic_isometric.png) · [top](renders/quality-audit/framing/volcanic_topdown.png) · [side](renders/quality-audit/framing/volcanic_sideprofile.png) | Feature pass: terrain visible 3/3, 1 active channels |
| frozen | 🟡 **B** | [iso](renders/quality-audit/framing/frozen_isometric.png) · [top](renders/quality-audit/framing/frozen_topdown.png) · [side](renders/quality-audit/framing/frozen_sideprofile.png) | Feature pass: terrain visible 2/3, 1 active channels |
| desert | 🟡 **B** | [iso](renders/quality-audit/framing/desert_isometric.png) · [top](renders/quality-audit/framing/desert_topdown.png) · [side](renders/quality-audit/framing/desert_sideprofile.png) | Feature pass: terrain visible 3/3, 1 active channels |

### ⚠️ `karst` — Grade **C**

**Overall:** 0A/0B/6C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ⚠️ **C** | [iso](renders/quality-audit/karst/grassland_isometric.png) · [top](renders/quality-audit/karst/grassland_topdown.png) · [side](renders/quality-audit/karst/grassland_sideprofile.png) | Feature terrain visible 3/3 but effect limited |
| mountain | ⚠️ **C** | [iso](renders/quality-audit/karst/mountain_isometric.png) · [top](renders/quality-audit/karst/mountain_topdown.png) · [side](renders/quality-audit/karst/mountain_sideprofile.png) | Feature terrain visible 3/3 but effect limited |
| coastal | ⚠️ **C** | [iso](renders/quality-audit/karst/coastal_isometric.png) · [top](renders/quality-audit/karst/coastal_topdown.png) · [side](renders/quality-audit/karst/coastal_sideprofile.png) | Feature terrain visible 3/3 but effect limited |
| volcanic | ⚠️ **C** | [iso](renders/quality-audit/karst/volcanic_isometric.png) · [top](renders/quality-audit/karst/volcanic_topdown.png) · [side](renders/quality-audit/karst/volcanic_sideprofile.png) | Feature terrain visible 3/3 but effect limited |
| frozen | ⚠️ **C** | [iso](renders/quality-audit/karst/frozen_isometric.png) · [top](renders/quality-audit/karst/frozen_topdown.png) · [side](renders/quality-audit/karst/frozen_sideprofile.png) | Feature terrain visible 3/3 but effect limited |
| desert | ⚠️ **C** | [iso](renders/quality-audit/karst/desert_isometric.png) · [top](renders/quality-audit/karst/desert_topdown.png) · [side](renders/quality-audit/karst/desert_sideprofile.png) | Feature terrain visible 3/3 but effect limited |

### ❌ `pass_lava_simulation` — Grade **D**

**Overall:** 0F + 6D across biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ❌ **D** | [iso](renders/quality-audit/pass_lava_simulation/grassland_isometric.png) · [top](renders/quality-audit/pass_lava_simulation/grassland_topdown.png) · [side](renders/quality-audit/pass_lava_simulation/grassland_sideprofile.png) | Pass skipped — missing prerequisite channels (never ran) |
| mountain | ❌ **D** | [iso](renders/quality-audit/pass_lava_simulation/mountain_isometric.png) · [top](renders/quality-audit/pass_lava_simulation/mountain_topdown.png) · [side](renders/quality-audit/pass_lava_simulation/mountain_sideprofile.png) | Pass skipped — missing prerequisite channels (never ran) |
| coastal | ❌ **D** | [iso](renders/quality-audit/pass_lava_simulation/coastal_isometric.png) · [top](renders/quality-audit/pass_lava_simulation/coastal_topdown.png) · [side](renders/quality-audit/pass_lava_simulation/coastal_sideprofile.png) | Pass skipped — missing prerequisite channels (never ran) |
| volcanic | ❌ **D** | [iso](renders/quality-audit/pass_lava_simulation/volcanic_isometric.png) · [top](renders/quality-audit/pass_lava_simulation/volcanic_topdown.png) · [side](renders/quality-audit/pass_lava_simulation/volcanic_sideprofile.png) | Pass skipped — missing prerequisite channels (never ran) |
| frozen | ❌ **D** | [iso](renders/quality-audit/pass_lava_simulation/frozen_isometric.png) · [top](renders/quality-audit/pass_lava_simulation/frozen_topdown.png) · [side](renders/quality-audit/pass_lava_simulation/frozen_sideprofile.png) | Pass skipped — missing prerequisite channels (never ran) |
| desert | ❌ **D** | [iso](renders/quality-audit/pass_lava_simulation/desert_isometric.png) · [top](renders/quality-audit/pass_lava_simulation/desert_topdown.png) · [side](renders/quality-audit/pass_lava_simulation/desert_sideprofile.png) | Pass skipped — missing prerequisite channels (never ran) |

### ⚠️ `pass_terrain_features` — Grade **C**

**Overall:** 0A/0B/6C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ⚠️ **C** | [iso](renders/quality-audit/pass_terrain_features/grassland_isometric.png) · [top](renders/quality-audit/pass_terrain_features/grassland_topdown.png) · [side](renders/quality-audit/pass_terrain_features/grassland_sideprofile.png) | Feature terrain visible 3/3 but effect limited |
| mountain | ⚠️ **C** | [iso](renders/quality-audit/pass_terrain_features/mountain_isometric.png) · [top](renders/quality-audit/pass_terrain_features/mountain_topdown.png) · [side](renders/quality-audit/pass_terrain_features/mountain_sideprofile.png) | Feature terrain visible 3/3 but effect limited |
| coastal | ⚠️ **C** | [iso](renders/quality-audit/pass_terrain_features/coastal_isometric.png) · [top](renders/quality-audit/pass_terrain_features/coastal_topdown.png) · [side](renders/quality-audit/pass_terrain_features/coastal_sideprofile.png) | Feature terrain visible 3/3 but effect limited |
| volcanic | ⚠️ **C** | [iso](renders/quality-audit/pass_terrain_features/volcanic_isometric.png) · [top](renders/quality-audit/pass_terrain_features/volcanic_topdown.png) · [side](renders/quality-audit/pass_terrain_features/volcanic_sideprofile.png) | Feature terrain visible 3/3 but effect limited |
| frozen | ⚠️ **C** | [iso](renders/quality-audit/pass_terrain_features/frozen_isometric.png) · [top](renders/quality-audit/pass_terrain_features/frozen_topdown.png) · [side](renders/quality-audit/pass_terrain_features/frozen_sideprofile.png) | Feature terrain visible 3/3 but effect limited |
| desert | ⚠️ **C** | [iso](renders/quality-audit/pass_terrain_features/desert_isometric.png) · [top](renders/quality-audit/pass_terrain_features/desert_topdown.png) · [side](renders/quality-audit/pass_terrain_features/desert_sideprofile.png) | Feature terrain visible 3/3 but effect limited |

## Scatter / Vegetation Passes

### ⚠️ `emergent_grass` — Grade **C**

**Overall:** 1A/0B/5C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ⚠️ **C** | [iso](renders/quality-audit/emergent_grass/grassland_isometric.png) · [top](renders/quality-audit/emergent_grass/grassland_topdown.png) · [side](renders/quality-audit/emergent_grass/grassland_sideprofile.png) | Scatter active=0, terrain=3/3, variation poor |
| mountain | ⚠️ **C** | [iso](renders/quality-audit/emergent_grass/mountain_isometric.png) · [top](renders/quality-audit/emergent_grass/mountain_topdown.png) · [side](renders/quality-audit/emergent_grass/mountain_sideprofile.png) | Scatter active=0, terrain=3/3, variation poor |
| coastal | ✅ **A** | [iso](renders/quality-audit/emergent_grass/coastal_isometric.png) · [top](renders/quality-audit/emergent_grass/coastal_topdown.png) · [side](renders/quality-audit/emergent_grass/coastal_sideprofile.png) | Scatter: 1 channels with spatial variation, terrain 3/3 |
| volcanic | ⚠️ **C** | [iso](renders/quality-audit/emergent_grass/volcanic_isometric.png) · [top](renders/quality-audit/emergent_grass/volcanic_topdown.png) · [side](renders/quality-audit/emergent_grass/volcanic_sideprofile.png) | Scatter active=0, terrain=3/3, variation poor |
| frozen | ⚠️ **C** | [iso](renders/quality-audit/emergent_grass/frozen_isometric.png) · [top](renders/quality-audit/emergent_grass/frozen_topdown.png) · [side](renders/quality-audit/emergent_grass/frozen_sideprofile.png) | Scatter active=0, terrain=3/3, variation poor |
| desert | ⚠️ **C** | [iso](renders/quality-audit/emergent_grass/desert_isometric.png) · [top](renders/quality-audit/emergent_grass/desert_topdown.png) · [side](renders/quality-audit/emergent_grass/desert_sideprofile.png) | Scatter active=0, terrain=3/3, variation poor |

### ❌ `emit_particle_systems` — Grade **D**

**Overall:** 0F + 6D across biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ❌ **D** | [iso](renders/quality-audit/emit_particle_systems/grassland_isometric.png) · [top](renders/quality-audit/emit_particle_systems/grassland_topdown.png) · [side](renders/quality-audit/emit_particle_systems/grassland_sideprofile.png) | No scatter/density channels active |
| mountain | ❌ **D** | [iso](renders/quality-audit/emit_particle_systems/mountain_isometric.png) · [top](renders/quality-audit/emit_particle_systems/mountain_topdown.png) · [side](renders/quality-audit/emit_particle_systems/mountain_sideprofile.png) | No scatter/density channels active |
| coastal | ❌ **D** | [iso](renders/quality-audit/emit_particle_systems/coastal_isometric.png) · [top](renders/quality-audit/emit_particle_systems/coastal_topdown.png) · [side](renders/quality-audit/emit_particle_systems/coastal_sideprofile.png) | No scatter/density channels active |
| volcanic | ❌ **D** | [iso](renders/quality-audit/emit_particle_systems/volcanic_isometric.png) · [top](renders/quality-audit/emit_particle_systems/volcanic_topdown.png) · [side](renders/quality-audit/emit_particle_systems/volcanic_sideprofile.png) | No scatter/density channels active |
| frozen | ❌ **D** | [iso](renders/quality-audit/emit_particle_systems/frozen_isometric.png) · [top](renders/quality-audit/emit_particle_systems/frozen_topdown.png) · [side](renders/quality-audit/emit_particle_systems/frozen_sideprofile.png) | No scatter/density channels active |
| desert | ❌ **D** | [iso](renders/quality-audit/emit_particle_systems/desert_isometric.png) · [top](renders/quality-audit/emit_particle_systems/desert_topdown.png) · [side](renders/quality-audit/emit_particle_systems/desert_sideprofile.png) | No scatter/density channels active |

### ✅ `pass_procedural_grass` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/pass_procedural_grass/grassland_isometric.png) · [top](renders/quality-audit/pass_procedural_grass/grassland_topdown.png) · [side](renders/quality-audit/pass_procedural_grass/grassland_sideprofile.png) | Scatter: 1 channels with spatial variation, terrain 3/3 |
| mountain | ✅ **A** | [iso](renders/quality-audit/pass_procedural_grass/mountain_isometric.png) · [top](renders/quality-audit/pass_procedural_grass/mountain_topdown.png) · [side](renders/quality-audit/pass_procedural_grass/mountain_sideprofile.png) | Scatter: 1 channels with spatial variation, terrain 3/3 |
| coastal | ✅ **A** | [iso](renders/quality-audit/pass_procedural_grass/coastal_isometric.png) · [top](renders/quality-audit/pass_procedural_grass/coastal_topdown.png) · [side](renders/quality-audit/pass_procedural_grass/coastal_sideprofile.png) | Scatter: 1 channels with spatial variation, terrain 3/3 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/pass_procedural_grass/volcanic_isometric.png) · [top](renders/quality-audit/pass_procedural_grass/volcanic_topdown.png) · [side](renders/quality-audit/pass_procedural_grass/volcanic_sideprofile.png) | Scatter: 1 channels with spatial variation, terrain 3/3 |
| frozen | ✅ **A** | [iso](renders/quality-audit/pass_procedural_grass/frozen_isometric.png) · [top](renders/quality-audit/pass_procedural_grass/frozen_topdown.png) · [side](renders/quality-audit/pass_procedural_grass/frozen_sideprofile.png) | Scatter: 1 channels with spatial variation, terrain 3/3 |
| desert | ✅ **A** | [iso](renders/quality-audit/pass_procedural_grass/desert_isometric.png) · [top](renders/quality-audit/pass_procedural_grass/desert_topdown.png) · [side](renders/quality-audit/pass_procedural_grass/desert_sideprofile.png) | Scatter: 1 channels with spatial variation, terrain 3/3 |

### ✅ `scatter_intelligent` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/scatter_intelligent/grassland_isometric.png) · [top](renders/quality-audit/scatter_intelligent/grassland_topdown.png) · [side](renders/quality-audit/scatter_intelligent/grassland_sideprofile.png) | Scatter: 1 channels with spatial variation, terrain 3/3 |
| mountain | ✅ **A** | [iso](renders/quality-audit/scatter_intelligent/mountain_isometric.png) · [top](renders/quality-audit/scatter_intelligent/mountain_topdown.png) · [side](renders/quality-audit/scatter_intelligent/mountain_sideprofile.png) | Scatter: 1 channels with spatial variation, terrain 3/3 |
| coastal | ✅ **A** | [iso](renders/quality-audit/scatter_intelligent/coastal_isometric.png) · [top](renders/quality-audit/scatter_intelligent/coastal_topdown.png) · [side](renders/quality-audit/scatter_intelligent/coastal_sideprofile.png) | Scatter: 1 channels with spatial variation, terrain 3/3 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/scatter_intelligent/volcanic_isometric.png) · [top](renders/quality-audit/scatter_intelligent/volcanic_topdown.png) · [side](renders/quality-audit/scatter_intelligent/volcanic_sideprofile.png) | Scatter: 1 channels with spatial variation, terrain 3/3 |
| frozen | ✅ **A** | [iso](renders/quality-audit/scatter_intelligent/frozen_isometric.png) · [top](renders/quality-audit/scatter_intelligent/frozen_topdown.png) · [side](renders/quality-audit/scatter_intelligent/frozen_sideprofile.png) | Scatter: 1 channels with spatial variation, terrain 3/3 |
| desert | ✅ **A** | [iso](renders/quality-audit/scatter_intelligent/desert_isometric.png) · [top](renders/quality-audit/scatter_intelligent/desert_topdown.png) · [side](renders/quality-audit/scatter_intelligent/desert_sideprofile.png) | Scatter: 1 channels with spatial variation, terrain 3/3 |

### ⚠️ `vegetation_depth` — Grade **C**

**Overall:** 0A/0B/6C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ⚠️ **C** | [iso](renders/quality-audit/vegetation_depth/grassland_isometric.png) · [top](renders/quality-audit/vegetation_depth/grassland_topdown.png) · [side](renders/quality-audit/vegetation_depth/grassland_sideprofile.png) | Scatter active=0, terrain=3/3, variation poor |
| mountain | ⚠️ **C** | [iso](renders/quality-audit/vegetation_depth/mountain_isometric.png) · [top](renders/quality-audit/vegetation_depth/mountain_topdown.png) · [side](renders/quality-audit/vegetation_depth/mountain_sideprofile.png) | Scatter active=0, terrain=3/3, variation poor |
| coastal | ⚠️ **C** | [iso](renders/quality-audit/vegetation_depth/coastal_isometric.png) · [top](renders/quality-audit/vegetation_depth/coastal_topdown.png) · [side](renders/quality-audit/vegetation_depth/coastal_sideprofile.png) | Scatter active=0, terrain=3/3, variation poor |
| volcanic | ⚠️ **C** | [iso](renders/quality-audit/vegetation_depth/volcanic_isometric.png) · [top](renders/quality-audit/vegetation_depth/volcanic_topdown.png) · [side](renders/quality-audit/vegetation_depth/volcanic_sideprofile.png) | Scatter active=0, terrain=3/3, variation poor |
| frozen | ⚠️ **C** | [iso](renders/quality-audit/vegetation_depth/frozen_isometric.png) · [top](renders/quality-audit/vegetation_depth/frozen_topdown.png) · [side](renders/quality-audit/vegetation_depth/frozen_sideprofile.png) | Scatter active=0, terrain=3/3, variation poor |
| desert | ⚠️ **C** | [iso](renders/quality-audit/vegetation_depth/desert_isometric.png) · [top](renders/quality-audit/vegetation_depth/desert_topdown.png) · [side](renders/quality-audit/vegetation_depth/desert_sideprofile.png) | Scatter active=0, terrain=3/3, variation poor |

## Material & Rendering Passes

### ✅ `macro_color` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/macro_color/grassland_isometric.png) · [top](renders/quality-audit/macro_color/grassland_topdown.png) · [side](renders/quality-audit/macro_color/grassland_sideprofile.png) | Material: 1 channels, coverage=100% |
| mountain | ✅ **A** | [iso](renders/quality-audit/macro_color/mountain_isometric.png) · [top](renders/quality-audit/macro_color/mountain_topdown.png) · [side](renders/quality-audit/macro_color/mountain_sideprofile.png) | Material: 1 channels, coverage=100% |
| coastal | ✅ **A** | [iso](renders/quality-audit/macro_color/coastal_isometric.png) · [top](renders/quality-audit/macro_color/coastal_topdown.png) · [side](renders/quality-audit/macro_color/coastal_sideprofile.png) | Material: 1 channels, coverage=100% |
| volcanic | ✅ **A** | [iso](renders/quality-audit/macro_color/volcanic_isometric.png) · [top](renders/quality-audit/macro_color/volcanic_topdown.png) · [side](renders/quality-audit/macro_color/volcanic_sideprofile.png) | Material: 1 channels, coverage=100% |
| frozen | ✅ **A** | [iso](renders/quality-audit/macro_color/frozen_isometric.png) · [top](renders/quality-audit/macro_color/frozen_topdown.png) · [side](renders/quality-audit/macro_color/frozen_sideprofile.png) | Material: 1 channels, coverage=100% |
| desert | ✅ **A** | [iso](renders/quality-audit/macro_color/desert_isometric.png) · [top](renders/quality-audit/macro_color/desert_topdown.png) · [side](renders/quality-audit/macro_color/desert_sideprofile.png) | Material: 1 channels, coverage=100% |

### ✅ `materials_v2` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/materials_v2/grassland_isometric.png) · [top](renders/quality-audit/materials_v2/grassland_topdown.png) · [side](renders/quality-audit/materials_v2/grassland_sideprofile.png) | Material: 5 channels, coverage=99% |
| mountain | ✅ **A** | [iso](renders/quality-audit/materials_v2/mountain_isometric.png) · [top](renders/quality-audit/materials_v2/mountain_topdown.png) · [side](renders/quality-audit/materials_v2/mountain_sideprofile.png) | Material: 5 channels, coverage=100% |
| coastal | ✅ **A** | [iso](renders/quality-audit/materials_v2/coastal_isometric.png) · [top](renders/quality-audit/materials_v2/coastal_topdown.png) · [side](renders/quality-audit/materials_v2/coastal_sideprofile.png) | Material: 5 channels, coverage=98% |
| volcanic | ✅ **A** | [iso](renders/quality-audit/materials_v2/volcanic_isometric.png) · [top](renders/quality-audit/materials_v2/volcanic_topdown.png) · [side](renders/quality-audit/materials_v2/volcanic_sideprofile.png) | Material: 5 channels, coverage=100% |
| frozen | ✅ **A** | [iso](renders/quality-audit/materials_v2/frozen_isometric.png) · [top](renders/quality-audit/materials_v2/frozen_topdown.png) · [side](renders/quality-audit/materials_v2/frozen_sideprofile.png) | Material: 5 channels, coverage=99% |
| desert | ✅ **A** | [iso](renders/quality-audit/materials_v2/desert_isometric.png) · [top](renders/quality-audit/materials_v2/desert_topdown.png) · [side](renders/quality-audit/materials_v2/desert_sideprofile.png) | Material: 5 channels, coverage=99% |

### ✅ `materials_v2_volcanic` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/materials_v2_volcanic/grassland_isometric.png) · [top](renders/quality-audit/materials_v2_volcanic/grassland_topdown.png) · [side](renders/quality-audit/materials_v2_volcanic/grassland_sideprofile.png) | Material: 4 channels, coverage=100% |
| mountain | ✅ **A** | [iso](renders/quality-audit/materials_v2_volcanic/mountain_isometric.png) · [top](renders/quality-audit/materials_v2_volcanic/mountain_topdown.png) · [side](renders/quality-audit/materials_v2_volcanic/mountain_sideprofile.png) | Material: 4 channels, coverage=100% |
| coastal | ✅ **A** | [iso](renders/quality-audit/materials_v2_volcanic/coastal_isometric.png) · [top](renders/quality-audit/materials_v2_volcanic/coastal_topdown.png) · [side](renders/quality-audit/materials_v2_volcanic/coastal_sideprofile.png) | Material: 4 channels, coverage=100% |
| volcanic | ✅ **A** | [iso](renders/quality-audit/materials_v2_volcanic/volcanic_isometric.png) · [top](renders/quality-audit/materials_v2_volcanic/volcanic_topdown.png) · [side](renders/quality-audit/materials_v2_volcanic/volcanic_sideprofile.png) | Material: 4 channels, coverage=100% |
| frozen | ✅ **A** | [iso](renders/quality-audit/materials_v2_volcanic/frozen_isometric.png) · [top](renders/quality-audit/materials_v2_volcanic/frozen_topdown.png) · [side](renders/quality-audit/materials_v2_volcanic/frozen_sideprofile.png) | Material: 4 channels, coverage=100% |
| desert | ✅ **A** | [iso](renders/quality-audit/materials_v2_volcanic/desert_isometric.png) · [top](renders/quality-audit/materials_v2_volcanic/desert_topdown.png) · [side](renders/quality-audit/materials_v2_volcanic/desert_sideprofile.png) | Material: 4 channels, coverage=100% |

### ✅ `multiscale_breakup` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/multiscale_breakup/grassland_isometric.png) · [top](renders/quality-audit/multiscale_breakup/grassland_topdown.png) · [side](renders/quality-audit/multiscale_breakup/grassland_sideprofile.png) | Material: 1 channels, coverage=100% |
| mountain | ✅ **A** | [iso](renders/quality-audit/multiscale_breakup/mountain_isometric.png) · [top](renders/quality-audit/multiscale_breakup/mountain_topdown.png) · [side](renders/quality-audit/multiscale_breakup/mountain_sideprofile.png) | Material: 1 channels, coverage=100% |
| coastal | ✅ **A** | [iso](renders/quality-audit/multiscale_breakup/coastal_isometric.png) · [top](renders/quality-audit/multiscale_breakup/coastal_topdown.png) · [side](renders/quality-audit/multiscale_breakup/coastal_sideprofile.png) | Material: 1 channels, coverage=100% |
| volcanic | ✅ **A** | [iso](renders/quality-audit/multiscale_breakup/volcanic_isometric.png) · [top](renders/quality-audit/multiscale_breakup/volcanic_topdown.png) · [side](renders/quality-audit/multiscale_breakup/volcanic_sideprofile.png) | Material: 1 channels, coverage=100% |
| frozen | ✅ **A** | [iso](renders/quality-audit/multiscale_breakup/frozen_isometric.png) · [top](renders/quality-audit/multiscale_breakup/frozen_topdown.png) · [side](renders/quality-audit/multiscale_breakup/frozen_sideprofile.png) | Material: 1 channels, coverage=100% |
| desert | ✅ **A** | [iso](renders/quality-audit/multiscale_breakup/desert_isometric.png) · [top](renders/quality-audit/multiscale_breakup/desert_topdown.png) · [side](renders/quality-audit/multiscale_breakup/desert_sideprofile.png) | Material: 1 channels, coverage=100% |

### ✅ `quixel_ingest` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/quixel_ingest/grassland_isometric.png) · [top](renders/quality-audit/quixel_ingest/grassland_topdown.png) · [side](renders/quality-audit/quixel_ingest/grassland_sideprofile.png) | Material: 1 channels, coverage=100% |
| mountain | ✅ **A** | [iso](renders/quality-audit/quixel_ingest/mountain_isometric.png) · [top](renders/quality-audit/quixel_ingest/mountain_topdown.png) · [side](renders/quality-audit/quixel_ingest/mountain_sideprofile.png) | Material: 1 channels, coverage=100% |
| coastal | ✅ **A** | [iso](renders/quality-audit/quixel_ingest/coastal_isometric.png) · [top](renders/quality-audit/quixel_ingest/coastal_topdown.png) · [side](renders/quality-audit/quixel_ingest/coastal_sideprofile.png) | Material: 1 channels, coverage=100% |
| volcanic | ✅ **A** | [iso](renders/quality-audit/quixel_ingest/volcanic_isometric.png) · [top](renders/quality-audit/quixel_ingest/volcanic_topdown.png) · [side](renders/quality-audit/quixel_ingest/volcanic_sideprofile.png) | Material: 1 channels, coverage=100% |
| frozen | ✅ **A** | [iso](renders/quality-audit/quixel_ingest/frozen_isometric.png) · [top](renders/quality-audit/quixel_ingest/frozen_topdown.png) · [side](renders/quality-audit/quixel_ingest/frozen_sideprofile.png) | Material: 1 channels, coverage=100% |
| desert | ✅ **A** | [iso](renders/quality-audit/quixel_ingest/desert_isometric.png) · [top](renders/quality-audit/quixel_ingest/desert_topdown.png) · [side](renders/quality-audit/quixel_ingest/desert_sideprofile.png) | Material: 1 channels, coverage=100% |

### ✅ `roughness_driver` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/roughness_driver/grassland_isometric.png) · [top](renders/quality-audit/roughness_driver/grassland_topdown.png) · [side](renders/quality-audit/roughness_driver/grassland_sideprofile.png) | Material: 1 channels, coverage=100% |
| mountain | ✅ **A** | [iso](renders/quality-audit/roughness_driver/mountain_isometric.png) · [top](renders/quality-audit/roughness_driver/mountain_topdown.png) · [side](renders/quality-audit/roughness_driver/mountain_sideprofile.png) | Material: 1 channels, coverage=100% |
| coastal | ✅ **A** | [iso](renders/quality-audit/roughness_driver/coastal_isometric.png) · [top](renders/quality-audit/roughness_driver/coastal_topdown.png) · [side](renders/quality-audit/roughness_driver/coastal_sideprofile.png) | Material: 1 channels, coverage=100% |
| volcanic | ✅ **A** | [iso](renders/quality-audit/roughness_driver/volcanic_isometric.png) · [top](renders/quality-audit/roughness_driver/volcanic_topdown.png) · [side](renders/quality-audit/roughness_driver/volcanic_sideprofile.png) | Material: 1 channels, coverage=100% |
| frozen | ✅ **A** | [iso](renders/quality-audit/roughness_driver/frozen_isometric.png) · [top](renders/quality-audit/roughness_driver/frozen_topdown.png) · [side](renders/quality-audit/roughness_driver/frozen_sideprofile.png) | Material: 1 channels, coverage=100% |
| desert | ✅ **A** | [iso](renders/quality-audit/roughness_driver/desert_isometric.png) · [top](renders/quality-audit/roughness_driver/desert_topdown.png) · [side](renders/quality-audit/roughness_driver/desert_sideprofile.png) | Material: 1 channels, coverage=100% |

### ✅ `stochastic_shader` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/stochastic_shader/grassland_isometric.png) · [top](renders/quality-audit/stochastic_shader/grassland_topdown.png) · [side](renders/quality-audit/stochastic_shader/grassland_sideprofile.png) | Material: 1 channels, coverage=100% |
| mountain | ✅ **A** | [iso](renders/quality-audit/stochastic_shader/mountain_isometric.png) · [top](renders/quality-audit/stochastic_shader/mountain_topdown.png) · [side](renders/quality-audit/stochastic_shader/mountain_sideprofile.png) | Material: 1 channels, coverage=100% |
| coastal | ✅ **A** | [iso](renders/quality-audit/stochastic_shader/coastal_isometric.png) · [top](renders/quality-audit/stochastic_shader/coastal_topdown.png) · [side](renders/quality-audit/stochastic_shader/coastal_sideprofile.png) | Material: 1 channels, coverage=100% |
| volcanic | ✅ **A** | [iso](renders/quality-audit/stochastic_shader/volcanic_isometric.png) · [top](renders/quality-audit/stochastic_shader/volcanic_topdown.png) · [side](renders/quality-audit/stochastic_shader/volcanic_sideprofile.png) | Material: 1 channels, coverage=100% |
| frozen | ✅ **A** | [iso](renders/quality-audit/stochastic_shader/frozen_isometric.png) · [top](renders/quality-audit/stochastic_shader/frozen_topdown.png) · [side](renders/quality-audit/stochastic_shader/frozen_sideprofile.png) | Material: 1 channels, coverage=100% |
| desert | ✅ **A** | [iso](renders/quality-audit/stochastic_shader/desert_isometric.png) · [top](renders/quality-audit/stochastic_shader/desert_topdown.png) · [side](renders/quality-audit/stochastic_shader/desert_sideprofile.png) | Material: 1 channels, coverage=100% |

## Gameplay Zone Passes

### ✅ `audio_zones` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/audio_zones/grassland_isometric.png) · [top](renders/quality-audit/audio_zones/grassland_topdown.png) · [side](renders/quality-audit/audio_zones/grassland_sideprofile.png) | Gameplay: 1 channels active, terrain 3/3 |
| mountain | ✅ **A** | [iso](renders/quality-audit/audio_zones/mountain_isometric.png) · [top](renders/quality-audit/audio_zones/mountain_topdown.png) · [side](renders/quality-audit/audio_zones/mountain_sideprofile.png) | Gameplay: 1 channels active, terrain 3/3 |
| coastal | ✅ **A** | [iso](renders/quality-audit/audio_zones/coastal_isometric.png) · [top](renders/quality-audit/audio_zones/coastal_topdown.png) · [side](renders/quality-audit/audio_zones/coastal_sideprofile.png) | Gameplay: 1 channels active, terrain 3/3 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/audio_zones/volcanic_isometric.png) · [top](renders/quality-audit/audio_zones/volcanic_topdown.png) · [side](renders/quality-audit/audio_zones/volcanic_sideprofile.png) | Gameplay: 1 channels active, terrain 3/3 |
| frozen | ✅ **A** | [iso](renders/quality-audit/audio_zones/frozen_isometric.png) · [top](renders/quality-audit/audio_zones/frozen_topdown.png) · [side](renders/quality-audit/audio_zones/frozen_sideprofile.png) | Gameplay: 1 channels active, terrain 3/3 |
| desert | ✅ **A** | [iso](renders/quality-audit/audio_zones/desert_isometric.png) · [top](renders/quality-audit/audio_zones/desert_topdown.png) · [side](renders/quality-audit/audio_zones/desert_sideprofile.png) | Gameplay: 1 channels active, terrain 3/3 |

### ✅ `cloud_shadow` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/cloud_shadow/grassland_isometric.png) · [top](renders/quality-audit/cloud_shadow/grassland_topdown.png) · [side](renders/quality-audit/cloud_shadow/grassland_sideprofile.png) | Gameplay: 2 channels active, terrain 3/3 |
| mountain | ✅ **A** | [iso](renders/quality-audit/cloud_shadow/mountain_isometric.png) · [top](renders/quality-audit/cloud_shadow/mountain_topdown.png) · [side](renders/quality-audit/cloud_shadow/mountain_sideprofile.png) | Gameplay: 2 channels active, terrain 3/3 |
| coastal | ✅ **A** | [iso](renders/quality-audit/cloud_shadow/coastal_isometric.png) · [top](renders/quality-audit/cloud_shadow/coastal_topdown.png) · [side](renders/quality-audit/cloud_shadow/coastal_sideprofile.png) | Gameplay: 2 channels active, terrain 3/3 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/cloud_shadow/volcanic_isometric.png) · [top](renders/quality-audit/cloud_shadow/volcanic_topdown.png) · [side](renders/quality-audit/cloud_shadow/volcanic_sideprofile.png) | Gameplay: 2 channels active, terrain 3/3 |
| frozen | ✅ **A** | [iso](renders/quality-audit/cloud_shadow/frozen_isometric.png) · [top](renders/quality-audit/cloud_shadow/frozen_topdown.png) · [side](renders/quality-audit/cloud_shadow/frozen_sideprofile.png) | Gameplay: 2 channels active, terrain 3/3 |
| desert | ✅ **A** | [iso](renders/quality-audit/cloud_shadow/desert_isometric.png) · [top](renders/quality-audit/cloud_shadow/desert_topdown.png) · [side](renders/quality-audit/cloud_shadow/desert_sideprofile.png) | Gameplay: 2 channels active, terrain 3/3 |

### 🟡 `decals` — Grade **B**

**Overall:** 0A/6B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | 🟡 **B** | [iso](renders/quality-audit/decals/grassland_isometric.png) · [top](renders/quality-audit/decals/grassland_topdown.png) · [side](renders/quality-audit/decals/grassland_sideprofile.png) | Gameplay: terrain=3/3, active_channels=0 |
| mountain | 🟡 **B** | [iso](renders/quality-audit/decals/mountain_isometric.png) · [top](renders/quality-audit/decals/mountain_topdown.png) · [side](renders/quality-audit/decals/mountain_sideprofile.png) | Gameplay: terrain=3/3, active_channels=0 |
| coastal | 🟡 **B** | [iso](renders/quality-audit/decals/coastal_isometric.png) · [top](renders/quality-audit/decals/coastal_topdown.png) · [side](renders/quality-audit/decals/coastal_sideprofile.png) | Gameplay: terrain=3/3, active_channels=0 |
| volcanic | 🟡 **B** | [iso](renders/quality-audit/decals/volcanic_isometric.png) · [top](renders/quality-audit/decals/volcanic_topdown.png) · [side](renders/quality-audit/decals/volcanic_sideprofile.png) | Gameplay: terrain=3/3, active_channels=0 |
| frozen | 🟡 **B** | [iso](renders/quality-audit/decals/frozen_isometric.png) · [top](renders/quality-audit/decals/frozen_topdown.png) · [side](renders/quality-audit/decals/frozen_sideprofile.png) | Gameplay: terrain=3/3, active_channels=0 |
| desert | 🟡 **B** | [iso](renders/quality-audit/decals/desert_isometric.png) · [top](renders/quality-audit/decals/desert_topdown.png) · [side](renders/quality-audit/decals/desert_sideprofile.png) | Gameplay: terrain=3/3, active_channels=0 |

### ✅ `gameplay_zones` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/gameplay_zones/grassland_isometric.png) · [top](renders/quality-audit/gameplay_zones/grassland_topdown.png) · [side](renders/quality-audit/gameplay_zones/grassland_sideprofile.png) | Gameplay: 1 channels active, terrain 3/3 |
| mountain | ✅ **A** | [iso](renders/quality-audit/gameplay_zones/mountain_isometric.png) · [top](renders/quality-audit/gameplay_zones/mountain_topdown.png) · [side](renders/quality-audit/gameplay_zones/mountain_sideprofile.png) | Gameplay: 1 channels active, terrain 3/3 |
| coastal | ✅ **A** | [iso](renders/quality-audit/gameplay_zones/coastal_isometric.png) · [top](renders/quality-audit/gameplay_zones/coastal_topdown.png) · [side](renders/quality-audit/gameplay_zones/coastal_sideprofile.png) | Gameplay: 1 channels active, terrain 3/3 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/gameplay_zones/volcanic_isometric.png) · [top](renders/quality-audit/gameplay_zones/volcanic_topdown.png) · [side](renders/quality-audit/gameplay_zones/volcanic_sideprofile.png) | Gameplay: 1 channels active, terrain 3/3 |
| frozen | ✅ **A** | [iso](renders/quality-audit/gameplay_zones/frozen_isometric.png) · [top](renders/quality-audit/gameplay_zones/frozen_topdown.png) · [side](renders/quality-audit/gameplay_zones/frozen_sideprofile.png) | Gameplay: 1 channels active, terrain 3/3 |
| desert | ✅ **A** | [iso](renders/quality-audit/gameplay_zones/desert_isometric.png) · [top](renders/quality-audit/gameplay_zones/desert_topdown.png) · [side](renders/quality-audit/gameplay_zones/desert_sideprofile.png) | Gameplay: 1 channels active, terrain 3/3 |

### ✅ `navmesh` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/navmesh/grassland_isometric.png) · [top](renders/quality-audit/navmesh/grassland_topdown.png) · [side](renders/quality-audit/navmesh/grassland_sideprofile.png) | Gameplay: 2 channels active, terrain 3/3 |
| mountain | ✅ **A** | [iso](renders/quality-audit/navmesh/mountain_isometric.png) · [top](renders/quality-audit/navmesh/mountain_topdown.png) · [side](renders/quality-audit/navmesh/mountain_sideprofile.png) | Gameplay: 2 channels active, terrain 3/3 |
| coastal | ✅ **A** | [iso](renders/quality-audit/navmesh/coastal_isometric.png) · [top](renders/quality-audit/navmesh/coastal_topdown.png) · [side](renders/quality-audit/navmesh/coastal_sideprofile.png) | Gameplay: 2 channels active, terrain 3/3 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/navmesh/volcanic_isometric.png) · [top](renders/quality-audit/navmesh/volcanic_topdown.png) · [side](renders/quality-audit/navmesh/volcanic_sideprofile.png) | Gameplay: 2 channels active, terrain 3/3 |
| frozen | ✅ **A** | [iso](renders/quality-audit/navmesh/frozen_isometric.png) · [top](renders/quality-audit/navmesh/frozen_topdown.png) · [side](renders/quality-audit/navmesh/frozen_sideprofile.png) | Gameplay: 2 channels active, terrain 3/3 |
| desert | ✅ **A** | [iso](renders/quality-audit/navmesh/desert_isometric.png) · [top](renders/quality-audit/navmesh/desert_topdown.png) · [side](renders/quality-audit/navmesh/desert_sideprofile.png) | Gameplay: 2 channels active, terrain 3/3 |

### ✅ `pass_navmesh_export` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/pass_navmesh_export/grassland_isometric.png) · [top](renders/quality-audit/pass_navmesh_export/grassland_topdown.png) · [side](renders/quality-audit/pass_navmesh_export/grassland_sideprofile.png) | Gameplay: 2 channels active, terrain 3/3 |
| mountain | ✅ **A** | [iso](renders/quality-audit/pass_navmesh_export/mountain_isometric.png) · [top](renders/quality-audit/pass_navmesh_export/mountain_topdown.png) · [side](renders/quality-audit/pass_navmesh_export/mountain_sideprofile.png) | Gameplay: 2 channels active, terrain 3/3 |
| coastal | ✅ **A** | [iso](renders/quality-audit/pass_navmesh_export/coastal_isometric.png) · [top](renders/quality-audit/pass_navmesh_export/coastal_topdown.png) · [side](renders/quality-audit/pass_navmesh_export/coastal_sideprofile.png) | Gameplay: 2 channels active, terrain 3/3 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/pass_navmesh_export/volcanic_isometric.png) · [top](renders/quality-audit/pass_navmesh_export/volcanic_topdown.png) · [side](renders/quality-audit/pass_navmesh_export/volcanic_sideprofile.png) | Gameplay: 2 channels active, terrain 3/3 |
| frozen | ✅ **A** | [iso](renders/quality-audit/pass_navmesh_export/frozen_isometric.png) · [top](renders/quality-audit/pass_navmesh_export/frozen_topdown.png) · [side](renders/quality-audit/pass_navmesh_export/frozen_sideprofile.png) | Gameplay: 2 channels active, terrain 3/3 |
| desert | ✅ **A** | [iso](renders/quality-audit/pass_navmesh_export/desert_isometric.png) · [top](renders/quality-audit/pass_navmesh_export/desert_topdown.png) · [side](renders/quality-audit/pass_navmesh_export/desert_sideprofile.png) | Gameplay: 2 channels active, terrain 3/3 |

### ✅ `pass_road_network` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/pass_road_network/grassland_isometric.png) · [top](renders/quality-audit/pass_road_network/grassland_topdown.png) · [side](renders/quality-audit/pass_road_network/grassland_sideprofile.png) | Gameplay: 2 channels active, terrain 3/3 |
| mountain | ✅ **A** | [iso](renders/quality-audit/pass_road_network/mountain_isometric.png) · [top](renders/quality-audit/pass_road_network/mountain_topdown.png) · [side](renders/quality-audit/pass_road_network/mountain_sideprofile.png) | Gameplay: 2 channels active, terrain 3/3 |
| coastal | ✅ **A** | [iso](renders/quality-audit/pass_road_network/coastal_isometric.png) · [top](renders/quality-audit/pass_road_network/coastal_topdown.png) · [side](renders/quality-audit/pass_road_network/coastal_sideprofile.png) | Gameplay: 2 channels active, terrain 3/3 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/pass_road_network/volcanic_isometric.png) · [top](renders/quality-audit/pass_road_network/volcanic_topdown.png) · [side](renders/quality-audit/pass_road_network/volcanic_sideprofile.png) | Gameplay: 2 channels active, terrain 3/3 |
| frozen | ✅ **A** | [iso](renders/quality-audit/pass_road_network/frozen_isometric.png) · [top](renders/quality-audit/pass_road_network/frozen_topdown.png) · [side](renders/quality-audit/pass_road_network/frozen_sideprofile.png) | Gameplay: 2 channels active, terrain 3/3 |
| desert | ✅ **A** | [iso](renders/quality-audit/pass_road_network/desert_isometric.png) · [top](renders/quality-audit/pass_road_network/desert_topdown.png) · [side](renders/quality-audit/pass_road_network/desert_sideprofile.png) | Gameplay: 2 channels active, terrain 3/3 |

### 🟡 `wildlife_zones` — Grade **B**

**Overall:** 0A/6B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | 🟡 **B** | [iso](renders/quality-audit/wildlife_zones/grassland_isometric.png) · [top](renders/quality-audit/wildlife_zones/grassland_topdown.png) · [side](renders/quality-audit/wildlife_zones/grassland_sideprofile.png) | Gameplay: terrain=3/3, active_channels=0 |
| mountain | 🟡 **B** | [iso](renders/quality-audit/wildlife_zones/mountain_isometric.png) · [top](renders/quality-audit/wildlife_zones/mountain_topdown.png) · [side](renders/quality-audit/wildlife_zones/mountain_sideprofile.png) | Gameplay: terrain=3/3, active_channels=0 |
| coastal | 🟡 **B** | [iso](renders/quality-audit/wildlife_zones/coastal_isometric.png) · [top](renders/quality-audit/wildlife_zones/coastal_topdown.png) · [side](renders/quality-audit/wildlife_zones/coastal_sideprofile.png) | Gameplay: terrain=3/3, active_channels=0 |
| volcanic | 🟡 **B** | [iso](renders/quality-audit/wildlife_zones/volcanic_isometric.png) · [top](renders/quality-audit/wildlife_zones/volcanic_topdown.png) · [side](renders/quality-audit/wildlife_zones/volcanic_sideprofile.png) | Gameplay: terrain=3/3, active_channels=0 |
| frozen | 🟡 **B** | [iso](renders/quality-audit/wildlife_zones/frozen_isometric.png) · [top](renders/quality-audit/wildlife_zones/frozen_topdown.png) · [side](renders/quality-audit/wildlife_zones/frozen_sideprofile.png) | Gameplay: terrain=3/3, active_channels=0 |
| desert | 🟡 **B** | [iso](renders/quality-audit/wildlife_zones/desert_isometric.png) · [top](renders/quality-audit/wildlife_zones/desert_topdown.png) · [side](renders/quality-audit/wildlife_zones/desert_sideprofile.png) | Gameplay: terrain=3/3, active_channels=0 |

### ✅ `wind_field` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/wind_field/grassland_isometric.png) · [top](renders/quality-audit/wind_field/grassland_topdown.png) · [side](renders/quality-audit/wind_field/grassland_sideprofile.png) | Gameplay: 1 channels active, terrain 3/3 |
| mountain | ✅ **A** | [iso](renders/quality-audit/wind_field/mountain_isometric.png) · [top](renders/quality-audit/wind_field/mountain_topdown.png) · [side](renders/quality-audit/wind_field/mountain_sideprofile.png) | Gameplay: 1 channels active, terrain 3/3 |
| coastal | ✅ **A** | [iso](renders/quality-audit/wind_field/coastal_isometric.png) · [top](renders/quality-audit/wind_field/coastal_topdown.png) · [side](renders/quality-audit/wind_field/coastal_sideprofile.png) | Gameplay: 1 channels active, terrain 3/3 |
| volcanic | ✅ **A** | [iso](renders/quality-audit/wind_field/volcanic_isometric.png) · [top](renders/quality-audit/wind_field/volcanic_topdown.png) · [side](renders/quality-audit/wind_field/volcanic_sideprofile.png) | Gameplay: 1 channels active, terrain 3/3 |
| frozen | ✅ **A** | [iso](renders/quality-audit/wind_field/frozen_isometric.png) · [top](renders/quality-audit/wind_field/frozen_topdown.png) · [side](renders/quality-audit/wind_field/frozen_sideprofile.png) | Gameplay: 1 channels active, terrain 3/3 |
| desert | ✅ **A** | [iso](renders/quality-audit/wind_field/desert_isometric.png) · [top](renders/quality-audit/wind_field/desert_topdown.png) · [side](renders/quality-audit/wind_field/desert_sideprofile.png) | Gameplay: 1 channels active, terrain 3/3 |

## Export & Preparation Passes

### ✅ `fog_masks` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/fog_masks/grassland_isometric.png) · [top](renders/quality-audit/fog_masks/grassland_topdown.png) · [side](renders/quality-audit/fog_masks/grassland_sideprofile.png) | Export: 1 channels active, terrain visible |
| mountain | ✅ **A** | [iso](renders/quality-audit/fog_masks/mountain_isometric.png) · [top](renders/quality-audit/fog_masks/mountain_topdown.png) · [side](renders/quality-audit/fog_masks/mountain_sideprofile.png) | Export: 1 channels active, terrain visible |
| coastal | ✅ **A** | [iso](renders/quality-audit/fog_masks/coastal_isometric.png) · [top](renders/quality-audit/fog_masks/coastal_topdown.png) · [side](renders/quality-audit/fog_masks/coastal_sideprofile.png) | Export: 1 channels active, terrain visible |
| volcanic | ✅ **A** | [iso](renders/quality-audit/fog_masks/volcanic_isometric.png) · [top](renders/quality-audit/fog_masks/volcanic_topdown.png) · [side](renders/quality-audit/fog_masks/volcanic_sideprofile.png) | Export: 1 channels active, terrain visible |
| frozen | ✅ **A** | [iso](renders/quality-audit/fog_masks/frozen_isometric.png) · [top](renders/quality-audit/fog_masks/frozen_topdown.png) · [side](renders/quality-audit/fog_masks/frozen_sideprofile.png) | Export: 1 channels active, terrain visible |
| desert | ✅ **A** | [iso](renders/quality-audit/fog_masks/desert_isometric.png) · [top](renders/quality-audit/fog_masks/desert_topdown.png) · [side](renders/quality-audit/fog_masks/desert_sideprofile.png) | Export: 1 channels active, terrain visible |

### ⚠️ `god_ray_hints` — Grade **C**

**Overall:** 0A/0B/6C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ⚠️ **C** | [iso](renders/quality-audit/god_ray_hints/grassland_isometric.png) · [top](renders/quality-audit/god_ray_hints/grassland_topdown.png) · [side](renders/quality-audit/god_ray_hints/grassland_sideprofile.png) | No export channels captured — pass may write files externally |
| mountain | ⚠️ **C** | [iso](renders/quality-audit/god_ray_hints/mountain_isometric.png) · [top](renders/quality-audit/god_ray_hints/mountain_topdown.png) · [side](renders/quality-audit/god_ray_hints/mountain_sideprofile.png) | No export channels captured — pass may write files externally |
| coastal | ⚠️ **C** | [iso](renders/quality-audit/god_ray_hints/coastal_isometric.png) · [top](renders/quality-audit/god_ray_hints/coastal_topdown.png) · [side](renders/quality-audit/god_ray_hints/coastal_sideprofile.png) | No export channels captured — pass may write files externally |
| volcanic | ⚠️ **C** | [iso](renders/quality-audit/god_ray_hints/volcanic_isometric.png) · [top](renders/quality-audit/god_ray_hints/volcanic_topdown.png) · [side](renders/quality-audit/god_ray_hints/volcanic_sideprofile.png) | No export channels captured — pass may write files externally |
| frozen | ⚠️ **C** | [iso](renders/quality-audit/god_ray_hints/frozen_isometric.png) · [top](renders/quality-audit/god_ray_hints/frozen_topdown.png) · [side](renders/quality-audit/god_ray_hints/frozen_sideprofile.png) | No export channels captured — pass may write files externally |
| desert | ⚠️ **C** | [iso](renders/quality-audit/god_ray_hints/desert_isometric.png) · [top](renders/quality-audit/god_ray_hints/desert_topdown.png) · [side](renders/quality-audit/god_ray_hints/desert_sideprofile.png) | No export channels captured — pass may write files externally |

### ✅ `horizon_lod` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/horizon_lod/grassland_isometric.png) · [top](renders/quality-audit/horizon_lod/grassland_topdown.png) · [side](renders/quality-audit/horizon_lod/grassland_sideprofile.png) | Export: 1 channels active, terrain visible |
| mountain | ✅ **A** | [iso](renders/quality-audit/horizon_lod/mountain_isometric.png) · [top](renders/quality-audit/horizon_lod/mountain_topdown.png) · [side](renders/quality-audit/horizon_lod/mountain_sideprofile.png) | Export: 1 channels active, terrain visible |
| coastal | ✅ **A** | [iso](renders/quality-audit/horizon_lod/coastal_isometric.png) · [top](renders/quality-audit/horizon_lod/coastal_topdown.png) · [side](renders/quality-audit/horizon_lod/coastal_sideprofile.png) | Export: 1 channels active, terrain visible |
| volcanic | ✅ **A** | [iso](renders/quality-audit/horizon_lod/volcanic_isometric.png) · [top](renders/quality-audit/horizon_lod/volcanic_topdown.png) · [side](renders/quality-audit/horizon_lod/volcanic_sideprofile.png) | Export: 1 channels active, terrain visible |
| frozen | ✅ **A** | [iso](renders/quality-audit/horizon_lod/frozen_isometric.png) · [top](renders/quality-audit/horizon_lod/frozen_topdown.png) · [side](renders/quality-audit/horizon_lod/frozen_sideprofile.png) | Export: 1 channels active, terrain visible |
| desert | ✅ **A** | [iso](renders/quality-audit/horizon_lod/desert_isometric.png) · [top](renders/quality-audit/horizon_lod/desert_topdown.png) · [side](renders/quality-audit/horizon_lod/desert_sideprofile.png) | Export: 1 channels active, terrain visible |

### 🟡 `pass_atmospheric_volumes` — Grade **B**

**Overall:** 0A/6B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | 🟡 **B** | [iso](renders/quality-audit/pass_atmospheric_volumes/grassland_isometric.png) · [top](renders/quality-audit/pass_atmospheric_volumes/grassland_topdown.png) · [side](renders/quality-audit/pass_atmospheric_volumes/grassland_sideprofile.png) | Export partial: channels=0, terrain=3/3 |
| mountain | 🟡 **B** | [iso](renders/quality-audit/pass_atmospheric_volumes/mountain_isometric.png) · [top](renders/quality-audit/pass_atmospheric_volumes/mountain_topdown.png) · [side](renders/quality-audit/pass_atmospheric_volumes/mountain_sideprofile.png) | Export partial: channels=0, terrain=3/3 |
| coastal | 🟡 **B** | [iso](renders/quality-audit/pass_atmospheric_volumes/coastal_isometric.png) · [top](renders/quality-audit/pass_atmospheric_volumes/coastal_topdown.png) · [side](renders/quality-audit/pass_atmospheric_volumes/coastal_sideprofile.png) | Export partial: channels=0, terrain=3/3 |
| volcanic | 🟡 **B** | [iso](renders/quality-audit/pass_atmospheric_volumes/volcanic_isometric.png) · [top](renders/quality-audit/pass_atmospheric_volumes/volcanic_topdown.png) · [side](renders/quality-audit/pass_atmospheric_volumes/volcanic_sideprofile.png) | Export partial: channels=0, terrain=3/3 |
| frozen | 🟡 **B** | [iso](renders/quality-audit/pass_atmospheric_volumes/frozen_isometric.png) · [top](renders/quality-audit/pass_atmospheric_volumes/frozen_topdown.png) · [side](renders/quality-audit/pass_atmospheric_volumes/frozen_sideprofile.png) | Export partial: channels=0, terrain=3/3 |
| desert | 🟡 **B** | [iso](renders/quality-audit/pass_atmospheric_volumes/desert_isometric.png) · [top](renders/quality-audit/pass_atmospheric_volumes/desert_topdown.png) · [side](renders/quality-audit/pass_atmospheric_volumes/desert_sideprofile.png) | Export partial: channels=0, terrain=3/3 |

### ✅ `pass_horizon_lod` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/pass_horizon_lod/grassland_isometric.png) · [top](renders/quality-audit/pass_horizon_lod/grassland_topdown.png) · [side](renders/quality-audit/pass_horizon_lod/grassland_sideprofile.png) | Export: 1 channels active, terrain visible |
| mountain | ✅ **A** | [iso](renders/quality-audit/pass_horizon_lod/mountain_isometric.png) · [top](renders/quality-audit/pass_horizon_lod/mountain_topdown.png) · [side](renders/quality-audit/pass_horizon_lod/mountain_sideprofile.png) | Export: 1 channels active, terrain visible |
| coastal | ✅ **A** | [iso](renders/quality-audit/pass_horizon_lod/coastal_isometric.png) · [top](renders/quality-audit/pass_horizon_lod/coastal_topdown.png) · [side](renders/quality-audit/pass_horizon_lod/coastal_sideprofile.png) | Export: 1 channels active, terrain visible |
| volcanic | ✅ **A** | [iso](renders/quality-audit/pass_horizon_lod/volcanic_isometric.png) · [top](renders/quality-audit/pass_horizon_lod/volcanic_topdown.png) · [side](renders/quality-audit/pass_horizon_lod/volcanic_sideprofile.png) | Export: 1 channels active, terrain visible |
| frozen | ✅ **A** | [iso](renders/quality-audit/pass_horizon_lod/frozen_isometric.png) · [top](renders/quality-audit/pass_horizon_lod/frozen_topdown.png) · [side](renders/quality-audit/pass_horizon_lod/frozen_sideprofile.png) | Export: 1 channels active, terrain visible |
| desert | ✅ **A** | [iso](renders/quality-audit/pass_horizon_lod/desert_isometric.png) · [top](renders/quality-audit/pass_horizon_lod/desert_topdown.png) · [side](renders/quality-audit/pass_horizon_lod/desert_sideprofile.png) | Export: 1 channels active, terrain visible |

### ✅ `prepare_heightmap_raw_u16` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/prepare_heightmap_raw_u16/grassland_isometric.png) · [top](renders/quality-audit/prepare_heightmap_raw_u16/grassland_topdown.png) · [side](renders/quality-audit/prepare_heightmap_raw_u16/grassland_sideprofile.png) | Export: 1 channels active, terrain visible |
| mountain | ✅ **A** | [iso](renders/quality-audit/prepare_heightmap_raw_u16/mountain_isometric.png) · [top](renders/quality-audit/prepare_heightmap_raw_u16/mountain_topdown.png) · [side](renders/quality-audit/prepare_heightmap_raw_u16/mountain_sideprofile.png) | Export: 1 channels active, terrain visible |
| coastal | ✅ **A** | [iso](renders/quality-audit/prepare_heightmap_raw_u16/coastal_isometric.png) · [top](renders/quality-audit/prepare_heightmap_raw_u16/coastal_topdown.png) · [side](renders/quality-audit/prepare_heightmap_raw_u16/coastal_sideprofile.png) | Export: 1 channels active, terrain visible |
| volcanic | ✅ **A** | [iso](renders/quality-audit/prepare_heightmap_raw_u16/volcanic_isometric.png) · [top](renders/quality-audit/prepare_heightmap_raw_u16/volcanic_topdown.png) · [side](renders/quality-audit/prepare_heightmap_raw_u16/volcanic_sideprofile.png) | Export: 1 channels active, terrain visible |
| frozen | ✅ **A** | [iso](renders/quality-audit/prepare_heightmap_raw_u16/frozen_isometric.png) · [top](renders/quality-audit/prepare_heightmap_raw_u16/frozen_topdown.png) · [side](renders/quality-audit/prepare_heightmap_raw_u16/frozen_sideprofile.png) | Export: 1 channels active, terrain visible |
| desert | ✅ **A** | [iso](renders/quality-audit/prepare_heightmap_raw_u16/desert_isometric.png) · [top](renders/quality-audit/prepare_heightmap_raw_u16/desert_topdown.png) · [side](renders/quality-audit/prepare_heightmap_raw_u16/desert_sideprofile.png) | Export: 1 channels active, terrain visible |

### ✅ `prepare_terrain_normals` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/prepare_terrain_normals/grassland_isometric.png) · [top](renders/quality-audit/prepare_terrain_normals/grassland_topdown.png) · [side](renders/quality-audit/prepare_terrain_normals/grassland_sideprofile.png) | Export: 1 channels active, terrain visible |
| mountain | ✅ **A** | [iso](renders/quality-audit/prepare_terrain_normals/mountain_isometric.png) · [top](renders/quality-audit/prepare_terrain_normals/mountain_topdown.png) · [side](renders/quality-audit/prepare_terrain_normals/mountain_sideprofile.png) | Export: 1 channels active, terrain visible |
| coastal | ✅ **A** | [iso](renders/quality-audit/prepare_terrain_normals/coastal_isometric.png) · [top](renders/quality-audit/prepare_terrain_normals/coastal_topdown.png) · [side](renders/quality-audit/prepare_terrain_normals/coastal_sideprofile.png) | Export: 1 channels active, terrain visible |
| volcanic | ✅ **A** | [iso](renders/quality-audit/prepare_terrain_normals/volcanic_isometric.png) · [top](renders/quality-audit/prepare_terrain_normals/volcanic_topdown.png) · [side](renders/quality-audit/prepare_terrain_normals/volcanic_sideprofile.png) | Export: 1 channels active, terrain visible |
| frozen | ✅ **A** | [iso](renders/quality-audit/prepare_terrain_normals/frozen_isometric.png) · [top](renders/quality-audit/prepare_terrain_normals/frozen_topdown.png) · [side](renders/quality-audit/prepare_terrain_normals/frozen_sideprofile.png) | Export: 1 channels active, terrain visible |
| desert | ✅ **A** | [iso](renders/quality-audit/prepare_terrain_normals/desert_isometric.png) · [top](renders/quality-audit/prepare_terrain_normals/desert_topdown.png) · [side](renders/quality-audit/prepare_terrain_normals/desert_sideprofile.png) | Export: 1 channels active, terrain visible |

### ✅ `prepare_unity_auxiliary_channels` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/prepare_unity_auxiliary_channels/grassland_isometric.png) · [top](renders/quality-audit/prepare_unity_auxiliary_channels/grassland_topdown.png) · [side](renders/quality-audit/prepare_unity_auxiliary_channels/grassland_sideprofile.png) | Export: 3 channels active, terrain visible |
| mountain | ✅ **A** | [iso](renders/quality-audit/prepare_unity_auxiliary_channels/mountain_isometric.png) · [top](renders/quality-audit/prepare_unity_auxiliary_channels/mountain_topdown.png) · [side](renders/quality-audit/prepare_unity_auxiliary_channels/mountain_sideprofile.png) | Export: 3 channels active, terrain visible |
| coastal | ✅ **A** | [iso](renders/quality-audit/prepare_unity_auxiliary_channels/coastal_isometric.png) · [top](renders/quality-audit/prepare_unity_auxiliary_channels/coastal_topdown.png) · [side](renders/quality-audit/prepare_unity_auxiliary_channels/coastal_sideprofile.png) | Export: 3 channels active, terrain visible |
| volcanic | ✅ **A** | [iso](renders/quality-audit/prepare_unity_auxiliary_channels/volcanic_isometric.png) · [top](renders/quality-audit/prepare_unity_auxiliary_channels/volcanic_topdown.png) · [side](renders/quality-audit/prepare_unity_auxiliary_channels/volcanic_sideprofile.png) | Export: 3 channels active, terrain visible |
| frozen | ✅ **A** | [iso](renders/quality-audit/prepare_unity_auxiliary_channels/frozen_isometric.png) · [top](renders/quality-audit/prepare_unity_auxiliary_channels/frozen_topdown.png) · [side](renders/quality-audit/prepare_unity_auxiliary_channels/frozen_sideprofile.png) | Export: 3 channels active, terrain visible |
| desert | ✅ **A** | [iso](renders/quality-audit/prepare_unity_auxiliary_channels/desert_isometric.png) · [top](renders/quality-audit/prepare_unity_auxiliary_channels/desert_topdown.png) · [side](renders/quality-audit/prepare_unity_auxiliary_channels/desert_sideprofile.png) | Export: 3 channels active, terrain visible |

### ✅ `shadow_clipmap` — Grade **A**

**Overall:** 6A/0B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ✅ **A** | [iso](renders/quality-audit/shadow_clipmap/grassland_isometric.png) · [top](renders/quality-audit/shadow_clipmap/grassland_topdown.png) · [side](renders/quality-audit/shadow_clipmap/grassland_sideprofile.png) | Export: 2 channels active, terrain visible |
| mountain | ✅ **A** | [iso](renders/quality-audit/shadow_clipmap/mountain_isometric.png) · [top](renders/quality-audit/shadow_clipmap/mountain_topdown.png) · [side](renders/quality-audit/shadow_clipmap/mountain_sideprofile.png) | Export: 2 channels active, terrain visible |
| coastal | ✅ **A** | [iso](renders/quality-audit/shadow_clipmap/coastal_isometric.png) · [top](renders/quality-audit/shadow_clipmap/coastal_topdown.png) · [side](renders/quality-audit/shadow_clipmap/coastal_sideprofile.png) | Export: 2 channels active, terrain visible |
| volcanic | ✅ **A** | [iso](renders/quality-audit/shadow_clipmap/volcanic_isometric.png) · [top](renders/quality-audit/shadow_clipmap/volcanic_topdown.png) · [side](renders/quality-audit/shadow_clipmap/volcanic_sideprofile.png) | Export: 2 channels active, terrain visible |
| frozen | ✅ **A** | [iso](renders/quality-audit/shadow_clipmap/frozen_isometric.png) · [top](renders/quality-audit/shadow_clipmap/frozen_topdown.png) · [side](renders/quality-audit/shadow_clipmap/frozen_sideprofile.png) | Export: 2 channels active, terrain visible |
| desert | ✅ **A** | [iso](renders/quality-audit/shadow_clipmap/desert_isometric.png) · [top](renders/quality-audit/shadow_clipmap/desert_topdown.png) · [side](renders/quality-audit/shadow_clipmap/desert_sideprofile.png) | Export: 2 channels active, terrain visible |

## Validation Passes

### 🟡 `saliency_refine` — Grade **B**

**Overall:** 0A/6B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | 🟡 **B** | [iso](renders/quality-audit/saliency_refine/grassland_isometric.png) · [top](renders/quality-audit/saliency_refine/grassland_topdown.png) · [side](renders/quality-audit/saliency_refine/grassland_sideprofile.png) | Validation ran and returned ok (synthetic terrain may not hit AAA thresholds) |
| mountain | 🟡 **B** | [iso](renders/quality-audit/saliency_refine/mountain_isometric.png) · [top](renders/quality-audit/saliency_refine/mountain_topdown.png) · [side](renders/quality-audit/saliency_refine/mountain_sideprofile.png) | Validation ran and returned ok (synthetic terrain may not hit AAA thresholds) |
| coastal | 🟡 **B** | [iso](renders/quality-audit/saliency_refine/coastal_isometric.png) · [top](renders/quality-audit/saliency_refine/coastal_topdown.png) · [side](renders/quality-audit/saliency_refine/coastal_sideprofile.png) | Validation ran and returned ok (synthetic terrain may not hit AAA thresholds) |
| volcanic | 🟡 **B** | [iso](renders/quality-audit/saliency_refine/volcanic_isometric.png) · [top](renders/quality-audit/saliency_refine/volcanic_topdown.png) · [side](renders/quality-audit/saliency_refine/volcanic_sideprofile.png) | Validation ran and returned ok (synthetic terrain may not hit AAA thresholds) |
| frozen | 🟡 **B** | [iso](renders/quality-audit/saliency_refine/frozen_isometric.png) · [top](renders/quality-audit/saliency_refine/frozen_topdown.png) · [side](renders/quality-audit/saliency_refine/frozen_sideprofile.png) | Validation ran and returned ok (synthetic terrain may not hit AAA thresholds) |
| desert | 🟡 **B** | [iso](renders/quality-audit/saliency_refine/desert_isometric.png) · [top](renders/quality-audit/saliency_refine/desert_topdown.png) · [side](renders/quality-audit/saliency_refine/desert_sideprofile.png) | Validation ran and returned ok (synthetic terrain may not hit AAA thresholds) |

### ⚠️ `validation_full` — Grade **C**

**Overall:** 0A/0B/6C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | ⚠️ **C** | [iso](renders/quality-audit/validation_full/grassland_isometric.png) · [top](renders/quality-audit/validation_full/grassland_topdown.png) · [side](renders/quality-audit/validation_full/grassland_sideprofile.png) | Validation returned error-status but 0 hard violations (10 soft issues on synthetic terrain — expected) |
| mountain | ⚠️ **C** | [iso](renders/quality-audit/validation_full/mountain_isometric.png) · [top](renders/quality-audit/validation_full/mountain_topdown.png) · [side](renders/quality-audit/validation_full/mountain_sideprofile.png) | Validation returned error-status but 0 hard violations (10 soft issues on synthetic terrain — expected) |
| coastal | ⚠️ **C** | [iso](renders/quality-audit/validation_full/coastal_isometric.png) · [top](renders/quality-audit/validation_full/coastal_topdown.png) · [side](renders/quality-audit/validation_full/coastal_sideprofile.png) | Validation returned error-status but 0 hard violations (9 soft issues on synthetic terrain — expected) |
| volcanic | ⚠️ **C** | [iso](renders/quality-audit/validation_full/volcanic_isometric.png) · [top](renders/quality-audit/validation_full/volcanic_topdown.png) · [side](renders/quality-audit/validation_full/volcanic_sideprofile.png) | Validation returned error-status but 0 hard violations (10 soft issues on synthetic terrain — expected) |
| frozen | ⚠️ **C** | [iso](renders/quality-audit/validation_full/frozen_isometric.png) · [top](renders/quality-audit/validation_full/frozen_topdown.png) · [side](renders/quality-audit/validation_full/frozen_sideprofile.png) | Validation returned error-status but 0 hard violations (11 soft issues on synthetic terrain — expected) |
| desert | ⚠️ **C** | [iso](renders/quality-audit/validation_full/desert_isometric.png) · [top](renders/quality-audit/validation_full/desert_topdown.png) · [side](renders/quality-audit/validation_full/desert_sideprofile.png) | Validation returned error-status but 0 hard violations (10 soft issues on synthetic terrain — expected) |

### 🟡 `validation_minimal` — Grade **B**

**Overall:** 0A/6B/0C/0D/0F across 6 biomes

| Biome | Grade | Renders | Evidence |
|-------|-------|---------|---------|
| grassland | 🟡 **B** | [iso](renders/quality-audit/validation_minimal/grassland_isometric.png) · [top](renders/quality-audit/validation_minimal/grassland_topdown.png) · [side](renders/quality-audit/validation_minimal/grassland_sideprofile.png) | Validation ran and returned ok (synthetic terrain may not hit AAA thresholds) |
| mountain | 🟡 **B** | [iso](renders/quality-audit/validation_minimal/mountain_isometric.png) · [top](renders/quality-audit/validation_minimal/mountain_topdown.png) · [side](renders/quality-audit/validation_minimal/mountain_sideprofile.png) | Validation ran and returned ok (synthetic terrain may not hit AAA thresholds) |
| coastal | 🟡 **B** | [iso](renders/quality-audit/validation_minimal/coastal_isometric.png) · [top](renders/quality-audit/validation_minimal/coastal_topdown.png) · [side](renders/quality-audit/validation_minimal/coastal_sideprofile.png) | Validation ran and returned ok (synthetic terrain may not hit AAA thresholds) |
| volcanic | 🟡 **B** | [iso](renders/quality-audit/validation_minimal/volcanic_isometric.png) · [top](renders/quality-audit/validation_minimal/volcanic_topdown.png) · [side](renders/quality-audit/validation_minimal/volcanic_sideprofile.png) | Validation ran and returned ok (synthetic terrain may not hit AAA thresholds) |
| frozen | 🟡 **B** | [iso](renders/quality-audit/validation_minimal/frozen_isometric.png) · [top](renders/quality-audit/validation_minimal/frozen_topdown.png) · [side](renders/quality-audit/validation_minimal/frozen_sideprofile.png) | Validation ran and returned ok (synthetic terrain may not hit AAA thresholds) |
| desert | 🟡 **B** | [iso](renders/quality-audit/validation_minimal/desert_isometric.png) · [top](renders/quality-audit/validation_minimal/desert_topdown.png) · [side](renders/quality-audit/validation_minimal/desert_sideprofile.png) | Validation ran and returned ok (synthetic terrain may not hit AAA thresholds) |

---

## Failures & Critical Issues

These passes need immediate attention:

- ❌ **pass_water_depth** (D): 0F + 6D across biomes
- ❌ **terrain_labels** (D): 0F + 6D across biomes
- ❌ **pass_morphology** (D): 0F + 6D across biomes
- ❌ **glacial** (D): 0F + 5D across biomes
- ❌ **pass_glacial** (D): 0F + 5D across biomes
- ❌ **pass_lava_simulation** (D): 0F + 6D across biomes
- ❌ **emit_particle_systems** (D): 0F + 6D across biomes
- 💀 **pass_banded_advanced** (F): 6/6 biomes hard-fail
