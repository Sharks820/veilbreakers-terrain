# R8-A5: Materials & Texturing Pipeline Audit + AAA Research

**Auditor:** Opus 4.7 (1M)  
**Date:** 2026-04-17  
**Scope:** 12 texturing/materials handlers (6,770 LOC total)  
**Verdict:** The pipeline is, with a few honest exceptions, a **Blender-side procedural-noise material library** dressed up in "AAA" language. The world-space terrain texturing (`terrain_materials_v2`, `terrain_macro_color`, `terrain_multiscale_breakup`, `terrain_roughness_driver`, `terrain_stochastic_shader`) is structurally sound as *Unity-side hand-off metadata* but ships essentially none of the advanced techniques Horizon/TLOU/UE5 use under the hood (HPG, triplanar on cliff layer, wetness cavity darkening, per-layer texel-density enforcement actually wired into blending). The Blender-side graphs (`procedural_materials.py`, `_build_terrain_recipe` in `terrain_materials.py`) are adequate for preview but are *not* the AAA ship pipeline — they are a fallback when Quixel maps aren't present, which is the case by default because `pass_quixel_ingest` never loads pixel data.

Grade overall: **C+** (was B across the R4 CSV; this review confirms multiple misleading docstrings that overstate what the code does).

---

## NEW BUGS (not in FIXPLAN)

| ID | File:Line | Severity | Description | Correct Fix |
|----|-----------|----------|-------------|-------------|
| BUG-R8-A5-001 | `terrain_materials.py:2162` and `:2179` | CRITICAL | `_clamp_rgba(color: Sequence[float], ...)` and `_build_terrain_recipe(..., layer_params: Mapping[str, Any], ...)` reference `Sequence` and `Mapping` types that are **never imported**. Works only because `from __future__ import annotations` stringifies annotations, so import-time doesn't fail. But any tool that resolves annotations at runtime (`typing.get_type_hints`, some test runners, pydantic-style inspection) will raise `NameError`. | `from collections.abc import Mapping, Sequence` at top of file (or `from typing import Mapping, Sequence` — stdlib both work since 3.9). |
| BUG-R8-A5-002 | `terrain_quixel_ingest.py:203-207` | HIGH | When `assets is not None`, the function **double-applies** every asset. It applies once (via the `resolved = list(assets)` dead local that Codex noted), but then at L203-207 unconditionally re-iterates the same `assets` list and calls `apply_quixel_to_layer` a second time for each. The second call overwrites `stack.populated_by_pass[key]` with identical data so the user-visible effect is just wasted work; but if `assets` contained duplicate IDs or the stack had `splatmap_weights_layer` transitions, it silently compounds. The earlier branch (when `assets is None`) already calls `apply_quixel_to_layer` via L192. So this whole L203-207 block is a logic bug introduced alongside BUG-52's dead-local. | Remove the L203-207 re-iteration entirely. When `assets is not None`, iterate once and apply in that branch. Pseudocode: `for a in assets: apply_quixel_to_layer(stack, a.asset_id, a); resolved.append(a)`. Delete the `if assets is not None: resolved = list(assets)` dead-local line too. |
| BUG-R8-A5-003 | `terrain_quixel_ingest.py` | HIGH | The module **never actually reads pixel data** from any Quixel texture file. `ingest_quixel_asset` only stores `Path` objects. `apply_quixel_to_layer` writes JSON strings into `stack.populated_by_pass` — a dict meant for provenance string tags, not payload. Nothing downstream (mask_stack, compose_terrain_node, BakedTerrain) actually loads these textures into tileable arrays or consumes them for blending. Net effect: Quixel "ingestion" is entirely **metadata registration** — a Unity-side importer would need to re-discover the paths. The docstring at L126 is honest about this ("We do not load the textures here"), but the overall shipping claim "Quixel workflow" is aspirational. | Either: (a) actually load textures via `PIL.Image.open(path).convert("RGB")` with size/channel validation, cache as `stack.quixel_textures[layer_id] = {"albedo": np.ndarray, "normal": ..., ...}`, or (b) rename module to `terrain_quixel_metadata_discovery` and strip the "ingest" implication. |
| BUG-R8-A5-004 | `terrain_quixel_ingest.py:37-49` | MEDIUM | Regex classifier uses `(^|[_\-])albedo([_\-]|\.)` pattern. This fails on Quixel's real naming like `xdkajbca_2K_Albedo.png` (works with `_`) but also fails on `Albedo.png` (no leading separator, relies on `^` — works in theory but the `^` match is against `filename`, not the full path — should be fine). More importantly, **order matters**: the regex tries `albedo` before `basecolor`. Quixel's actual convention is `_Albedo` for 2023+ assets, but Unreal/Substance exports use `_BaseColor`. Both work. BUT `roughness` before `metallic_roughness` means ORM-packed textures (common in UE5 Megascans) get classified as `roughness` only, losing the metallic & AO channels. No pattern handles packed ARM/ORM/MRA/RMA texture layouts. | Add packed-channel patterns: `(^\|[_\-])(arm\|orm\|mra\|rma\|masks)([_\-]\|\.)` → classified as `packed_masks` with metadata flag noting which channels are in R/G/B/A. Default Quixel 2K packed is R=AO, G=Roughness, B=Displacement. |
| BUG-R8-A5-005 | `terrain_stochastic_shader.py:64-115` | CRITICAL (doc/behavior mismatch) | **The function is misnamed and the Unity template lies.** Docstring at L3-6 cites "Heitz & Neyret 2018 … Histogram-Preserving Blending Operator" and L43 `histogram_preserving: bool = True`. Actual code: a **bilinear-upsampled low-frequency RNG of uniform random UV offsets in [-0.5, 0.5]**. This is ordinary Perlin-style UV dithering. It does **not**: (a) partition the output on a triangle grid, (b) sample 3 patches at each triangle, (c) compute barycentric weights, (d) apply a variance-preserving formula `c = (c0 - μ)√w0² + w1² + w2² + μ`, (e) use a Gaussianized→inverse LUT. This is Fix 5.4 scope, but the report also needs to flag that `StochasticShaderTemplate.histogram_preserving: bool = True` is a **lie** shipped into the Unity schema JSON. Unity-side importer will think it's getting HPG and set up shader graph accordingly. | Beyond Fix 5.4's rename: set `histogram_preserving=False` as the default dataclass value and update `export_unity_shader_template` payload. Unity shader template must advertise capability honestly; otherwise integration breaks. |
| BUG-R8-A5-006 | `terrain_stochastic_shader.py:183-189` | MEDIUM | "Fold offset magnitude as a small perturbation into roughness_variation" — this is a **semantically wrong channel coupling**. `offset_magnitude` is in UV-space coords (0-0.707 max for sqrt(0.5²+0.5²)). Multiplying by 0.1 or 0.02 adds uniform positive bias in the range [0, 0.07] to roughness, biasing the terrain toward rougher. Worse: it *erases* the stochastic signal's zero-mean property — now any cell with a non-trivial offset has elevated roughness regardless of actual surface wear. This is cargo-cult "attach a metric so the pipeline sees the pass ran." | Either remove the L183-189 block entirely (offset is shader-consumed, not stack-consumed), or write the mask to a dedicated `uv_offset_mask` channel (not roughness). The current "make the pipeline honest" justification in the docstring at L163-165 is dishonest — it pollutes a physically meaningful channel to satisfy a bookkeeping check. |
| BUG-R8-A5-007 | `terrain_macro_color.py:104-106` | MEDIUM | Altitude cool-shift math: `alt_mix = clip((h_norm - 0.6)/0.4, 0,1)` then `color = color * (1 - alt_mix*0.4) + cool_target * alt_mix * 0.4`. This is **only locally normalized** — if `stack.height_min_m` / `height_max_m` metadata are correct, `h_norm` is 0..1 over the entire terrain span. But the "cool shift" starts at 0.6 of relative span. For a tile that happens to be all in the top 40% of world altitude (e.g., a mountain region), every cell gets cool-shifted. For a lowland tile, no cell gets cool-shifted even if those cells are near sea level vs. mountain peaks in absolute world terms. The altitude gate should be **world-absolute** (e.g., > 400m in meters) not normalized — or the normalization should use a fixed world snow-line, not the tile's own min/max. | Change altitude gate to world-meter absolute: `alt_mix = np.clip((h - SNOW_LINE_START_M) / SNOW_LINE_BAND_M, 0, 1)` with constants ~400m start, 200m band. Pull from `state.intent.composition_hints['snow_line_m']` when present. |
| BUG-R8-A5-008 | `terrain_macro_color.py:87-94` | LOW | `biome_id` dispatch uses a Python `for bid, rgb in pal.items()` with `color[mask] = np.array(rgb)`. This is O(palette_size × pixels) and does one scatter per biome. For 8 biomes × 1024² = 8M assignments. Fine for dev, but it's also **order-sensitive**: if two palette entries share a biome_id key (shouldn't happen but `_resolve_palette` doesn't dedup), the last wins silently. | Add explicit dedup + dtype check in `_resolve_palette`. Use `np.take` with a contiguous biome lookup table instead: build `palette_lut = np.array([pal[i] for i in range(max_id+1)])` then `color = palette_lut[biome_arr]`. Same result, 10× faster, no mask iteration. |
| BUG-R8-A5-009 | `terrain_multiscale_breakup.py:111-113` | HIGH (design) | The `(5m, 20m, 100m)` breakup scales are hardcoded for a world where `cell_size` is ~1m. If `stack.cell_size = 0.25m` (a 4× finer terrain), the 5m scale becomes 20 cells — fine. But if `cell_size = 4m` (coarse terrain), the 5m scale becomes 1.25 cells, clamped to `max(1, ...)` at L74 → degenerate breakup (salt-and-pepper). No warning is issued. No validation that `cell_size ≤ min(scales_m) / 4` (the Nyquist bound for the smallest scale). | Add `if min(scales_m) / cell_m < 4.0: issues.append(ValidationIssue(code="BREAKUP_SCALE_UNDERSAMPLED", severity="soft", message=...))`. The pass returns `issues=[]` today which is deceptive. |
| BUG-R8-A5-010 | `terrain_multiscale_breakup.py:75` | MEDIUM | Amplitudes are `1/(i+1)` → `(1.0, 0.5, 0.33)` for 3 scales. Weight-normalized after sum. This produces a frequency spectrum where the smallest scale (5m) has 55% of the variance. **Opposite of AAA practice** — macro variation should dominate, micro should only sprinkle. Horizon/UE5 macro variation techniques use amplitudes like `(0.15, 0.35, 0.50)` where *macro* scale (largest) dominates. Our breakup is "grainy" not "varied." | Flip amplitude ordering: `amp = 1.0 / (len(scales_m) - i)` so the largest scale gets `amp=1.0` and smallest gets `1/N`. This matches the perceptual intent of "subtle wide-band variation with fine-grain garnish." |
| BUG-R8-A5-011 | `terrain_roughness_driver.py:62` | MEDIUM | `base = base * (1.0 - 0.6 * er_norm) + 0.85 * 0.6 * er_norm` — the second term is `0.51 * er_norm`, and combined with the first lerp weight of `0.6 * er_norm` means at `er_norm=1.0`, we get `base*0.4 + 0.51 = base*0.4 + 0.51`. For any `base ≥ 0.73`, this **decreases** roughness on fully eroded cells, contradicting the docstring's claim "eroded cells push toward 0.85." Should be a clean `lerp(base, 0.85, er_norm * 0.6)` = `base * (1 - 0.6*er_norm) + 0.85 * 0.6 * er_norm`. The `0.85 * 0.6` = 0.51 **IS wrong** — a lerp-to-target uses `target * weight + source * (1-weight)`, so the term should be `0.85 * er_norm` not `0.85 * 0.6 * er_norm`. Currently the target is effectively `0.51` not `0.85`. | Change L62 to `base = base * (1.0 - 0.6 * er_norm) + 0.85 * er_norm * 0.6` — wait, that's the same. The bug is: if the intent is "at er_norm=1, output = 0.4*base + 0.6*0.85 = 0.4*base + 0.51", the docstring's claim of "push toward 0.85" is misleading. Either (a) write `base = lerp(base, 0.85, er_norm)` to actually reach 0.85 at full erosion, or (b) fix the docstring to say "blend 60% toward 0.85." |
| BUG-R8-A5-012 | `terrain_roughness_driver.py:59-62` | MEDIUM | Erosion is normalized **per-tile**: `er_norm = er / er.max()`. Two adjacent tiles with different peak erosion values will normalize to the same `er_norm=1.0` at their respective peaks, producing a **seam** in roughness_variation at tile boundaries. This is a classic tiling determinism failure. Same pattern at L68 for deposition. | Pass a world-absolute `erosion_max_global` through `state.intent.composition_hints` and use it: `er_norm = np.clip(er / hints.get('erosion_max_global', er.max()), 0, 1)`. This is the same tiling bug family as BUG-R8-A5-007. |
| BUG-R8-A5-013 | `terrain_shadow_clipmap_bake.py:106` | HIGH | `ray_h = h + dz_per_step_m * step` — this is the **fixed** form Fix 5.6 is aware of (the old bug was `ray_h = h.copy()` + incremental update which lost data). But there's an additional bug: `h` here is the **full heightmap**, so `ray_h` at each step is "the terrain at each sample cell plus a constant climb." This doesn't represent a ray from origin. The correct formulation is: for each **ray origin** `(y, x)`, its height is `h[y, x]`, and at step `s` along the sun direction, the ray is at world `(x + s*dx, y + s*dy, h[y, x] + s*dz_per_step_m)`. The current code instead uses `h[syi, sxi]` as the **terrain** height at the sampled cell but compares against `h + step*dz_per_step_m` which adds the climb to **every origin**, not just the rays with that origin. This means the occlusion test at L115 `terrain_h > ray_h` is comparing terrain at `(sy, sx)` against the origin `(y, x)` height + climb. Array shapes happen to match because `h`, `ray_h`, `terrain_h` are all (rows, cols), but the **semantics are wrong**: this tests "is the terrain ahead of me taller than I will be at step s if I start at my own altitude" for every origin in parallel — which is actually correct! Re-reading, it IS correct: each `(y,x)` cell is an independent ray origin, and we walk forward along (dx, dy). OK, not a bug. | N/A — my first read missed the vectorization. Keep an eye on step_cells scaling at L92: `step_cells = max(1.0, (clipmap_res / max(num_steps, 1)) * 0.5)` means for clipmap_res=512, num_steps=24 → step_cells = 10.67. March reaches `24*10.67 = 256` cells = half the map. That's fine for finding occlusion from nearby peaks but **misses distant shadows**. |
| BUG-R8-A5-014 | `terrain_shadow_clipmap_bake.py:92` | MEDIUM | `step_cells = max(1.0, (clipmap_res / max(num_steps, 1)) * 0.5)` — the 0.5 factor halves the march stride. With default 24 steps and 512 clipmap, total march distance is `24 * 256 / 512 = 12` world-tile-units? No: `step_cells * num_steps = 256 cells = half the clipmap`. For a 1km terrain tile that's ~500m of sun-march; if the sun is low (elevation ~0.2 rad ≈ 11°), long shadows beyond 500m are clipped. | Expose `max_march_cells` as a hint. Alternatively use **horizon-angle shadowing** (single-pass, O(N log N) via prefix max along sun direction) for world-scale shadows — and keep ray-march only for fine detail. See `HORAYZON` reference. |
| BUG-R8-A5-015 | `terrain_shadow_clipmap_bake.py:117` | MEDIUM | Soft shadow: `mask = np.where(occluded, mask * 0.55, mask)`. Each step compounds multiplicatively. After 24 steps of continuous occlusion (common for a cell at the base of a tall cliff), `mask = 0.55^24 ≈ 4.4e-6`. Effectively binary hard-shadow, **zero soft penumbra**. AAA shadowmaps use PCF or VSM kernel. | Either (a) track depth-into-shadow (count of occluded steps) and use a `smoothstep` on that count, or (b) use a single minimum-distance-to-occluder and apply exponential soft shadow `exp(-dist/penumbra_scale)`. |
| BUG-R8-A5-016 | `terrain_shadow_clipmap_bake.py:183` | LOW | `resampled = _resample_height(mask.astype(np.float64), max(rows, cols))` then `resampled = resampled[:rows, :cols]`. If rows ≠ cols (non-square terrain tile), this resamples to a square and **crops the longer side**, discarding real data. Fix 5.6 targets `_resample_height`'s square assumption but the `pass_shadow_clipmap` caller perpetuates it. | After Fix 5.6 makes `_resample_height` accept `(target_rows, target_cols)`, call it here with `(rows, cols)` directly — no crop needed. |
| BUG-R8-A5-017 | `terrain_baked.py:47` | LOW (doc) | Docstring says `ridge_map: (H, W) float32, -1 = crease, +1 = ridge`. This is **non-standard**. `TerrainMaskStack.ridge_map` elsewhere in the codebase is documented as [0, 1] where 1 = ridge crest (see `_terrain_erosion.py`). Consumers reading BakedTerrain will get confused about whether negative values are meaningful. | Either (a) change docstring to match the 0..1 convention, or (b) if BakedTerrain really stores signed curvature, rename the field `curvature_signed` and keep `ridge_map` as a separate 0..1 map. Check `compose_map` consumer behavior. |
| BUG-R8-A5-018 | `terrain_baked.py:174-181` | LOW | `to_npz` serializes `metadata` as JSON inside a uint8 buffer inside a `.npz`. `from_npz` does `np.load(path, allow_pickle=False)`. The uint8 buffer round-trips fine. But: nothing validates that the material_masks have consistent dtype with height_grid. If a caller passes `material_masks={'slope': int_array}`, `__post_init__` at L86-94 converts float-only. A `bool` mask becomes float. Silent dtype inflation. | Add a `dtype` field to each material_mask metadata entry, or at least warn when a non-float array is auto-promoted. |
| BUG-R8-A5-019 | `terrain_materials_v2.py:245` | MEDIUM | `curv_w = np.where((curvature >= ch.curvature_min) & (curvature <= ch.curvature_max), 1.0, 0.0)` — a **hard step function** in a pipeline that uses smoothstep for slope/altitude/wetness. Causes hard visible seams along curvature isolines. Same issue at L249 for wetness. | Use `_smoothstep_band` for curvature and wetness too, mirroring the slope/altitude treatment. |
| BUG-R8-A5-020 | `terrain_materials_v2.py:195-261` | HIGH | `compute_slope_material_weights` demands `slope` be on the stack at L208-210. But **no pass in this module produces slope** — the contract says `requires_channels=("slope", "height")`. This is fine as a dependency declaration but means the caller must have run `pass_slope_curvature` first. If the channel is missing, `raise KeyError`. Meanwhile in `compute_world_splatmap_weights` at L2404 of `terrain_materials.py`, the slope is **computed on demand** via `compute_slope_map(hmap, cell_size=cell_size)`. Inconsistent policy: one path silently recomputes, one path fails hard. | Unify. Recommend: `materials_v2` should be a pure consumer of `slope`; if missing, fail hard (current behavior is correct). Legacy `compute_world_splatmap_weights` should also require slope on the stack OR be deprecated. The silent recomputation hides dependency graph issues. |
| BUG-R8-A5-021 | `terrain_materials.py:2657-2659` | LOW | `for poly in getattr(mesh, "polygons", []):  poly.material_index = 0` — after clearing materials and appending a single material. This is a no-op since a cleared material slot defaults to 0 anyway. But **preserves prior material_index assignments when `mesh.materials.clear()` is not available** (old Blender fallback at L2651-2655). Dead code or defensive? Only defensive when the clear branch isn't taken; otherwise zero-work. Cosmetic. | Remove dead loop after confirming all supported Blender versions have `.clear()`. |
| BUG-R8-A5-022 | `terrain_materials.py:2699-2708` | MEDIUM | The second `if object_name:` block at L2699-2708 is a **duplicate** of the first one at L2641-2645. If Blender's `mesh.materials.clear()` wasn't available in the first block (old Blender), the second block tries again with `obj.data.materials.clear()`. Both are testing the same mesh. The loop at L2641-2658 already handled the happy path. This block is dead or redundant in all modern Blender versions. Worse, at L2651-2655 already handled the no-`.clear()` fallback inline, so L2699-2708 is wholly redundant. | Delete L2699-2708. Confirm no test depends on the double-apply. |
| BUG-R8-A5-023 | `procedural_materials.py:1307` | HIGH | `build_metal_material` sets `bsdf_rust.inputs["Metallic"].default_value = 0.0` with comment "Rust is always dielectric (PBR binary rule)." **True-ish** — rust (Fe₂O₃) is a dielectric pigment *on top of* a metal substrate. But in the PBR metal/rough workflow, rust patches are typically represented as `metallic=0` pixels **within** the metallic mask of the same material — a spatial mask, not a **shader-mixed** Fresnel blend. This `MixShader` between `bsdf_clean(metallic=1)` and `bsdf_rust(metallic=0)` with a greyscale Fac from ramp_rust is **energy-conserving** only if the ramp is 0/1 hard; for soft ramps in the middle (Fac=0.5), we're physically interpolating two different BRDF families, which is non-physical (can produce >1 albedo-equivalent in reflectance). | Implement rust as a **mask** over a single BSDF: feed `ramp_rust` into `Metallic` (0 where rust, 1 where clean) and into a `Mix` node that produces the Base Color (rust pigment vs. metal tint) and **another Mix** that produces Roughness (high where rust, low where clean). Single BSDF, physically-proper transition. The current Mix-Shader approach is common in tutorials but is non-PBR-correct. |
| BUG-R8-A5-024 | `procedural_materials.py:943-1018` | HIGH (design) | `_build_normal_chain` cascades three `ShaderNodeBump` nodes by feeding each Bump's `Normal` output into the next Bump's `Normal` input. This is **numerically degenerate**. Bump nodes compute a tangent-space perturbation from a scalar height gradient; chaining them means each successive Bump perturbs on top of an already-perturbed normal basis. The physically correct AAA approach is **Reoriented Normal Mapping** (Barre-Brisebois & Hill, 2012): sample each detail normal, reorient each against the surface tangent basis, then compose with a specific blend formula (the "partial derivative blend" or UDN blend). Bump-chaining gives a rough approximation but loses directional fidelity for high-frequency detail. | Replace Bump-chain with three `Normal Map` nodes sampling dedicated normal textures (or Voronoi→Bump for procedurals) and composite via **UDN blend** (Unity Detail Normal) — add XY components, renormalize, preserve Z. See https://blog.selfshadow.com/publications/blending-in-detail/. The current Bump-chain is sold in MATERIAL_LIBRARY entries as `micro/meso/macro_normal_strength` but isn't delivering what those strengths would in a real DCC detail-normal workflow. |
| BUG-R8-A5-025 | `procedural_materials.py:1122-1128` | MEDIUM | Stone builder clamps base_color to `min(1.0, bc * 2.5)` before MULTIPLY-blending. For a MATERIAL_LIBRARY stone entry with base `(0.14, 0.12, 0.10)` → `(0.35, 0.30, 0.25)`. Then MULTIPLY with mixed noise color (0..1). **Result**: the base_color the artist wrote in the library is silently **brightened by 2.5×** before display. Same pattern at L1604-1608 for terrain builder (2.0× scale). This means every material's visual output differs from its library `base_color` value in a non-obvious way. If an artist tunes `base_color=(0.14,...)` to hit a specific albedo, the shipped result is the brightened 2.5× value. | Remove the scale factor. If MULTIPLY with ~0.5-mean noise would darken too much, change blend to `OVERLAY` or `SOFT_LIGHT` which preserve original tone. Or document the 2.5× scale in a top-level comment. |
| BUG-R8-A5-026 | `procedural_materials.py:36-53` | LOW (palette intent) | `_DARK_STONE_BASE = (0.12, 0.10, 0.08, 1.0)` — these are treated as "linear sRGB" in the header comment. Blender's Principled BSDF Base Color input expects **linear sRGB** when the color picker is in "Linear" mode, but the file literally hard-codes these as float values directly fed into `bsdf.inputs["Base Color"].default_value`. That IS linear because Blender stores default_value as linear internally. OK. But `validate_dark_fantasy_color` uses `colorsys.rgb_to_hsv` on linear values — **colorsys expects gamma-encoded sRGB**, not linear. HSV of a linear-space color gives a distorted saturation/value reading, which means the `s = min(s, 0.40)` clamp doesn't actually cap saturation as perceived. | Either (a) convert to sRGB gamma before HSV check: `r_s = r**(1/2.2)`, etc., or (b) use a perceptual-uniform space (OkLab, OkLCH) for the dark-fantasy palette enforcement. |
| BUG-R8-A5-027 | `procedural_materials.py:60-73` | LOW | `validate_dark_fantasy_color` is **unused** — grep shows no callers. Defined but never enforced. | Either wire into material-creation paths (validate every `base_color` in MATERIAL_LIBRARY at import time) or remove. |
| BUG-R8-A5-028 | `terrain_palette_extract.py:70` | MEDIUM | `rng = np.random.default_rng(0)` — **seed is hardcoded to 0**. The docstring at L3-4 claims "Deterministic given a seeded RNG (default seed=0)" but there is no way to pass a different seed. For two calls on the same image this is deterministic; for two calls on the same image with different random initializations (debugging, variance analysis), impossible. | Add `seed: int = 0` parameter to `extract_palette_from_image`. |
| BUG-R8-A5-029 | `terrain_palette_extract.py:74-86` | LOW | K-means loop is capped at 20 iterations with convergence check `atol=1e-5`. For 8M+ pixel images (1024² RGB), this often doesn't converge in 20 iters. No warning. | Emit a warning if `not_converged` after the loop, or raise the cap to 50. |
| BUG-R8-A5-030 | `terrain_materials_ext.py:232` | LOW | Module defines `validate_cliff_silhouette_area(fraction, tier="secondary")` but thresholds `HERO_CLIFF_MIN_FRAC=0.08` and `SECONDARY_CLIFF_MIN_FRAC=0.03` are only pixel-coverage checks — **the function never actually measures the silhouette**. It takes the fraction as an input. Whichever caller measures pixel coverage decides the fraction; grep shows no production caller (only test). Dead API surface. | Either (a) add a helper `measure_cliff_pixel_coverage(rendered_frame, cliff_mask) → float` and call it from a validation pass, or (b) delete the unused thresholds. |
| BUG-R8-A5-031 | `terrain_materials.py:1307-1315` | MEDIUM | `apply_corruption_tint` — `new_a = a + (1.0 - a) * corruption_level` pushes alpha toward 1 at full corruption. Then L1305 `vertex_colors.append((r,g,b,a))` — but the **caller** at L1794 writes these to a CORNER-domain color attribute. In Blender, CORNER domain means one color per **loop**, not per-vertex. The code at L1797-1801 iterates `for poly in mesh.polygons: for li in poly.loop_indices: ... vc_layer.data[li].color = raw_colors[vi]`. So corruption tinted vertex colors get splatted to all loop corners sharing that vertex. This works, but UV seams (where a vertex has multiple loops with different UVs) get the same corruption value — which is fine for corruption but means this isn't a "per-corner" splatmap, it's per-vertex-splatted-to-corners. Minor; document so consumers don't expect seam-independent tinting. | Docstring note at L1281 clarifying CORNER-domain semantics. |
| BUG-R8-A5-032 | `terrain_materials.py:1323-1355` | MEDIUM | `_simple_noise_2d` uses hash `(xi * 374761393 + yi * 668265263 + seed * 1274126177) ^ 0x5DEECE66D`. This is a **very weak hash** — the multipliers are reasonable primes but XORing with the LCG constant `0x5DEECE66D` (Java's `Random` constant) doesn't improve dispersion; it's cargo-culted. Grid-axis-aligned aliasing shows up as Moiré on biome transitions at low noise_scale. | Replace with FNV-1a or xxHash32 on a packed `(xi, yi, seed)` uint64. Or use numpy's `np.random.default_rng(hash((xi,yi,seed)))` (slow but correct). |

---

## STOCHASTIC SHADER ANALYSIS

### What `build_stochastic_sampling_mask` actually does (line-by-line, L64-115)

1. **L80-83**: Guards — require `stack.height`, `tile_size_m > 0`.
2. **L85-89**: Compute a low-frequency grid `(tiles_y, tiles_x)` sized to cover the terrain extent in tile-unit counts.
3. **L91-93**: Seeded numpy RNG, draw two independent uniform `[-0.5, 0.5]` grids of shape `(tiles_y, tiles_x)` — one for `u` offsets, one for `v` offsets.
4. **L95-102**: Build per-cell bilinear-interp weights from the full grid resolution `(rows, cols)` down onto the low-freq grid.
5. **L104-114**: Bilinearly interpolate the RNG grids to the full resolution for both `u` and `v`.
6. **L115**: Stack into `(H, W, 2)` float32 output.

### What it claims to do vs. what it does

| Docstring claim | Actual behavior | Verdict |
|-----------------|-----------------|---------|
| "Heitz & Neyret 2018 Histogram-Preserving Blending" (L4-6) | Bilinear-upsampled per-tile uniform UV-offset noise | **FALSE** |
| "matches how Heitz-Neyret chooses tile indices from a triangular basis" (L72-74) | No triangular basis; uses rectangular RNG grid with bilinear weights | **FALSE** |
| `histogram_preserving: bool = True` in StochasticShaderTemplate (L43) | Template flag is emitted in exported Unity JSON; Unity side will reconstruct shader assuming HPG exists | **MISREPRESENTS CAPABILITY** |
| "break visible tiling" (L69) | UV offsets do break literal repeat patterns in the sampling domain | **TRUE** (cheap UV-dither is a valid basic tiling-breakup technique) |
| "locally coherent via a low-freq RNG grid upsample" (L72-74) | Low-freq grid + bilinear upsample = yes, smooth locally | **TRUE** |
| Deterministic via seed (L91) | `np.random.default_rng(seed & 0xFFFFFFFF)` | **TRUE** |

### What correct HPG implementation requires (reference: Heitz-Neyret 2018, jcgt.org follow-ups)

**Precomputation (offline, per-input-texture):**

1. **Histogram transformation** → build LUT:
   - For each channel, sort pixel values.
   - For each sorted index `i`, compute `g_i = invCDF_gaussian(i / N)` (inverse Gaussian CDF with μ=0.5, σ=1/6).
   - Store pixel's original color at the buffer location, and keep a **forward LUT** `T: original_value → gaussianized_value` and **inverse LUT** `T⁻¹: gaussianized_value → original_value`.
2. **Gaussianized input texture** `T(image)` — same pixel positions, new values with approximately Gaussian histogram.

**Runtime (per-fragment / per-cell):**

3. **Triangle-grid partition**: Hexagonal / triangular lattice on UV space (not rectangular). Each fragment lies inside a triangle with 3 vertices.
4. **Random patch lookup per vertex**: Each lattice vertex has a pseudo-random UV offset into the input texture (this is the one part our code approximates, but rectangularly, not triangularly).
5. **Sample 3 patches**: Sample `T(image)` at the fragment's UV + each vertex's offset.
6. **Barycentric weights** `(w0, w1, w2)` with `w0 + w1 + w2 = 1` — computed from the fragment's position within the triangle.
7. **Variance-preserving blend** (the math Heitz derives):
   
   ```
   c_blended = (w0*c0 + w1*c1 + w2*c2 - μ) / sqrt(w0² + w1² + w2²) + μ
   ```
   
   where `μ = 0.5` (Gaussian mean). This formula preserves the variance of the input distribution — a linear blend `w0*c0 + w1*c1 + w2*c2` would reduce variance; dividing by `sqrt(Σwᵢ²)` restores it.
8. **Inverse LUT lookup**: `final_color = T⁻¹(c_blended)` — remap back to the original texture's color distribution.

### What our code would actually need to produce (per Fix 5.4 + AAA-correct implementation)

A real `build_histogram_preserving_blend_mask` pass in numpy would need to:

1. Take `input_texture: np.ndarray (Ht, Wt, 3)` as a new parameter (the terrain's tileable albedo).
2. Compute sorted histograms per channel, derive LUT + inverse LUT as a `(256, 3)` table (or similar).
3. For each terrain cell, compute: (a) which triangle-grid cell it's in, (b) the 3 vertex positions, (c) pseudo-random offsets per vertex, (d) barycentric weights.
4. Output either (a) the precomputed Gaussianized texture + LUT bundles as shader-side data, or (b) a per-cell triangle-id + weight tuple that the Unity shader consumes.

The Unity-side shader then samples 3 times and applies the variance-preserving formula + inverse LUT lookup in the pixel shader.

**Our code ships none of this.** Fix 5.4's rename to `build_uv_offset_noise_mask` is the honest fix for current behavior. The "real" implementation is not a rename — it's an entirely new module (~400 LOC) for the numpy + Unity-shader-side implementation. Budget accordingly.

---

## PBR CORRECTNESS ASSESSMENT

### Metal/Rough workflow

| Rule | Pipeline status |
|------|-----------------|
| Metals have `metallic=1`, dielectrics `metallic=0` (binary) | **MOSTLY CORRECT**. MATERIAL_LIBRARY metals (iron, steel, gold, bronze) have `metallic=1`. BUG-R8-A5-023 notes the metal material's mix-shader approach is energy-incorrect for soft rust transitions. Chitin explicitly corrected to 0.0 (good). |
| Dielectric base color in linear sRGB, 0.05-0.75 range (physical albedo) | **MOSTLY CORRECT**. Stone bases are `(0.12-0.30, ...)` — in range. BUG-R8-A5-025 the 2.5× MULTIPLY scaling puts effective albedo to 0.35-0.75 post-blend — borderline too bright for dark fantasy. |
| Metal base color is Fresnel F0 (reflectance at normal incidence) | **CORRECT**. `_GOLD_METAL = (1.0, 0.86, 0.57)` is the standard physical F0 for gold. Silver, copper, iron, bronze, steel all have correct F0 values. |
| Roughness in [0.04, 1.0] — never below perceptual minimum | **MOSTLY CORRECT**. `glass` at 0.05, `water_surface` at 0.05, `mineral_pool` at 0.08 — all borderline but defensible for their materials. `polished_steel` at 0.20 is good. |
| Specular = 0.5 (F0=0.04) for dielectrics, unless authored otherwise | **NOT EXPLICITLY SET**. Blender's default Specular IOR Level = 0.5 → F0=0.04 ≈ glass/plastic. `ice_crystal`, `glass`, `water_surface` don't override IOR in builders (but `glass` sets `ior=1.45`, `water` sets `ior=1.333`). For organic (build_organic_material at L1398-1402), IOR is conditionally set. Generally fine. |

### Tangent-space normals

- `_build_normal_chain` cascades `ShaderNodeBump` nodes. Bump takes a scalar height and uses `Bump.Distance * dH/du × tangent + dH/dv × bitangent` internally to produce a **tangent-space perturbation**, which it writes to the BSDF's `Normal` input — but Blender's Principled BSDF `Normal` input expects **world-space normal** (after the Normal Map node's tangent-to-world transform). When Bump feeds directly into `Normal` input, Cycles/Eevee handles the space automatically. This works but has two issues:
  - **Bug BUG-R8-A5-024**: chain-of-Bump is not physically meaningful (each Bump resamples the previous world-space normal as if it were a height).
  - **No swizzle validation**: if the user loads an OpenGL-convention external normal map (via a real Image Texture, not the procedural Voronoi/Noise in `_build_normal_chain`), no channel-Y inversion check is in the pipeline. DirectX vs. OpenGL inversion is a classic invisibile bug.

### Energy conservation

- `build_metal_material` mixes two BSDFs via `ShaderNodeMixShader`. This is **energy-conserving** (MixShader normalizes by Fac), but physically wrong because the two BSDFs have different microfacet models — see BUG-R8-A5-023.
- `build_organic_material` sets `subsurface=1.0` then relies on Blender's Principled BSDF to energy-balance SSS against base diffuse. Principled BSDF does this correctly.
- **No radiometric calibration**: no `pass_validate_albedo_range` that checks dielectric albedo stays in [0.05, 0.75].

### Roughness "workflow"

See `terrain_roughness_driver.py` analysis. The pipeline:
- `multiscale_breakup` writes initial roughness_variation from noise (BUG-R8-A5-010).
- `stochastic_shader` adds uv-offset magnitude to roughness_variation (BUG-R8-A5-006).
- `roughness_driver` re-computes roughness from wetness + erosion + deposition + AO (overwrites or accumulates).

This is **passable** in intent — wetness reduces roughness, erosion increases, dust-in-cavities increases — but:
- BUG-R8-A5-011 (erosion math incorrect).
- BUG-R8-A5-012 (per-tile normalization breaks tiling determinism).
- There is **no cavity AO** physically correct implementation; `ambient_occlusion_bake` is consumed at L72-77 but the source of this channel is not in any texturing pass we audited (it's produced elsewhere).

---

## AAA TEXTURING STACK GAP ANALYSIS

### AAA reference stack (compiled from Horizon Forbidden West / TLOU2 / UE5 Landscape + Terrain3D best practices)

The canonical AAA terrain-texturing stack has 7+ layers:

1. **Macro Albedo / Color variation** (world-space, 50m-200m scale) — per-biome color drift to break repetition.
2. **Splatmap (slope/height/wetness-gated)** — 4-8 surface types per tile, weights sum to 1.
3. **Per-layer PBR textureset** — each layer has albedo, normal (tangent-space), metallic, roughness, AO, height (packed ORM/RGB/etc).
4. **Height-based blending** — at layer transitions, the layer with higher local heightmap value wins (cracks → low layer shows through).
5. **Triplanar on cliff/steep slopes** — XY/XZ/YZ projections blended by normal dot, avoids UV stretch on near-vertical geometry.
6. **Wetness mask** — from rain/puddle/river proximity; darkens albedo, reduces roughness, slightly shifts color toward blue-green.
7. **Micro/Meso/Macro normal cascade** — fine detail from hi-freq normal map; composited via **Reoriented Normal Mapping / UDN blend**, not Bump-chain.
8. **Stochastic sampling (HPG)** — destroys visible repetition in any tileable texture without breaking PBR.
9. **Procedural snow/moss/dirt overlays** — driven by top-down normal dot + noise.
10. **Per-tile baked shadow / AO** — directional sun occlusion, ambient cavity AO.
11. **Per-layer texel density coherency** — all layers sized to same cm-per-meter budget.
12. **Distance-based tiling** — macro scale at distance, micro scale up close.

### Our pipeline status

| AAA Layer | Our Module | Status |
|-----------|------------|--------|
| Macro Albedo (1) | `terrain_macro_color.py` | **Partial**. Produces 3-channel color from biome+wetness+altitude. Bugs: BUG-R8-A5-007 (altitude gate per-tile-normalized). No world-space 50m-200m color-noise variation — just biome-id scatter. |
| Splatmap (2) | `terrain_materials_v2.py::compute_slope_material_weights` + `terrain_materials.py::auto_assign_terrain_layers` + `compute_world_splatmap_weights` | **Correct**. 5-layer default (ground/cliff/scree/wet_rock/snow) with smoothstep envelopes. BUG-R8-A5-019 (curvature/wetness use hard step not smoothstep). |
| Per-layer PBR (3) | `procedural_materials.py` MATERIAL_LIBRARY | **Blender-only**. 60+ material presets with proper PBR values. But these are **procedural-node shaders**, not textured. Unity side gets Quixel paths via `terrain_quixel_ingest` but no actual image loading (BUG-R8-A5-003). |
| Height-based blend (4) | `terrain_materials.py::height_blend` + `_create_height_blend_group` (Blender node group) + `terrain_materials_ext.py::compute_height_blended_weights` | **CORRECT and AAA-quality**. The `HeightBlend` group at L1548-1666 implements the standard `clamp((Height_A - Height_B) * Contrast + 0.5) * Mask` formula used in UE5 Landscape material functions. `_build_terrain_recipe` at L2586-2595 hooks this up between ground/slope/cliff/special layers. **This is the best part of the pipeline.** |
| Triplanar (5) | `MaterialChannel.triplanar: bool` flag in `terrain_materials_v2.py` | **Declarative-only**. Flag is set (cliff=True, wet_rock=True) but **no shader implementation**. The Unity-side importer would need to read this flag and wire triplanar. Blender-side builders don't implement triplanar. No `ShaderNodeTexCoord` using `Generated` + normal-based projection blend. |
| Wetness (6) | `terrain_materials_v2.py::wetness` envelope + `terrain_roughness_driver.py` + `terrain_macro_color.py` | **Partial**. Wetness as a splatmap gate exists. Roughness-lowering on wet cells exists (L53-54). Color-darkening on wet cells exists (macro_color L99-101). **Missing**: roughness anisotropy from water film direction, color saturation boost (wet colors are more saturated). |
| Micro/Meso/Macro Normals (7) | `procedural_materials.py::_build_normal_chain` | **Implemented but with BUG-R8-A5-024** — Bump-chain is not RNM/UDN. The `micro/meso/macro_normal_strength` fields in MATERIAL_LIBRARY are consumed but don't deliver physically correct results. |
| Stochastic HPG (8) | `terrain_stochastic_shader.py` | **LIE**. See stochastic shader section above. Ships UV offset dither claiming HPG. |
| Procedural snow/moss/dirt (9) | `terrain_macro_color.py::snow_line_factor` overlay (L109-113) | **Partial**. Snow overlay works. No moss, no dirt accumulation procedural overlays. No top-down normal-dot gate (would require reading the mesh normal). |
| Baked shadow/AO (10) | `terrain_shadow_clipmap_bake.py` | **Partial**. Sun-shadow ray-march exists. BUG-R8-A5-014 (short march range), BUG-R8-A5-015 (no soft penumbra). Ambient cavity AO assumed pre-baked in `ambient_occlusion_bake` channel but no bake pass seen in this audit scope. Fix 5.5 (EXR export) still pending — ships .npy not .exr. |
| Texel density (11) | `terrain_materials_ext.py::validate_texel_density_coherency` | **Validator only**. Checks that all `MaterialChannelExt.texel_density_m` values are within 2× of minimum. **Not wired into any pipeline pass** — validator is callable from tests but no production caller. |
| Distance-based tiling (12) | None | **MISSING**. No `detail_scale` near/far LOD in any module we audited. Unity-side Shader Graph Template has `TileSize` as a single float at L136. |

### Summary

What we have that matches AAA practice:
- Per-biome splatmap with smoothstep envelopes (8 biomes V2, 14 total).
- Height-based blending via Blender node group — the `HeightBlend` custom group is genuine AAA practice.
- Per-pass mask_stack architecture with channel declarations.
- Seeding/determinism infra (derive_pass_seed).
- Quixel asset discovery (metadata-only).

What doesn't match AAA practice:
- HPG not implemented (stochastic_shader is a UV-dither noise lookalike).
- Triplanar declarative-only — no shader code.
- Detail normals via Bump-chain, not UDN/RNM.
- No distance-based tiling / macro-micro frequency mixing in the actual shader output.
- No real Quixel pixel ingestion.
- No automated PBR validation gates (albedo range, roughness floor, metallic binary check).
- Shadow clipmap is a toy (24 steps, 0.55^n hard fade).
- Material graphs in `procedural_materials.py` are preview-quality, not ship-quality.

---

## NATURAL TEXTURING RESEARCH FINDINGS

### What makes terrain look photorealistic (from Horizon/TLOU/UE5/Megascans literature)

1. **Macro color variation dominates perception**. Humans register repetition at the macro scale (20m-200m patches) as "fake-ness" before they see fine texture issues. Horizon Forbidden West's terrain shader uses a colorize step to unify per-asset colors under a biome palette. Our `terrain_macro_color` handles this conceptually but too tile-locally (BUG-R8-A5-007).

2. **Height-blending is the single most important technique**. Cracks, pebbles, grass tufts need to visually "fill in the low spots" between layers. Our `height_blend` + `_create_height_blend_group` + `_build_terrain_recipe` wiring is legitimately AAA-caliber — this is the one area where we match production pipelines.

3. **Wetness darkening must not flatten roughness uniformly**. Real wet surfaces have **anisotropic** roughness (water films flow along gravity and cling to crevices). Our pipeline uniformly lowers roughness by 0.15 at wet=1. A more physical approach: `roughness = lerp(dry_rough, wet_rough, wet) * (1 + 0.3 * cavity_mask)` — water pools in cavities, stays rougher there.

4. **Rock scree vs. soil transitions are frequency-dependent**. A realistic scree field has: (a) macro color consistent with upstream cliff, (b) meso-scale boulder clusters from fracture statistics, (c) fine gravel texture. Our pipeline gates scree on slope+altitude (good) but doesn't inherit macro color from the cliff above — `macro_color` computes independently per biome.

5. **Triplanar mapping is mandatory for anything above ~45° slope**. Without it, UV stretch on cliff walls shows up as characteristic "smeared" texture bands. The MaterialChannel flag exists but is unused; this is the single largest visible-quality gap in our shipped materials.

6. **Stochastic sampling (HPG or equivalent) is the difference between "professional" and "indie" terrain**. Plain tileable textures at macro scale show 50m+ repetition that instantly breaks immersion. **Our shader claims HPG but delivers UV dither** — UV dither does partially break tiling but introduces its own artifacts at tile junctions (blurring). HPG is tileability-preserving; UV dither is not.

7. **Per-layer texel density consistency**. A grass layer at 0.5m texel-density and a rock layer at 4m texel-density create visible resolution discontinuities at the blend edge. Our `validate_texel_density_coherency` catches this structurally but it's not enforced at pipeline runtime (tests only).

8. **Natural boundaries are never straight**. `compute_biome_transition` at L1358-1501 with its noise-displaced boundary is correct practice. But it uses `_simple_noise_2d` (BUG-R8-A5-032) which has axis-aligned aliasing — the boundary wobble has visible grid structure at low noise_scale.

### Megascans/Quixel workflow best-practices

A correctly-ingested Quixel surface asset needs:
1. **Albedo (linear sRGB, no shadow/AO baked in)** — Quixel's `_Albedo` is pre-processed to be lighting-neutral. Our classifier at L37 gets this.
2. **Normal (OpenGL or DirectX, tangent-space)** — metadata must declare the convention. Quixel ships OpenGL by default. Our classifier gets the file but **no convention metadata is preserved** — Unity importer has no way to know if Y needs flipping.
3. **Roughness OR Metallic-Roughness packed** — Quixel ships individual files; Unreal integration packs to ORM (Occlusion/Roughness/Metallic in RGB). Our classifier doesn't handle packed (BUG-R8-A5-004).
4. **Displacement/Height** — typically 16-bit grayscale. Our classifier gets the file but doesn't validate bit depth.
5. **JSON metadata sidecar** — Quixel's official metadata includes `meta.json` with `{id, type, tags, dimensions_m, texel_density, categories, seamless_tileable: bool}`. Our code at L103-107 reads any `.json` and merges into a single flat `metadata: Dict[str, Any]`. No schema validation. No check that `seamless_tileable: true` (we can't tile a non-tileable asset).
6. **Cross-biome blending** — a Quixel asset shipped for `thornwood_forest` should have a slight color shift applied to match `corrupted_swamp`'s palette. Our `DARK_FANTASY_PALETTE` biome colors could feed this via HSV-space multiplication on the Albedo before shader sampling. **Not implemented**.

### Key references

- Heitz & Neyret 2018 (HPG): [High-Performance By-Example Noise using a Histogram-Preserving Blending Operator](https://inria.hal.science/hal-01824773/file/HPN2018.pdf)
- Unity Grenoble demo of HPG (runnable reference): https://unity-grenoble.github.io/website/demo/2020/10/16/demo-histogram-preserving-blend-synthesis.html
- Deliot & Heitz 2019 follow-up (Gaussianization refinements): [UnityGaussianTex](https://github.com/Error-mdl/UnityGaussianTex)
- Horizon Forbidden West deferred texturing: [Guerrilla Games](https://www.guerrilla-games.com/read/adventures-with-deferred-texturing-in-horizon-forbidden-west)
- TLOU Material Art GDC: https://80.lv/articles/the-material-art-of-the-last-of-us-part-i-gdc-presentation-is-now-available-for-free
- UE5 Auto-Landscape: https://jennasoenksen.com/ue5-auto-landscape-material
- Terrain3D texture prep: https://terrain3d.readthedocs.io/en/latest/docs/texture_prep.html
- Reoriented Normal Mapping (Barre-Brisebois & Hill): https://blog.selfshadow.com/publications/blending-in-detail/
- TexTile differentiable tileability metric: https://arxiv.org/html/2403.12961
- Histogram-preserving tiling (Bitterli): https://benedikt-bitterli.me/histogram-tiling/

---

## QUALITY TESTS FOR TEXTURING

Concrete automated tests that would catch "shitty textures" before ship:

### 1. Histogram flatness / entropy gate
**What it catches**: Materials whose albedo channel is a flat near-uniform color (e.g., a failed procedural where noise amplitude is 0).
```python
def test_albedo_has_variance(baked: BakedTerrain):
    """Every baked tile's albedo channel must have >X shannon entropy."""
    for channel_name, arr in baked.material_masks.items():
        if channel_name.startswith("albedo"):
            hist, _ = np.histogram(arr, bins=64, range=(0, 1))
            hist = hist / hist.sum()
            entropy = -(hist * np.log2(hist + 1e-9)).sum()
            assert entropy > 4.0, f"{channel_name} histogram entropy {entropy:.2f} < 4.0 — flat texture"
```

### 2. Tileability check (TexTile-style)
**What it catches**: A texture whose left edge ≠ right edge (non-tileable).
```python
def test_seam_discontinuity(texture: np.ndarray, max_seam_l1: float = 0.05):
    """L1 distance between left col and right col must be small."""
    left = texture[:, 0]
    right = texture[:, -1]
    top = texture[0, :]
    bottom = texture[-1, :]
    assert np.abs(left - right).mean() < max_seam_l1
    assert np.abs(top - bottom).mean() < max_seam_l1
```

### 3. Normal map validity
**What it catches**: Non-unit normals (encoded wrong), Y-inverted (OpenGL ↔ DirectX swizzle).
```python
def test_normal_map_valid(normal: np.ndarray):
    """Normal map must encode unit vectors; Y channel convention must be known."""
    # Decode: nm ∈ [0,1] → n ∈ [-1, 1]
    n = normal * 2.0 - 1.0
    length_sq = (n**2).sum(axis=-1)
    assert np.abs(length_sq - 1.0).mean() < 0.02, "Normals not unit length"
    # Check Y-up majority (OpenGL convention)
    assert n[..., 1].mean() > 0.3, "Y channel not majority positive — might be DirectX"
```

### 4. PBR albedo range
**What it catches**: Materials that are too dark (< 0.03) or too bright (> 0.9) for real-world dielectrics.
```python
def test_dielectric_albedo_in_range(material: dict):
    if material["metallic"] < 0.1:  # dielectric
        lum = 0.2126 * material["base_color"][0] + 0.7152 * material["base_color"][1] + 0.0722 * material["base_color"][2]
        assert 0.03 < lum < 0.9, f"Dielectric {material['key']} luminance {lum:.2f} out of [0.03, 0.9]"
```

### 5. Metallic binary check
**What it catches**: Middle metallic values (0.3-0.7) which are non-physical for any real surface.
```python
def test_metallic_is_binary(material: dict):
    m = material["metallic"]
    assert m < 0.1 or m > 0.9, f"Non-binary metallic {m} for {material['key']} — rust/wear should be a mask, not a scalar"
```

### 6. Tiling artifact detection (repetition score)
**What it catches**: Rendered terrain frame showing visible texture repetition at 10m+ scale.
```python
def test_rendered_frame_repetition(frame: np.ndarray, patch_size: int = 64):
    """Autocorrelation of frame should not have peaks at regular intervals."""
    gray = frame.mean(axis=-1)
    # FFT-based autocorrelation
    f = np.fft.fft2(gray - gray.mean())
    autocorr = np.abs(np.fft.ifft2(f * np.conj(f)))
    # Peaks at (dy, dx) ≠ (0,0) indicate repetition
    autocorr[0, 0] = 0
    peak_ratio = autocorr.max() / autocorr.mean()
    assert peak_ratio < 8.0, f"Tiling peak ratio {peak_ratio:.1f} > 8 — visible repetition"
```

### 7. Roughness floor
**What it catches**: Mirror-smooth surfaces that cause specular aliasing.
```python
def test_roughness_floor(material_masks: dict):
    rough = material_masks.get("roughness_variation")
    if rough is not None:
        assert rough.min() >= 0.04, f"Roughness min {rough.min():.3f} < 0.04 — specular aliasing risk"
```

### 8. Texel density coherency (already implemented, just needs to run)
**What it catches**: Mismatched cm/m between blending layers.
Current code: `terrain_materials_ext.py::validate_texel_density_coherency`. **Wire it into the ship-validation pass, not just tests.**

### 9. Stochastic mask variance sanity
**What it catches**: UV-offset mask that is uniform (dead noise) or saturated (excessive dither).
```python
def test_stochastic_mask_variance(mask: np.ndarray):
    """UV offset mask std should be in [0.1, 0.35]."""
    assert 0.1 < mask.std() < 0.35, f"Mask std {mask.std():.3f} outside [0.1, 0.35]"
```

### 10. Macro color saturation cap
**What it catches**: Biomes pushing saturation beyond dark-fantasy 40% limit.
```python
def test_macro_color_saturation(macro_color: np.ndarray):
    """All pixels must have saturation ≤ 0.40 (VeilBreakers palette rule)."""
    import colorsys
    # Vectorized HSV conversion on linear RGB — approximate
    max_c = macro_color.max(axis=-1)
    min_c = macro_color.min(axis=-1)
    sat = np.where(max_c > 1e-6, (max_c - min_c) / max_c, 0.0)
    assert sat.max() < 0.42, f"Saturation {sat.max():.3f} exceeds 0.40 cap"
```

### 11. Shadow clipmap contrast sanity
**What it catches**: All-shadowed or all-lit tiles (bug in ray-march clipping).
```python
def test_shadow_clipmap_contrast(shadow_mask: np.ndarray):
    """Shadow mask should have both lit (>0.9) and shadowed (<0.5) cells unless the tile is a plateau."""
    lit_frac = (shadow_mask > 0.9).mean()
    shadow_frac = (shadow_mask < 0.5).mean()
    # At least 2% of tile shadowed AND at least 10% lit, except for flat plateaus
    assert lit_frac > 0.1 and (shadow_frac > 0.02 or lit_frac > 0.95)
```

### 12. Determinism under tiling
**What it catches**: The per-tile normalization bugs (BUG-R8-A5-007, 012).
```python
def test_tile_seam_roughness_continuity(tile_a: BakedTerrain, tile_b_adjacent: BakedTerrain):
    """Roughness at tile A's right edge should match tile B's left edge within tolerance."""
    rough_a_right = tile_a.material_masks["roughness_variation"][:, -1]
    rough_b_left = tile_b_adjacent.material_masks["roughness_variation"][:, 0]
    assert np.abs(rough_a_right - rough_b_left).max() < 0.05
```

---

## GRADE CORRECTIONS

Based on this audit, the following function grades in `GRADES_VERIFIED.csv` need downgrading. (Exact current grades should be pulled from the CSV during the audit-artifact merge — estimates here based on terrain_audit_2026_04_15 convention.)

| Function | Current (likely) | New | Reason |
|----------|------------------|-----|--------|
| `build_stochastic_sampling_mask` | B | **D** | Ships UV dither as HPG. The entire Unity-side pipeline gets a `histogram_preserving=True` flag that is false. Misrepresented capability. |
| `pass_stochastic_shader` | B | **C-** | Inherits the lie; also adds BUG-R8-A5-006 (pollutes roughness_variation with UV magnitude). |
| `compute_multiscale_breakup` | B+ | **C** | Amplitude ordering is inverted (BUG-R8-A5-010); cell_size validation missing (BUG-R8-A5-009). Works but produces grainy not varied breakup. |
| `compute_macro_color` | B+ | **C+** | Per-tile normalization bug for altitude gate; biome lookup uses slow mask iteration. |
| `compute_roughness_from_wetness_wear` | B | **C+** | Math bug in erosion lerp (BUG-R8-A5-011); per-tile normalization (BUG-R8-A5-012). |
| `bake_shadow_clipmap` | B | **C** | Soft shadow is effectively binary (BUG-R8-A5-015); short march range (BUG-R8-A5-014). Conceptually correct, implementation is a toy. |
| `export_shadow_clipmap_exr` | C+ | **D+** | The function name **lies** — it writes .npy. Already in Fix 5.5 scope but the current state is actively misleading. |
| `pass_quixel_ingest` | B- | **D** | BUG-52 (dead local) + BUG-R8-A5-002 (double-apply logic bug) + BUG-R8-A5-003 (never loads pixels) + BUG-R8-A5-004 (no packed-texture classifier). The function is essentially a Path discovery scanner dressed as "ingest." |
| `ingest_quixel_asset` | B | **C-** | No schema validation on the JSON sidecar; no texture-file header validation; no dimension/channel sanity check. |
| `apply_quixel_to_layer` | B- | **C-** | Uses `stack.populated_by_pass` (a provenance string dict) as a payload channel — semantic abuse. |
| `_build_normal_chain` | A- | **C+** | The Bump-chain approach is not RNM/UDN — not what AAA uses. Misrepresents the `micro/meso/macro_normal_strength` fields as true detail-normal composition. |
| `build_metal_material` | B | **C** | Two-BSDF MixShader for rust is non-PBR-correct (BUG-R8-A5-023). |
| `build_stone_material` | B | **C+** | Silent 2.5× base_color brightening (BUG-R8-A5-025); Bump-chain via `_build_normal_chain`. |
| `build_terrain_material` | B | **C+** | Same 2.0× brightening; same Bump-chain issue. |
| `validate_dark_fantasy_color` | B | **D** | Unused (BUG-R8-A5-027); also uses linear-on-HSV (BUG-R8-A5-026). |
| `extract_palette_from_image` | A- | **B-** | Hardcoded seed (BUG-R8-A5-028); no convergence warning. |
| `_simple_noise_2d` | B | **C** | Weak hash with grid-axis aliasing (BUG-R8-A5-032). |
| `_clamp_rgba` | A | **C** | BUG-R8-A5-001 — Sequence not imported. Would fail runtime type resolution. |
| `_build_terrain_recipe` | B+ | **B** | BUG-R8-A5-001 — Mapping not imported. Function logic itself is decent. |
| `compute_height_blended_weights` | A- | **A-** | **No downgrade** — this is the best-written part of the pipeline. |
| `height_blend` | A- | **A-** | **No downgrade** — clean, correct implementation of the standard UE5-style formula. |
| `_create_height_blend_group` | A | **A** | **No downgrade** — cleanly builds the Blender group for height blending. |
| `compute_slope_material_weights` | A- | **B+** | Hard step on curvature/wetness (BUG-R8-A5-019). |
| `auto_assign_terrain_layers` | B+ | **B+** | **No change** — logic is sound; moisture modulation is a legitimate AAA feature. |
| `compute_world_splatmap_weights` | A | **A-** | Silent slope recomputation (BUG-R8-A5-020 — inconsistent with v2). Vectorized impl is genuinely good. |
| `compute_biome_transition` | B | **B-** | Uses weak `_simple_noise_2d`; otherwise correct. |
| `validate_texel_density_coherency` | A | **B+** | Correct but **never wired into production** — tests-only. Downgrade for lack of enforcement, not for logic. |

### Aggregate delta

- Net downgrades: 22 functions
- Net upgrades: 0
- No-change: 3 functions
- Most severe: `build_stochastic_sampling_mask` (B→D), `pass_quixel_ingest` (B-→D), `export_shadow_clipmap_exr` (C+→D+), `validate_dark_fantasy_color` (B→D)

### Cross-pipeline impact

The **single highest-leverage fix** for perceived AAA quality is implementing real triplanar in the Unity-side shader graph for cliff/wet_rock/steep_slope layers. This is a one-to-two-day implementation in Unity shader code and would close the largest visible-quality gap listed in the AAA stack gap analysis. It doesn't touch Python code at all.

The **second-highest-leverage fix** is real HPG (Heitz-Neyret 2018) — a ~400 LOC Python + Unity shader addition. Budget 1 sprint-week including LUT precompute + triangle-grid shader. This replaces `terrain_stochastic_shader.py` module entirely and brings Fix 5.4's second half (the real `build_histogram_preserving_blend_mask`) into existence.

The **third-highest-leverage fix** is actually loading Quixel pixel data in `pass_quixel_ingest` — without it, the entire "Quixel workflow" claim is false. This is a 3-4 day implementation including `PIL.Image` + channel validation + `stack.quixel_textures` wiring + a `test_quixel_texture_loaded` integration test.

---

**End of R8-A5 audit.**
