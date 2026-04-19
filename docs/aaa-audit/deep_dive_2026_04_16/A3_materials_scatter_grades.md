# A3 Materials / Vegetation / Scatter / Polish / Export / Telemetry — Function-by-Function Grades
## Date: 2026-04-16, Auditor: Opus 4.7 ultrathink

## Summary
Audited 49 files (~46,000 lines, ~430 public functions) covering materials, vegetation, scatter, atmospheric, zones, exports, LOD, telemetry, and polish modules. The codebase shows two distinct quality tiers: **(a) the "manifest/contract" tier (Bundle K/L/N/O export descriptors, mask classifiers, telemetry, validators) is consistently A- to B+** — clean numpy, deterministic, well-tested logic that produces correct *metadata*; and **(b) the "runtime asset" tier (atmospheric volumes, decals, LOD pipeline, billboard impostors, vegetation L-system, environment_scatter) is C+ to D** — visibly missing the components Unreal/Unity/SpeedTree ship by default. Every "export" pass writes a JSON descriptor and a flipped RAW buffer; **none** of them actually produces a Unity `TerrainData.asset` (binary YAML), a UE5 Landscape `.umap`, a Houdini geometry stream, an OpenEXR clipmap, an FBX LOD chain, or VDB volume — all are stubs that punt the real conversion to a future Unity-side importer that does not exist in this repo.

The strongest single module is `terrain_assets.py` (Bundle E scatter intelligence) which at last implements real Poisson-disk-in-mask + cluster-around-feature placement honoring slope/altitude/wetness rules in fully-vectorized numpy — that's an honest A-. The weakest are `atmospheric_volumes.py` (BUG-11 confirmed: every volume pinned to `pz = 0.0`, terrain-unaware), `lod_pipeline.py` (no QEM, "octahedral imposter" is just a vertical prism with un-baked empty atlas, billboards are single quads), `terrain_decal_placement.py` (only a density mask — no UV projector, no normal-aligned mesh, no decal actor), and `terrain_shadow_clipmap_bake.py` (writes `.npy` and lies in sidecar JSON about being EXR float32). `procedural_meshes.py` is a 22K-line library of ~250 hand-built parametric mesh generators that ship at indie/AA quality — they have UVs, sharp edges, and beveled boxes, but they have no PBR materials assigned, no texture coordinates beyond box projection, no LOD chains, and no skinning rigs. Compared to a real Quixel Megascans pipeline (3D scan + 4K PBR + impostor + collision LOD0-3), these are placeholder geometry only.

Nine NEW BUGS found beyond BUG-11 (numbered BUG-50 through BUG-58 to avoid clashes with A2). The 12-step orchestrator (`terrain_twelve_step.py`) explicitly admits Steps 4 and 5 are pass-through stubs — flatten zones and canyon/river A* carves are NOT implemented. `edit_hero_feature` in `terrain_live_preview.py` is purely cosmetic — it appends string labels to `state.side_effects` and never mutates a single byte of geometry. The "stochastic shader" claims Heitz-Neyret 2018 but ships a bilinear UV-offset noise grid, not the histogram-preserving triangle blending that breaks tiling. Cloud shadow has no advection or wind animation and no cross-tile coherence (each tile generates an independent random field that will hard-edge at seams).

## Module: terrain_bundle_j.py (registrar, 67 lines)

### `register_bundle_j_passes` (line 49) — A
prior: A | what: registers 10 ordered Bundle J passes on TerrainPassController | ref: Standard registrar pattern matching Bundle K/L/N/O. | bug: none | AAA gap: This is purely a wiring concern; comparable to UE5 plugin module registration. | upgrade: Already production-quality.

## Module: terrain_bundle_k.py (registrar, 53 lines)

### `register_bundle_k_passes` (line 40) — A
Identical pattern. Calls 6 sub-pass registrars in canonical order. Production-quality wiring.

## Module: terrain_bundle_l.py (registrar, 40 lines)

### `register_bundle_l_passes` (line 30) — A
3-pass registrar for horizon_lod / fog_masks / god_ray_hints. Clean.

## Module: terrain_bundle_n.py (registrar, 53 lines)

### `register_bundle_n_passes` (line 34) — A-
prior: A | what: explicitly states "Bundle N has no mutating passes — just verify modules loaded" and pokes attributes via `_ = module.fn` to ensure imports don't break. | bug: none | AAA gap: Pretty clean — only knock is the `_ = …` pattern is a smoke test, not a real registration; if a module renames `record_telemetry` the registrar fails at startup which is actually desirable. | upgrade: Already fine.

## Module: terrain_bundle_o.py (registrar, 33 lines)

### `register_bundle_o_passes` (line 19) — A
2-pass registrar for water_variants and vegetation_depth. Clean.

## Module: terrain_palette_extract.py (137 lines)

### `_labels_for` (line 29) — A
Vectorized squared-Euclidean argmin via the `|p|² − 2p·c + |c|²` identity. This is the textbook efficient k-means assignment step. Matches sklearn's `_labels_inertia` strategy.

### `extract_palette_from_image` (line 40) — A-
prior: B+ | what: pure-numpy deterministic k-means (seed=0, 20 iterations, allclose convergence) with auto float/uint8 normalization and RGBA→RGB strip. | ref: scikit-learn `KMeans` defaults to k-means++ init; this uses uniform random init which is empirically inferior — for n=k=8 the convergence basin is shallow but image palette extraction can land in local minima with random init. Quixel Megascans pipeline uses k-means++ for color palette extraction. | bug: hardcoded `seed=0` (line 70) ignores caller-supplied seed; `k = min(k, n)` does not error if user requests k=100 on a 50-pixel image (silent shrink). | AAA gap: missing k-means++ init; missing `k_optimization` (silhouette / elbow) the way Adobe Stock palette extractor picks k; missing perceptual color distance (LAB, not raw RGB — RGB k-means biases toward green because of luminance weighting). | upgrade to A: switch to LAB color space via `colour-science` or simple sRGB→Linear→XYZ→LAB; use k-means++ init (5 lines of code); accept caller-supplied seed.

### `_label_for_rgb` (line 104) — B
prior: B | what: rule-based label assignment using luminance + dominant channel. | ref: Hue-based classification is the standard photography color-grouping approach. | bug: rule "g > r AND g > b ⇒ foliage" misclassifies cyan grays and aqua water as foliage; "b > r AND b > g ⇒ water" misclassifies sky/cloud blues as water (no saturation gate). | AAA gap: real palette tagging in Adobe / Quixel uses learned color-name embeddings (e.g. CIELAB nearest neighbor against ISCC-NBS color list with 267 names). | upgrade to A: gate by saturation (HSV.S > 0.15) and add luminance bands; use a small lookup against ~20 reference palette swatches.

### `palette_to_biome_mapping` (line 119) — C+
prior: C | what: maps the 6 fixed labels to 6 fixed biome strings. | bug: deterministic 1:1 lookup that doesn't consider palette weights, ratio between labels, or scene context — a desert reference image with one dark rock returns biome "shadow" because dark wins. | AAA gap: World Creator and Gaea use color-clusters as material-blend hints, not biome IDs; biome should be intent-driven, not color-driven. | upgrade to A: weight-based plurality voting + biome cohesion check.

## Module: terrain_quixel_ingest.py (248 lines)

### `_classify_texture` (line 75) — A-
prior: A- | what: regex-based filename → channel classification with 11 patterns. | ref: Quixel Megascans naming convention `<asset>_<channel>_<lod>.<ext>` — the regex `(^|[_\-])albedo([_\-]|\.)` correctly captures `Asset_Albedo.png` and `Asset_Albedo_LOD0.exr` without grabbing `MyAlbedoBakery.png`. | bug: missing `BaseColor`, `MetalRough`, `ARM` (AO+Roughness+Metallic packed) which UE5 Megascans imports use. Missing `Opacity` / `Translucency` for foliage atlases. | upgrade to A: add 4 more channel patterns covering UE5 packed maps.

### `ingest_quixel_asset` (line 82) — A-
prior: A- | what: parses a Megascans asset folder into typed `QuixelAsset` with first-match-wins LOD0 selection. | ref: Quixel Bridge exports follow `<id>_<resolution>_<channel>_LOD<n>.<ext>` — first occurrence sorting on `iterdir()` does NOT guarantee LOD0 (alphabetical may put `LOD1` before `LOD0` if no zero-padding, but Megascans does pad). The `sorted(asset_path.iterdir())` is fragile. | bug: drops JSON parse errors silently (line 107 `continue`) — if a malformed metadata sidecar exists, no warning emerges. | AAA gap: no resolution detection (`2K`, `4K`, `8K` in filename), no PBR validation (does roughness range [0..1]?), no displacement scale extraction from sidecar. | upgrade to A: parse resolution token, validate channel value ranges, surface JSON errors as ValidationIssues.

### `apply_quixel_to_layer` (line 126) — C+
prior: C | what: stuffs the asset's texture paths as a JSON STRING into `stack.populated_by_pass[key]`. | bug: this is type-coercion abuse — `populated_by_pass` is `Dict[str, str]` for tracking pass provenance; embedding texture path JSON as a synthetic key/value pair pollutes the provenance log and makes downstream readers parse JSON out of metadata strings. | AAA gap: real ingest creates a `MaterialChannel` with texture references, not a stringified blob. Unreal's Bridge creates Material Instances with texture parameter overrides. | upgrade to A: add a typed `quixel_layers: Dict[str, QuixelAsset]` field on `TerrainMaskStack`; pass actual references to the Unity exporter.

### `pass_quixel_ingest` (line 166) — B-
prior: B | what: registered Bundle K pass that reads composition_hints["quixel_assets"] descriptor list, ingests each, and appends issues. | bug: lines 182-207 contain a duplicated apply loop — when `assets` is passed in directly the function applies them TWICE (once at line 192 inside the descriptor loop AND once at line 207 in the unconditional follow-up). | AAA gap: no parallelism, no texture preload validation. | upgrade to A: remove duplicate apply loop, validate texture file existence + size in parallel via ThreadPoolExecutor.

### `register_bundle_k_quixel_ingest_pass` (line 223) — A
Standard registrar wrapping `pass_quixel_ingest` with `assets=None`. Clean.

## Module: terrain_decal_placement.py (178 lines)

### `compute_decal_density` (line 33) — C+
prior: C+ | what: per-DecalKind 2D density mask in [0,1] computed from wetness/curvature/erosion/basin/ridge/gameplay/traversability signals. | ref: Compared to UE5 Decal Actor / Unity DecalProjector — those project a textured quad onto the terrain along a normal vector with a defined size, rotation, and material. This function produces a *density mask only*. | bug: BLOOD_STAIN gates on `gameplay == 1` (hardcoded magic number; should be `GameplayZoneType.COMBAT.value`). The `norm()` helper rescales each signal to its own [0..1] inside this single tile — adjacent tiles will normalize to different ranges, causing seam discontinuities. | AAA gap: **CRITICAL** — there is no actual decal placement. Real engines need (position, normal, rotation, scale, material_id) per decal instance. This module gives only a 2D heatmap; the Unity exporter `_decals_json` (terrain_unity_export.py:600) does extract individual decal placements but caps at 512 per kind via `coords[:512]` (silently drops the rest), uses scale=1.0 / rotation=0.0 unconditionally, and computes normal via 3×3 finite difference (no curvature alignment, no random-yaw). | upgrade to A: produce a `List[DecalInstance]` with proper (world_pos, normal_vec, yaw_rad, scale_m, material_id, source_seed) — use Poisson-disk-in-mask sampling instead of dumping every cell with density>0.5; compute random yaw from a hash; actually align the up-axis to terrain normal.

### `pass_decals` (line 121) — C+
prior: C | what: iterates `DecalKind` and writes the dict into `stack.decal_density`. | bug: never produces actual instance positions — only heatmaps. The pass name "decals" is misleading; should be `decal_density_masks`. | AAA gap: same as above — heat map ≠ decal. | upgrade to A: produce instance arrays inline; expose as `stack.decal_instances: Dict[str, np.ndarray (N,7)]`.

### `register_bundle_j_decals_pass` (line 157) — A
Standard registrar.

## Module: terrain_stochastic_shader.py (230 lines)

### `StochasticShaderTemplate` (dataclass, line 38) — B+
Clean PBR template config. Contract is correct (tile_size_m, randomness_strength, histogram_preserving bool, layer_index).

### `build_stochastic_sampling_mask` (line 64) — C+
prior: C | what: bilinear-interpolated random UV-offset grid, one offset per tile-cell, smoothed across cell boundaries. | ref: **The docstring claims Heitz-Neyret 2018 "High-Performance By-Example Noise using a Histogram-Preserving Blending Operator"**, but the actual algorithm is just smooth value noise on a (tile_y, tile_x) grid bilinearly resampled to (rows, cols). Heitz-Neyret samples three triangle vertices per pixel, performs CDF-equalized weight blending, and reconstructs the histogram via a precomputed inverse CDF — that's why it preserves albedo histograms. **None of that is here.** | bug: docstring lie — `histogram_preserving=True` is metadata only, no histogram preservation actually executes. Bilinear resample creates visible diagonal artifacts at low randomness_strength. | AAA gap: SpeedTree, Unreal Material Function `MS_HistogramPreservingBlend`, and Substance Painter all implement actual Heitz-Neyret. This is a placeholder. | upgrade to A: rewrite as actual triangle-grid sampler with three weighted texture lookups per pixel + inverse-CDF histogram remap; pre-bake CDF LUT into the export template.

### `export_unity_shader_template` (line 118) — C
prior: C | what: writes a JSON manifest declaring "shader_graph_type": "ShaderGraph/TerrainLit_Stochastic". | bug: the named shader graph asset does not exist anywhere in this repo nor on the Unity side (no `.shadergraph` file). The exporter writes a contract for a nonexistent consumer. | AAA gap: Unity ShaderGraph requires actual `.shadergraph` JSON files (binary YAML format with specific node IDs and connections). This is a stub manifest. | upgrade to A: ship a real `.shadergraph` with the Heitz-Neyret subgraph; or stop pretending and document this as "engine-side TODO".

### `pass_stochastic_shader` (line 150) — C+
prior: C | what: builds the bilinear noise mask and folds magnitude into `roughness_variation` as a small perturbation. | bug: the docstring contains a confused parenthetical "(no new channel — stores on stack.composition_hints style; we embed the mask into roughness_variation channel's third dimension? No — that changes dtype...)" — this is a half-finished thought that should not ship in a docstring. | AAA gap: the mask is not exported anywhere — only the roughness perturbation lands. | upgrade to A: actually export the offset mask as a 2-channel float32 RAW, register it in the manifest.

### `register_bundle_k_stochastic_shader_pass` (line 208) — A
Standard registrar.

## Module: terrain_roughness_driver.py (135 lines)

### `compute_roughness_from_wetness_wear` (line 25) — A-
prior: A- | what: physically-motivated roughness blend — wet = 0.15, eroded = 0.85, deposition = 0.70, AO concavity adds dust 0.05. Starts from existing roughness_variation if present. | ref: Matches SpeedTree's wetness shader and Unreal's `MS_StandardWear` material function. | bug: the deposition term `base * (1 - 0.3 * dep_norm) + 0.70 * 0.3 * dep_norm` has algebra mistake — when dep_norm=1, base contributes 0.7×base + 0.21, but the COMMENT says "deposition cells push toward 0.70" — at dep_norm=1 the actual output is 0.7×base + 0.21, e.g. base=0.55 ⇒ 0.595, NOT 0.70. The MULTIPLY factor is inconsistent with the lerp intent. | AAA gap: no temperature/humidity drive (real wetness shaders consider seasonal moisture); no dust accumulation falloff with slope (dust collects on flat surfaces, not vertical cliffs — this code applies AO uniformly). | upgrade to A: fix lerp algebra to `base * (1 - dep_norm * 0.3) + 0.70 * dep_norm * 0.3 / 0.3` ⇒ proper lerp toward 0.70 weighted at 0.3; gate AO dust by slope < 30°.

### `pass_roughness_driver` (line 82) — A-
Clean. Reads optional channels with safe fallbacks. Writes `roughness_variation` with provenance.

### `register_bundle_k_roughness_driver_pass` (line 115) — A
Standard registrar.

## Module: terrain_shadow_clipmap_bake.py (233 lines)

### `_resample_height` (line 31) — A-
Bilinear resample helper. Correct, vectorized.

### `bake_shadow_clipmap` (line 53) — B
prior: B+ | what: ray-marches sun direction across heightmap, multiplies mask by 0.55 per occlusion hit (soft shadow). | ref: Stock approach. AAA studios use horizon-based ambient occlusion (HBAO) or ground truth ambient occlusion (GTAO) for terrain — see Jimenez 2016 GTAO paper. This is a direct ray cast, simpler and slower. | bug: `step_cells = max(1.0, (clipmap_res / max(num_steps, 1)) * 0.5)` means at clipmap_res=512 and num_steps=24, each step is 10.6 cells — way too coarse for shadow detail; you'll miss any occluder narrower than 10 cells. The 0.55 occlusion multiplier is arbitrary and not energy-conservative — N hits drops to 0.55^N which goes near zero very fast. | AAA gap: no temporal accumulation, no penumbra computation (just multiplicative falloff), no separation between direct and ambient. | upgrade to A: cap minimum step at 1 cell; replace 0.55 multiplier with horizon-tangent integration (HBAO formulation: `1 - sin(horizon_angle)`); add a separate AO bake.

### `export_shadow_clipmap_exr` (line 122) — D
prior: B (claimed) | what: **named "exr" but writes .npy** because OpenEXR is not in deps. Sidecar JSON declares `"format": "float32_npy"` and `"intended_format": "exr_float32"`. | bug: **CRITICAL** — the function name promises EXR but ships .npy. The Unity export contract validator (`terrain_unity_export_contracts.py:288`) explicitly checks `if enc != "float"` → flags violation, but the manifest writer (`terrain_unity_export.py:_write_raw_array`) doesn't go through this path for shadow clipmaps. The contract is unverified. The Unity-side importer for `.npy` does not exist — `np.save` writes a numpy magic-string header that no Unity binary EXR/RAW loader will parse. | AAA gap: real production needs actual OpenEXR via OpenImageIO Python bindings or `openexr` PyPI package (works on Windows/Linux/Mac). | upgrade to A: add `openexr` to deps; write proper EXR via `OpenEXR.OutputFile` with PixelType.FLOAT; OR be honest and rename to `export_shadow_clipmap_npy`.

### `pass_shadow_clipmap` (line 157) — B-
prior: B | what: bakes clipmap, resamples to height shape, multiplies into existing cloud_shadow if present. | bug: multiplying with cloud shadow conflates two physically different signals (sun occlusion vs cloud cover) — a cell shadowed by a cliff at noon will lose the cloud shadow signal too. Should add a separate channel `sun_shadow_clipmap`. | AAA gap: see ray-march bug above. | upgrade to A: separate channels; honest float blending.

### `register_bundle_k_shadow_clipmap_pass` (line 212) — A
Standard registrar.

## Module: terrain_materials.py (2766 lines, legacy biome-keyed system)

(The file is a 25-function legacy module. Prior audits have graded most functions; I'll grade only the architecturally-load-bearing publics here and reference the rest as inherited.)

### `get_default_biome` (line 50) — A-
Trivial accessor. Returns "thornwood_forest" string. Fine.

### `_get_material_def` / `get_all_terrain_material_keys` (line 997-1002) — A
Library accessors. Fine.

### `get_biome_palette` (line 1015) — B+
prior: B+ | what: returns a palette dict with ground/slopes/cliffs/water_edges keyed lists per biome. | bug: hardcoded list — adding a biome requires editing this function. | AAA gap: Quixel Bridge stores biome palettes as JSON assets; this is a Python literal. | upgrade to A: load palettes from `data/biomes/<name>.json`.

### `_classify_face` / `_face_slope_angle` (line 1046-1068) — A-
Clean trig. Used by face-classifier.

### `assign_terrain_materials_by_slope` (line 1096) — B+
prior: B | what: walks faces, classifies by slope angle band + height vs water, returns material indices. | ref: Compared to Unity's TerrainData splatmap (alphamap channels) which Unity Terrain shader reads — this is a per-face material slot index, the OLD multi-material approach which forces draw call per material. Unity terrain layers are far more efficient. | bug: face-cycle distribution `mat_offset = fi % len(zone_materials)` produces sequential striping across the mesh — visible regular bands. | AAA gap: legacy approach — Unity HDRP terrain wants splatmap weights, not per-face material indices. | upgrade to A: deprecate in favor of `terrain_materials_v2.compute_slope_material_weights` which already does the right thing. The fact that BOTH systems coexist is technical debt.

### `blend_terrain_vertex_colors` (line 1167) — B
prior: B | what: writes 4-channel splatmap weights to vertex colors. | ref: Unity HDRP TerrainLit shader can read vertex colors as a fallback splat source — this works. | bug: zone_weights are hardcoded magic numbers `(0.6, 0.0, 0.4, 0.0)` for "ground"; no biome-specific tuning. | AAA gap: Quixel terrain layers blend on a per-pixel basis at texture resolution; vertex colors blend at vertex resolution — much coarser. For a 256×256 vertex grid that's 65K splat samples vs. 1024×1024 pixels = 1M. | upgrade to A: bake to a real splatmap texture not vertex colors.

### `apply_corruption_tint` (line 1281) — C+
prior: C | what: blends a corruption tint color into existing vertex colors via factor. | bug: works only on already-painted vertex colors; if not painted, silently no-ops. | AAA gap: corruption is a runtime gameplay-driven effect that should be a shader parameter, not baked vertex colors. | upgrade to A: emit as separate `corruption_intensity` channel for shader.

### `_simple_noise_2d` (line 1323) — C
prior: C | what: hash-based pseudo-noise via sin trickery. | bug: not real Perlin, not seeded reproducibly across platforms (sin precision varies). The classic GLSL `fract(sin(dot(p, vec2(12.9898,78.233))) * 43758.5453)` hash. | AAA gap: noise.pnoise2 / scipy.ndimage / opensimplex — any of these is deterministic, fast, and shader-equivalent. | upgrade to A: use opensimplex2 or stb_perlin port.

### `compute_biome_transition` (line 1358) — B
Multi-biome blend interpolation. Adequate. Missing temporal coherence between adjacent calls — same call returns same blend, so good for determinism.

### `height_blend` (line 1508) — B+
Two-material height blend with smoothstep. Standard technique. OK.

### `_create_height_blend_group` (line 1548) — B
Creates a Blender shader node group. The actual node tree is a height-mask + mix shader. Adequate.

### `handle_setup_terrain_biome` (line 1673) — B
275-line bpy handler. Wires terrain mesh to a biome material. Standard handler pattern.

### `auto_assign_terrain_layers` (line 1948) — B
Auto-assigns Unity-style terrain layers from biome rules. Fine.

### `_resolve_biome_palette_name` / `_resolve_special_band_policy` / `_clamp_rgba` / `_build_terrain_recipe` (lines 2119-2172) — B
Helpers for terrain recipe construction. OK.

### `compute_world_splatmap_weights` (line 2365) — B+
prior: B+ | what: blends biome splatmaps across the world map at biome boundaries. | ref: Standard. | upgrade to A: weight by ecotone graph distance, not euclidean.

### `create_biome_terrain_material` / `handle_create_biome_terrain` (lines 2515-2713) — B
Bpy material creators. ~200 lines each. Wire up Principled BSDF + textures from biome palette. Adequate but uses single-tile UV approach (visible repetition).

## Module: terrain_materials_ext.py (234 lines)

### `MaterialChannelExt` (dataclass, line 29) — A-
Wraps `MaterialChannel` with `height_blend_gamma`, `texel_density_m`, `micro_normal_texture`, `micro_normal_strength`, `respects_displacement`. Matches Unreal Material Layer Blend Asset fields.

### `validate_texel_density_coherency` (line 57) — A
prior: A | what: flags channels whose texel density diverges from the min by > max_ratio. | ref: This is exactly the Unreal `Texel Density` audit rule — adjacent terrain layers must be within ~2× texel density or visible texture-resolution discontinuities appear. | bug: none significant. | upgrade: None — already production.

### `compute_height_blended_weights` (line 105) — A-
prior: A | what: applies per-layer gamma curves to base splatmap weights with non-linear height bias. | ref: This is the standard Megascans / Unreal "Height Lerp" or "Height Blend" technique used to make snow accumulate on peaks and moss in valleys. | bug: when `total <= 1e-9` falls back to base weights — this is correct fallback but it leaks the unmodified base into the output, so cells that were intended to fade out still appear with original weights. | upgrade to A: instead of falling back to base, fall back to the dominant channel by weight.

### `validate_cliff_silhouette_area` (line 180) — A-
Hero/secondary cliff area gate. Hard fails when cliff silhouette < 8% (hero) or 3% (secondary) of frame. Reasonable thresholds for AAA framing.

## Module: terrain_materials_v2.py (374 lines)

### `MaterialChannel` (dataclass, line 39) — A-
Slope/altitude/curvature/wetness envelopes with smoothstep falloff. Matches Unreal Landscape Material Layer authoring.

### `MaterialRuleSet` (line 72) — A
Validated rule set with default channel fallback. Clean.

### `default_dark_fantasy_rules` (line 106) — B+
prior: B+ | what: 5-channel ground/cliff/scree/wet_rock/snow rule set. | bug: hardcoded altitude thresholds (snow > 250m, scree < 200m) — should be biome-parameterized. | AAA gap: real terrain shaders have 8-12 layers (e.g. Horizon FW: dirt, sand, grass_short, grass_long, rock_smooth, rock_jagged, snow, wet_mud, scree, ice). | upgrade to A: expand to 8-channel default.

### `_smoothstep_band` (line 181) — A
Clean linear ramp band. Used in production.

### `compute_slope_material_weights` (line 195) — A-
prior: A | what: vectorized per-channel envelope evaluation, fallback-channel-on-zero, normalize to sum=1. | ref: Matches Unity HDRP TerrainLit splatmap normalization contract. | bug: `curv_w = np.where(... & ...)` returns hard 0/1, no smoothstep — sharp boundaries on curvature transitions. | upgrade to A: replace hard curvature gate with smoothstep band like slope/altitude.

### `pass_materials` (line 269) — A-
Region-scoped pass with proper mask preservation outside region. Production-quality.

### `register_bundle_b_material_passes` (line 349) — A

## Module: procedural_materials.py (1870 lines)

### `validate_dark_fantasy_color` (line 61) — B+
prior: B+ | what: HSV clamp to S<0.40, V in [0.10, 0.50] enforcing the dark-fantasy palette. | ref: Comparable to Substance Painter's color-clamping per material library. | bug: silent clamp without warning — designer hands a saturated red, gets back a dim brown, no log. | upgrade to A: emit ValidationIssue when clamping is significant.

### `_place` / `_add_node` / `_get_bsdf_input` (lines 895-925) — A
Blender shader node tree helpers. Defensive (`getattr`, `try/except` around input lookup). Standard.

### `_build_normal_chain` (line 943) — A-
prior: A- | what: 3-layer normal chain (micro/meso/macro) with strength-weighted Vector Math + Bump combine. | ref: This is the canonical AAA "detail normal layer" pattern — Substance Painter, UE5 Material Layers, Unity HDRP all do exactly this. | bug: the macro normal is the bump from base noise — should be a sampled high-poly bake or Megascans normal map; using procedural noise for macro detail is appropriate ONLY for terrain ground, not for wood/stone hero assets. | upgrade to A: accept an optional `macro_normal_texture` param so artists can bake from sculpts.

### `build_stone_material` (line 1025) — B+
prior: B+ | what: builds a 3-layer Voronoi+Noise stone material with multi-scale bump. | ref: This is good — Voronoi for cell pattern, Noise for surface variation. | bug: hardcoded `Voronoi.scale = 5.0`, no per-stone-type tuning. | AAA gap: real stone scans (Quixel) have anisotropic crystallography baked into normal maps — pure procedural lacks that. | upgrade to A: parameterize Voronoi randomness/distance metric per stone type.

### `build_wood_material` (line 1155) — B+
Similar pattern. Wave + Noise for grain. Adequate.

### `build_metal_material` (line 1252) — B
Edge wear via Voronoi rim mask. Good for AAA. Bug: rim emission factor is calculated even when `emission_strength == 0` (wasted nodes).

### `build_organic_material` (line 1350) — B
Subsurface + sheen. Reasonable for moss/skin.

### `build_terrain_material` (line 1497) — A-
prior: A- | what: 3-octave noise + slope-mask + 3-layer normal chain. | ref: This is the 80%-quality version of an Unreal Landscape Material — base color blends per slope, multi-octave noise gives macro/meso/micro variation. | bug: line 1597 comment "Bug 11 fix" describes a legitimate clamping fix to base color tint. | AAA gap: no triplanar projection (UV stretching on cliffs guaranteed); no parallax occlusion; no virtual texture. | upgrade to A: add a Geometry node with WorldNormal-driven triplanar mix; expose POM displacement amount.

### `build_fabric_material` (line 1629) — B+
Brick-pattern weave with sheen. Solid.

### `create_procedural_material` (line 1742) — A-
prior: A- | what: dispatch to the appropriate builder based on `node_recipe`. | upgrade to A: cache materials by hash of params; current code creates a new material per call.

### `get_library_keys` / `get_library_info` (lines 1798-1803) — A
Accessors. Clean.

### `handle_create_procedural_material` (line 1817) — B+
Bpy entry point. Standard handler.

## Module: procedural_meshes.py (22607 lines, ~250 generators)

This file is too large to grade function-by-function — it contains mesh generators for ~250 dark fantasy assets (weapons, props, vegetation, monsters, architecture). I grade at the architectural level + spot-check representatives.

### `_grid_vector_xyz` / `_detect_grid_dims_from_vertices` / `_detect_grid_dims` (lines 69-106) — A-
prior: A- | what: counts unique rounded X/Y to infer rows/cols. | ref: Robust for non-square meshes. | bug: `round(... 3)` precision can collide on degenerate meshes; sqrt-fallback is safe. | upgrade to A: use np.unique on positions instead of set for vector-precision counting.

### `_get_trig_table` (line 119, lru_cache) — A
prior: A | Excellent micro-optimization. Caches (cos, sin) per segment count.

### `_auto_detect_sharp_edges` (line 132) — A-
prior: B+ | what: Newell's method face normal + dihedral angle threshold. Boundary edges always sharp. | ref: Standard sharp-edge detection. | bug: O(F) per face for normal computation is fine; the edge-face dict assembly is correct. | upgrade to A: vectorize via numpy if faces > 10K.

### `_auto_generate_box_projection_uvs` (line 192) — C+
prior: C | what: bounding-box projection UVs along XZ or XY. | bug: this is the cheapest possible UV generation — all weapons get the SAME UV layout regardless of geometry shape. Cylindrical objects get smashed UVs. Result: visible texture stretching on every non-box asset. | AAA gap: Quixel Megascans use UV-unwrapped meshes with proper seam placement. Smart UV Project (Blender) or atlas-packing (Houdini) is standard. | upgrade to A: switch to per-face triplanar UVs OR call Blender's smart_project bpy.ops on Blender side and bake.

### `_make_result` (line 233) — A-
Packages mesh dict with sharp-edge auto-detection and dimensions. Clean.

### `_alias_generator_category` / `_GeneratorRegistry` (lines 282-300) — A-
Backward-compat alias system for category renames. Reasonable design.

### `_compute_dimensions` (line 335) — A
Single-pass min/max in one scan. Optimal.

### `_circle_points` / `_make_box` / `_make_cylinder` / `_make_cone` / `_make_torus_ring` / `_make_tapered_cylinder` (lines 370-585) — A-
Primitive constructors using cached trig. Production-quality utility code.

### `_make_beveled_box` (line 588) — B+
24-vertex beveled cube with chamfered edges. The bevel logic is hand-coded and works but is fragile (relies on 12-edge enumeration). Should use Blender's bmesh.ops.bevel — but this is pure-logic and headless.

### `_enhance_mesh_detail` (line 691) — B+
prior: B+ | what: edge-collapse-style subdivision near sharp edges to reach min_vertex_count. | bug: 3-pass cap may not hit target on dense meshes; output may have non-manifold edges if sharp edges meet at vertices that are split independently. | AAA gap: production tools (Houdini) use proper subdivision modifiers (Catmull-Clark on quads). | upgrade to A: Catmull-Clark subdivision instead of midpoint insertion.

### `_merge_meshes` (line 853) — A
Concat + index remap. Standard.

### `_make_faceted_rock_shell` (line 867) — A-
Custom angular rock generator with seed-driven ridge perturbation, x/y/z scale variance, fracture bias. This is real procedural rock geometry — comparable to Megascans rock_low_poly variants.

### `_make_sphere` / `_make_lathe` / `_make_profile_extrude` (lines 959-1048) — A-
UV sphere, lathe, profile extrude — standard parametric primitives.

### Generator Functions (lines 1089-22607, ~245 functions)

Spot-checked: `generate_table_mesh`, `generate_chair_mesh`, `generate_tree_mesh`, `generate_rock_mesh`, `generate_greatsword_mesh`, `generate_humanoid_beast_body`.

**Architectural Grade for Generators: B / B-**
prior: B | what: each generator hand-builds vertices/faces/UVs for one asset type with style variants (e.g. `style="open_face"` for helmets). 
ref: Compared to Quixel Megascans (3D scanned, 4K PBR textured, LOD0-3 with billboards, photogrammetric quality) these are **parametric primitive assemblies** — boxes, cylinders, spheres glued together. They generate in <1ms each but visually rate as **AA-quality placeholder geometry**, not AAA shipped quality.
bug: NO generator embeds material assignments — every mesh ships with a single MeshSpec; the bridge layer assigns one material based on `metadata.category`. Real game props have 3-7 material slots (handle_wood, blade_metal, pommel_gold, etc.).
AAA gap: 
  - No skinning rigs on humanoid_beast_body / quadruped_body — these are static T-pose meshes, useless for animation.
  - No collision proxies (separate convex hull mesh).
  - No LOD chains baked in (relies on lod_pipeline to generate).
  - No texture coordinates beyond box projection (every asset will texture-stretch).
  - All UVs are auto-generated, never hand-unwrapped — guaranteed visible seams on hero props.
  - No Houdini procedural variants — same seed → same exact mesh; no genome-style variation.
upgrade to A: 
  - Add per-mesh material slot maps (`material_slots: List[str]` in MeshSpec).
  - Add `collision_hull` field auto-computed via convex hull.
  - Add Tripo3D integration to upgrade hero props to actual sculpted geometry.
  - Replace box-projection UVs with smart-project (Blender side).

The 22K-line file is **technically impressive engineering** (no library deps, fully testable, deterministic) but **artistically AA-tier**. For a real AAA dark-fantasy game you would Quixel Bridge / Tripo / Sketchfab the props, not generate them parametrically. These are perfectly fine as **prototype/blockout** geometry until art is done.

## Module: vegetation_lsystem.py (1188 lines)

### `LSYSTEM_GRAMMARS` (dict, line 33) — B+
7 tree-type L-system grammars (oak, pine, birch, willow, dead, ancient, twisted). Reasonable starting set. Real SpeedTree has hundreds of species with measured biological parameters.

### `expand_lsystem` (line 125) — A
Standard string-rewriting L-system expansion. Pure-logic, deterministic, correct.

### `_rotate_vector` (line 153) — A
Rodrigues' rotation formula. Correct, optimized.

### `_TurtleState` (line 181) — A-
Slot-optimized class with copy. Good Python perf.

### `BranchSegment` (line 211) — A-
Slot-optimized branch segment data class.

### `interpret_lsystem` (line 245) — B+
prior: B | what: turtle-graphics interpreter with stack push/pop, gravity drag, randomness. | ref: This is a faithful turtle interpreter — comparable to L-Py / Houdini L-System SOP. | bug: gravity drag `state.dz -= grav_amount * 0.1` is applied per-step; this means deep branches accumulate gravity exponentially — willows get over-droopy with high iteration counts. Should be a per-segment proportional pull, not cumulative. The `+ rng.gauss(0.0, randomness * 0.2)` length perturbation can produce negative lengths at high randomness. | AAA gap: SpeedTree models phototropism (light-seeking), apical dominance, and biomechanical stress — none of that is here. | upgrade to A: cap segment_length to positive, replace cumulative gravity with proportional bias toward (0,0,-1).

### `_generate_cylinder_ring` / `branches_to_mesh` (lines 380-437) — A-
Truncated cone branches with proper perpendicular ring construction. Solid mesh generation. Bug: `min_radius_for_geometry=0.01` drops twigs to leaf placeholders — fine for performance.

### `generate_roots` (line 539) — A-
Visible root segments at trunk base. 3-8 roots, downward angled. Adequate.

### `generate_lsystem_tree` (line 609) — A-
prior: A- | what: full pipeline — expand → interpret → roots → mesh. Caps iterations to 6 (commented MISC-020 bug fix to prevent ~4.7M vert blowout at 8 iterations). | ref: 290K verts at 6 iterations is acceptable for a hero tree LOD0; real games average 5K-15K per tree LOD0. | bug: at iteration=6 the polygon count is 50× too high for a non-hero tree. Should be configurable per asset role. | upgrade to A: vertex-budget-driven iteration cap (target N verts → solve for iteration count).

### `_LEAF_PRESETS` / `generate_leaf_cards` (lines 716-750) — B+
prior: B | what: cross-quad leaf cards at branch tips with random rotation/scale/tilt. | ref: This is the classic "billboard cluster" technique — every game tree shipped 2005-2015 used this. Modern SpeedTree uses real leaf geometry with subsurface scattering. | bug: cards do not face the camera (no billboard component); they face random directions. They will show as paper-thin slabs from grazing angles. | AAA gap: missing leaf-card spherical projection (rotate to camera up), missing alpha cutout texture, missing subsurface translucency setup. | upgrade to A: add camera-facing rotation as runtime shader concern; expose alpha cutout material slot; mark cards as `unity:two_sided=true`.

### `bake_wind_vertex_colors` (line 889) — A-
prior: A- | what: R = primary sway radial+height, G = leaf flutter (depth-based), B = hash-based phase offset. | ref: This matches the Unity Wind Zone shader convention exactly — Unreal's Pivot Painter Tool also uses RGB packing in vertex colors. | bug: the B channel `phase_hash = math.sin(vx * 12.9898 + ...) * 43758.5453` is the well-known GLSL hash that has known visual artifacts (axial banding) and floating-point precision issues at large coordinate values. | AAA gap: Pivot Painter uses 16-bit precision via two 8-bit channels; this stuffs phase into single 8-bit B. | upgrade to A: pack phase into RG (16-bit) and store sway scaling in BA.

### `generate_billboard_impostor` (line 975) — D
prior: C | what: produces billboard mesh ("cross" = 2 intersecting quads, "octahedral" = N-sided prism). | bug: **CRITICAL** — there is no actual texture baking. The function returns metadata `"next_steps": [...]` listing things the caller "should do" but never does. The "octahedral impostor" is just an N-sided cylinder — a real octahedral imposter (the Unreal/Microsoft technique from "GPU Gems 3" + "Shaderbits Octahedral Imposter") uses 8 cap-octahedron view directions captured into a 2K atlas with parallax depth offset. This implementation produces zero texture data and zero parallax. | AAA gap: SpeedTree, UE5, and the open-source ImpostorBakery all bake 8-16 view atlas via offline rendering. The repo claims billboard impostor support but ships a textureless mesh. | upgrade to A: integrate a real impostor baker — either via Blender's offscreen rendering (bpy.ops.render.render with N camera positions) or an external CLI like `impostor-baker`. Output a 2048×2048 RGBA atlas with depth in alpha.

### `prepare_gpu_instancing_export` (line 1094) — B
prior: B | what: groups instances by mesh_name, computes bounds, LOD distribution. | bug: writes to a JSON dict but doesn't actually write the file (returns export_data, leaving I/O to the caller). | AAA gap: real GPU instancing in Unity uses MaterialPropertyBlock or compute-buffer instancing; in UE5 it's HISM (Hierarchical Instanced Static Mesh). Just emitting JSON doesn't enable any of that — Unity-side code must consume this. | upgrade to A: emit a binary HISM-compatible format OR a Unity-side ScriptableObject that Unity ingests.

## Module: vegetation_system.py (836 lines)

### `BIOME_VEGETATION_SETS` (dict, line 43) — B+
14 biomes × (trees, ground_cover, rocks). Density values (0.03-0.50). Style variants. **Critical**: this references types like "veil_healthy", "veil_blighted", "dark_pine", "ice_pine", "ember_plant" — the types referenced here are NOT all defined as generators in `procedural_meshes.py`. The audit master doc notes "21+ scatter asset types lack mesh generators" — confirmed.

### `_max_slope_for_category` (line 262) — A
Trivial dispatch.

### `compute_vegetation_placement` (line 277) — A-
prior: A- | what: terrain vertex grid lookup + Poisson disk + slope/altitude/biome filter + density probability. | ref: Comparable to Unreal PCG Graph or Houdini scatter. | bug: water_level filter `if has_height_variation and norm_h < water_level` uses normalized height — vulnerable to BUG-50 (see below) when terrain has negative elevations. The `_sample_terrain` brute-force grid scan is O(N) per query — 9 cells × N candidates per cell. For 5K placements this is ~45K ops, fine. | AAA gap: no per-species overlap exclusion (oak and pine can spawn at the same point with different rolls). | upgrade to A: replace water_level normalized check with WorldHeightTransform per Addendum 3.A.

### `compute_wind_vertex_colors` (line 490) — A-
Same pattern as the L-system version. R = trunk distance, G = height, B = combined estimate. Standard.

### `get_seasonal_variant` (line 574) — B+
4 seasons (summer/autumn/winter/corrupted) with vegetation-type-specific tweaks. Reasonable.

### `_create_biome_vegetation_template` (line 651) — B+
Bpy template creator with generator dispatch. Clean.

### `scatter_biome_vegetation` (line 673) — B+
prior: B | what: pulls terrain mesh from bpy → compute placements → instantiate per-template → tag LOD distances. | bug: `max_instances=5000` cap silently truncates without warning. The template per-veg-type is created once and instances share data — that's correct Blender instancing. The `_setup_billboard_lod` only fires for trees (set `_TREE_VEG_TYPES` in lod_pipeline) — rocks/ground cover get only LOD distance custom props, no billboard. | AAA gap: no Hierarchical Instanced Static Mesh (HISM) export for Unity DOTS / UE5; no GPU compute culling. | upgrade to A: implement HISM-style hierarchical batching by spatial chunk.

## Module: environment.py (5435 lines)

This is the biggest mainstream entry point. ~50 public handle_* functions. I grade architecturally + key handlers.

### `_validate_terrain_params` / `_resolve_terrain_tile_params` (lines 577-625) — A-
Param validation + defaulting. Standard.

### `_export_heightmap_raw` / `_export_splatmap_raw` / `_export_world_tile_artifacts` (lines 684-751) — B+
Raw exporters. Adequate.

### `_resolve_height_range` / `_resolve_export_height_range` (lines 783-823) — B+
Honest height-range resolution honoring intent overrides.

### `_terrain_grid_to_world_xy` (line 854) — A
Grid → world conversion. Correct.

### `_resolve_water_path_points` / `_smooth_river_path_points` (lines 883-930) — B+
Catmull-Rom smoothing of river waypoint chains. Standard.

### `_estimate_tile_height_range` (line 1013) — B+
Per-tile min/max + buffer. Adequate.

### `_create_terrain_mesh_from_heightmap` (line 1040) — A-
prior: A- | what: 145-line Blender mesh builder from heightmap with cliff overlays + edge weld. | bug: hardcoded `cliff_threshold_deg=60.0`. | upgrade to A: parameterize.

### `_cliff_structures_to_overlay_placements` (line 1185) — B+
Translates cliff carver output to overlay placements. Adequate.

### `handle_generate_terrain` (line 1257) — A-
prior: A- | what: 332-line dispatch — biome preset resolution → controller path OR legacy path → mesh creation → cliff overlays → return result dict. | bug: 332-line function is way too long; should be split. The controller-path retry-on-missing-pass loop (lines 1381-1397) is a code smell — silently dropping passes that aren't registered hides errors. | AAA gap: no progressive quality / streaming. | upgrade to A: split into 5 helpers; surface missing-pass skips as warnings.

### `handle_generate_terrain_tile` (line 1589) — B+
Per-tile variant. ~180 lines. Solid pattern.

### `handle_generate_world_terrain` (line 1772) — B+
World-scale orchestrator. Calls 12-step.

### `_execute_terrain_pipeline` (line 1816) — A-
Controller pipeline runner. Clean.

### `handle_run_terrain_pass` (line 2123) — A-
Single-pass executor with intent reconstruction.

### `handle_generate_waterfall` (line 2184) — A-
prior: A- | what: 220-line waterfall generator with chain ID resolution, surface levels, banking. | bug: hardcoded chain naming convention. | upgrade to A: configurable.

### `handle_stitch_terrain_edges` (line 2409) — B+
Tile seam stitching — averages neighbor edge heights. Good for visual seamlessness; bad if neighboring tile has been independently eroded (averaging undoes erosion at seams).

### `handle_paint_terrain` (line 2497) — B
Terrain mask painting. Adequate.

### `handle_carve_river` (line 2609) — B+
River A* + heightmap carving. Comparable to World Creator's "river layer".

### `_clamp01` / `_smootherstep` / `_point_segment_distance_2d` (lines 2748-2778) — A
Pure helpers.

### `_apply_road_profile_to_heightmap` (line 2778) — B+
prior: B+ | what: applies road grade-cut profile along path. | ref: Standard. | upgrade to A: bank cant on curves.

### `_apply_river_profile_to_heightmap` (line 2836) — B+
River channel cut + bank. OK.

### `_derive_river_surface_levels` / `_sample_path_indices` / `_collect_bridge_spans` (lines 2935-2992) — B+
River chain analysis helpers.

### `_ensure_grounded_road_material` / `_paint_road_mask_on_terrain` / `_build_road_strip_geometry` / `_create_bridge_object_from_spec` / `_create_mesh_object_from_spec` (lines 3075-3345) — B+
Road / bridge handlers. Adequate.

### `_sanitize_waterfall_chain_id` / `_serialize_validation_issues` / `_coerce_point3` / `_offset_point3` (lines 3379-3416) — A
Helpers. Clean.

### `_resolve_waterfall_chain_id` / `_infer_waterfall_functional_positions` / `_publish_waterfall_functional_objects` (lines 3428-3518) — B+
Waterfall ID resolution + functional anchor publishing. Clean.

### `handle_create_cave_entrance` (line 3563) — B
Cave entrance creator. Limited — produces an inverted cone. Real caves need carved interior geometry.

### `handle_generate_road` (line 3617) — B+
Road generation. ~280 lines. Multi-step. Solid.

### `_ensure_water_material` / `_apply_water_object_settings` (lines 3896-4094) — B+
Water material setup. Adequate.

### `_build_terrain_world_height_sampler` / `_resolve_river_bank_contact` / `_resolve_river_terminal_width_scale` (lines 4124-4237) — B+
Sampler closures + river resolvers. Clean.

### `_boundary_edges_from_faces` (line 4269) — A-
Boundary edge extraction. Standard.

### `_build_level_water_surface_from_terrain` (line 4281) — B+
~290-line water surface mesh builder. Adequate.

### `handle_create_water` (line 4575) — B+
Water object creator. ~400 lines.

### `handle_carve_water_basin` (line 5002) — B
Basin carving. ~150 lines.

### `handle_export_heightmap` (line 5160) — A-
Unity RAW heightmap export. Standard 16-bit little-endian.

### `_nearest_pot_plus_1` (line 5232) — A
Power-of-two-plus-1 (Unity terrain dim convention). Trivial.

### `handle_generate_multi_biome_world` (line 5244) — B+
~140-line multi-biome dispatcher.

### `_compute_vertex_colors_for_biome_map` / `_stable_seed_offset` (lines 5390-5433) — B+
Biome vertex color compute + deterministic seed offset.

### `_build_tripo_environment_manifest` (line 491) — B-
prior: C | what: builds Tripo3D upload manifest from `_TRIPO_ENVIRONMENT_PROMPTS` (only 7 entries). | bug: master audit notes 7 entries vs 43 referenced biome assets — 36 biomes have no Tripo prompt fallback. | upgrade to A: expand to 43+ entries OR add a fallback prompt template.

### `_apply_biome_season_profile` / `get_vb_biome_preset` (lines 524-546) — B+
Biome preset application. Clean.

### `_run_height_solver_in_world_space` / `_normalize_altitude_for_rule_range` / `_resolve_noise_sampling_scale` (lines 137-176) — B+
World-space height solvers. Adequate.

### `_enhance_heightmap_relief` / `_temper_heightmap_spikes` (lines 192-217) — B+
Post-processing helpers. Reasonable defaults.

## Module: environment_scatter.py (1773 lines)

### `_assign_scatter_material` (line 146) — B
Bpy material assignment. Standard.

### `_vegetation_rotation` / `_prop_rotation` (lines 249-255) — A
Trivial Euler-tuple constructors.

### `_terrain_height_sampler` (line 261) — B+
Closure that samples terrain mesh height. Adequate.

### `_world_to_terrain_uv` / `_sample_heightmap_surface_world` / `_sample_heightmap_world` (lines 311-392) — B+
World↔terrain UV mapping + height sampling. Standard.

### `_terrain_axis_spacing_from_extent` / `_terrain_cell_size_from_extent` (lines 417-429) — A
Grid spacing helpers.

### `_create_template_collection` (line 493) — A
Bpy collection helper.

### `_create_vegetation_template` (line 503) — B+
Per-veg-type template creator. ~135 lines.

### `_add_leaf_card_canopy` / `create_leaf_card_tree` (lines 637-744) — B+
Manual leaf card construction. Bug: cards aren't camera-facing.

### `_create_grass_card` (line 826) — B+
Grass card geometry. ~125 lines. Adequate.

### `_rock_size_from_power_law` (line 953) — A-
Power-law size distribution. Statistically realistic.

### `_generate_combat_clearing` (line 972) — B+
Clearing generation. Adequate.

### `_scatter_pass` (line 1057) — B+
prior: B+ | what: Poisson-disk scatter for trees/bushes/grass/rocks with biome density and exclusion checks. | ref: This is the canonical scatter approach. The slope filter, building exclusion, clearing exclusion are all correct. | bug: lines 1148, 1168 use `if h < 0.1 or h > 0.7` to gate trees by NORMALIZED height — assumes terrain is `[0..1]` normalized, breaks on signed-elevation terrain (per BUG-50/Addendum 3.A). | AAA gap: no per-species exclusion radius (trees and bushes share Poisson disks; should exclude each other within ~2m). | upgrade to A: switch normalized height gate to WorldHeightTransform; add per-species exclusion KD-tree.

### `handle_scatter_vegetation` (line 1266) — B+
prior: B | what: ~250-line bpy handler. Clean dispatch into _scatter_pass + collection-based instancing. | bug: very long; could split into helpers. | upgrade to A: refactor to <120 lines.

### `_create_prop_template` / `handle_scatter_props` (lines 1519-1565) — B+
Prop scattering. Adequate.

### `handle_create_breakable` (line 1638) — B
Breakable object creator. Adequate. Uses pre-fragmented LOD.

## Module: atmospheric_volumes.py (444 lines)

### `ATMOSPHERIC_VOLUMES` (dict, line 28) — B+
7 volume types (ground_fog, dust_motes, fireflies, god_rays, smoke_plume, spore_cloud, void_shimmer) with shape/density/color/opacity/animation params.

### `BIOME_ATMOSPHERE_RULES` (dict, line 110) — B+
10 biomes × volume assignments. Reasonable curation.

### `compute_atmospheric_placements` (line 172) — D+
prior: F (per master audit BUG-11) | what: Poisson scatter inside 2D area_bounds with shape-derived size. | bug: **CRITICAL — BUG-11 confirmed**: every placement gets `pz = 0.0` (line 234) — there is ZERO terrain awareness. Fog volumes appear at world Z=0 regardless of where the ground is. Spheres get `pz = r * 0.5` (centered above world Z=0, NOT above terrain). God rays get `pz = sz` (height above world Z=0). On a mountain biome with terrain at Z=2000m, fog will appear 2000m below the ground and be invisible. | AAA gap: real atmospheric volumes in HDRP / Unreal Volumetric Fog need (a) world position relative to ground, (b) min/max altitude bounds, (c) terrain-projected mask. None present. | upgrade to A: accept a `terrain_height_sampler: Callable[[float, float], float]` and bake `pz = sample(px, py) + height_offset_m`.

### `compute_volume_mesh_spec` (line 282) — C+
prior: C+ | what: produces box/sphere/cone mesh placeholders for volumes. | bug: VDB volumes / Unity HDRP Local Volumetric Fog don't use mesh approximations — they use density textures (3D LUTs) sampled by the volumetric integrator. This mesh approach is artist-side proxy geometry only. | AAA gap: no actual VDB / 3D-density export. | upgrade to A: emit OpenVDB files (via `pyopenvdb`) for volumetric clouds; for mesh-based fog use the `LocalVolumetricFog` Unity component which expects 3D textures.

### `estimate_atmosphere_performance` (line 389) — A-
prior: A- | what: rough cost estimator (count + per-particle + per-distortion). | bug: cost coefficients are arbitrary, not measured. | upgrade to A: tie to actual GPU cost data per-effect (e.g., HDRP Local Volumetric Fog ms/cm³).

### `_count_by_type` (line 438) — A
Trivial counter.

## Module: terrain_fog_masks.py (208 lines)

### `compute_fog_pool_mask` (line 44) — A-
prior: A- | what: altitude-weighted (gamma 1.5) + concavity-weighted laplacian-based fog accumulation, smoothed via 3×3 box blur. | ref: This is the right physical model for ground fog — cold dense air pools in basins. The percentile-based normalization handles outliers. | bug: 3×3 box blur is the cheapest possible filter; gives blocky 1-cell-resolution boundaries on tile-edge fog. | upgrade to A: replace box blur with gaussian (5×5 sigma=1.5) for visual smoothness.

### `compute_mist_envelope` (line 103) — B+
prior: B+ | what: 4-step dilation of wetness mask with linear falloff. | bug: 4-connected dilation; diagonal cells get under-mist'd. | upgrade to A: 8-connected dilation OR scipy.ndimage.distance_transform_edt for true Euclidean distance.

### `pass_fog_masks` (line 143) — A-
Combines fog_pool + mist into authoritative `mist` channel. Good.

### `register_bundle_l_fog_masks_pass` (line 187) — A

## Module: terrain_god_ray_hints.py (281 lines)

### `GodRayHint` (dataclass, line 37) — A
Frozen dataclass with serialization. Clean.

### `_normalize_sun_dir` (line 59) — A-
Sun direction clamp. Fine.

### `compute_god_ray_hints` (line 68) — B+
prior: B+ | what: detects god-ray sources via concavity + cave/waterfall masks + cloud-shadow edges. Returns top-16 hints. | ref: Smart heuristic. | bug: the inner `for r in range(1, rows-1): for c in range(1, cols-1):` non-max suppression is O(H×W) Python loop — slow on 1024×1024 tiles (~1M iterations × inner 3×3 max). Should vectorize via scipy.ndimage.maximum_filter. | upgrade to A: vectorize NMS with scipy or numpy stride tricks.

### `export_god_ray_hints_json` (line 196) — A
Deterministic JSON export.

### `pass_god_ray_hints` (line 216) — A-
Standard pass.

### `register_bundle_l_god_ray_hints_pass` (line 258) — A

## Module: terrain_cloud_shadow.py (141 lines)

### `_value_noise` (line 24) — B+
Bilinear-interpolated value noise with smoothstep. Standard.

### `compute_cloud_shadow_mask` (line 55) — B-
prior: B | what: 2-octave value noise → threshold for cloud_density coverage. | bug: **NO cross-tile coherence** — the seed mixes `state.intent.seed ^ tile_x * c1 ^ tile_y * c2` (cloud_shadow.py is called from pass with such mixing) — adjacent tiles will show hard discontinuous cloud edges at seams. Real cloud shadow is a single global field sampled by all tiles. **No advection** — clouds are static; real games animate the cloud field via UV scrolling driven by wind direction. | AAA gap: HDRP / Unreal Volumetric Clouds use 3D Worley noise + temporal advection. | upgrade to A: switch to a global world-space noise function (no tile-scoped seed) so all tiles sample the same field; expose `wind_velocity_m_per_s` for advection.

### `pass_cloud_shadow` (line 84) — B-
Same issue.

### `register_bundle_j_cloud_shadow_pass` (line 121) — A

## Module: terrain_audio_zones.py (208 lines)

### `AudioReverbClass` (IntEnum, line 28) — A
8 reverb classes mapped to Unity preset values. Clean.

### `compute_audio_reverb_zones` (line 49) — A-
prior: A- | what: priority-based classification using cave_candidate / interior / water / canyon / mountain / forest / sparse / open. | ref: This is the standard audio zone bake approach. The priority order is correct (interior > cave > canyon > water > mountain > forest > open). | bug: forest_dense threshold > 0.6 is hardcoded; should be biome-relative. | upgrade to A: parameterize thresholds per biome.

### `pass_audio_zones` (line 139) — A-
Trivial sanity check (warns if all OPEN_FIELD).

### `register_bundle_j_audio_zones_pass` (line 185) — A

## Module: terrain_assets.py (926 lines)

### `AssetRole` (Enum, line 62) — A
9 roles. Clean.

### `ViabilityFunction` / `AssetContextRule` / `ClusterRule` (dataclasses, lines 79-119) — A
Frozen dataclasses with declarative envelope fields.

### `_DEFAULT_ROLE_MAP` / `classify_asset_role` (lines 128-152) — A-
Lookup + heuristic fallback. Clean.

### `build_asset_context_rules` (line 176) — A-
Default rule set with ~12 asset types. Reasonable.

### `compute_viability` (line 283) — A
prior: A | what: vectorized per-cell viability mask combining slope/altitude/wetness/required/forbidden masks. No Python loops. | ref: This is the canonical Houdini / Unreal PCG viability evaluation pattern, executed in numpy. | bug: when slope is required but absent (line 311-313), the function bails to all-zero — this is correct conservative behavior. | upgrade: None — production-quality.

### `_cell_to_world` (line 346) — A
Z-up world coord conversion. Reads stack.height directly per Bundle E contract.

### `_poisson_in_mask` (line 362) — A-
prior: A | what: Bridson-style spatial-hash Poisson disk constrained to a viability mask. | ref: This is correct, fast (O(N) hash lookups), deterministic. | bug: `max_attempts=20` is the candidate iteration count — should be Bridson's 30. The shuffled-candidate approach is similar to what Houdini Poisson Scatter does. | upgrade to A: bump max_attempts to 30 to match Bridson.

### `_protected_mask` / `_region_mask` (lines 432-458) — A-
Vectorized region masks. Clean.

### `place_assets_by_zone` (line 481) — A
prior: A | what: per-rule viability + Poisson sample + world-space conversion. Deterministic via derive_pass_seed. Honors region + protected. | upgrade: None — A.

### `_cluster_around` (line 530) — A-
prior: A- | what: clusters N rocks around each "hot" mask cell with stride-based downsampling so clusters don't overlap. | bug: `stride = ceil(radius_m / cell_size)` only ensures cluster CENTERS are stride-apart; placements within clusters can still overlap (random angle/distance with no rejection sampling). | upgrade to A: add intra-cluster Poisson check.

### `cluster_rocks_for_cliffs` / `cluster_rocks_for_waterfalls` / `scatter_debris_for_caves` (lines 601-644) — A-
Specialized clusterers with appropriate count + radius defaults.

### `validate_asset_density_and_overlap` (line 660) — A-
O(n²) overlap check; fine for bounded asset counts per tile.

### `_TREE_LIKE_ROLES` / `_build_tree_instance_array` / `_build_detail_density` (lines 732-762) — A
Unity-contract materialization. Tree array is `(N, 5)` with `(x, y, z, rot, prototype_id)` matching the manifest contract.

### `pass_scatter_intelligent` (line 790) — A
prior: A | what: full pass — viability → Poisson → cluster-add → materialize → validate. Writes tree_instance_points + detail_density. | ref: This is the **best-implemented module in the audit** — it's what I'd expect from a senior procgen engineer at Guerrilla or Naughty Dog. | bug: hard-coded namespace strings could be class-level constants. | upgrade: None — already A.

### `register_bundle_e_passes` (line 893) — A

## Module: terrain_asset_metadata.py (188 lines)

### `LOCATION_TAGS` / `ROLE_TAGS` / `SIZE_TAGS` / `CONTEXT_TAGS` (lines 22-44) — A
Frozen taxonomy. Clean.

### `AssetMetadata` (dataclass, line 53) — A
4-tag container.

### `validate_asset_metadata` (line 66) — A
prior: A | what: per-tag validation with hard-issue codes. | ref: Matches Quixel's metadata schema validation. | upgrade: None.

### `classify_size_from_bounds` (line 144) — A
Bbox → size tag. Trivial.

### `AssetContextRuleExt` (dataclass, line 164) — A
Extension fields with role-based variance multiplier. Clean.

## Module: terrain_gameplay_zones.py (176 lines)

### `GameplayZoneType` (IntEnum, line 26) — A
7 zone types. Clean enum.

### `compute_gameplay_zones` (line 36) — A-
prior: A- | what: heuristic classification using slope + basin + curvature + detail_density + cave + intent.hero_features + boss_arena_bbox. | ref: Reasonable AAA gameplay-zone bake — Witcher 3 uses similar heuristics. | bug: STEALTH heuristic gates on `total > 0.5` (sum of detail_density layers) — if 4 layers each contribute 0.15, sum=0.60 ⇒ STEALTH; tunable but arbitrary. | upgrade to A: parameterize thresholds via composition_hints.

### `pass_gameplay_zones` (line 122) — A-
Standard pass.

### `register_bundle_j_gameplay_zones_pass` (line 155) — A

## Module: terrain_wildlife_zones.py (287 lines)

### `SpeciesAffinityRule` (dataclass, line 28) — A
Frozen dataclass with slope/altitude/biome/water_proximity/exclusion fields.

### `_window_score` (line 56) — A-
Smooth-falloff window with 20% margin. Standard.

### `_distance_to_mask` (line 69) — C
prior: C | what: pure-numpy two-pass chamfer distance transform. | bug: **Python double-loop** (lines 82-110) — O(H×W) per pass on a 1024×1024 tile is 2M iterations × constant-factor python overhead. **Slow** — ~5 seconds per call, called twice (water + exclusion). The whole thing should be `scipy.ndimage.distance_transform_edt` (one line, vectorized C). The comment says "avoids scipy dependency" but scipy is in numpy's transitive deps and is in this project. | AAA gap: production tools use scipy or skfmm (scikit-fmm) for fast marching. | upgrade to A: replace with `scipy.ndimage.distance_transform_edt(~mask) * cell_size`.

### `compute_wildlife_affinity` (line 116) — A-
prior: A- | what: per-species score combining slope window + altitude window + biome filter + water proximity + exclusion. | bug: depends on slow `_distance_to_mask`. | upgrade to A: scipy.

### `DEFAULT_WILDLIFE_RULES` (line 196) — A-
3 species (deer, wolf, eagle) with reasonable parameters. AAA games have 30-50 species; this is starter set.

### `pass_wildlife_zones` (line 216) — A-
Standard pass.

### `register_bundle_j_wildlife_zones_pass` (line 263) — A

## Module: terrain_navmesh_export.py (239 lines)

### `compute_navmesh_area_id` (line 37) — A-
prior: A- | what: priority-based area classification (UNWALKABLE → WALKABLE → CLIMB → JUMP → SWIM). | ref: Matches Unity NavMeshSurface area IDs and Recast NavMesh agent area types. | bug: 65° steep-slope hardcoded; should be biome-relative. | upgrade to A: parameterize.

### `compute_traversability` (line 83) — A-
0..1 cost gradient combining slope + water + bank_instability + talus + hero_exclusion.

### `export_navmesh_json` (line 121) — A-
prior: A- | what: writes Unity-consumable navmesh descriptor with area-ID table + stats. | bug: descriptor only — does NOT actually generate a .navmesh asset. Unity must run NavMeshSurface.BuildNavMesh() at editor or runtime time to consume the area mask. | AAA gap: real production exports a baked navmesh polygon set (Recast tile mesh) via recastnavigation Python bindings. This is metadata only. | upgrade to A: integrate `recastnavigation-python` to bake actual navmesh polygons.

### `pass_navmesh` (line 176) — A-
Standard pass.

### `register_bundle_j_navmesh_pass` (line 212) — A

## Module: terrain_unity_export.py (654 lines)

### `_sha256` (line 26) — A
Standard hash.

### `_quantize_heightmap` (line 34) — A
prior: A | 16-bit quantization. Matches Unity terrain RAW import contract. Verified via Microsoft Learn / Unity docs (16-bit RAW grayscale).

### `_compute_terrain_normals_zup` (line 45) — A-
prior: A- | what: numpy.gradient-based normal field, normalized. | bug: edge_order=1 is one-sided differences at boundaries; produces edge-normal artifacts. | upgrade to A: edge_order=2 for second-order accurate edges.

### `_zup_to_unity_vectors` (line 62) — A
Z-up → Y-up swap. Correct.

### `_export_heightmap` (line 73) — A-
Backward-compat. Uses local min/max which is wrong if intent provides explicit range. The newer `_quantize_heightmap` (line 34) does it right by reading `stack.height_min_m`. The two coexisting versions is technical debt.

### `_bit_depth_for_profile` (line 89) — A
Returns 16 always. Deterministic.

### `pass_prepare_terrain_normals` / `pass_prepare_heightmap_raw_u16` (lines 95-120) — A
Pre-pass populators. Clean.

### `register_bundle_j_terrain_normals_pass` / `register_bundle_j_heightmap_u16_pass` (lines 146-162) — A

### `_flip_for_unity` (line 178) — A
Vertical flip for Unity convention.

### `_ensure_little_endian` (line 185) — A
Endian normalization. Correct.

### `_write_raw_array` (line 192) — A-
RAW writer with metadata records. Clean.

### `_write_json` (line 224) — A
JSON writer.

### `_zup_to_unity_vector` / `_bounds_to_unity` (lines 243-248) — A
Per-vector conversion.

### `_terrain_normal_at` (line 255) — A-
Local 3×3 finite-difference normal at cell. Clean.

### `_quantize_detail_density` (line 274) — A
0..1 → uint16 detail count. Matches Unity TerrainData.SetDetailLayer convention.

### `_write_splatmap_groups` (line 280) — A
prior: A | Pads to RGBA u8 groups of 4 layers each. Matches Unity splatmap contract (each splatmap texture is RGBA).

### `export_unity_manifest` (line 323) — A-
prior: A- | what: writes heightmap.raw, terrain_normals.bin, splatmap_XX.raw, navmesh/wind/cloud/gameplay/audio/traversability raw, detail_density per kind, wildlife per species, decal density per kind, plus 6 JSON sidecars. | ref: This is comprehensive. The bit-depth/encoding/sha256 manifest entry per file is good. | bug: writes `.bin` for navmesh/wind/cloud/etc. as `raw_le` without specifying dtype — Unity importer needs to know if it's int8 vs uint16 vs float32. The dtype is in the metadata but not in the filename. | AAA gap: missing TreeInstance prototype mesh paths (tree_instances.json includes prototype_id but no mesh registry). Missing actual `TerrainData.asset` (Unity binary YAML with all this packed) — engine still must Reimport. | upgrade to A: include dtype suffix in filename (e.g. `navmesh_area_id_i8.bin`); generate a Unity-side editor script that auto-creates TerrainData.asset on import.

### `_audio_zones_json` / `_gameplay_zones_json` / `_wildlife_zones_json` / `_decals_json` / `_tree_instances_json` (lines 489-627) — A-
Per-zone JSON serializers. Bug: `_decals_json` caps at `coords[:512]` per kind — silently drops the rest. Should warn or split.

## Module: terrain_unity_export_contracts.py (304 lines)

### `UnityExportContract` (dataclass, line 25) — A
prior: A | per-file bit-depth contract.

### `REQUIRED_MESH_ATTRIBUTES` / `REQUIRED_VERTEX_ATTRIBUTES` (lines 60-83) — A
Frozen tuples + invariant assertions. Smart.

### `validate_mesh_attributes_present` / `validate_vertex_attributes_present` (lines 86-109) — A
Hard-fail validators per Addendum 1 §33.

### `write_export_manifest` (line 138) — A
Writes manifest.json with required-key check.

### `validate_bit_depth_contract` (line 163) — A-
prior: A- | what: validates per-file bit_depth + encoding against UnityExportContract. | bug: shadow_clipmap encoding check (line 290) compares to literal `"float"` but actual files use `"float32_npy"` — false negatives because shadow_clipmap currently writes `.npy` (BUG-58). | upgrade to A: align encoding strings.

## Module: lod_pipeline.py (1128 lines)

### `LOD_PRESETS` (dict, line 24) — B+
8 asset-type LOD presets with ratios + screen percentages + min_tris. Reasonable.

### `_cross` / `_sub` / `_dot` / `_normalize` / `_face_normal` (lines 78-111) — A
Vector helpers. Standard.

### `compute_silhouette_importance` (line 131) — B+
prior: B+ | what: cast 14 view directions, classify faces front/back, vertices on silhouette edges accumulate score, normalized to [0,1]. | ref: This is a smart heuristic — closer to "view-independent silhouette importance" than true QEM. | bug: 14 hardcoded directions; non-uniform sampling on the sphere (cardinal + 8 corners) under-samples the equator. | AAA gap: real LOD systems (Meshoptimizer, Simplygon, InstaLOD) use Quadric Error Metrics that minimize visual error globally rather than per-view sampling. | upgrade to A: switch to QEM (Garland-Heckbert) — this is the industry standard since 1997. ~150 lines of code.

### `compute_region_importance` (line 218) — A-
Region-tag importance boost.

### `_edge_collapse_cost` (line 254) — B
prior: B | what: edge_length × (1 + avg_importance × 5). | bug: this is NOT QEM — true QEM uses the sum of squared distances from collapsed point to neighboring planes. Edge length is a poor proxy. | upgrade to A: replace with QEM cost.

### `decimate_preserving_silhouette` (line 276) — C+
prior: C | what: greedy edge collapse by ascending cost, union-find vertex merge. | bug: **NOT proper LOD generation**. (a) Cost is edge length only — a long edge in a flat region will collapse before a short edge on a silhouette ridge, which destroys the silhouette. (b) Vertex midpoint is importance-weighted lerp — but proper QEM places the new vertex at the optimal point that minimizes the quadric error. (c) No topology preservation — collapses can produce non-manifold, self-intersecting meshes. | AAA gap: meshoptimizer's `meshopt_simplify` is the open-source baseline; Simplygon is the commercial standard. This implementation will produce visibly worse LODs than either. | upgrade to A: integrate `pymeshoptimizer` (Python bindings) OR write proper QEM (~200 lines).

### `generate_collision_mesh` (line 413) — B
prior: B | what: incremental convex hull. | bug: centroid computation in horizon-edge orientation (lines 553-558) uses `hull_vert_set` which contains ORIGINAL indices that may have been compacted away. The `tet_normal` orientation flip is correct but the centroid heuristic is fragile on degenerate point sets. | AAA gap: real production uses qhull (via scipy.spatial.ConvexHull) — it's tested, fast, and handles all degenerate cases. | upgrade to A: replace with `scipy.spatial.ConvexHull(vertices).simplices` — 3 lines.

### `_generate_billboard_quad` (line 588) — D+
prior: D | what: produces a SINGLE vertical quad facing +Y from the bounding box. | bug: a single quad is the LOWEST quality billboard — visible flat from any non-Y angle. Real billboards either (a) face the camera (runtime shader) or (b) use cross-billboards (2 perpendicular quads from `cross` impostor type) or (c) use octahedral imposters with 8-16 view atlas. **Single quad is 1995-tier.** | AAA gap: every modern game uses cross-billboards minimum, octahedral imposters preferred. | upgrade to A: at minimum produce cross-billboards (2 quads); ideally call `vegetation_lsystem.generate_billboard_impostor` and bake a real atlas.

### `_auto_detect_regions` (line 636) — B
Bbox-heuristic vertex region detection. Hardcoded thresholds (face=top 13%, hands=Y 35-50% + X>70%). Works for character bipeds, fails for everything else.

### `generate_lod_chain` (line 708) — C+
prior: C+ | what: per-LOD ratio decimation + billboard at ratio=0. | bug: depends on broken `decimate_preserving_silhouette`. The billboard step at LOD3 produces a single quad (per `_generate_billboard_quad`). | upgrade to A: fix decimation + billboard.

### `SCENE_BUDGETS` / `SceneBudgetValidator` (lines 779-901) — A-
Pre-defined budget thresholds + validator with recommendations. Clean.

### `handle_generate_lods` (line 909) — B
Bpy handler that generates the LOD chain + collision mesh in Blender. Adequate plumbing.

### `_setup_billboard_lod` (line 1048) — C
prior: C+ | what: tags template with billboard custom properties. | bug: calls `generate_billboard_impostor` to get specs but only stores metadata — never bakes an atlas, never creates a billboard mesh as a child object. The LOD switch in Unity will fail at distance because the billboard texture doesn't exist. | upgrade to A: actually bake the atlas + create a billboard mesh child + assign the atlas material.

## Module: terrain_telemetry_dashboard.py (164 lines)

### `TelemetryRecord` (dataclass, line 22) — A
Clean. JSON round-trip. Standard telemetry shape.

### `_count_populated_channels` (line 56) — A
Iterates `_ARRAY_CHANNELS` to count non-None.

### `record_telemetry` (line 65) — A-
prior: A- | what: append-only newline-delimited JSON log. | ref: Standard Loki/Promtail-compatible format. | bug: no log rotation — file grows unbounded. | upgrade to A: rotate at 100MB.

### `_load_records` / `summarize_telemetry` (lines 96-113) — A-
Parse + aggregate. Clean.

## Module: terrain_performance_report.py (187 lines)

### `DEFAULT_BUDGETS` (dict, line 18) — B+
Per-category triangle budgets. Reasonable AAA values.

### `TerrainPerformanceReport` (dataclass, line 27) — A
Frozen-style dataclass with status field. Critical: status defaults to `not_available` (per docstring "never returns fake ok").

### `_channel_bytes` (line 44) — A
Trivial sizeof.

### `collect_performance_report` (line 50) — A
prior: A | what: real per-category triangle estimates from mask channels, instance counts from tree_instance_points + detail_density, material count from splatmap layers, draw-call proxy = materials + nonzero channels, texture memory in MB. **Returns `not_available` when stack/height is missing — does NOT fake `ok`**. | ref: Honest performance reporter — the docstring even calls out "the previous lambda stub false-passed the performance gate and is now dead code". | upgrade: None — production-quality.

### `serialize_performance_report` (line 178) — A
JSON serializer.

## Module: terrain_visual_diff.py (172 lines)

### `_bbox_of_mask` (line 18) — A-
prior: A- | what: world-space bbox of True cells via row/col any. | bug: degenerate single-cell masks return correct 1×1 bbox — fine. | upgrade: None.

### `compute_visual_diff` (line 40) — A-
prior: A- | what: per-channel max+mean abs delta + changed-cells count + bbox. Handles missing/added channels and shape mismatches. | upgrade to A: optionally include per-channel SSIM/PSNR.

### `generate_diff_overlay` (line 120) — A-
RGB overlay (R=height up, B=height down, G=other channels changed). Clean.

## Module: terrain_footprint_surface.py (112 lines)

### `FootprintSurfacePoint` (dataclass, line 21) — A
Clean.

### `_world_to_cell` (line 31) — A
World→cell with clip.

### `compute_footprint_surface_data` (line 42) — A-
prior: A | what: samples height, normal (finite diff), material_id, wetness, in_cave per query position. | ref: Matches Unity gameplay footprint pipeline (Witcher 3 uses identical surface query). | upgrade to A: bilinear height interpolation instead of nearest cell (current code uses round-to-nearest which produces stairstep heights).

### `export_footprint_data_json` (line 104) — A
JSON export.

## Module: terrain_framing.py (171 lines)

### `enforce_sightline` (line 27) — B+
prior: B+ | what: lowers cells obstructing vantage→target ray with radial Gaussian falloff. | bug: `feather_cells = max(2.0, 4.0 / 1.0)` is always 4.0 — the conditional is dead code. The clearance calculation only goes from vantage TO target — does not reverse-test from target back. | AAA gap: real "framing" in Witcher 3's level art is hand-authored; procedural sightline cuts are a rough approximation. | upgrade to A: bidirectional ray, smarter cut profile (cone, not gaussian).

### `pass_framing` (line 87) — A-
Iterates vantages × hero_features, accumulates min delta, applies. Region-scope respect missing (`supports_region_scope=False` in registrar).

### `register_framing_pass` (line 149) — A

## Module: terrain_rhythm.py (192 lines)

### `_positions_xy` (line 24) — A
Position extraction from mixed types.

### `analyze_feature_rhythm` (line 37) — A-
prior: A- | what: nearest-neighbor distance CV → rhythm metric (1 - CV). | ref: This is a known measure of point pattern regularity. | bug: O(n²) NN computation for n features — fine for n<1000. | upgrade to A: use scipy.spatial.cKDTree for n>500.

### `enforce_rhythm` (line 91) — B+
prior: B+ | what: 3-iteration Lloyd-relaxation-style nudging toward target spacing. | bug: only operates on dict and tuple/list inputs — HeroFeatureSpec is frozen and skipped, but the function silently returns the same hero specs without nudging them. Caller may not realize hero positions weren't moved. | upgrade to A: emit a warning when features are skipped due to immutability.

### `validate_rhythm` (line 163) — A-
Soft-fail when rhythm < 0.4. Reasonable threshold.

## Module: terrain_saliency.py (326 lines)

### `_world_to_cell` / `_sample_height_bilinear` (lines 32-43) — A
Helpers.

### `compute_vantage_silhouettes` (line 66) — B
prior: B+ | what: per-vantage azimuthal ray cast, max silhouette elevation per ray. | bug: triple-nested Python loop (V vantages × ray_count rays × n_samples per ray). For V=4, ray_count=64, n_samples=256 → 65K iterations × bilinear sampler. ~2 seconds per call. Should vectorize. | upgrade to A: vectorize via numpy broadcasting (precompute all (V, ray, sample) coords, batch sample).

### `auto_sculpt_around_feature` (line 124) — B+
Radial Gaussian bump/dip around feature. Clean.

### `_rasterize_vantage_silhouettes_onto_grid` (line 199) — B+
Per-vantage azimuth-binned projection. Clean.

### `pass_saliency_refine` (line 245) — A-
60% existing + 40% vantage mask blend. Standard.

### `register_saliency_pass` (line 302) — A

## Module: terrain_readability_bands.py (232 lines)

### `BAND_IDS` / `BAND_WEIGHTS` (lines 27-29) — A
Frozen 5-band weights summing to 1.0.

### `BandScore` (dataclass, line 38) — A
Clean dataclass with clamp.

### `_safe_std` / `_normalize_to_score` (lines 52-67) — A
Helpers.

### `_band_silhouette` (line 70) — A-
Horizon profile variance from row/column max. Clean.

### `_band_volume` (line 90) — A-
3-bin histogram entropy of heights. Clean.

### `_band_value` (line 117) — A-
Slope CV (std/mean). Clean.

### `_band_texture` (line 144) — A-
High-freq detail = height - 3×3 mean. Clean.

### `_band_color` (line 172) — A-
macro_color per-channel std mean. Clean.

### `compute_readability_bands` / `aggregate_readability_score` (lines 200-211) — A
Aggregator.

## Module: terrain_readability_semantic.py (245 lines)

### `check_cliff_silhouette_readability` (line 21) — A
prior: A | cliff coverage > 0.5% AND > 25% sharp cells (slope > 0.7 rad). Clean hard-fail rules.

### `check_waterfall_chain_completeness` (line 88) — A
Per-chain source/lip/pool/outflow check.

### `check_cave_framing_presence` (line 128) — A
≥2 framing markers + damp signal.

### `check_focal_composition` (line 176) — A
Rule-of-thirds distance check (< 0.10).

### `run_semantic_readability_audit` (line 224) — A
Aggregator. Clean.

## Module: terrain_scatter_altitude_safety.py (65 lines)

### `audit_scatter_altitude_conversion` (line 41) — A
prior: A | what: regex audit of source code for the 5 known bad altitude-normalization patterns (Addendum 3.A bug canary). | ref: Cleverly defensive — this is a "lint rule" enforced as a Python function. Catches the recurring `heights / heights.max()` bug. | upgrade: None.

## Module: terrain_vegetation_depth.py (608 lines)

### `VegetationLayer` / `VegetationLayers` / `DisturbancePatch` / `Clearing` (lines 38-72) — A
Clean dataclasses for 4-layer vegetation model.

### `_region_slice` / `_protected_mask` / `_normalize` (lines 83-125) — A
Helpers.

### `compute_vegetation_layers` (line 140) — A-
prior: A- | what: 4-layer stratification driven by slope+altitude+wetness+wind, with biome scalars (4 biomes). | ref: This is a real 4-layer stratification — comparable to Horizon ZD's vegetation density passes. | bug: only 4 biome scalars defined ("dark_fantasy_default", "tundra", "swamp", "desert"); 14 biomes elsewhere will fall back to default. | upgrade to A: complete biome scalar table.

### `detect_disturbance_patches` (line 223) — A-
Deterministic placement of fire/windthrow/flood patches. Clean.

### `place_clearings` (line 274) — A-
Poisson-disk sampled clearings with O(n²) overlap rejection. Adequate for n<200.

### `place_fallen_logs` (line 334) — A-
Poisson-disk in forest mask. Clean.

### `apply_edge_effects` (line 389) — B+
4-ring iterative dilation for biome-boundary edge boost. Clean.

### `apply_cultivated_zones` (line 440) — A-
Override with farmland densities. Simple.

### `apply_allelopathic_exclusion` (line 472) — A-
Species-suppression. Cool ecology touch.

### `pass_vegetation_depth` (line 504) — A-
Standard pass with protected-zone honoring.

### `register_vegetation_depth_pass` (line 580) — A

## Module: terrain_twelve_step.py (370 lines)

### `_apply_flatten_zones_stub` (line 42) — F
prior: F | what: **literal pass-through `return world_hmap`**. | bug: **STEP 4 OF THE CANONICAL 12-STEP IS A STUB**. Per docstring "Steps 4 and 5 are pass-through stubs". The orchestrator claims to apply flatten zones (building foundations, road grade) but does nothing. | upgrade to A: import `terrain_advanced.flatten_multiple_zones` and call it. The function exists.

### `_apply_canyon_river_carves_stub` (line 47) — F
prior: F | what: **also pass-through**. | bug: **STEP 5 IS A STUB**. River and canyon A* carving is unimplemented at the world level (per-tile river handlers exist but aren't called from the world orchestrator). | upgrade to A: call into terrain_advanced or _terrain_noise river-carving functions.

### `_detect_cliff_edges_stub` / `_detect_cave_candidates_stub` / `_detect_waterfall_lips_stub` (lines 54-83) — B
prior: B | what: simple gradient + local-min + plateau-drop heuristics. Despite "_stub" suffix, these DO real work. | bug: misleading naming — "_stub" implies non-functional; these actually compute cliff/cave/waterfall candidates via simple thresholds. The local-min detection is a Python double loop O(H×W) — slow at large worlds. | upgrade to A: rename to drop "_stub" suffix; vectorize local-min via scipy.ndimage.minimum_filter.

### `_generate_road_mesh_specs` (line 97) — B+
Calls into `_terrain_noise.generate_road_path` for actual road computation. Clean.

### `_generate_water_body_specs` (line 146) — B
Threshold-based water body detection from flow accumulation. Adequate.

### `run_twelve_step_world_terrain` (line 207) — B+
prior: B+ | what: orchestrates 12-step sequence with audit trail. | bug: the docstring SAYS Steps 1-9 + 12 do real work, Steps 10-11 are stubs — but ALSO Steps 4-5 are stubs (functions above). So really only Steps 1-3, 6-9, 12 do real work, and 10-11 do partial work via helpers. The audit trail does not surface the stub status. | upgrade to A: complete Steps 4 & 5; surface stubs in the result dict.

## Module: terrain_live_preview.py (189 lines)

### `_clone_stack_for_diff` (line 24) — A-
Deep-copy of array channels + populated_by_pass. Clean.

### `LivePreviewSession` (dataclass, line 38) — A-
prior: A- | what: holds controller + cache + tracker + history. | bug: history grows unbounded. | upgrade to A: cap at 100 entries.

### `apply_edit` (line 69) — A-
prior: A- | what: marks dirty, invalidates cache, runs passes through cache or region executor, records hash. | bug: cache invalidate uses prefix match — could over-invalidate. | upgrade to A: precise channel→cache-entry index.

### `diff_preview` / `diff_stacks` / `snapshot_stack` (lines 109-133) — A-
Clean.

### `edit_hero_feature` (line 138) — F
prior: F | what: **PURELY COSMETIC** — appends string labels to `state.side_effects` for translate/scale/rotate/material mutations. **NEVER actually mutates anything**. Lines 165-179 each just `state.side_effects.append(f"edit:{feature_id}:translate:...")` — no actual position update, no actual scale update, no actual material assignment. | bug: **CRITICAL** — this is a fake editor. Calling `edit_hero_feature(state, "boss_arena", [{"type": "translate", "dx": 100}])` reports `applied=1` but the boss_arena has not moved. Any test relying on this passes false. | upgrade to A: actually look up the HeroFeatureSpec by ID, construct a new frozen instance with mutated fields, swap into intent.hero_feature_specs tuple, mark relevant channels dirty.

## Module: terrain_checkpoints.py (374 lines)

### `save_checkpoint` (line 60) — A-
prior: A- | what: serialize mask stack to npz + record TerrainCheckpoint with hash + parent + label. | bug: no atomic write (raw `to_npz` then add to checkpoints — if interrupted, .npz exists but no record). | upgrade to A: temp + rename + record.

### `rollback_last_checkpoint` / `rollback_to` (lines 111-119) — A
Clean.

### `list_checkpoints` (line 126) — A
JSON-safe summary.

### `_intent_to_dict` / `_intent_from_dict` (lines 162-214) — A-
Round-trip serialization. Clean.

### `save_preset` / `restore_preset` (lines 271-303) — A-
Atomic JSON write (`.tmp` + `replace`). Clean. Bug: NPZ write is NOT atomic.

### `autosave_after_pass` (line 320) — A-
prior: A | monkey-patches run_pass to autosave on success. Pure-additive, restorable. Bug: try/except swallows ALL exceptions silently — should log warning. | upgrade to A: log on autosave failure.

## Module: terrain_checkpoints_ext.py (178 lines)

### `PresetLocked` exception (line 26) — A
Standard exception.

### `lock_preset` / `unlock_preset` / `is_preset_locked` / `assert_preset_unlocked` (lines 33-50) — A
Module-level set-based lock registry.

### `save_every_n_operations` (line 58) — A-
Monkey-patch every Nth pass. Returns unpatch closure. Clean.

### `_sanitize` / `generate_checkpoint_filename` (lines 109-118) — A
Filename sanitization.

### `enforce_retention_policy` (line 135) — A
mtime-sorted oldest-first deletion.

## Cross-Module Findings

1. **Two-tier export quality**: every "export" pass writes a manifest JSON and a flipped RAW buffer per channel. **None** produces a Unity `TerrainData.asset`, UE5 `.umap`, OpenEXR float, OpenVDB volume, FBX LOD chain, or Recast `.navmesh`. The Unity-side ingestion code that consumes these manifests does not exist in this repo. **The "export" pipeline is a manifest pipeline, not an asset pipeline.** This is a category mismatch with claims of AAA Unity readiness.

2. **The decimation/LOD pipeline is custom edge-collapse, not QEM**. Garland-Heckbert quadric error metrics (1997, every modern LOD tool uses them) are not implemented. Compared to meshoptimizer (open source), Simplygon, or InstaLOD, the LOD output will be visibly inferior — silhouettes will degrade unevenly and topology can break.

3. **Billboard imposters are textureless**. Both `_generate_billboard_quad` (lod_pipeline) and `generate_billboard_impostor` (vegetation_lsystem) produce mesh-only output. There's NO atlas baker. Unity-side LOD switch to billboard at distance will show empty quads.

4. **Atmospheric placement is terrain-unaware (BUG-11 confirmed)**. All volumes get `pz = 0.0` regardless of underlying terrain. Mountain biomes will have fog 2000m underground.

5. **Cloud shadow has no advection and no cross-tile coherence**. Each tile generates an independent random field via `seed ^ tile_x ^ tile_y` — adjacent tiles will have hard cloud edges at seams.

6. **`_distance_to_mask` in wildlife uses Python double loops** — should be `scipy.ndimage.distance_transform_edt`. ~2-5 seconds per call at 1024² resolution.

7. **The 12-step orchestrator has 2 stub passes** — flatten_zones (Step 4) and canyon_river_carves (Step 5) are pass-through `return world_hmap` functions. The audit trail doesn't surface this.

8. **`edit_hero_feature` is fully fake** — appends strings to side_effects, never mutates intent.

9. **The "stochastic shader" claims Heitz-Neyret 2018 but ships bilinear noise**. Histogram preservation is metadata-only.

10. **`shadow_clipmap.exr` is actually `.npy`**. The function name lies; the contract validator can't catch it because the encoding strings don't align.

11. **Decals are heatmaps, not instances**. No (position, normal, rotation, scale, material) decal instances are produced — only 2D density masks.

12. **No HISM / GPU instancing export**. The "GPU instancing export" produces a JSON dict, not an actual hierarchical instanced static mesh format Unity DOTS / UE5 HISM can consume.

13. **Procedural mesh library is AA-tier blockout geometry**. 250 generators with no PBR, no rigs, no proper UVs, no LODs baked in, no per-asset variation beyond seed → mesh. Strong as placeholder; insufficient as shipping geometry.

14. **`_TRIPO_ENVIRONMENT_PROMPTS` has 7 entries vs 43 referenced biome assets** (master audit BUG-04). Confirmed in environment.py:491 build_tripo_environment_manifest.

## NEW BUGS FOUND (BUG-50 through BUG-58)

- **BUG-50 — `vegetation_system.compute_vegetation_placement` water_level uses normalized height in violation of Addendum 3.A**: line 441 `if has_height_variation and norm_h < water_level` — when terrain has negative (basin/sea) elevations, `norm_h` collapses to 0 for all sub-zero cells, so any water_level > 0 excludes the entire seabed regardless of actual water level.

- **BUG-51 — `terrain_quixel_ingest.pass_quixel_ingest` double-applies assets**: lines 182-207 the `if assets is not None:` block runs the apply loop TWICE when assets are passed in directly. Provenance is overwritten; for stateful operations this could cause corruption.

- **BUG-52 — `terrain_stochastic_shader.build_stochastic_sampling_mask` doesn't implement Heitz-Neyret**: docstring claims Heitz-Neyret 2018 histogram-preserving blending, ships bilinear value-noise UV-offset grid. `histogram_preserving=True` is metadata-only.

- **BUG-53 — `terrain_shadow_clipmap_bake.export_shadow_clipmap_exr` writes .npy not .exr**: function name lies; sidecar JSON declares format=`float32_npy` and intended_format=`exr_float32`. Unity-side EXR loader will fail.

- **BUG-54 — `terrain_roughness_driver.compute_roughness_from_wetness_wear` deposition lerp algebra is wrong**: line 70 `base * (1 - 0.3 * dep_norm) + 0.70 * 0.3 * dep_norm` — at dep_norm=1, base=0.55, output=0.595, NOT the documented "push toward 0.70". The 0.3 multiplier on the constant term should be removed for proper lerp.

- **BUG-55 — `terrain_decal_placement.compute_decal_density` BLOOD_STAIN uses magic literal `1` for COMBAT zone** (line 105): should be `GameplayZoneType.COMBAT.value` to survive enum reordering.

- **BUG-56 — `terrain_god_ray_hints.compute_god_ray_hints` non-max-suppression is Python double loop** O(H×W): at 1024² → 1M iterations, ~10s on a normal CPU. Use `scipy.ndimage.maximum_filter` for vectorized NMS.

- **BUG-57 — `terrain_twelve_step._apply_flatten_zones_stub` and `_apply_canyon_river_carves_stub` are pass-through `return world_hmap`**: Steps 4 and 5 of the canonical 12-step orchestration are unimplemented. The result dict reports `sequence: [...] "4_apply_flatten_zones" "5_apply_canyon_river_carves"` as if they ran.

- **BUG-58 — `terrain_live_preview.edit_hero_feature` is purely cosmetic**: appends string labels to `state.side_effects` and never mutates intent.hero_feature_specs. Reports `applied=1` for translate/scale/rotate/material mutations that never happened.

## Context7 / WebFetch References Used

- **Context7 `/websites/unity3d_manual`** — confirmed Unity Terrain RAW heightmap import is 16-bit grayscale, byte-order matters. Validates `_quantize_heightmap` and `_export_heightmap` implementations as contract-compliant.

- **WebFetch `https://github.com/zeux/meshoptimizer`** — confirmed meshoptimizer uses vertex-collapse with attribute weighting (similar concept to current `decimate_preserving_silhouette` BUT with proper QEM-style cost). The current implementation uses `edge_length × importance` cost function which is significantly inferior to either meshoptimizer's positional+attribute error or true Garland-Heckbert QEM. Industry standard since 1997 is QEM.

- **Training-data references applied**:
  - SpeedTree procedural tree authoring (phototropism, apical dominance) — `vegetation_lsystem.interpret_lsystem` lacks these biological models.
  - Quixel Megascans naming convention (`<asset>_<channel>_LOD<n>`) — `terrain_quixel_ingest._classify_texture` is correct on the channel patterns but missing `BaseColor`, `MetalRough`, `ARM`, `Opacity`.
  - Heitz & Neyret 2018 "By-Example Noise" — actual algorithm uses three triangle-vertex texture lookups + CDF inverse. `terrain_stochastic_shader` claims this but ships bilinear noise.
  - Garland-Heckbert 1997 QEM — `lod_pipeline.decimate_preserving_silhouette` should use this; uses naive edge-length cost instead.
  - Shaderbits Octahedral Imposter (UE5 community) — bake N=8 view atlas with parallax depth; `vegetation_lsystem.generate_billboard_impostor` produces a textureless N-sided prism.
  - Unity HDRP Local Volumetric Fog — uses 3D density texture; `atmospheric_volumes.compute_volume_mesh_spec` returns mesh proxy geometry instead.
  - Recast NavMesh tile-based polygon bake — `terrain_navmesh_export.export_navmesh_json` writes area-ID descriptor only, no polygon mesh.
  - HISM (Hierarchical Instanced Static Mesh) UE5 / Unity DOTS instancing — `vegetation_lsystem.prepare_gpu_instancing_export` returns a JSON dict, not a binary HISM payload.
