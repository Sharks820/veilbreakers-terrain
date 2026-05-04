# A4 Audit: Texture & Materials System

**Date:** 2026-04-27
**Auditor:** Deep-dive AAA review
**Depth:** Standard — full file read, line-level citations
**Reference bar:** MicroSplat, Heitz & Neyret 2018/2019 histogram-preserving blending, Unity HDRP PBR, UE5 Landscape Material

**Files audited:**
- `veilbreakers_terrain/handlers/terrain_stochastic_shader.py` (1167 lines)
- `veilbreakers_terrain/handlers/terrain_quixel_ingest.py` (994 lines)
- `veilbreakers_terrain/handlers/terrain_materials_v2.py` (962 lines)
- `veilbreakers_terrain/handlers/terrain_materials_ext.py` (471 lines)
- `veilbreakers_terrain/handlers/terrain_texture_layer_stack.py` (92 lines)
- `veilbreakers_terrain/handlers/terrain_materials.py` (~1700 lines reviewed)
- `veilbreakers_terrain/handlers/procedural_materials.py` (~1900 lines reviewed)
- `veilbreakers_terrain/handlers/terrain_palette_extract.py` (332 lines)

---

## CRITICAL FINDINGS (P0)

### [P0-01] EXR/HDR float images divided by 255 — displacement data destroyed

**File:** `terrain_quixel_ingest.py:264–266`

**Finding:**
```python
elif raw.max() > 2.0:
    # Float image with HDR values — clamp/scale to [0,1] range assuming uint8 origin
    raw = raw / 255.0
```

This branch is reached for every float32 EXR or 16-bit TIFF where any pixel exceeds 2.0 — which is the normal case for displacement maps. Quixel exports displacement in metres, commonly with values in the 0.0–8.0 m range. After this division, a 4-metre displacement value becomes 0.016 — a 64x attenuation. The result is written into `height_displacement` on the `TextureLayer` and into `terrain_displacement` on the mask stack. Downstream erosion, parallax occlusion, and terrain mesh displacement all use this corrupted value silently.

**Root cause:** The guard comment says "assuming uint8 origin" but float EXR images loaded by imageio arrive as float32 with physical units, not uint8-mapped 0–255. The uint8 branch above (line 262) already correctly handles integer-origin data via `np.iinfo(orig_dtype).max`. This else-branch is only reached for float-origin images.

**AAA comparison:** No AAA pipeline divides physical-unit float displacement by 255. MicroSplat reads displacement directly and remaps with an explicit world-scale parameter. UE5 uses a HeightScale node. The correct fix is to clamp float images to [0,1] without scaling when they are already in that range, and to use a configurable `displacement_scale_m` parameter for out-of-range maps.

**Fix:**
```python
elif raw.max() > 1.0:
    # Float image out of [0,1] — normalize to [0,1] using actual min/max.
    # For physical displacement (EXR, 0–8m), caller should pass displacement_scale_m
    # to reconstruct world-space values. Do NOT assume uint8 origin.
    r_min, r_max = float(raw.min()), float(raw.max())
    span = r_max - r_min if r_max > r_min else 1.0
    raw = (raw - r_min) / span
```
Add a `displacement_scale_m: float = 1.0` parameter to `_load_texture_as_float` and surface it through `apply_quixel_to_layer` so callers can reconstruct physical units.

---

### [P0-02] `HistogramPreservingBlend` HLSL function is NOT histogram-preserving — mislabeled, produces wrong tonal output

**File:** `terrain_stochastic_shader.py:124–135` (triangular mode), `terrain_stochastic_shader.py:303–308` (hex mode)

**Finding (triangular template):**
```hlsl
// Histogram-preserving blend: Gaussian to uniform CDF transform
// Applied as a contrast correction to preserve texture luminance.
float4 HistogramPreservingBlend(float4 c0, float4 c1, float4 c2, float3 w, float contrast)
{
    // Weighted blend
    float4 blended = c0 * w.x + c1 * w.y + c2 * w.z;
    // Contrast correction: expand toward mean to counteract
    // the variance compression of weighted averaging.
    // correction = mean + (blended - mean) * contrast_scale
    float4 mean = (c0 + c1 + c2) / 3.0;
    return mean + (blended - mean) * contrast;
}
```

This is a contrast-adjusted weighted average, not histogram-preserving blending. The Heitz & Neyret (2018/2019) algorithm requires:
1. Transform each sample from Gaussian distribution to uniform distribution using the precomputed CDF `T` (the LUT baked in `build_stochastic_sampling_mask`)
2. Blend in uniform space
3. Apply inverse transform `T^-1` to return to Gaussian space

The Python CPU-side bake (`build_stochastic_sampling_mask`) correctly implements rank-based CDF remapping. However, the HLSL shader that runs at render time performs none of this — it never references the LUT baked on the CPU side, because the LUT is never uploaded to GPU as a texture parameter. The result is that tile seam transitions show luminance drift exactly as they would without the Heitz algorithm. The function name and comment create a false impression of correctness, making this a silent wrong-output bug.

**AAA comparison:** Heitz & Neyret 2019 (JCGT) "High-Performance By-Example Noise using a Histogram-Preserving Blending Operator" Section 4 explicitly shows the LUT-based T/T^-1 transform as a required GPU pass. Contrast-boost is not equivalent. Epic's own Unreal stochastic tiling reference implementation includes the LUT as a `Texture2D _Lut` shader parameter.

**Fix:**
The HLSL template must:
1. Accept a `TEXTURE2D _HistogramLUT` parameter (uploaded from the CPU-baked LUT)
2. Transform each sample: `c0_g = SampleHistogramLUT(_HistogramLUT, c0)`
3. Blend in Gaussian-mapped space
4. Apply inverse: `result = InvHistogramLUT(_HistogramLUT, blended)`

If a full LUT upload is not yet feasible, the function must be renamed to `ContrastBlend` and the comment must not claim histogram preservation. The Python bake result is currently orphaned — it is never connected to the HLSL path.

---

### [P0-03] `default_dark_fantasy_rules()` produces 5 splatmap layers — silently exceeds Unity 4-layer budget in `pass_materials`

**File:** `terrain_materials_v2.py:107–174` (rule definition), `terrain_materials_v2.py:795–919` (pass_materials — no layer count check)

**Finding:**
`default_dark_fantasy_rules()` defines 5 channels: ground, cliff, scree, wet_rock, snow. `pass_materials` calls `compute_slope_material_weights(stack, rules)` with these rules, produces a `(H, W, 5)` weight array, and writes it to `splatmap_weights_layer` with no enforcement of the Unity 4-channel limit.

The Quixel ingest path **does** enforce the budget (via `_UNITY_MAX_SPLATMAP_LAYERS = 4`) and raises a `ValueError` at layer 4. But `pass_materials` takes a different code path and writes the 5-layer array directly, bypassing that guard. Any downstream Unity exporter that reads `splatmap_weights_layer` expecting a (H, W, 4) array will either crash or silently drop the 5th channel.

**AAA comparison:** Unity Terrain's built-in splatmap limit is exactly 4 channels per material. MicroSplat extends this with multi-splatmap packing (8, 12, 16 channels using multiple RGBA textures), but that requires explicit opt-in. No AAA tool silently writes a 5-channel splatmap to a field that Unity consumes as 4 channels.

**Fix:**
Add a layer count check in `pass_materials` immediately after computing `new_weights`:
```python
_UNITY_SPLATMAP_LAYER_LIMIT = 4
if new_weights.shape[2] > _UNITY_SPLATMAP_LAYER_LIMIT:
    issues.append(ValidationIssue(
        code="MAT_SPLATMAP_OVER_BUDGET",
        severity="hard",
        affected_feature="splatmap_weights_layer",
        message=(
            f"Rule set produces {new_weights.shape[2]} layers, "
            f"exceeding Unity 4-channel splatmap limit"
        ),
        remediation=(
            "Reduce to 4 channels or enable multi-splatmap packing "
            "via hints['multi_splatmap_enabled'] = True"
        ),
    ))
```
For a 5-channel default, either merge scree into ground as the lowest-priority layer, or implement multi-splatmap export (2x RGBA textures).

---

### [P0-04] Normal map blending operates in [0,1] packed space without decoding to [-1,1]

**File:** `terrain_quixel_ingest.py:639–654`

**Finding:**
```python
if stack.terrain_normals is None:
    base_n = np.zeros((rows, cols, 3), dtype=np.float32)
    base_n[:, :, 2] = 1.0   # <-- wrong: packed flat normal should be (0.5, 0.5, 1.0)
    stack.set("terrain_normals", base_n, "quixel_ingest")

blended_n = (
    stack.terrain_normals + sampled_normal * layer_weight[:, :, np.newaxis]
)
norms = np.linalg.norm(blended_n, axis=2, keepdims=True)
```

Two bugs compound here:

1. **Wrong base normal:** A packed tangent-space flat normal is `(0.5, 0.5, 1.0)` in [0,1] encoding. Initializing to `(0, 0, 1)` means the base has a decoded direction of `(-1, -1, 1)` normalized, which is not "up" in tangent space.

2. **Blending in packed space:** `stack.terrain_normals` stores packed [0,1] values. `sampled_normal` is loaded from disk also in [0,1]. Addition of packed normals is geometrically meaningless — it's equivalent to adding `(2n-1)` vectors *after* applying a constant +1 offset to each, which produces wrong directions. The correct approach is to decode both to [-1,1], add as vectors (or use Whiteout/UDN reorientation for tangent-space compositing), normalize, then re-encode.

**AAA comparison:** Every PBR normal-blend tutorial (MicroSplat, Substance, UE5 Normal Blend) decodes from [0,1] to [-1,1] before any vector math. Whiteout blend (Vlachos 2010) or UDN blend is standard for layered tangent normals. Raw packed-space addition is undefined behavior for normal maps.

**Fix:**
```python
def _decode_normal(n_packed: np.ndarray) -> np.ndarray:
    """[0,1] packed → [-1,1] tangent-space normals."""
    return n_packed * 2.0 - 1.0

def _encode_normal(n: np.ndarray) -> np.ndarray:
    """[-1,1] → [0,1] packed."""
    return (n * 0.5 + 0.5).clip(0.0, 1.0)

# Initialize base as flat normal in packed space
if stack.terrain_normals is None:
    base_n = np.full((rows, cols, 3), 0.5, dtype=np.float32)
    base_n[:, :, 2] = 1.0   # (0.5, 0.5, 1.0) = packed flat normal
    stack.set("terrain_normals", base_n, "quixel_ingest")

# Whiteout blend in [-1,1] space
base_decoded = _decode_normal(stack.terrain_normals)
sample_decoded = _decode_normal(sampled_normal)
# Whiteout: n1.xy + n2.xy, n1.z * n2.z
blended_xy = base_decoded[..., :2] + sample_decoded[..., :2] * layer_weight[..., np.newaxis]
blended_z = base_decoded[..., 2:3] * sample_decoded[..., 2:3]
blended_n = np.concatenate([blended_xy, blended_z], axis=-1)
norms = np.linalg.norm(blended_n, axis=2, keepdims=True)
norms = np.where(norms < 1e-8, 1.0, norms)
stack.set("terrain_normals", _encode_normal(blended_n / norms).astype(np.float32), "quixel_ingest")
```

---

### [P0-05] Albedo textures blended in gamma space — color math is physically wrong

**File:** `terrain_quixel_ingest.py:600–612`

**Finding:**
```python
if albedo_array is not None:
    sampled_albedo = _bilinear_sample_texture(albedo_array.astype(np.float32), uv_y, uv_x)
    if stack.macro_color is None:
        stack.set("macro_color",
            (sampled_albedo * layer_weight[:, :, np.newaxis]).astype(np.float32),
            "quixel_ingest")
    else:
        blended = stack.macro_color + sampled_albedo * layer_weight[:, :, np.newaxis]
        stack.set("macro_color", blended.astype(np.float32), "quixel_ingest")
```

`_load_texture_as_float` performs no sRGB→linear conversion. Quixel albedo textures on disk are sRGB-encoded (gamma ≈ 2.2). All weighted blending here operates in gamma-encoded space. Blending `0.5 * dark_srgb + 0.5 * light_srgb` produces a different result than blending in linear and re-encoding — approximately 20–30% darker mid-tones, the well-known "dark seam" artifact that separates amateur from professional texture blending.

**AAA comparison:** Every PBR pipeline (Unity URP/HDRP, UE5, MicroSplat) explicitly linearizes albedo before any blending operation. The Substance Designer sRGB/linear pipeline documentation calls this out as requirement #1. Roughness, AO, metallic, and displacement are linear and do not need this conversion — but albedo does.

**Fix:**
Add sRGB linearization in `_load_texture_as_float` for albedo channels, or at the call site in `apply_quixel_to_layer`:
```python
def _srgb_to_linear(arr: np.ndarray) -> np.ndarray:
    """IEC 61966-2-1 sRGB expansion to linear light."""
    return np.where(arr <= 0.04045, arr / 12.92, ((arr + 0.055) / 1.055) ** 2.4)

# In apply_quixel_to_layer, before blending:
if albedo_array is not None:
    albedo_linear = _srgb_to_linear(albedo_array.astype(np.float32))
    # ... blend in linear, then re-encode to sRGB before storing if needed
```
The `TextureLayer.color_space` field already exists to track this — it should drive conditional linearization.

---

## HIGH-SEVERITY (P1)

### [P1-01] ORM vs MA channel packing mismatch — Quixel AO silently mapped to Metallic

**File:** `terrain_stochastic_shader.py:208–212`

**Finding:**
```hlsl
SurfaceData surfaceData = (SurfaceData)0;
surfaceData.albedo     = albedo.rgb;
surfaceData.metallic   = metallic.r;   // reads R channel
surfaceData.smoothness = metallic.a;   // reads A channel
surfaceData.occlusion  = ao;
```

The shader uses Unity MA packing: R=Metallic, A=Smoothness (= 1 - Roughness). Quixel Bridge exports ORM packing: R=AO/Occlusion, G=Roughness, B=Metallic. If a Quixel ORM map is connected to the `_MetallicGlossMap` slot (which is the natural mapping given the slot name), the result is:
- `surfaceData.metallic` = Quixel AO value (0.6–1.0 on rock) → stone appears highly metallic
- `surfaceData.smoothness` = undefined (alpha channel of ORM, often 1.0) → stone appears perfectly smooth
- `surfaceData.occlusion` = correct, but sourced separately from `_OcclusionMap`

This is not a theoretical concern — Quixel Bridge's Unity package explicitly uses ORM packing and labels the slot accordingly. Any VeilBreakers artist connecting Quixel surface assets to this shader will get physically wrong metallic/roughness values with no error.

**AAA comparison:** MicroSplat ships with explicit ORM support and documents its packing convention prominently. UE5's Quixel integration uses ORM by default. Unity's HDRP Lit shader also supports ORM packing via `_MaskMap` (MOHS: Metallic, AO, Detail mask, Smoothness).

**Fix:**
Either switch to ORM packing:
```hlsl
// ORM: R=AO, G=Roughness, B=Metallic
surfaceData.occlusion  = orm.r;
surfaceData.metallic   = orm.b;
surfaceData.smoothness = 1.0 - orm.g;  // roughness → smoothness
```
Or add a shader keyword `_USE_ORM_PACKING` to support both. Document the convention in `StochasticShaderTemplate.__post_init__` with an assertion.

---

### [P1-02] No object-space normal path for triplanar cliff projection

**File:** `terrain_materials_v2.py:177–250` (triplanar_blend), `terrain_stochastic_shader.py` (no triplanar normal handling)

**Finding:**
`triplanar_blend()` in `terrain_materials_v2.py` performs UV projection from 3 world-space axes and blends the results using abs(normal) weights. The blended value is written to the splatmap and used for weight computation. However, when a triplanar-projected normal map is fetched for a cliff face, it is fetched from a tangent-space normal map (the standard Quixel output) and blended as if it were a world-space quantity.

Tangent-space normals from an XZ-projected sample have a different tangent frame than normals from a YZ-projected sample. Blending them in packed [0,1] space without reorienting from each tangent frame to object space produces visually incorrect shading on cliff edges where projection axes blend — typically manifesting as washed-out or incorrectly lit cliff faces.

The correct approach for triplanar normal blending requires either:
1. Object-space normal maps (rare, baked offline)
2. Tangent reorientation per projection axis using the surface normal, followed by UDN or Whiteout blend

Neither is implemented. `_build_normal_chain()` in `procedural_materials.py` uses only procedural bump nodes with no tangent reorientation.

**AAA comparison:** Ben Golus's "Normal Mapping for a Triplanar Shader" (2017, cited in UE5 triplanar shading docs) explicitly identifies tangent-frame mismatch as the primary artifact of naive triplanar normal mapping and provides the exact reorientation math. MicroSplat's triplanar mode implements this reorientation. Ignoring it is the #1 quality gap that distinguishes hobbyist from AAA triplanar results.

**Fix:**
In the HLSL template, for each triplanar projection axis, apply surface-normal reorientation before blending:
```hlsl
// Reorient tangent normal n_t for blend axis given surface normal n_s
float3 ReorientNormal(float3 n_t, float3 n_s) {
    // UDN blend
    n_t = float3(n_t.xy + n_s.xy, n_s.z);
    return normalize(n_t);
}
```

---

### [P1-03] Hero cliff texel density (1024 px/m) documented but never enforced by validator

**File:** `terrain_materials_ext.py:87–96, 117–146`

**Finding:**
The docstring for `validate_texel_density_coherency()` states:
> Hero assets: 1024 px/m (triplanar cliff faces, hero props)

The validator defines `_HERO_MIN = 1024.0` at line 117. However, the enforcement block at line 142–162 classifies channels only by their `triplanar` flag:
```python
tier_min = _TERRAIN_MIN if ch.triplanar else _LOD1_MIN
tier_name = "terrain (512 px/m)" if ch.triplanar else "LOD1 (256 px/m)"
```

`_HERO_MIN` is referenced only in the `remediation` string (line 159) and in `_build_material_channel_exts` (line 771) where it is used as a *default density* for channels listed in `hero_material_ids`. It is never used as a *minimum threshold* for validation. A cliff channel with `texel_density_m=512.0` passes validation even though the spec requires 1024.

**AAA comparison:** VeilBreakers' own spec says hero cliff faces at 1024 px/m. This is consistent with Destiny 2 and Horizon Zero Dawn's documented cliff-face texel budgets. Soft-enforcing it as a remediation hint while hard-enforcing 512 defeats the purpose of tiered enforcement.

**Fix:**
```python
# In the AAA tier compliance loop:
if ch.triplanar:
    # Check both hero and terrain tiers
    if ch.channel_id in hero_ids or ch.texel_density_m >= _HERO_MIN:
        tier_min = _HERO_MIN
        tier_name = "hero (1024 px/m)"
    else:
        tier_min = _TERRAIN_MIN
        tier_name = "terrain (512 px/m)"
else:
    tier_min = _LOD1_MIN
    tier_name = "LOD1 (256 px/m)"
```
The `hero_ids` set should be passed into the function as a parameter.

---

## MEDIUM (P2)

### [P2-01] `TerrainTextureLayerStack.validate()` uses `hasattr` on dict-based TerrainMaskStack

**File:** `terrain_texture_layer_stack.py:53`

**Finding:**
```python
elif terrain_stack is not None and not hasattr(terrain_stack, layer.terrain_mask_source):
    issues.append(f"{layer.layer_id}: terrain_mask_source '{layer.terrain_mask_source}' not found on stack")
```

`TerrainMaskStack` stores channels in an internal dict accessed via `.get()` / `.set()`. It does not expose channels as Python attributes. `hasattr(stack, "cliff_mask")` returns `False` for any dynamically registered channel, making this validation check produce false failures for all valid stack channels. The correct check is `stack.get(layer.terrain_mask_source) is None`.

**Fix:**
```python
elif terrain_stack is not None:
    # TerrainMaskStack stores channels in a dict; use .get() not hasattr
    getter = getattr(terrain_stack, "get", None)
    if getter is not None:
        if getter(layer.terrain_mask_source) is None:
            issues.append(f"{layer.layer_id}: terrain_mask_source '{layer.terrain_mask_source}' not found on stack")
    elif not hasattr(terrain_stack, layer.terrain_mask_source):
        issues.append(f"{layer.layer_id}: terrain_mask_source '{layer.terrain_mask_source}' not found on stack")
```

---

### [P2-02] Two conflicting height-blend systems operate simultaneously without explicit coordination

**File:** `terrain_materials_v2.py:842–843` (calls `compute_height_blended_weights`), `terrain_materials_v2.py:605–622` (calls `apply_brucks_blend`)

**Finding:**
`pass_materials` applies two separate height-blend operations in sequence:

1. **`compute_height_blended_weights`** (from `terrain_materials_ext.py:194`): Applies per-layer gamma power curves to world elevation, normalized per-call. Modifies all L layers.
2. **`apply_brucks_blend`** (line 614): Applies the MicroSplat Brucks formula specifically to the cliff/ground boundary using strata height. Modifies only cliff and ground layers.

These two systems have different height inputs (world elevation vs. strata height), different mathematical models (gamma power vs. Brucks contrast), and different scopes (all layers vs. two layers). The Brucks blend is applied *after* the gamma blend, using the already-gamma-modified cliff weight as its `blend_alpha` input. The Brucks formula assumes `blend_alpha` represents a slope-based weight in [0,1], but after gamma-blending it reflects both slope and elevation. The interaction is undefined by design and produces different outputs depending on the terrain's altitude distribution.

**AAA comparison:** MicroSplat uses exactly one height-blend system (Brucks) applied once. Having two height-blend passes with undefined interaction is a maintenance and debugging hazard. If the intent is to keep both, document the exact contract: "gamma blend modulates by elevation, Brucks blend sharpens rock/dirt transition using packed height" and ensure they are applied to disjoint concerns.

**Recommendation:** Decide on one system. If both are needed, enforce strict ordering in code comments and validate that the Brucks input alpha has been de-correlated from the elevation gamma effect before it is used.

---

### [P2-03] k-means color clustering runs in gamma space

**File:** `terrain_palette_extract.py:97–136`

**Finding:**
`extract_palette_from_image()` accepts uint8 or float32 images and converts to float32 [0,1] before k-means clustering. No sRGB→linear conversion is applied. Clustering in perceptual (gamma) space means Euclidean distances in RGB underweight differences in dark regions (where human perception is most sensitive) and overweight differences in bright regions. The resulting palette centroids are biased toward bright colors.

The Lab-based `palette_to_biome_mapping()` downstream *does* apply correct IEC 61966-2-1 gamma expansion before converting to XYZ/Lab (verified in `_rgb_to_lab()`). So the mismatch is: palette extraction is in gamma space, biome matching is in Lab space derived from linear — meaning the centroid coordinates passed into `palette_to_biome_mapping()` are sRGB values being interpreted as linear before Lab conversion, introducing a systematic error.

**Fix:**
Apply `_srgb_to_linear()` (or the correct IEC expansion) before k-means in `extract_palette_from_image()`. Since `_rgb_to_lab` already does this internally, the simplest fix is to cluster in Lab space directly rather than RGB.

---

## LOW (P3)

### [P3-01] `validate_dark_fantasy_color` never shifts hue — zone intent not enforced

**File:** `procedural_materials.py:109–131`

**Finding:**
The function signature promises to validate and nudge colors toward zone-specific hue targets. The implementation extracts HSV, nudges saturation and value, but the hue variable `h` is read and then returned unchanged — no zone-specific hue center is applied. The nudging logic operates on `s` and `v` only. A "crimson abyss" zone color of `(0.2, 0.15, 0.1)` will pass validation and be returned with no hue correction toward red even if the zone palette specifies a warm-red center.

**Fix:** Add zone-specific hue targets and a nudge toward them:
```python
_ZONE_HUE_CENTER = {"abyss": 0.0, "tundra": 0.58, "highlands": 0.08, ...}
if zone_id in _ZONE_HUE_CENTER:
    target_h = _ZONE_HUE_CENTER[zone_id]
    # Lerp hue toward target by 20% (non-destructive)
    h = h + 0.2 * ((target_h - h + 0.5) % 1.0 - 0.5)
```

---

### [P3-02] Triangular and hex stochastic modes implemented; Wang tiles absent

**File:** `terrain_stochastic_shader.py` (module level)

**Finding:**
The stochastic shader system implements triangular-basis (Heitz 2019) and Mikkelsen 2022 hex-tiling modes, both with Python CPU bakes and HLSL runtime templates. Wang tile tiling (Cohen et al. 2003) is not implemented. Wang tiles produce better results than regular grid tiling for low-frequency macro textures (large rock slabs, soil) where hex or triangular sampling can still produce visible star-shaped artifacts at tile centers.

This is a feature gap, not a bug. No incorrect output occurs. However, the `tiling_mode` parameter validation in `StochasticShaderTemplate.__post_init__` accepts only `{"triangular", "hex"}` — any attempt to use Wang tiles raises `ValueError` with a message that suggests they are a supported but misspelled option.

**Fix:** Add Wang tile support or update the error message to clarify Wang tiles are not implemented. For now: `raise ValueError(f"tiling_mode must be 'triangular' or 'hex' (Wang tiles not yet implemented); got {self.tiling_mode!r}")`.

---

## CLEAN FINDINGS

The following items were specifically audited and are correct:

**Brucks height-blend formula (`terrain_materials_v2.py:225–255`):** `apply_brucks_blend()` correctly implements the MicroSplat formula `ma = max(h_rock + (1-alpha), h_dirt + alpha) - contrast`. The implementation is vectorized, numerically stable, and matches the Brucks/Giliam reference.

**Shader name JSON/HLSL sync:** Both triangular and hex templates declare `ShaderName` in the JSON payload matching the HLSL `#pragma` declaration. Sync is correct for both modes.

**Splatmap budget enforcement in Quixel ingest path:** `_UNITY_MAX_SPLATMAP_LAYERS = 4` is enforced via `ValueError` at layer 5 in `apply_quixel_to_layer`. The guard is present and effective for the ingest code path (the gap is in `pass_materials`, flagged as P0-03).

**Python-side histogram equalization (rank remapping):** `build_stochastic_sampling_mask` and `build_hex_tiling_mask` correctly implement rank-based CDF remapping using `np.argsort(np.argsort(...))`. The CPU bake is mathematically sound; the problem is it is not used by the HLSL shader (flagged P0-02).

**`_rgb_to_lab()` pipeline (`terrain_palette_extract.py:14–40`):** Correct IEC 61966-2-1 sRGB→linear→XYZ→Lab pipeline with proper D65 white point. Lab centroids in `_BIOME_LAB_CENTROIDS` are correctly derived.

**Bilinear texture sampling (`terrain_quixel_ingest.py`, `_bilinear_sample_texture`):** Correctly uses normalized UV coordinates with boundary clamping. No off-by-one at texture edges.

**`TerrainTextureLayerStack.normalized_weights()`:** Correct L1 normalization with epsilon guard against zero-sum pixels.

**`blend_terrain_vertex_colors()` color space handling (`terrain_materials.py`):** Correctly linearizes weights via `_srgb_to_linear` before blending and re-encodes via `_linear_to_srgb`. Alpha channel (snow/water special) treated as linear throughout. Height-blend proxy matches MicroSplat intent.

**`MaterialChannelExt` dataclass (`terrain_materials_ext.py`):** Clean ABC with `height_blend_gamma`, `texel_density_m`, `triplanar` flags. The `albedo_tint` documented as "linear sRGB" — naming is slightly contradictory (linear sRGB = linear, not sRGB) but the values are correct as intended.

---

## STATISTICS

| Severity | Count | Immediate ship risk |
|----------|-------|---------------------|
| P0       | 5     | Yes — silent wrong output, data corruption, or hard Unity export failure |
| P1       | 3     | Yes — incorrect PBR output visible in production renders |
| P2       | 3     | Medium — validation errors, undefined behavior in edge cases |
| P3       | 2     | Low — minor quality gaps, no incorrect output |
| **Total** | **13** | |

**P0 priority order for fixes:**
1. P0-02 first (mislabeled HLSL function propagates false confidence system-wide)
2. P0-04 (normal map corruption is visible immediately in any render)
3. P0-05 (albedo gamma blending affects every texture layer boundary)
4. P0-01 (EXR displacement corruption is silent and hard to detect post-export)
5. P0-03 (Unity splatmap overflow crashes exporter or silently drops a layer)

**Relation to known active bugs from master guide:**
- W-1 (water dual semantics): out of scope for this audit
- Scatter C-: out of scope for this audit
- DataContractQA F: P0-02 (false histogram-preserving claim), P0-04 (normal blending), P0-05 (albedo gamma) all contribute to visual QA failures at the shader level

---

_Auditor: Claude (deep-dive AAA review)_
_Reference standard: Heitz & Neyret 2019 JCGT, MicroSplat 3.0 documentation, Unity HDRP PBR shader model, UE5 Landscape Material, Ben Golus Triplanar Normal Reorientation (2017)_
