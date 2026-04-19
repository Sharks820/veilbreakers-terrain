# B12 — Materials Core Deep Re-Audit (Wave 2)

**Auditor:** Opus 4.7 ultrathink (1M)
**Date:** 2026-04-16
**Scope:** 4 files under `veilbreakers_terrain/handlers/`
- `terrain_materials.py` (2766 LoC, 24 callables)
- `terrain_materials_ext.py` (234 LoC, 4 callables)
- `terrain_materials_v2.py` (374 LoC, 8 callables)
- `procedural_materials.py` (1870 LoC, 15 callables)

**Total surface enumerated:** 51 callables (incl. nested `_hash`, `_new_input`, `_hook_vector`, `__post_init__`, `index_of`, `channel_id`, `_place`).

**Bench standards used:**
- **UE5 Material Editor / Landscape `LandscapeLayerBlend`** — height-blend mode `LB_HeightBlend` with per-layer Heightmap textures, weight-blend `LB_WeightBlend`, and alpha-blend `LB_AlphaBlend`. Industry contract: weights normalized to sum=1; height-blend uses `Lerp(A, B, smoothstep(t-k, t+k, h_a-h_b))`.
- **Unity HDRP `TerrainLit`** — splatmap RGBA, 4 layers/pass URP, 8 layers/pass HDRP; per-layer mask map (R=metallic, G=AO, B=height, A=smoothness); diffuse alpha = smoothness fallback. Height-blend optional via `_EnableHeightBlend`.
- **Substance Designer** — node-graph material authoring with "Height Blend" filter that does `(h_a + opacity_a*255) > (h_b + opacity_b*255)`.
- **Quixel Megascans** — strict PBR: dielectric metallic=0, conductor metallic=1; albedo for dielectrics 50–243 sRGB; dedicated AORM channel-pack convention.
- **Triplanar mapping** — three planar projections weighted by `pow(abs(normal), k)` with k≈4–8; cliff layers should triplanar to avoid stretching.
- **Blender 4.x bpy** — `NodeTreeInterface.new_socket(name, in_out, socket_type)` is the modern API (3.x used `group.inputs.new`).

**Rubric:**
- **A+** — Ships in Horizon Forbidden West / God of War Ragnarök.
- **A** — Ships in current AAA UE5 game (Senua II, Black Myth).
- **A-** — Ships in shipping AAA but with a known limitation.
- **B+** — Ships in AA / strong indie. Missing one piece of AAA polish.
- **B** — Functional but obviously not AAA.
- **C** — Hobby quality; works but visibly wrong.
- **D** — Broken, hardcoded, or violates PBR.
- **F** — Bug, crash, or actively misleading.

**Splatmap weight grading rule (per spec):**
- **A** = proper height-blend gamma per layer + weight-renormalization to sum=1.
- **B** = renormalized splatmap weights but no per-layer height curve.

---

## FILE 1 — `terrain_materials.py` (2766 LoC)

This file is the *legacy biome-keyed* surface. It coexists with `terrain_materials_v2.py`. Per prior audit it carries technical debt: two parallel material-assignment APIs, biome-keyed magic numbers, vertex-color-only splatmap, and a partial Blender shader graph with HeightBlend group. The redeeming pieces are `compute_world_splatmap_weights` (fully vectorized) and `_create_height_blend_group` (real Blender height-blend node group).

### 1.1 `get_default_biome` — `terrain_materials.py:50`
- **Prior grade:** A
- **My grade:** A — AGREE
- **What it does:** Returns the constant `"thornwood_forest"`.
- **Reference:** Trivial constant accessor.
- **Bug/gap:** None.
- **AAA gap:** None.
- **Severity:** —
- **Upgrade:** None.

### 1.2 `_get_material_def` — `terrain_materials.py:997`
- **Prior grade:** A-
- **My grade:** A- — AGREE
- **What it does:** Two-tier dict lookup with `or` fallback into `MATERIAL_LIBRARY`.
- **Reference:** Standard chain-of-responsibility pattern.
- **Bug/gap:** Truthy-or pattern (`TERRAIN_MATERIALS.get(key) or MATERIAL_LIBRARY.get(key)`) treats an empty `{}` as missing — fine because no entry is `{}`, but a sentinel `is not None` check is safer.
- **AAA gap:** Doesn't log the lookup path so callers can't diagnose collision when a key exists in *both* tables. UE5/Substance graph-asset lookups always emit a redirector log.
- **Severity:** Low
- **Upgrade to A:** Replace `or` with `if x is not None: return x` and log when both tables contain the key.

### 1.3 `get_all_terrain_material_keys` — `terrain_materials.py:1002`
- **Prior grade:** A
- **My grade:** A — AGREE
- **What it does:** Walks `BIOME_PALETTES` and unions every material key referenced by any zone.
- **Reference:** Set-builder over palette graph; correct.
- **Bug/gap:** Only consults `BIOME_PALETTES` (the legacy v1 table). A key that exists *only* in `BIOME_PALETTES_V2` will be silently absent from this set. Given v2 is the supported authoring path, that is misleading.
- **AAA gap:** Sister function for v2 missing.
- **Severity:** Medium
- **Upgrade to A+:** Walk both `BIOME_PALETTES` and `BIOME_PALETTES_V2`. Add `get_all_terrain_layer_keys_v2()` companion.

### 1.4 `get_biome_palette` — `terrain_materials.py:1015`
- **Prior grade:** A
- **My grade:** A — AGREE
- **What it does:** Looks up legacy palette dict, raises `ValueError` with the available list on miss.
- **Reference:** Standard. Error message is helpful.
- **Bug/gap:** `available = sorted(BIOME_PALETTES.keys())` materializes a list every miss — fine.
- **AAA gap:** Doesn't take a `season` arg so it cannot resolve `mountain_pass_summer` → falls through to "unknown biome" for v2-aware callers. `_resolve_biome_palette_name` solves this for V2 but is only called inside V2 paths.
- **Severity:** Low
- **Upgrade:** Wire season-aware resolver in.

### 1.5 `_face_slope_angle` — `terrain_materials.py:1046`
- **Prior grade:** A
- **My grade:** A — AGREE
- **What it does:** Computes slope angle in degrees from face normal as `acos(|nz|/||n||)`.
- **Reference:** `|nz|` correctly treats up- and down-facing normals symmetrically (inverted faces still classify as flat). `acos` clamped against FP error. Standard.
- **Bug/gap:** Returns degrees in `[0,90]` only because of `abs(nz)` — docstring says `[0,180]` which is **incorrect**. Real range is `[0,90]`.
- **AAA gap:** None.
- **Severity:** Low (docstring lie).
- **Upgrade:** Fix docstring to `[0,90]`.

### 1.6 `_classify_face` — `terrain_materials.py:1068`
- **Prior grade:** B+
- **My grade:** B+ — AGREE
- **What it does:** Maps `(normal, face_z, water_level)` → one of 4 zones using two slope thresholds (30°, 60°) and a `water_level + 0.5` band.
- **Reference:** Comparable to UE5 Landscape's auto-paint thresholds — but UE5 uses curvature as a third axis. Bundle B v2 module already does this correctly.
- **Bug/gap:** The `+0.5` water band is hardcoded — should be a parameter. With water_level=0 the entire shoreline within 0.5 m gets `water_edges` regardless of biome scale.
- **AAA gap:** No smoothing band — produces hard zone borders that splatmap blending must hide later. UE5 / Substance use smoothstep transitions.
- **Severity:** Medium
- **Upgrade to A:** Take `water_band_meters: float = 0.5` parameter; return weights instead of single zone label so caller can blend.

### 1.7 `assign_terrain_materials_by_slope` — `terrain_materials.py:1096`
- **Prior grade:** B
- **My grade:** B- — DISPUTE (one notch lower)
- **What it does:** Per-face material-slot index assignment using `_classify_face`, distributed within zone via `mat_offset = fi % len(zone_materials)`.
- **Reference:** This is the *pre-splatmap* per-face material-slot model used by Quake 1 era engines. Modern terrain (UE5 Landscape, Unity Terrain, Frostbite) uses a single material with N layers blended by splatmap weights.
- **Bug/gap:** `fi % len(zone_materials)` produces *visible regular striping* across the mesh (face-index ordering is grid-row order on Blender procedural meshes). On a 256×256 grid this is unmistakable.
- **AAA gap:** Wrong abstraction entirely. AAA terrain uses a single multi-layer shader; per-face slots cause a draw call per material per chunk and forfeit blending.
- **Severity:** High (architectural)
- **Upgrade:** Deprecate. Route all callers to `terrain_materials_v2.compute_slope_material_weights` + `auto_assign_terrain_layers`. Add a `DeprecationWarning` here.

### 1.8 `blend_terrain_vertex_colors` — `terrain_materials.py:1167`
- **Prior grade:** B
- **My grade:** C+ — DISPUTE (one notch lower)
- **What it does:** Computes per-vertex RGBA splatmap weights by averaging `zone_weights` from adjacent faces.
- **Reference:** Vertex-color splatmap is acceptable as a *fallback* (Unity TerrainLit can read vertex colors), but real splatmap textures dominate AAA pipelines because vertex resolution is far below pixel resolution.
- **Bug/gap (file:line):**
  - `terrain_materials.py:1217-1222`: `zone_weights` are biome-agnostic magic numbers `(0.6, 0.0, 0.4, 0.0)` etc. There is no per-biome variation; every biome paints the same R/G/B/A balance per zone. Identical thornwood and crystal cavern splatmaps at vertex level.
  - The "isolated vertex" fallback `(0.0, 0.0, 1.0, 0.0)` defaults to dirt, not a biome-appropriate ground.
  - Normalization is by `r+g+b+a` total per-vertex (not per-channel sum across vertices) — fine for sum=1 but silently *also normalizes alpha*, which means a corruption pixel with a=1 has its R/G/B forced to zero. That's not how Megascans splatmaps work — alpha should be a *separate* mask layer.
- **AAA gap:** Vertex resolution. For a 256×256 vertex grid, splat resolution = 65k samples vs. a real 1024×1024 splatmap = 1M samples (15× coarser). Texture-resolution splatmaps with anti-aliased blends are AAA standard.
- **Severity:** High (compared to AAA, this is hobby-tier).
- **Upgrade to A:** Bake to a real `splatmap_RGBA.png` texture sampled per-pixel; drive zone_weights from `BIOME_PALETTES_V2` per-biome; treat alpha as orthogonal not as a 4th-of-RGBA budget.

### 1.9 `apply_corruption_tint` — `terrain_materials.py:1281`
- **Prior grade:** B+
- **My grade:** B+ — AGREE
- **What it does:** Lerps RGB toward `_CORRUPTION_PURPLE` and pushes alpha → 1 by `1-(1-a)*c`.
- **Reference:** Standard `lerp(a, b, t)` overlay. Alpha curve is the canonical "screen" combine.
- **Bug/gap:** Tint is in *linear sRGB* (palette dark `0.12, 0.04, 0.14`) but applied directly to vertex colors which Blender interprets as linear *or* sRGB depending on the color attribute color space — there is no explicit color space tag. With `FLOAT_COLOR` attributes (which `handle_setup_terrain_biome` uses) Blender treats them as linear; OK. With `BYTE_COLOR` it would be sRGB and the tint would be wrong gamma. The function does not document or enforce this.
- **AAA gap:** Modifies all four channels of the splatmap — see §1.8: alpha conflation. A real corruption mask should be a 5th layer.
- **Severity:** Medium (silent gamma assumption).
- **Upgrade to A:** Take an explicit `linear: bool = True` param; document FLOAT_COLOR contract; produce a separate corruption mask channel rather than mutating splatmap.

### 1.10 `_simple_noise_2d` (with nested `_hash`) — `terrain_materials.py:1323` (`_hash` at 1342)
- **Prior grade:** B
- **My grade:** C+ — DISPUTE (down one)
- **What it does:** Hash-lattice value-noise with Hermite (smoothstep) interpolation.
- **Reference:** This is *value noise*, not gradient noise. Value noise has visible axis-aligned grid artifacts; AAA biome boundaries use Perlin/Simplex/OpenSimplex2 *gradient* noise. The `_hash` constants `374761393, 668265263, 0x5DEECE66D` are reasonable; the `% 10000 / 5000.0 - 1.0` discretization throws away ~17 bits of entropy and produces a coarsely-quantized output.
- **Bug/gap (file:line):**
  - `terrain_materials.py:1342-1345`: `seed * 1274126177` → for large seeds and `xi*374761393` integer overflow on Python is a non-issue (arbitrary precision), but the XOR with `0x5DEECE66D` then `& 0x7FFFFFFF` collapses to 31 bits. The final `% 10000` only uses ~13 bits.
  - The "Hermite" smoothing is `t² (3 − 2t)` — *cubic*, not Hermite. Should be called smoothstep. Quintic (Perlin) `6t⁵−15t⁴+10t³` is C² and is the AAA standard for noise interpolation; cubic is C¹ which causes derivative discontinuities visible as faceting on slopes/normals.
  - Coordinate-axis bias (value noise has obvious grid lines).
- **AAA gap:** Real biome boundaries in Horizon use gradient OpenSimplex2 + domain warp. This produces visibly procedural straight-ish boundaries.
- **Severity:** Medium (only used for biome transition edges, but those are visible).
- **Upgrade to A:** Replace with `pyfastnoise2`/SimplexNoise; quintic interpolation; full 32-bit hash output.

### 1.11 `compute_biome_transition` — `terrain_materials.py:1358`
- **Prior grade:** B+
- **My grade:** B — DISPUTE (down half)
- **What it does:** Per-vertex blend factor `t` between two biomes' v2-weight outputs across an axis-aligned boundary, with noise displacement and smoothstep softening.
- **Reference:** Comparable to RDR2's biome-blend implementation but simpler — RDR2 uses a 2D Voronoi region map and per-edge SDF.
- **Bug/gap (file:line):**
  - `terrain_materials.py:1431-1434`: `boundary_axis` only supports `"x"` or `"y"` — no diagonal, no curved, no 2D mask.
  - `terrain_materials.py:1456-1457`: noise input uses `vy * noise_scale` and `vz * noise_scale` — taking *Z* (vertical) as a noise axis means a column of vertices at the same XY but different Z gets different blend factors → vertical striping at cliff faces. Should use only XY.
  - `terrain_materials.py:1485-1492`: re-normalises after blend, but if both source weight tuples are normalized to sum=1, the lerp is *already* normalized to sum=1 (linear combination preserves sums). The defensive renormalize is fine but unneeded.
  - Calls `auto_assign_terrain_layers` *twice* per call (once per biome) — for a 256k vertex mesh that is two full slope traversals (~2× 0.5s = 1s of pure-Python overhead). Should compute slopes once and pass through.
- **AAA gap:** No 2D mask support → cannot do the world-region biome graph that AAA terrain uses (Voronoi regions or paint-region masks).
- **Severity:** High (vertical striping bug, perf).
- **Upgrade to A:** Use only XY for noise input; accept a precomputed `weights_a` and `weights_b` rather than recomputing; support an arbitrary 2D mask (`region_mask: np.ndarray`).

### 1.12 `height_blend` — `terrain_materials.py:1508`
- **Prior grade:** B+
- **My grade:** B+ — AGREE
- **What it does:** Pure-Python scalar height-blend `clamp((h_a − h_b + offset)·contrast + 0.5)·mask`. Contrast scaled 1×–20×.
- **Reference:** Matches the canonical UE5 `LB_HeightBlend` formula. The `+0.5` bias centers the blend around equal heights, the contrast multiplier sharpens the transition. Standard.
- **Bug/gap (file:line):**
  - `terrain_materials.py:1542`: `result = height_diff * mask` — multiplying by `mask` *after* clamp means a `mask=0.5` cell *with full A height dominance* still only gets `0.5` blend factor. Real height-blend should be `lerp(0, height_diff, mask)` style or the mask should gate *which* layer wins, not scale the result. As written, `mask=0` always returns `0` (always layer A) regardless of `h_a`/`h_b` — the mask becomes a hard "select A" override rather than a soft gradient.
  - The function name is *blend factor* but the docstring says `0.0 = use layer A, 1.0 = use layer B` — that contradicts the multiply-by-mask line which makes mask=0 always layer A. Internally consistent but semantically muddy.
- **AAA gap:** No per-layer height-bias (gamma) — `terrain_materials_ext.compute_height_blended_weights` already covers that. This is the simpler sibling.
- **Severity:** Medium (semantic ambiguity).
- **Upgrade to A:** Define mask as the splatmap weight-ratio between A and B and compute `t = smoothstep(mask − k, mask + k, h_a − h_b + offset)` like the canonical formula.

### 1.13 `_create_height_blend_group` (with nested `_new_input`) — `terrain_materials.py:1548` (`_new_input` at 1588)
- **Prior grade:** B
- **My grade:** B — AGREE
- **What it does:** Builds a Blender shader node group implementing `clamp((h_a − h_b)·contrast_scaled + 0.5) · mask`. Idempotent (returns existing group if name collides). Has Blender 4.0+ `interface.new_socket` path with 3.x fallback.
- **Reference:** Confirmed against Blender 4.5 docs (Context7 query): `NodeTreeInterface.new_socket(name, in_out, socket_type)` is the canonical 4.x API.
- **Bug/gap (file:line):**
  - `terrain_materials.py:1588-1600`: `_new_input` swallows the `socket_type` argument when called for `Mask` and `Blend_Contrast` with no explicit type → defaults to `NodeSocketFloat` ✓, but `min_value`/`max_value` kwargs are passed via `setattr` only if the attr exists. On Blender 4.1+ the float socket's range attrs are `min_value`/`max_value` on the *interface socket*, not the deprecated `inputs` socket — so the `else: sock = group.inputs.new(...)` branch may silently drop the range. Acceptable for fallback path.
  - `terrain_materials.py:1601-1605`: same group is reused if it exists — but if the shader-graph topology changed between authoring versions, the cached group is stale. No version stamp.
  - `terrain_materials.py:1656-1664`: the `mask_mult` step inherits the `height_blend` semantic bug — multiplying the clamped height-diff by the mask makes the mask a hard gate. See §1.12.
- **AAA gap:** No per-layer height bias (gamma), no triplanar input, no explicit "transition softness" socket. UE5's `MakeMaterialAttributesFromHeightBlend` exposes per-layer transition values.
- **Severity:** Medium
- **Upgrade to A:** Add `Transition_Softness` socket; replace mask-multiply with smoothstep-around-mask; tag group with `version` int property and rebuild on mismatch.

### 1.14 `handle_setup_terrain_biome` — `terrain_materials.py:1673`
- **Prior grade:** B
- **My grade:** B- — DISPUTE (down half)
- **What it does:** Top-level Blender command handler that (a) optionally lists biomes, (b) builds Blender materials for each palette key by looking up `_get_material_def`, (c) appends to mesh material slots, (d) assigns face material indices via `assign_terrain_materials_by_slope`, (e) paints vertex colors via `blend_terrain_vertex_colors`, (f) optionally tints via `apply_corruption_tint`.
- **Reference:** This wires together the *legacy* path. Not the v2 path. Both paths now exist in parallel.
- **Bug/gap (file:line):**
  - `terrain_materials.py:1773-1775`: `slot_offset = len(obj.material_slots) - len(mat_keys)` is a heuristic that breaks if material slots were already partially populated. It silently clamps negative to 0 — the assignment then collides with existing slots. Real fix: track the index range of newly-appended slots explicitly.
  - `terrain_materials.py:1748-1764`: when reusing an existing material (`mat is None` is false), the new-material branch sets `bsdf` defaults; reuse skips them. So if the user changes `MATERIAL_LIBRARY[key]['base_color']` between runs, existing materials don't update. Should rebuild or at least overwrite the BSDF defaults.
  - `terrain_materials.py:1746-1766`: builds *only* a Principled BSDF with flat `base_color/roughness/metallic` — no procedural recipe, no normal chain, no roughness variation. Compare to `procedural_materials.build_stone_material` which does everything. This handler creates *materially worse* materials than the procedural builders for the same keys.
  - `terrain_materials.py:1781-1801`: writes vertex colors to `CORNER` domain (per-loop) using `vi = mesh.loops[li].vertex_index`. Correct.
- **AAA gap:** Per-face material slots + vertex-color splatmap is a Quake-era topology (see §1.7). Modern: single material with multi-layer splatmap texture.
- **Severity:** High (technical debt).
- **Upgrade to A:** Deprecate this handler in favor of `handle_create_biome_terrain` (v2 path with `create_biome_terrain_material`).

### 1.15 `auto_assign_terrain_layers` — `terrain_materials.py:1948`
- **Prior grade:** A-
- **My grade:** A- — AGREE
- **What it does:** Per-vertex 4-channel splatmap weights (R=ground, G=slope, B=cliff, A=special) computed from per-vertex slope angle (averaged from incident face normals), height percentile, and optional moisture-map sampling. Renormalizes to sum=1, with biome-aware special-band policy injected by `_resolve_special_band_policy`.
- **Reference:** Closely matches the auto-paint heuristics in UE5 Landscape's "AutoPaint Material Function" template (slope+altitude+moisture). The smoothstep-style `t = angle/slope_flat_rad` and `t = (angle-flat)/(cliff-flat)` linear bands inside-zone are correct.
- **Bug/gap (file:line):**
  - `terrain_materials.py:2018-2020`: `nz_n = nz / length` then `dot = clip(nz_n, -1, 1)` then `acos(dot)` — for an inverted face (downward-normal averaged with upward-normals near a cliff overhang) this produces angles near π (180°), which the slope tests treat as a steeper cliff. Should be `abs(nz_n)` like `_face_slope_angle` does.
  - `terrain_materials.py:2050-2057`: `t = angle / slope_flat_rad` is a *linear* ramp inside zone — visible banding at the boundary. Should be smoothstep.
  - `terrain_materials.py:2066-2067`: `mi = int(...v_coord*(m_rows-1))` uses nearest-neighbor moisture sampling — visible mosaic at coarse moisture grids. Should bilerp.
  - `terrain_materials.py:2074-2079`: `r = r * 1.2` then alpha is added independently — `r * 1.2` may exceed 1.0 before the renormalize; renormalize divides by `rgb_sum` then scales by `1 - a`, which restores sum=1 but *loses* the boost relative to other channels because the boost is rescaled away. The intended effect (boost ground at high moisture) is therefore *partially canceled*. Subtle.
  - `terrain_materials.py:2096-2100`: special-channel formula uses two linear ramps (`1 - h_pct/special_low_pct` for low, `(h_pct-special_high_pct)/(1-special_high_pct)` for high) — linear. Should be smoothstep.
- **AAA gap:** No curvature input. UE5/Senua II auto-paint uses 4 axes (slope, altitude, curvature, wetness). Curvature lets ridges and valleys differ.
- **Severity:** Medium (visible linear-ramp banding).
- **Upgrade to A:** Add curvature term; replace linear `t` with `t*t*(3-2t)` smoothstep; bilerp moisture; use `abs(nz_n)`.

### 1.16 `_resolve_biome_palette_name` — `terrain_materials.py:2119`
- **Prior grade:** A
- **My grade:** A — AGREE
- **What it does:** Maps `(biome, season)` → resolved key, with `mountain_pass` season aliases.
- **Reference:** Standard.
- **Bug/gap:** Hardcoded to `mountain_pass` only. Adding seasonal variants for other biomes requires editing this function — should be a `SEASON_ALIASES` dict.
- **Severity:** Low
- **Upgrade to A+:** Table-driven aliases.

### 1.17 `_resolve_special_band_policy` — `terrain_materials.py:2135`
- **Prior grade:** A-
- **My grade:** A- — AGREE
- **What it does:** Returns biome-aware overrides for `special_low_pct`, `special_high_pct`, and the `restrict_low_to_ground`/`restrict_high_to_ground` flags. For mountain-pass biomes, restricts the special channel to low ground only (avoids snow contour rings).
- **Reference:** This is a good piece of domain knowledge — the snow-contour ringing at fixed altitudes is a real artifact in slope-driven splatting.
- **Bug/gap:** Only mountain_pass biomes get the special policy. Crystal cavern, mushroom forest etc. have similar issues that aren't addressed.
- **Severity:** Low
- **Upgrade:** Generalize to a per-biome `SPECIAL_POLICY` table.

### 1.18 `_clamp_rgba` — `terrain_materials.py:2162`
- **Prior grade:** A
- **My grade:** A — AGREE
- **What it does:** Scales/biases RGB and clamps to [0,1] while preserving alpha.
- **Reference:** Standard. Used by `_build_terrain_recipe` to make dark/light variants of base color.
- **Bug/gap:** Type annotation references `Sequence[float]` but `Sequence` is not imported (only `Any` from `typing`). Saved by `from __future__ import annotations` at line 21 — annotations are strings. Still triggers warnings in strict type checkers.
- **Severity:** Low (cosmetic).
- **Upgrade:** Add `from collections.abc import Sequence, Mapping` near top.

### 1.19 `_build_terrain_recipe` (with nested `_hook_vector`) — `terrain_materials.py:2172` (`_hook_vector` at 2190)
- **Prior grade:** A-
- **My grade:** A- — AGREE
- **What it does:** Builds a per-layer Blender shader sub-graph for terrain materials with three branches: `stone` (Voronoi fracture + Wave strata + bump), `organic` (multi-octave Noise + Bump), and `terrain` default (multi-scale Noise + Bump). Returns a "height_socket" output that downstream code wires into the height-blend group.
- **Reference:** Substance-Designer-style node graph authoring inside Blender. The stone branch with Voronoi-fracture + Wave-strata is a standard "fractured rock" recipe.
- **Bug/gap (file:line):**
  - `terrain_materials.py:2179`: `Mapping[str, Any]` not imported (see §1.18).
  - `terrain_materials.py:2207-2219`: `strata.wave_type = "BANDS"` and `strata.bands_direction = "Z"` — Z-aligned bands on a terrain mesh oriented Z-up means horizontal strata lines, which is geologically correct. But this is *world-space*, not surface-space, so a tilted cliff face shows misaligned strata. Should use object/UV mapping rotated to the cliff normal.
  - `terrain_materials.py:2280-2284`: `bump.inputs["Strength"].default_value = normal_strength * 0.54` — magic 0.54 multiplier. Comparable values for organic (0.72) and terrain (0.72 + wear*0.30). Why these constants? No comment.
  - `terrain_materials.py:2247-2253`: `shape_ramp` has hardcoded `(0.03,...)` and `(0.96,...)` element colors — does not respect the layer base_color, only uses it for the Mix RGB inputs. Means stone normal-driven contrast is identical regardless of biome (a wet swamp stone has the same dark/light ramp as a desert sandstone).
  - `terrain_materials.py:2222-2231`: `fracture` Voronoi at `detail_scale * 0.82` is correct, but `fracture_mix.inputs[1].default_value = 0.12` — magic 0.12 means fracture contributes at most 12% of height, which is too little for actual rock fracturing. Compare to Megascans rock surfaces where fracture is the dominant macro feature.
  - No triplanar mapping. A vertical cliff face textured with object-space coordinates stretches along the world-Z axis. AAA cliffs use triplanar projection (three planar projections weighted by `pow(abs(normal), k)`).
- **AAA gap:** No triplanar; world-space strata; magic-numbered constants tuned by feel not by reference asset.
- **Severity:** Medium-High (no triplanar = visibly stretched cliffs).
- **Upgrade to A:** Add triplanar branch for `stone` recipe; expose magic constants as named params; rotate strata to face normal; let base_color drive stone_dark/stone_light bias.

### 1.20 `compute_world_splatmap_weights` — `terrain_materials.py:2365`
- **Prior grade:** B+ (per-spec rule with proper renormalize but no per-layer height-blend gamma)
- **My grade:** B+ — AGREE
- **What it does:** Fully vectorized numpy implementation of the world-tiled v2 splatmap: takes a 2D heightmap, computes slope via `compute_slope_map`, applies the same slope/altitude/moisture rules as `auto_assign_terrain_layers`, returns `(H,W,4)` RGBA weights normalized to sum=1.
- **Reference:** Per the user's grading rule, this is **B** (renormalized splatmap weights without per-layer height-blend gamma). Bumped to B+ because the implementation is *correct* numpy and the docstring honestly notes the previous slow path.
- **Bug/gap (file:line):**
  - `terrain_materials.py:2462-2474`: same `r * 1.2` boost-then-normalize cancellation as §1.15.
  - `terrain_materials.py:2452-2454`: `np.where(is_flat, 1-t_flat, ...)` — three nested `np.where` calls. Numpy idiom is fine but readability suffers vs. building per-mask masks once.
  - `terrain_materials.py:2502-2505`: `with np.errstate(...): scale = np.where(rgb_sum>0, remaining/rgb_sum, 0)` — the `errstate` correctly suppresses RuntimeWarning, then the `np.where` correctly handles the divide-by-zero fallback. Good.
  - `terrain_materials.py:2507`: returns `np.float64` even though splatmaps are typically saved as `uint8` × 4 channels (256 quantization levels). Caller has to cast. Consider returning `float32` like `terrain_materials_v2.compute_slope_material_weights` does.
  - No per-layer height bias (snow on peaks via gamma curve, valley moss via 1/gamma) — relies entirely on hard altitude band thresholds.
- **AAA gap:** No height-blend per layer; no curvature; no shoreline carving (the special channel uses altitude not water-distance).
- **Severity:** Medium
- **Upgrade to A:** Pipe output through `terrain_materials_ext.compute_height_blended_weights` for the gamma stage; return float32; add curvature.

### 1.21 `create_biome_terrain_material` — `terrain_materials.py:2515`
- **Prior grade:** B
- **My grade:** B — AGREE
- **What it does:** Builds the Blender material graph for a v2 biome: 4 Principled BSDFs (one per layer) + per-layer recipe sub-graphs from `_build_terrain_recipe`, then chains 3 `MixShader` + `_create_height_blend_group` instances driven by the splatmap separated into RGBA channels. Optionally clears the mesh's existing material slots and writes a vertex-color attribute.
- **Reference:** Right architecture (single material, multi-BSDF, splatmap-driven mix). UE5's `LayerBlend_Standard` material function does the same thing as a node graph.
- **Bug/gap (file:line):**
  - `terrain_materials.py:2540-2548`: `mat = bpy.data.materials.get(mat_name)` reuses existing material then `nodes.clear()` rebuilds it. Good — palette edits propagate.
  - `terrain_materials.py:2604-2605`: `mix_01 = MixShader(layer[0], layer[1])` — chains 3 MixShader nodes is `O(N)` in shader instructions but each pair only blends two layers. With 4 layers this is fine; with 8 layers you'd want a tree.
  - `terrain_materials.py:2611`: `links.new(separate.outputs["Green"], hb_01.inputs["Mask"])` — uses the splatmap *G* channel as the ground/slope mix mask. But the splatmap G is the *slope* weight, not a relative mask between ground and slope. The intended semantic of HeightBlend's mask socket is the relative weighting `slope_w / (ground_w + slope_w)`. As wired, when both ground and slope have weight 0.5, the mix uses mask=0.5 (correct only if ground_w + slope_w = 1, which is rare since R + G + B + A = 1).
  - `terrain_materials.py:2624`: `links.new(separate.outputs["Blue"], hb_02.inputs["Mask"])` — same semantic issue; B is the absolute cliff weight, not relative.
  - `terrain_materials.py:2637`: `links.new(vcol_node.outputs["Alpha"], hb_03.inputs["Mask"])` — uses raw alpha. Same issue.
  - `terrain_materials.py:2648-2650`: `mesh.materials.clear()` destroys existing material slots — destructive without warning.
  - `terrain_materials.py:2666-2673`: `preserve_existing_splatmap` logic — checks if any existing color attribute pixel has nonzero sum; if yes, skip repaint. Hidden behavior — caller doesn't see what was preserved.
  - `terrain_materials.py:2676-2679`: `mesh.calc_normals_split()` is deprecated in Blender 4.0+ and replaced by automatic split-normal handling; `calc_normals` was removed in 4.0. The fallback chain works but should warn or skip on 4.x.
  - `terrain_materials.py:2699-2708`: *second* identical material-clear-and-append block at the bottom — duplicate of lines 2648-2655. Dead code or bug.
- **AAA gap:** Splatmap channels are wired as absolute weights into mix-shader masks rather than as relative pair masks. UE5 `LayerBlend` handles this internally with its `Layer.Weight` semantics.
- **Severity:** High (mix-mask semantic bug); High (duplicate block).
- **Upgrade to A:** Compute pair-relative masks `g/(r+g)` etc. as Math nodes before each HeightBlend group; remove the duplicate material-clear block at line 2699; gate `calc_normals_split` on Blender version.

### 1.22 `handle_create_biome_terrain` — `terrain_measure_materials.py:2713`
- **Prior grade:** A-
- **My grade:** A- — AGREE
- **What it does:** MCP/JSON command-handler wrapper around `create_biome_terrain_material` with list mode and result dict.
- **Reference:** Standard handler shape.
- **Bug/gap:** `bpy.data.objects.get(object_name)` at line 2760 happens *after* `create_biome_terrain_material` already called the same lookup — duplicate lookup, no major perf issue but redundant.
- **AAA gap:** None for the handler shape itself.
- **Severity:** Low
- **Upgrade:** Have `create_biome_terrain_material` return the resolved object alongside the material to avoid the second lookup.

---

## FILE 2 — `terrain_materials_ext.py` (234 LoC)

Bundle B Addendum 1.B.2 supplement. Adds height-blend gamma, texel-density coherency, micro-normal metadata, cliff silhouette area validation. Headless-compatible (no bpy).

### 2.1 `class MaterialChannelExt` (with `channel_id` property) — `terrain_materials_ext.py:29`
- **Prior grade:** A
- **My grade:** A — AGREE
- **What it does:** Wraps a Bundle B `MaterialChannel` and adds `height_blend_gamma`, `texel_density_m`, `micro_normal_texture`, `micro_normal_strength`, `respects_displacement`. Property forwards `channel_id`.
- **Reference:** Field set matches Unreal Material Layer Blend Asset and Unity Terrain Layer mask map fields. Megascans channels expose the same five concepts.
- **Bug/gap:** No validator for `height_blend_gamma > 0` (a zero or negative gamma would crash `np.power`).
- **AAA gap:** No `displacement_texture` path or `pom_steps` parameter — those are AAA POM/Tessellation features.
- **Severity:** Low
- **Upgrade to A+:** Add `__post_init__` validation; expose POM params.

### 2.2 `validate_texel_density_coherency` — `terrain_materials_ext.py:57`
- **Prior grade:** A
- **My grade:** A — AGREE
- **What it does:** Flags channels whose `texel_density_m` ratio vs. the minimum exceeds `max_ratio` (default 2.0).
- **Reference:** Texel-density coherency is a real AAA QC rule (Quixel uses 256 px/m as the Megascans standard; mixing 64 px/m with 256 px/m is visible).
- **Bug/gap:** Returns `[issue]` with code `MAT_TEXEL_DENSITY_INVALID` for `min_d <= 0` and *short-circuits return* — only the first invalid channel is reported. Should report all invalid channels.
- **AAA gap:** Only checks ratio vs. minimum. Should also check vs. *world-pixel-per-meter target* (default 256 in Megascans). A density of 32 with a min of 32 would pass this check but fails the AAA threshold.
- **Severity:** Low-Medium
- **Upgrade to A:** Aggregate all invalid channels; add absolute-density-floor check.

### 2.3 `compute_height_blended_weights` — `terrain_materials_ext.py:105`
- **Prior grade:** A-
- **My grade:** A — DISPUTE (up half)
- **What it does:** Per-spec **A-grade implementation**: takes `(H,W,L)` base splatmap weights, `(H,W)` heightmap, `(L,)` per-channel gammas. Normalizes heights to [0,1] *per call* without mutating the world-meter source (per Rule 10), applies `pow(h01, gamma)` for gamma≥1 (peak-biased) and `pow(1-h01, 1/gamma)` for gamma<1 (valley-biased), multiplies into base weights, renormalizes to sum=1 with safe fallback to base weights when total collapses.
- **Reference:** This is **the canonical "Megascans/UE5 Height Lerp" recipe** — snow on peaks via high gamma, moss in valleys via low gamma. Per the user's spec rule, presence of per-layer gamma + renormalization = **A**.
- **Bug/gap (file:line):**
  - `terrain_materials_ext.py:160-163`: when `total <= 1e-9` the fallback restores the *unmodified base weights*. This is correct and well-defined, but means a cell that was *intended* to fade out (all gamma curves drove its layers to 0) will appear in the output with the original splatmap colors. The prior audit called this "leaks the unmodified base into the output" — actually this is the *only* well-defined behavior; the alternative is to leave the cell black or pick the dominant-by-base channel.
  - No validation that gammas are positive (handled by `max(g, 1e-6)` clamp at line 146 — good).
- **AAA gap:** None — this is the AAA recipe. The only thing missing for an A+ would be exposing a `bias` term so the height curve can be offset (Substance Designer's "Height Blend" filter exposes both a contrast and a bias).
- **Severity:** —
- **Upgrade to A+:** Add `bias_per_channel: Optional[Sequence[float]]` parameter; document the fallback semantic explicitly in the docstring.

### 2.4 `validate_cliff_silhouette_area` — `terrain_materials_ext.py:180`
- **Prior grade:** A-
- **My grade:** A- — AGREE
- **What it does:** Hard-rejects cliffs that occupy < 8% of the frame (hero) or < 3% (secondary).
- **Reference:** Visible-feature thresholds are a real AAA QC rule (Naughty Dog's encounter-design playbook talks about 5–10% silhouette coverage for landmark features).
- **Bug/gap:** Tier validation: lowercases the string and accepts only `"hero"`/`"secondary"`. Magic-numbered thresholds — should be configurable.
- **AAA gap:** Only validates pixel coverage. Doesn't check *contrast against background* — a 10%-coverage cliff that matches the sky color is invisible. AAA QC also checks luminance contrast.
- **Severity:** Low
- **Upgrade to A:** Add optional `background_luminance` parameter and check Weber contrast.

---

## FILE 3 — `terrain_materials_v2.py` (374 LoC)

Bundle B canonical materials pass. Slope/altitude/curvature/wetness-driven splatmap weights via vectorized numpy, registered as a TerrainPassController pass. This is the *correct* architecture; everything in `terrain_materials.py` should converge here.

### 3.1 `class MaterialChannel` — `terrain_materials_v2.py:40`
- **Prior grade:** A
- **My grade:** A — AGREE
- **What it does:** Dataclass declaring per-channel envelope fields (slope_min/max/falloff in radians, altitude_min/max/falloff in world meters, curvature_min/max, wetness_min/max, base_weight, triplanar flag, base_color_hex, roughness, metallic).
- **Reference:** Direct analog to UE5 `LandscapeLayerInfoObject` + Unity `TerrainLayer` per-layer envelope. Field set is correct for slope-driven splatmap authoring.
- **Bug/gap:**
  - No validation: `slope_min > slope_max` is allowed; `base_weight < 0` is allowed; `base_color_hex` is not parsed (just a string).
  - No micro/macro-normal fields here — they live in the `Ext` wrapper. Awkward split.
- **AAA gap:** Real AAA channel descriptors include displacement/POM params, micro normal, macro variation tile, base AORM. The Ext wrapper covers some but not all.
- **Severity:** Low
- **Upgrade to A+:** Merge `Ext` fields into base; add `__post_init__` validation; parse `base_color_hex` to RGB.

### 3.2 `class MaterialRuleSet` (with `__post_init__` and `index_of`) — `terrain_materials_v2.py:73`
- **Prior grade:** A
- **My grade:** A — AGREE
- **What it does:** Tuple of `MaterialChannel` + `default_channel_id`. `__post_init__` checks unique IDs and that default is in the set. `index_of` linear-scan lookup.
- **Reference:** Standard. Correctly enforces uniqueness invariant.
- **Bug/gap:** `index_of` is O(N) per call; called once per pass per channel so OK for small N. No caching.
- **AAA gap:** None.
- **Severity:** —
- **Upgrade:** Cache `index_of` as a dict at `__post_init__`.

### 3.3 `default_dark_fantasy_rules` — `terrain_materials_v2.py:106`
- **Prior grade:** A-
- **My grade:** A- — AGREE
- **What it does:** Returns 5 channels (ground, cliff, scree, wet_rock, snow) with per-channel envelopes tuned for dark fantasy. Default = "ground".
- **Reference:** Channel set is sensible for dark fantasy — though "wet_rock" with `wetness_min=0.3` requires a wetness mask which isn't always available.
- **Bug/gap:**
  - `terrain_materials_v2.py:144-146`: scree's `altitude_max_m=200.0` is a hardcoded world-altitude assumption — assumes terrain max ≈ 200m. For a tall mountain biome this clips scree off.
  - `terrain_materials_v2.py:168`: snow's `altitude_min_m=250.0` likewise hardcoded.
  - No per-biome variants — same rules for thornwood and crystal cavern.
- **AAA gap:** UE5 Open World Demo's auto-paint material has 8 layers and biome variants. Our 5 channels with one rule set for all biomes is AA-grade, not AAA.
- **Severity:** Medium
- **Upgrade to A:** Per-biome rule-set variants; altitude thresholds expressed as percentile of the actual terrain range, not absolute meters.

### 3.4 `_smoothstep_band` — `terrain_materials_v2.py:181`
- **Prior grade:** A
- **My grade:** A- — DISPUTE (down half)
- **What it does:** Returns `up(value, lo) * down(value, hi)` where `up` ramps 0→1 over `[lo-f, lo]` and `down` ramps 1→0 over `[hi, hi+f]`.
- **Reference:** This is a *trapezoidal* mask, not a smoothstep. Real smoothstep is `t*t*(3-2t)`. The function uses linear ramps, which produces visible banding at zone boundaries when the gradient crosses the mask edge.
- **Bug/gap:** The name `_smoothstep_band` is misleading — it's `_trapezoidal_band`. Apply `t*t*(3-2t)` to `up` and `down` for true smoothstep.
- **AAA gap:** Linear ramps cause C¹ discontinuities visible as faceting.
- **Severity:** Medium (naming + visible artifact).
- **Upgrade to A:** Apply Hermite smoothstep `up = up*up*(3-2*up)`.

### 3.5 `compute_slope_material_weights` — `terrain_materials_v2.py:195`
- **Prior grade:** A-
- **My grade:** A- — AGREE
- **What it does:** Vectorized per-channel envelope computation from stack's slope/height/curvature/wetness, fallback default-channel for zero-total cells, normalize to sum=1.
- **Reference:** Correct numpy vectorization. Matches Unity HDRP TerrainLit splatmap normalization contract (sum to 1, no negative weights).
- **Bug/gap (file:line):**
  - `terrain_materials_v2.py:237-246`: `curv_w = np.where((curvature >= min) & (curvature <= max), 1.0, 0.0)` — *hard* gate, no smoothstep band. Same for `wet_w`. The slope/altitude axes get the trapezoidal `_smoothstep_band` treatment, the curvature/wetness axes do not. Inconsistent and produces sharp transitions.
  - `terrain_materials_v2.py:247`: `combined = base_weight * slope_w * alt_w * curv_w * wet_w` — multiplicative AND across all four envelopes. If any one is 0, the channel is 0. With hard curv/wet gates that means a cell with curvature `1e-9` outside the band gets exactly 0 — a knife-edge transition.
  - `terrain_materials_v2.py:255`: fallback assigns weight=1.0 to default channel. Correct fallback semantic.
- **AAA gap:** Curvature/wetness need smoothstep banding too. Per-spec rule, this is **B** (no per-layer height-blend gamma) — bumped to A- because the architecture is right and gamma can be added downstream via `compute_height_blended_weights`.
- **Severity:** Medium (hard curv/wet gates).
- **Upgrade to A:** Replace `np.where` with `_smoothstep_band(curvature, min, max, falloff_curvature)`; add `curvature_falloff` and `wetness_falloff` fields to MaterialChannel.

### 3.6 `pass_materials` — `terrain_materials_v2.py:269`
- **Prior grade:** A
- **My grade:** A — AGREE
- **What it does:** Bundle B pass adapter — derives a deterministic seed via `derive_pass_seed`, computes new weights via `compute_slope_material_weights`, region-scopes by merging with existing weights when a region BBox is given, stores results in `splatmap_weights_layer` and `material_weights`, returns `PassResult` with per-layer coverage metrics and dominant-layer detection.
- **Reference:** Correct PassController contract. Region scoping with merge-into-existing is the right approach for tiled / regional updates.
- **Bug/gap (file:line):**
  - `terrain_materials_v2.py:284-295`: `seed = derive_pass_seed(...)` is computed but never *used* downstream — `compute_slope_material_weights` is deterministic and doesn't take a seed. The `seed_used` metric is reported but the weights are seed-independent. Dead seed.
  - `terrain_materials_v2.py:316-321`: when `existing is None`, the merged tensor is initialized to zeros and only the region is filled. Cells outside the region have all-zero splatmap (`sum=0`), which downstream consumers might reject. The comment acknowledges this — "Leave outside cells as zero-sum (downstream code can treat that as 'not authored yet')". OK if downstream is consistent.
  - `terrain_materials_v2.py:323-324`: stores the *same* tensor in two channels (`splatmap_weights_layer` and `material_weights`). The two names exist for legacy reasons. Aliasing means a downstream pass that mutates one mutates both — risky.
- **AAA gap:** None for the pass shape itself. Region merging is good.
- **Severity:** Low (dead seed, aliasing)
- **Upgrade to A+:** Remove the seed computation if not used; deep-copy when storing into the second channel name.

### 3.7 `register_bundle_b_material_passes` — `terrain_materials_v2.py:349`
- **Prior grade:** A
- **My grade:** A — AGREE
- **What it does:** Registers `pass_materials` on the global `TerrainPassController` with channel I/O contract.
- **Reference:** Standard plugin-registration shape.
- **Bug/gap:** None.
- **Severity:** —
- **Upgrade:** None.

---

## FILE 4 — `procedural_materials.py` (1870 LoC)

The procedural Blender shader-graph library — 45+ named materials with a 6-recipe builder dispatch (stone, wood, metal, organic, terrain, fabric). This is *the* module that creates real Blender materials with multi-octave noise, Voronoi cells, color ramps, bump nodes, and a 3-layer micro/meso/macro normal cascade. Far better than `terrain_materials.handle_setup_terrain_biome`.

### 4.1 `validate_dark_fantasy_color` — `procedural_materials.py:61`
- **Prior grade:** A-
- **My grade:** A- — AGREE
- **What it does:** Clamps color to saturation ≤ 0.40 and value 0.10–0.50 in HSV. Uses `colorsys`.
- **Reference:** VeilBreakers palette rule. Correctly notes that metallic colors should not be passed through this.
- **Bug/gap:**
  - Uses `colorsys.rgb_to_hsv` which expects sRGB-like values. The library tuples are documented as "linear sRGB" but `colorsys` treats them as gamma-encoded sRGB. So the saturation/value computations are *gamma-incorrect*. For dark colors (V≈0.10) the gamma error is small; for bright colors it matters.
  - Returns 3-tuple but library entries are 4-tuples (RGBA). Caller has to repack. No alpha pass-through.
- **AAA gap:** No validation that the input is in [0,1] — a value > 1 is silently re-saturated.
- **Severity:** Medium (gamma silently wrong).
- **Upgrade to A:** Convert linear → sRGB → HSV → clamp → HSV → sRGB → linear; pass alpha through; validate input range.

### 4.2 `_place` — `procedural_materials.py:895`
- **Prior grade:** A
- **My grade:** A — AGREE
- **What it does:** Sets `node.location = (x, y)`. One-liner.
- **Reference:** Trivial.
- **Bug/gap:** None.
- **Severity:** —
- **Upgrade:** None.

### 4.3 `_add_node` — `procedural_materials.py:900`
- **Prior grade:** A
- **My grade:** A — AGREE
- **What it does:** `tree.nodes.new(type=...)`, places, optionally labels.
- **Reference:** Standard Blender API call. Correct.
- **Bug/gap:** No error handling for unknown node types — `tree.nodes.new` raises `RuntimeError` on bad type.
- **Severity:** —
- **Upgrade:** None needed.

### 4.4 `_get_bsdf_input` — `procedural_materials.py:925`
- **Prior grade:** A
- **My grade:** A — AGREE
- **What it does:** Looks up Principled BSDF socket by name with Blender 3.x→4.x rename fallback table (`Subsurface Weight` → `Subsurface`, etc.).
- **Reference:** This is the **correct** way to handle Blender 4.0 BSDF socket renames — Context7 confirms the rename happened in 4.0. Fallback table is comprehensive.
- **Bug/gap:** Last-resort returns `bsdf.inputs.get(name)` again — same lookup as line 1, will always be `None`. Could just `return None` directly. Minor.
- **Severity:** —
- **Upgrade:** None.

### 4.5 `_build_normal_chain` — `procedural_materials.py:943`
- **Prior grade:** B+
- **My grade:** B+ — AGREE
- **What it does:** Builds three cascading Bump nodes (micro Noise scale 40-80, meso Voronoi scale 10-20, macro Noise scale 2-5) feeding `bump_micro.Normal → bump_meso.Normal → bump_macro.Normal → bsdf.Normal`.
- **Reference:** This is the AAA "3-layer normal cascade" technique used by Naughty Dog and Guerrilla. Multi-frequency normal maps create the illusion of detail at multiple viewing distances. Implementation is structurally correct.
- **Bug/gap (file:line):**
  - `procedural_materials.py:984`: `links.new(noise_micro.outputs["Fac"], bump_micro.inputs["Height"])` — uses `Fac` (scalar), correct for Bump.
  - `procedural_materials.py:997`: `links.new(voronoi_meso.outputs["Distance"], bump_meso.inputs["Height"])` — uses `Distance` not `Fac`. Voronoi `Distance` is unbounded; Bump's Height expects [0,1]. Should remap or normalize.
  - `procedural_materials.py:983/996/1012`: Distance values `0.002, 0.005, 0.02` are world-space step-out distances — magic numbers, not derived from material's actual physical scale.
  - No anti-tiling. The same noise scale on the same UVs produces visible repetition. Megascans uses domain warp + macro variation maps to break tiling.
  - Generates *cumulative* normal — micro feeds into meso feeds into macro. This is *correct* topology but means the macro bump's strength scales the *whole stack* — not the textbook recommendation, which is to combine via Normal Map mixing (`ShaderNodeMixShader` with `Normal Map` nodes or `Normal` math). Simple Bump cascading works but is computationally wasteful (each Bump samples the height twice for derivatives).
- **AAA gap:** No anti-tiling, no detail normal mip-bias, no per-distance LOD blend (real AAA materials fade micro detail at distance).
- **Severity:** Medium
- **Upgrade to A:** Use `ShaderNodeNormalMap` + RNM blend; add domain-warp UV input to break tiling; expose distance-fade via camera distance.

### 4.6 `build_stone_material` — `procedural_materials.py:1025`
- **Prior grade:** B+
- **My grade:** B+ — AGREE
- **What it does:** Builds a stone shader graph: Voronoi block pattern + Noise mortar + Noise surface variation + MixRGB overlay + Multiply tint + Math roughness variation + 3-layer normal chain.
- **Reference:** Recipe is approximately a Substance Designer "Stone Wall" graph. Voronoi for blocks, Noise for mortar lines, MixRGB OVERLAY for blending. Standard.
- **Bug/gap (file:line):**
  - `procedural_materials.py:1068`: `links.new(tex_coord.outputs["Object"], mapping.inputs["Vector"])` — uses Object coordinates. For terrain materials (which are used inside this builder via `node_recipe="stone"`), Object coords mean every chunk re-maps from its origin → seams between chunks. Should use Generated or World for terrain, UV for assets.
  - `procedural_materials.py:1080-1083`: ColorRamp positions `(0.4, 0.6)` for block edges produce *very narrow* mortar bands. A wider band reads better.
  - `procedural_materials.py:1118-1130`: `mix_base.blend_type = "MULTIPLY"` with `Color1 = (bc * 2.5)` clamped to 1.0. The 2.5× pre-multiply assumes that the average noise value is ~0.4 (1/2.5) so the multiplied result lands around `bc`. Magic number.
  - `procedural_materials.py:1140-1143`: `math_rough.operation = "MULTIPLY_ADD"` with `[1] = roughness_variation` and `[2] = roughness` — formula is `noise.Fac * roughness_variation + roughness`. Since `noise.Fac ∈ [0,1]`, the result range is `[roughness, roughness + roughness_variation]`. Asymmetric — should be `(noise - 0.5) * 2 * variation + roughness` for symmetric variation around the base.
  - No triplanar projection.
- **AAA gap:** No triplanar; world-Z-aligned mortar lines on cliffs; no displacement/POM; no real albedo/AORM channel pack.
- **Severity:** Medium
- **Upgrade to A:** Add triplanar branch; symmetric roughness variation; UV/Object/World coordinate-space param.

### 4.7 `build_wood_material` — `procedural_materials.py:1155`
- **Prior grade:** B+
- **My grade:** B+ — AGREE
- **What it does:** Wave (BANDS, Y direction) for grain + Noise for knots + ColorRamp for grain color + MixRGB OVERLAY + 3-layer normal chain.
- **Reference:** Classic Blender procedural wood. Wave-as-grain is correct; knots-as-noise is approximate (real wood knots are radial, not Perlin-isotropic).
- **Bug/gap (file:line):**
  - `procedural_materials.py:1186`: `tex_coord.outputs["Object"]` — wood usually wants UVs (for planks) not object coords.
  - `procedural_materials.py:1191-1198`: Wave bands are *Y-aligned* in object space. A plank rotated 90° has cross-grain. Should use UV with U-aligned.
  - `procedural_materials.py:1203-1210`: ColorRamp colors are derived as `bc * 0.5` and `bc * 1.5`, both clamped silently by Blender to [0,1]. For a dark wood `bc=(0.14, 0.11, 0.08)`, `bc*1.5 = (0.21, 0.165, 0.12)` — fine. For a brighter wood, the 1.5× clips.
  - `procedural_materials.py:1224`: `mix_knots.inputs["Fac"].default_value = wear_intensity` — wear intensity controls knot visibility, semantically odd. Wear should be edge-wear, not knots.
  - No anisotropic. Real wood is anisotropic along the grain.
- **AAA gap:** No anisotropic, no UV-space rotation control, no real radial knot modeling.
- **Severity:** Medium
- **Upgrade to A:** UV coordinates by default; anisotropic on; separate `knot_density` from `wear_intensity`.

### 4.8 `build_metal_material` — `procedural_materials.py:1252`
- **Prior grade:** B+
- **My grade:** A- — DISPUTE (up half)
- **What it does:** Two BSDFs (clean + rust/wear) with `bsdf_rust.metallic = 0.0` (rust is dielectric — PBR-correct), MixShader gated by Noise→ColorRamp rust mask, 3-layer normal chain on clean BSDF, normal also fed to rust BSDF via macro-bump lookup.
- **Reference:** **Correct PBR binary metal/dielectric handling** — rust/oxidation is dielectric and the function explicitly comments this rule. This is the right architecture.
- **Bug/gap (file:line):**
  - `procedural_materials.py:1280`: clean `roughness = max(0.05, params.roughness * 0.3)` — magic 0.3 multiplier means polished steel gets `0.20 * 0.3 = 0.06` ≈ near-mirror. Correct intent but the 0.3 should be a named constant.
  - `procedural_materials.py:1306`: rust `roughness = min(1.0, params.roughness + 0.3)` — 0.3 absolute add, magic.
  - `procedural_materials.py:1336-1343`: searches `nodes` for `node.label == "Macro Bump"` — string-match coupling to `_build_normal_chain`'s internal labels. If `_build_normal_chain` renames the macro bump node, this breaks silently.
  - No fresnel-driven edge wear (real worn metal has clean edges where wear has exposed fresh metal).
- **AAA gap:** No edge-wear via Pointiness or Curvature; no clearcoat for shine-on-rust; no SSGI-influenced AO.
- **Severity:** Medium (label-coupling fragility).
- **Upgrade to A:** Return the macro_bump node from `_build_normal_chain` instead of label-searching; add edge-wear via `ShaderNodeNewGeometry.Pointiness`.

### 4.9 `build_organic_material` — `procedural_materials.py:1350`
- **Prior grade:** B+
- **My grade:** B+ — AGREE
- **What it does:** Principled BSDF with subsurface (weight, scale, radius, color) + transmission + IOR + coat + anisotropic + emission. Voronoi pore + Noise skin variation + MixRGB OVERLAY + roughness wet/dry. Optional rim fresnel via LayerWeight + MixRGB into Emission Color.
- **Reference:** Comprehensive PBR coverage. Subsurface scale `0.005` is millimeter-scale — physically correct for skin. Subsurface radius `[1.0, 0.2, 0.1]` (R/G/B) is correct for chromatic flesh SSS.
- **Bug/gap (file:line):**
  - `procedural_materials.py:1389`: default `sss_color = (bc[0]*1.5, bc[1]*0.5, bc[2]*0.4, 1.0)` — magic transformation that pushes SSS toward red. Fine for skin, wrong for green slime.
  - `procedural_materials.py:1438`: Voronoi `feature = "F1"` — F1 distance is the standard cell pattern. Correct.
  - `procedural_materials.py:1453`: `mix_color.inputs["Fac"].default_value = 0.25` — magic 0.25 mix factor.
  - `procedural_materials.py:1481`: `layer_weight.inputs["Blend"].default_value = 0.3` — magic 0.3 fresnel blend.
  - Rim color routed into *Emission* — that's a fresnel-driven self-illumination which is artistic, not physical. Acceptable for stylized creature surfaces but not PBR-correct.
- **AAA gap:** No anisotropic-tangent control for fur direction; no per-vertex SSS variation.
- **Severity:** Low-Medium
- **Upgrade to A:** Per-material override for sss_color blend formula; expose mix_color.Fac and layer_weight.Blend as params.

### 4.10 `build_terrain_material` — `procedural_materials.py:1497`
- **Prior grade:** A-
- **My grade:** A- — AGREE
- **What it does:** Multi-scale noise (large + medium + fine) MixRGB OVERLAY chain + Geometry.Normal → SeparateXYZ.Z → ColorRamp slope mask → MULTIPLY_ADD into roughness + base color tint + 3-layer normal chain. Supports transmission and emission.
- **Reference:** This is a *good* procedural terrain shader. Multi-scale noise is the right idea; slope-driven roughness via `geometry.Normal.z` is a clean way to get cliff-vs-flat differentiation.
- **Bug/gap (file:line):**
  - `procedural_materials.py:1539`: `tex_coord.outputs["Object"]` — same Object-coord issue as stone.
  - `procedural_materials.py:1581`: `geometry = ShaderNodeNewGeometry` and `separate.outputs["Z"]` reads world-space normal Z. Correct for world-up terrain.
  - `procedural_materials.py:1590-1593`: ColorRamp `(0.3, 0.7)` for slope mask — produces slope band starting at ~73° (acos(0.3)) and ending at ~46° (acos(0.7)). Wait — ColorRamp `position 0.3` color black, `position 0.7` color white means low Z (steep) → black, high Z (flat) → white. So roughness gets *added* on flat ground, *subtracted* on cliffs. Reads correctly.
  - `procedural_materials.py:1600-1608`: 2× pre-multiply with clamp — same magic-number concern as stone.
  - No height-map output for layer blending.
- **AAA gap:** No height output for use with HeightBlend group; no triplanar; no macro variation map (Megascans uses a separate large-scale tile-breaker texture).
- **Severity:** Low-Medium
- **Upgrade to A:** Expose a height-output socket; add macro variation noise; triplanar branch.

### 4.11 `build_fabric_material` — `procedural_materials.py:1629`
- **Prior grade:** B+
- **My grade:** B+ — AGREE
- **What it does:** Brick texture for weave + Noise color variation + Sheen weight 0.3 + optional SSS + 3-layer normal chain. Uses UV coords (correct for fabric).
- **Reference:** Brick-as-weave is a budget approximation. Real fabric uses dedicated yarn-loop normal maps (e.g., MARVELOUS Designer outputs). Sheen is correctly applied.
- **Bug/gap (file:line):**
  - `procedural_materials.py:1653`: `sheen_input.default_value = 0.3` — hardcoded sheen, no per-material override.
  - `procedural_materials.py:1681-1685`: Brick `Mortar Size 0.01`, `Brick Width 0.5`, `Row Height 0.25` — produces a 2:1 brick aspect ratio, not square weave. Square weave would be 1:1.
  - `procedural_materials.py:1687-1692`: brick colors are `bc*0.9`, `bc*1.1`, `bc*0.6` for color1, color2, mortar. Mortar 0.6× of base is reasonable for shadow lines.
  - No sheen-tint (silk vs. cotton).
- **AAA gap:** Brick-as-weave is hobby-tier vs. real woven-yarn normal maps.
- **Severity:** Low (acceptable for fabric)
- **Upgrade to A:** Replace brick with a noise-warped grid + dedicated yarn normal map; expose sheen as param.

### 4.12 `create_procedural_material` — `procedural_materials.py:1742`
- **Prior grade:** A
- **My grade:** A — AGREE
- **What it does:** Top-level entry point: validates `material_key`, deep-copies entry, normalizes `base_color` to RGBA tuple, dispatches to `GENERATORS[recipe](mat, entry)`.
- **Reference:** Standard factory pattern.
- **Bug/gap:**
  - `procedural_materials.py:1769`: `entry = dict(MATERIAL_LIBRARY[material_key])` — shallow copy. If a builder mutates a nested list (e.g., `subsurface_radius`), it mutates the library. Builders don't appear to do this, but the contract is fragile.
  - `procedural_materials.py:1772-1779`: defensive RGBA padding — correct, has explicit comment about Bug 10.
- **AAA gap:** No support for material variants (e.g., `rough_stone_wall_wet`).
- **Severity:** Low
- **Upgrade to A+:** `copy.deepcopy(entry)`; variant-suffix parser.

### 4.13 `get_library_keys` — `procedural_materials.py:1798`
- **Prior grade:** A
- **My grade:** A — AGREE
- **What it does:** Returns sorted list of MATERIAL_LIBRARY keys.
- **Reference:** Trivial.
- **Bug/gap:** None.
- **Severity:** —
- **Upgrade:** None.

### 4.14 `get_library_info` — `procedural_materials.py:1803`
- **Prior grade:** A
- **My grade:** A — AGREE
- **What it does:** Returns shallow dict copy of a library entry.
- **Reference:** Trivial.
- **Bug/gap:** Shallow copy — see §4.12.
- **Severity:** Low
- **Upgrade:** Use `deepcopy`.

### 4.15 `handle_create_procedural_material` — `procedural_materials.py:1817`
- **Prior grade:** A
- **My grade:** A — AGREE
- **What it does:** MCP/JSON command-handler wrapper around `create_procedural_material` with list mode + categorization by recipe + optional object-attach.
- **Reference:** Standard handler shape.
- **Bug/gap:** `obj.data.materials[0] = mat` *replaces* the first slot without warning. Destructive without a `force` flag.
- **AAA gap:** None for handler shape.
- **Severity:** Low
- **Upgrade:** Add `replace_existing: bool = True` param.

---

## CROSS-CUTTING ISSUES (file-spanning)

### X.1 Two parallel material-assignment systems
- **Location:** `terrain_materials.py` (legacy v1) coexists with `terrain_materials_v2.py` (Bundle B canonical).
- **Severity:** **High** — technical debt drag, callers don't know which path is current.
- **Upgrade:** Deprecate `assign_terrain_materials_by_slope`, `blend_terrain_vertex_colors`, `handle_setup_terrain_biome` with `DeprecationWarning`. Migrate all callers to `pass_materials` + `compute_height_blended_weights`.

### X.2 Vertex-color splatmap as primary, not texture splatmap
- **Location:** `blend_terrain_vertex_colors`, `handle_setup_terrain_biome`, `create_biome_terrain_material`.
- **Severity:** **High** — vertex-resolution splatmaps (~65k samples on 256² vertex grid) are 15× coarser than 1024² splatmap textures (~1M samples). AAA terrain bakes splatmap textures.
- **Upgrade:** Add a `bake_splatmap_texture(weights, resolution=1024) → np.ndarray` and wire it through.

### X.3 Splatmap channel semantics conflated with mix-shader masks
- **Location:** `create_biome_terrain_material:2611-2637`.
- **Severity:** **High** — uses absolute splatmap channels as binary-mix masks, but HeightBlend masks should be relative (e.g., `slope_w / (ground_w + slope_w)`).
- **Upgrade:** Add Math nodes to compute pair-relative masks before each HeightBlend group.

### X.4 No triplanar projection anywhere
- **Location:** `_build_terrain_recipe`, `build_stone_material`, `build_terrain_material`.
- **Severity:** **Medium-High** — vertical cliff faces textured with Object/Generated coords stretch along world-Z. Standard AAA fix is triplanar.
- **Upgrade:** Add `_triplanar_branch(tree, links, vector_input, scale)` helper that returns a triplanar Vector socket; wire into stone/terrain builders.

### X.5 Hardcoded magic numbers throughout
- **Location:** `build_stone_material:1124, 1135`; `build_metal_material:1280, 1306`; `_build_normal_chain:983, 996, 1012`; `_build_terrain_recipe:2230, 2280, 2289` etc.
- **Severity:** Medium — tuned by feel, not by reference Megascans assets.
- **Upgrade:** Extract a `MATERIAL_TUNING_CONSTANTS` block; document the source asset for each.

### X.6 Linear ramps where smoothstep is needed
- **Location:** `auto_assign_terrain_layers:2050-2057, 2096-2099`; `_smoothstep_band` (linear trapezoidal); `compute_world_splatmap_weights`.
- **Severity:** Medium — visible C¹ banding at zone transitions.
- **Upgrade:** Replace linear `t` with `t*t*(3-2t)` everywhere in zone-band code.

### X.7 No height-blend gamma in v1/v2 splatmap functions
- **Location:** `compute_world_splatmap_weights`, `compute_slope_material_weights`.
- **Severity:** Per spec rule, this is the difference between **B** and **A**. Functions output renormalized weights but don't apply per-layer gamma curves.
- **Upgrade:** Pipe through `compute_height_blended_weights` either as a downstream pass or as an in-line option.

### X.8 Curvature/wetness hard gates in v2
- **Location:** `compute_slope_material_weights:237-246`.
- **Severity:** Medium — knife-edge transitions on curvature/wetness axes.
- **Upgrade:** Add `curvature_falloff` and `wetness_falloff` fields; use `_smoothstep_band` for all four axes.

### X.9 `Sequence`/`Mapping` type annotations not imported
- **Location:** `terrain_materials.py:2162, 2179`.
- **Severity:** Low — saved by `from __future__ import annotations`. IDE/strict-typecheck noise only.
- **Upgrade:** Add `from collections.abc import Sequence, Mapping`.

### X.10 Duplicate object-material-clear block
- **Location:** `terrain_materials.py:2648-2655` and `terrain_materials.py:2699-2708`.
- **Severity:** **High** — second block runs unconditionally after the first, re-clearing slots. Either dead code or a bug that doubles destructive operations.
- **Upgrade:** Delete the second block (lines 2699-2708).

### X.11 Blender 4.x deprecated API calls without version guard
- **Location:** `create_biome_terrain_material:2676-2679` calls `mesh.calc_normals_split()` (deprecated in 4.x).
- **Severity:** Low — fallback chain works but produces deprecation warnings.
- **Upgrade:** Skip on Blender ≥ 4.0; auto-split-normals is automatic.

### X.12 Linear sRGB color space confusion
- **Location:** `apply_corruption_tint`, `validate_dark_fantasy_color`.
- **Severity:** Medium — `apply_corruption_tint` mixes in linear-sRGB constants without checking the color attribute color space; `validate_dark_fantasy_color` runs HSV ops on linear-sRGB tuples (gamma-incorrect).
- **Upgrade:** Pass color-space through explicitly; gamma-correct HSV via sRGB transfer.

---

## SUMMARY GRADES (re-audit)

| Function | Prior | Re-audit | Verdict |
|---|---|---|---|
| `get_default_biome` | A | A | AGREE |
| `_get_material_def` | A- | A- | AGREE |
| `get_all_terrain_material_keys` | A | A | AGREE |
| `get_biome_palette` | A | A | AGREE |
| `_face_slope_angle` | A | A | AGREE (docstring lie) |
| `_classify_face` | B+ | B+ | AGREE |
| `assign_terrain_materials_by_slope` | B | **B-** | DISPUTE down |
| `blend_terrain_vertex_colors` | B | **C+** | DISPUTE down |
| `apply_corruption_tint` | B+ | B+ | AGREE |
| `_simple_noise_2d` | B | **C+** | DISPUTE down |
| `compute_biome_transition` | B+ | **B** | DISPUTE down |
| `height_blend` | B+ | B+ | AGREE |
| `_create_height_blend_group` | B | B | AGREE |
| `handle_setup_terrain_biome` | B | **B-** | DISPUTE down |
| `auto_assign_terrain_layers` | A- | A- | AGREE |
| `_resolve_biome_palette_name` | A | A | AGREE |
| `_resolve_special_band_policy` | A- | A- | AGREE |
| `_clamp_rgba` | A | A | AGREE |
| `_build_terrain_recipe` | A- | A- | AGREE |
| `compute_world_splatmap_weights` | B+ | B+ | AGREE (per spec rule) |
| `create_biome_terrain_material` | B | B | AGREE |
| `handle_create_biome_terrain` | A- | A- | AGREE |
| `MaterialChannelExt` | A | A | AGREE |
| `validate_texel_density_coherency` | A | A | AGREE |
| `compute_height_blended_weights` | A- | **A** | DISPUTE up (per spec rule) |
| `validate_cliff_silhouette_area` | A- | A- | AGREE |
| `MaterialChannel` | A | A | AGREE |
| `MaterialRuleSet`/`__post_init__`/`index_of` | A | A | AGREE |
| `default_dark_fantasy_rules` | A- | A- | AGREE |
| `_smoothstep_band` | A | **A-** | DISPUTE down (mis-named, linear) |
| `compute_slope_material_weights` | A- | A- | AGREE |
| `pass_materials` | A | A | AGREE (dead seed) |
| `register_bundle_b_material_passes` | A | A | AGREE |
| `validate_dark_fantasy_color` | A- | A- | AGREE (gamma flaw) |
| `_place` | A | A | AGREE |
| `_add_node` | A | A | AGREE |
| `_get_bsdf_input` | A | A | AGREE |
| `_build_normal_chain` | B+ | B+ | AGREE |
| `build_stone_material` | B+ | B+ | AGREE |
| `build_wood_material` | B+ | B+ | AGREE |
| `build_metal_material` | B+ | **A-** | DISPUTE up (PBR-correct) |
| `build_organic_material` | B+ | B+ | AGREE |
| `build_terrain_material` | A- | A- | AGREE |
| `build_fabric_material` | B+ | B+ | AGREE |
| `create_procedural_material` | A | A | AGREE |
| `get_library_keys` | A | A | AGREE |
| `get_library_info` | A | A | AGREE |
| `handle_create_procedural_material` | A | A | AGREE |

**Counts:** AGREE 41 / DISPUTE-down 6 / DISPUTE-up 3.

**Verdict on the 4-file core:**
- `terrain_materials_v2.py` + `terrain_materials_ext.py` are the AAA-quality path (mostly A-/A grades).
- `terrain_materials.py` is the legacy v1 surface and carries real technical debt — vertex-color splatmap, per-face material slots, mix-shader masks driven by absolute splatmap channels, duplicate destructive material-clear block.
- `procedural_materials.py` is a *good* procedural shader-graph library (B+/A- average) — its main AAA gaps are the lack of triplanar and tile-breaking, not architectural.

**Top 5 fixes by ROI:**
1. Delete the duplicate material-clear block at `terrain_materials.py:2699-2708` (X.10) — High severity, trivial fix.
2. Fix the splatmap-mask-as-mix-mask bug in `create_biome_terrain_material:2611-2637` (X.3) — High severity, ~10 Math nodes.
3. Add triplanar branch to `_build_terrain_recipe` and `build_stone_material` (X.4) — Medium-High severity, one helper function.
4. Replace linear ramps with smoothstep in `auto_assign_terrain_layers` and `_smoothstep_band` (X.6, §3.4) — Medium severity, two-line edits.
5. Deprecate `assign_terrain_materials_by_slope` + `blend_terrain_vertex_colors` + `handle_setup_terrain_biome` (X.1) — High severity for tech-debt removal, single-day migration.
