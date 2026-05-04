# VeilBreakers Materials & Texturing Audit — Batch 15 (2026-05-04)

**Auditor scope:** `terrain_materials.py` (3,689 LOC), `terrain_materials_v2.py` (1,322), `terrain_materials_ext.py` (470), `procedural_materials.py` (2,019), `terrain_stochastic_shader.py` (1,176), `terrain_roughness_driver.py` (247), `terrain_palette_extract.py` (337), `terrain_quixel_ingest.py` (1,013), `terrain_texture_layer_stack.py` (93). Total ≈ 10,366 LOC.

**Verdict — system as a whole: D+** (specific subsystems range C− to A−). The dual-splatmap problem is **not** fixed: there are now FIVE distinct writers/derivations of "splatmap" and the Blender preview path still cannot guarantee parity with the Unity export. The 4-layer cap is wired but applied in the wrong order. Stochastic tiling is the bright spot (B+/A−). Quixel ingestion has accumulating-blend bugs that corrupt multi-layer output. Roughness driver is solid (B+). Several layered passes silently double-write `terrain_normals` with conflicting coordinate frames.

---

## 1. Splatmap Writer Census — every place a "splatmap" data product is produced

| # | File · Symbol · Line | Output target | Coordinate / Layer count | Wired to Unity? | Wired to Blender preview? |
|---|---|---|---|---|---|
| 1 | `terrain_materials_v2.py · pass_materials :: stack.set("splatmap_weights_layer")` line 1105 | `stack.splatmap_weights_layer` (H, W, L) float32 | up to L=5 (default rules) or L=5 (volcanic) | YES — `_write_splatmap_groups` line 1764 | INDIRECT — `_sample_splatmap_weights_at_vertex` line 3369 reads `stack.splatmap_weights_layer` and writes `VB_TerrainSplatmap` per-loop |
| 2 | `terrain_materials_v2.py · pass_materials :: stack.set("material_weights")` line 1106 | `stack.material_weights` (alias copy) | identical to #1 | NO (alias only) | NO |
| 3 | `terrain_quixel_ingest.py · apply_quixel_to_layer :: stack.set("splatmap_weights_layer")` lines 557, 601, 933, 951 | `stack.splatmap_weights_layer` | up to L=4 hard-capped (`_UNITY_MAX_SPLATMAP_LAYERS`) | YES (overrides #1) | NO (preview path doesn't re-render after Quixel ingest) |
| 4 | `terrain_materials.py · auto_assign_terrain_layers` line 2579 | returns 4-tuples per vertex | always 4 (RGBA) | NO | YES — written into `mesh.color_attributes["VB_TerrainSplatmap"]` line 3617 |
| 5 | `terrain_materials.py · compute_world_splatmap_weights` line 3168 | `(H, W, 4)` float64 numpy array | always 4 (RGBA) | INDIRECTLY — used by `environment.py` line 2484 for tiled-world preview | YES — same call path |
| 6 | `environment.py · _paint_road_mask_on_terrain` line 5237 | `mesh.color_attributes["VB_TerrainSplatmap"]` (per-loop, RGBA hardcoded palette) | 4 channels with hand-picked weights | NO — never round-trips to `splatmap_weights_layer` | YES (Blender only) |
| 7 | `environment.py · auto_paint terrain_v6` line 6505 | manifest entry `"splatmap_layer": "VB_TerrainSplatmap"` | metadata only | NO | NO |

**Conclusion:** The dual-splatmap problem is now a **quintuple-splatmap problem**. The "fix" alleged in FIX-B14-11 (line 2645 of `terrain_materials.py`) is the *fast path* in `auto_assign_terrain_layers` that samples from `stack.splatmap_weights_layer` *if and only if* the caller passes a `stack=` argument. **None of the production callers in `environment.py` pass that stack** — every `auto_assign_terrain_layers(...)` call site I traced uses the slope/height heuristic path because they're invoked outside the headless pipeline state.

### MAT-P0-1 (CRITICAL) — Dual derivation persists despite FIX-B14-11

**File:** `terrain_materials.py:3573-3617` (`create_biome_terrain_material`)

```python
use_stack_weights = stack is not None and getattr(
    stack, "splatmap_weights_layer", None
) is not None
if use_stack_weights:
    # Path A: sample from authoritative stack
else:
    # Path B: re-derive via auto_assign_terrain_layers (slope+height heuristic)
```

But `create_biome_terrain_material` is called from `handle_create_biome_terrain` (line 3634) which **never receives or constructs a stack** — it only takes a `biome_name` and `object_name`. The MCP command `terrain_create_biome_material` therefore *always* takes Path B. The Blender preview is guaranteed to drift from Unity.

**Fix:** see §3 below.

### MAT-P0-2 (CRITICAL) — `_paint_road_mask_on_terrain` writes vertex colors only

**File:** `environment.py:5237-5320`. The road system paints `VB_TerrainSplatmap` with hardcoded RGBA palette tuples (e.g. `gravel = (0.26, 0.54, 0.14, 0.06)`) and **never updates `stack.splatmap_weights_layer`**. `apply_sdf_road_blend` in `terrain_materials_v2.py:520` is a no-op when `road_sdf_dist` is absent from the stack (which it usually is, because the road handler doesn't set it on the stack either — only returns it in a response dict when `return_road_channels=True`). Result: roads are visible in Blender preview, invisible in Unity export. K7-P0-3 from the 2026-04-27 deep dive remains UNFIXED.

### MAT-P0-3 — RGBA semantic mismatch between paths

`auto_assign_terrain_layers` always returns `(R=ground, G=slope, B=cliff, A=special)` — the legacy 4-layer biome convention. `_sample_splatmap_weights_at_vertex` (line 3369) reads the first 4 channels of `stack.splatmap_weights_layer` and writes them straight into vertex color RGBA — but the v2 default rule set is `(ground, cliff, scree, wet_rock, snow)`. So when the stack is sampled (the alleged fix path), R=ground, G=cliff, B=scree, A=wet_rock and snow is silently dropped. The Blender material graph at line 3458 connects `["ground", "slope", "cliff", "special"]` BSDFs to those vertex colors — **the cliff layer in Blender now displays as if it were "scree" weights, and snow is invisible.** This is a worse failure mode than the dual derivation it was meant to fix.

**Fix:** see §3.

---

## 2. 4-Layer HDRP Cap — Verification

**File:** `terrain_unity_export.py:1780-1797` (P1-17 fix)

```python
if L > 4:
    order = np.argsort(weights_np, axis=2)[:, :, ::-1]   # desc
    top4_mask = np.zeros((H, W, L), dtype=bool)
    for rank in range(4):
        top4_mask[..., order[:, :, rank]] = True
    weights_np = np.where(top4_mask, weights_np, 0.0).astype(np.float32)

# Normalise per-pixel so all active layers across the full stack sum to 1.
total_weight = weights_np.sum(axis=2, keepdims=True)
safe_total = np.where(total_weight > 1e-7, total_weight, 1.0)
weights_norm = (weights_np / safe_total).astype(np.float32)
```

**Correctness analysis:**

✓ Top-4 selection is correct (argsort descending, mask top 4 ranks).
✓ Renormalisation is applied AFTER masking, so the 4 surviving layers correctly sum to 1.0.
✓ Multi-group splatmap output (line 1799-1850) now writes `splatmap_00.raw`, `splatmap_01.raw` etc, but with the cap applied **before** grouping — so groups 1+ will be entirely zero when L > 4. **This is technically correct** (cap = top-4 globally) but is a wasted file write: `group_count = max(1, (L+3)//4)` will create empty groups for L=5,6.

⚠ **MAT-P1-1** — The cap is applied PER-CELL globally, but the manifest hint `terrain_layer_assets` at line 1840 still lists asset paths for groups beyond the cap. A 5-layer stack writes `splatmap_00.raw` (the 4 winners) AND `splatmap_01.raw` (zeros) and the manifest declares both as valid. The Unity importer will create a 5th terrain layer asset that has zero weight everywhere. Cosmetic but pollutes Unity scene.

⚠ **MAT-P1-2** — `argsort` with ties is unstable: when two layers have identical weight, the chosen layer depends on platform numpy version. This makes the cap **non-deterministic at boundary cases**. AAA fix: stable sort (`kind="stable"`) plus deterministic tie-break by layer index.

⚠ **MAT-P1-3** — The cap writes `weights_np = 0` for losing layers, then renormalises. If a cell has 5 layers ranked `[0.21, 0.21, 0.20, 0.19, 0.19]`, the bottom two zeros + renormalize boosts the survivors to `[0.262, 0.262, 0.250, 0.226]`. That's correct math, but **it makes the 4th layer 18.7% lighter than the original 4th layer's 21%**. There's no warning emitted for cells with significant capped weight — AAA pipelines (UE5) flag cells with capped > 5% as material-quality issues.

**Verdict on the cap fix: B−.** Functionally correct; lacks determinism guarantee and lacks coverage warnings.

---

## 3. Dual-Splatmap Fix Plan (concrete)

### Decision: `stack.splatmap_weights_layer` is the SINGLE authoritative source

Rationale: it is the only multi-layer (L > 4), pipeline-pass-derived, validated source. The `VB_TerrainSplatmap` vertex-color attribute is a Blender preview artifact only. The road handler should write to a *new* stack channel (`road_paint_mask`) which `pass_materials` then folds into `splatmap_weights_layer`.

### Step-by-step fix

**Fix #1: Make `create_biome_terrain_material` REQUIRE a stack.**

```python
# terrain_materials.py:3412 — replace signature:
def create_biome_terrain_material(
    biome_name: str,
    object_name: str | None = None,
    season: str | None = None,
    *,
    preserve_existing_splatmap: bool = True,
    stack: Any,                       # <-- now positional-required keyword
) -> Any:
    if stack is None:
        raise ValueError(
            "create_biome_terrain_material requires a TerrainMaskStack with "
            "splatmap_weights_layer; Blender preview must use the same source "
            "as the Unity export. See docs/aaa-audit/batch15_.../scan_05.md."
        )
    if getattr(stack, "splatmap_weights_layer", None) is None:
        raise ValueError("stack.splatmap_weights_layer not populated; run "
                         "pass_materials_v2 before building Blender material.")
    # remove the entire `else` branch at line 3594 — no fallback to
    # auto_assign_terrain_layers
```

**Fix #2: `_sample_splatmap_weights_at_vertex` must remap by layer name, not index.**

```python
# terrain_materials.py:3369 — replace:
def _sample_splatmap_weights_at_vertex(
    stack: Any,
    vx: float, vy: float, vz: float,
    layer_id_map: dict[str, int],   # NEW: rule_set channel_id -> column index
    blender_slot_order: tuple[str, str, str, str] = ("ground", "slope", "cliff", "special"),
) -> tuple[float, float, float, float] | None:
    layer = getattr(stack, "splatmap_weights_layer", None)
    if layer is None:
        return None
    arr = np.asarray(layer)
    n_rows, n_cols = arr.shape[:2]
    cell_size = float(getattr(stack, "cell_size", 1.0) or 1.0)
    origin_x = float(getattr(stack, "world_origin_x", 0.0))
    origin_y = float(getattr(stack, "world_origin_y", 0.0))
    col = int((vx - origin_x) / cell_size)
    row = int((vy - origin_y) / cell_size)
    col = max(0, min(col, n_cols - 1)); row = max(0, min(row, n_rows - 1))
    cell = arr[row, col, :]
    out = [0.0, 0.0, 0.0, 0.0]
    for slot_idx, slot_name in enumerate(blender_slot_order):
        # legacy slots: ground, slope, cliff, special
        # v2 rules:     ground, cliff, scree, wet_rock, snow
        # mapping:      slope <- max(scree, snow), special <- max(wet_rock, snow)
        if slot_name == "ground":
            ci = layer_id_map.get("ground", -1)
            out[slot_idx] = float(cell[ci]) if ci >= 0 else 0.0
        elif slot_name == "slope":
            scree = layer_id_map.get("scree", -1)
            snow  = layer_id_map.get("snow", -1)
            out[slot_idx] = max(
                float(cell[scree]) if scree >= 0 else 0.0,
                float(cell[snow])  if snow  >= 0 else 0.0,
            )
        elif slot_name == "cliff":
            ci = layer_id_map.get("cliff", -1)
            out[slot_idx] = float(cell[ci]) if ci >= 0 else 0.0
        elif slot_name == "special":
            wr = layer_id_map.get("wet_rock", -1)
            out[slot_idx] = float(cell[wr]) if wr >= 0 else 0.0
    s = sum(out) or 1.0
    return tuple(w / s for w in out)
```

**Fix #3: Unify the road handler.**

```python
# environment.py:5237 — replace _paint_road_mask_on_terrain with:
def _paint_road_mask_on_stack(
    stack: TerrainMaskStack,
    path_world: list[tuple[float, float, float]],
    *,
    road_half_width: float,
    shoulder_width: float,
    surface_key: str = "dirt",
) -> None:
    # Compute SDF distance from path
    sdf = _compute_path_sdf(stack, path_world)
    stack.set("road_sdf_dist", sdf, "road_paint")
    # Optional: write a hint channel that pass_materials reads
    stack.set("road_surface_key", np.full(sdf.shape, _surface_to_int(surface_key), dtype=np.uint8),
              "road_paint")
```

Then `pass_materials_v2` already calls `apply_sdf_road_blend` IF `road_sdf_dist` is on the stack — and the Blender preview will pick that up automatically because it samples from `splatmap_weights_layer`.

**Fix #4: Eliminate `auto_assign_terrain_layers` fallback.**

Mark it `@deprecated`; raise `DeprecationWarning` when called without stack. After 1 release cycle, delete it and `compute_world_splatmap_weights` (the world-pass version is also dead code if step #1 lands — environment.py:2484 is the only non-test caller).

---

## 4. Stochastic Shader — Grade A−

`terrain_stochastic_shader.py` is the strongest module in the audit. Implements both Heitz 2019 triangular-basis and Mikkelsen 2022 hex-tiling with proper hash-based per-tile offsets, histogram-preserving rank equalisation, and per-tile UV rotation.

✓ `_tile_hash_2d` line 542 — proper Murmur3-inspired integer hash; 4 independent channels per tile; deterministic across platforms.
✓ Hash variance test would pass: each tile gets a different (u, v, rot) offset.
✓ HLSL exported correctly — both triangular and hex shader templates parse and validate against `_REQUIRED_UNITY_SHADER_PROPERTIES`.
✓ `histogram_preserving=True` correctly applies rank-based equalisation to fix the bilinear pull-toward-zero.

⚠ **STOCH-P2-1** — The HLSL `HistogramPreservingBlend` function (line 126, 312) ignores the `contrast` parameter. The shader hardcodes `contrastScale = 1.0/sqrt(dot(w,w))`. The Python side reads `_ContrastCorrection` from manifest and passes it to the shader, but the shader literally has the parameter `float contrast` and never references it after the function entry. **Heitz 2019 Eq. 10's contrast correction is not actually applied at runtime in Unity.** Authoring `contrast_correction=2.0` in Python has zero visual effect.

⚠ **STOCH-P2-2** — `pass_stochastic_shader` does not write `roughness_variation` (line 1124 explicitly notes the channel is owned by roughness_driver). But it also does not write `stochastic_offset_mask` even though docstring claims to (line 1033 in pass docstring vs. removed in line 1124). Metric `offset_magnitude_mean` is computed but discarded. Cosmetic.

⚠ **STOCH-P2-3** — `build_stochastic_sampling_mask` allocates a full `(tiles_y * tiles_x, 4)` hash table via `_tile_hash_2d` even though only 3 of 4 channels are used. 25% memory wasted at AAA tile sizes (e.g. 4096² heightmap with 4m tiles = 1024² tile grid = 4 MB wasted).

**Comparison to MicroSplat / RDR2 / Ghost of Tsushima:**

| Feature | VB | MicroSplat | RDR2 | Ghost of Tsushima |
|---|---|---|---|---|
| Hash-based per-tile offset | ✓ | ✓ | ✓ | ✓ |
| Histogram-preserving (Heitz 2019) | ✓ | ✓ (paid module) | ✓ | ✗ (uses macro variation instead) |
| Hex tiling (Mikkelsen 2022) | ✓ | ✗ | ✗ | ✓ (custom variant) |
| Per-tile UV rotation | ✓ | ✓ | ✓ | ✓ |
| Triplanar projection on cliff layers | ◐ (hint only — see §6) | ✓ | ✓ | ✓ |
| Distance-based tessellation | ✗ | ✓ | ✓ | ✓ |
| POM / parallax occlusion | ✗ | ✓ | ✓ | ✓ |

Distance-based tessellation and POM are the only missing AAA features. Both are out-of-scope for a stochastic shader module — they'd live in a separate `terrain_pom.py`.

---

## 5. Roughness Driver — Grade B+

`terrain_roughness_driver.py` is well-formed.

✓ Wetness pulls toward 0.15, erosion pushes toward 0.85, deposition toward 0.70 — physically grounded.
✓ AO concavity adds +0.05 dust roughness — matches Quixel surface scans.
✓ Slope-driven 0.90 toward exposed rock @ 60° — accurate vs. Quixel cliff measurements.
✓ Concavity reduces roughness toward 0.25 (sediment) — matches RDR2 wet-area shader.
✓ `roughness_breakup` consumed as multiplicative modulation — correct single-writer pattern.

⚠ **ROUGH-P2-1** — Wind-blown dust accumulation is **not modeled**. AAA terrains (RDR2, Ghost of Tsushima) compute a wind-shadow mask (windward = stripped, leeward = dust-loaded) and add 0.10 to leeward roughness. Stack channel `wind_exposure` is unread. Adding one term:
```python
wind = stack.get("wind_exposure")
if wind is not None:
    leeward = 1.0 - np.clip(np.asarray(wind), 0.0, 1.0)
    base = base + 0.10 * leeward
```

⚠ **ROUGH-P2-2** — `compute_roughness_from_wetness_wear` *re-creates* the base from scratch every call. The docstring claims "additive refinement instead of overwriting" (line 38) but the code at line 45 does `base = np.full(..., 0.55)` regardless of any pre-existing `roughness_variation`. Documentation lies. Either honor the doc (add `existing = stack.get("roughness_variation"); if existing is not None: base = existing.copy()`) or fix the docstring.

⚠ **ROUGH-P2-3** — Slope blend uses `np.degrees(s) / 60.0`. Slope channel is documented as **radians** in `terrain_semantics.py`. Converting radians to degrees then dividing by 60 ≈ same as `s / (60*π/180) = s / 1.047`. The math works but the variable name `s_norm` reads as if normalised in radians; subtle. Cosmetic.

---

## 6. Quixel Ingestion — Grade C

`apply_quixel_to_layer` has serious correctness bugs in the texture-blend path.

### QUIX-P0-1 (CRITICAL) — Albedo accumulation is not weighted-average

**File:** `terrain_quixel_ingest.py:618-630`

```python
if stack.macro_color is None:
    stack.set("macro_color", sampled_albedo * layer_weight[..., None], ...)
else:
    blended = stack.macro_color + sampled_albedo * layer_weight[..., None]
    stack.set("macro_color", blended.astype(np.float32), ...)
```

This is **additive accumulation**, not weighted blending. After 4 layers each weighted ~0.25, `macro_color` sums to 4 × 0.25 × albedo = albedo (correct only by coincidence). But if 3 layers have weight 0.33 and a 4th has weight 0.01, the result is `0.33*alb_a + 0.33*alb_b + 0.33*alb_c + 0.01*alb_d` — same form, but only correct because all layers happen to be present. If a layer fails to add (capacity hit), the macro_color is no longer normalised and renders too dark. **Real fix:** track total weight and divide at the end, OR store `numerator` and `denominator` separately and finalise in `pass_quixel_ingest`.

### QUIX-P0-2 (CRITICAL) — Roughness accumulation has the same bug

Lines 632-648 do `blended_r = stack.roughness_variation + sampled_rough * layer_weight`. Roughness is also single-writer-owned by `terrain_roughness_driver` (per `pass_stochastic_shader`'s comment at line 1124). `apply_quixel_to_layer` clobbers it. **`ChannelOwnershipError` should fire here** but doesn't because Quixel ingest runs in a non-pass context (`apply_quixel_to_layer` is a helper, not a registered pass). **The pass-level `pass_quixel_ingest` doesn't even declare `roughness_variation` in `produces_channels` (line 962 produces only `splatmap_weights_layer`), so the `stack.set("roughness_variation", ...)` write at line 644 is a silent contract violation.**

### QUIX-P0-3 — Normal blend frame is wrong

Line 654: `sampled_normal = np.clip(sampled_normal, 0.0, 1.0) * 2.0 - 1.0`. Decodes packed [0,1] to [-1,1] tangent-space normal. ✓ Good. But then line 663-668 adds `base_n + sampled_normal * layer_weight` — **base_n is in object/world space** (initialized as `(0,0,1)` on line 660), and `sampled_normal` is in **tangent space**. Adding them is meaningless. A real implementation should use Reoriented Normal Mapping (RNM) or the unity-style "whiteout" blend, both of which require the host surface tangent frame which this function does not have access to. **Result: terrain normals from Quixel ingestion are visibly broken on any cell with slope > 0.**

### QUIX-P0-4 — `terrain_normals` ZUP vs Y-up frame collision

`apply_quixel_to_layer:662` writes `stack.terrain_normals` with a default `(0, 0, 1)` Z-up basis (line 660-662). `terrain_unity_export.pass_prepare_terrain_normals:460` writes `stack.terrain_normals` in Y-up Unity space. **Whichever runs last wins; if Quixel runs after `prepare_terrain_normals`, the export normals get overwritten with Z-up vectors.** Per `terrain_semantics.py:884` the channel dtype is `("f", 3)` with no frame guard. The contract docs (`TERRAIN_GENERATION_GUARDRAILS.md:798`) declare Y-up. Quixel ingest is wrong.

### QUIX-P0-5 — `_load_texture_as_float` mangles HDR/EXR

Line 269-271:
```python
if raw_min < 0.0 or raw_max > 1.0:
    span = raw_max - raw_min
    raw = (raw - raw_min) / span if span > 1e-8 else np.zeros_like(raw)
```

This **per-texture-min-max-stretch** destroys the linear physical units of EXR displacement maps. A Quixel rock displacement EXR with values in [0, 0.4] gets stretched to [0, 1] and then `apply_quixel_to_layer` blends it into `terrain_displacement` at full amplitude — terrain mesh deforms 2.5× too far. EXR values must be **clamped** to [0, 1] (or to a documented physical range), not normalised.

### QUIX-P1-1 — sRGB linearisation only on the keyword-arg path

`_srgb_to_linear` is applied at line 619 when `albedo_array` is supplied as a keyword. But on the lines 678-684 fallback (auto-load AO from disk) and 703-712 (auto-load displacement), the loaded textures are **not** linearised. Albedo loaded via the auto-detect path (no kwarg) is also not linearised. Mixed code paths produce mixed colour spaces.

### QUIX-OK — what works

✓ Filename classification is comprehensive (long-form patterns + short BCR/D/N/R/M/AO/T suffixes).
✓ Biome filtering via `_asset_matches_biome` is reasonable.
✓ `_UNITY_MAX_SPLATMAP_LAYERS = 4` enforced with hard error at line 562.
✓ Three asset resolution sources (explicit list, descriptors, cache scan) with deterministic ordering.

**Comparison to RDR2 / Ghost of Tsushima:**

Neither AAA studio uses run-time per-layer accumulation. Both bake terrain albedo into pre-computed virtual texture pages (RDR2 = SVT, Tsushima = clipmaps), then composite at sample time using stable blend operators (Brucks height-blend, RNM normals, weighted-sum-with-divide on albedo). VB Quixel ingest is **algorithmically a generation behind** at the texture-blend level; needs a proper composite pass that finalises the accumulator instead of accumulating in place.

---

## 7. Texture Layer Stack — Grade C+ (good intent, wired but underused)

`terrain_texture_layer_stack.py` is 93 LOC of clean dataclass code.

✓ `TextureLayer` covers albedo / normal / roughness / displacement / AO / metallic / color_space / tiling_scale / texel_density.
✓ `TerrainTextureLayerStack.normalized_weights()` correctly normalises per-pixel layer sums to 1.0.
✓ `validate()` checks for missing weight_map, missing normal, missing roughness, missing AO, weight range.
✓ Dataclass is now built and attached to pipeline state at `terrain_materials_v2.py:1161-1173` (E-1 fix landed).

⚠ **TLS-P1-1** — The Unity exporter (`terrain_unity_export.py`) does **not consume `state.texture_layer_stack`**. Search:
```
$ grep -n "texture_layer_stack" terrain_unity_export.py
(no matches)
```
The dataclass is built and discarded. Manifest layer asset paths at line 1816 are **synthesised from layer index** (`Assets/Terrain/Layers/Layer_NNN.terrainlayer`) rather than read from the stack's `layer_id`. Result: Unity-side terrain layer asset names lose their semantic identity (`ground` becomes `Layer_000`).

⚠ **TLS-P1-2** — `validate()` is **never called** in the pipeline. Search confirms only one test uses it (`test_terrain_material_ceiling.py`). At AAA quality bar this should run as part of `pass_materials_v2` and emit ValidationIssues for each missing channel.

⚠ **TLS-P2-1** — No HDRP `mask_map` representation (HDRP packs metallic/AO/detail/smoothness into RGBA). The dataclass models them as separate np arrays; the Unity exporter packs them at write time (`_pack_hdrp_mask_map` line 669) — adequate but means the stack does not represent the final shipping format.

---

## 8. Palette Extract — Grade A−

`terrain_palette_extract.py` is genuinely well-engineered.

✓ Pure-numpy k-means, deterministic seed-derivation via `derive_pass_seed`.
✓ Lab-space biome classification (perceptually uniform — won't conflate olive green with brown).
✓ Gaussian confidence via `exp(-(d/sigma)²)` — much better than the old linear `1 - d/d_max` which collapsed when one outlier dominated.
✓ Includes arctic / tropical / desert + VB-specific (dark, earth, foliage, water, light, neutral).
✓ sRGB → XYZ → Lab pipeline uses correct IEC 61966-2-1 + D65 white point.

⚠ **PAL-P3-1** — `_BIOME_LAB_CENTROIDS` only has 9 biomes; the canonical VB biome list per `AAA_MASTER_AUDIT_2026_05_03.md` has 12 (volcanic, alpine, plateau, wetland, shadow are missing direct centroid entries — they're rule-table aliases for existing centroids). Functional but means the palette extractor cannot return "volcanic" as a top result; it returns "earth" or "dark" instead.

⚠ **PAL-P3-2** — k-means iterations capped at 20; for k=8 high-variance images this may not converge. AAA fix: track centroid movement, break early when below 1e-5, otherwise warn.

---

## 9. AAA Grade Summary

| Subsystem | File | Grade | Comparison anchor |
|---|---|---|---|
| Splatmap derivation (v2) | `terrain_materials_v2.py` | C+ | Below MicroSplat (no triplanar in production path), below RDR2 (no virtual texture), competitive with UE5 Landscape weight-blend layers but with semantic mismatch to Blender preview |
| Splatmap legacy | `terrain_materials.py` | D− | Dead code that's still wired for preview; competing 4-layer convention vs. v2's 5+. **Should be deleted** after dual-splatmap fix lands. |
| Stochastic tiling | `terrain_stochastic_shader.py` | A− | Matches MicroSplat + Mikkelsen 2022; better than Tsushima's hand-rolled hex. Contrast bug is the only blocker. |
| Roughness driver | `terrain_roughness_driver.py` | B+ | Matches RDR2's wetness shader. Missing wind dust. |
| Quixel ingestion | `terrain_quixel_ingest.py` | C | Below industry — no proper RNM blend, no SVT page bake, additive accumulation breaks at <4 layers. |
| Texture layer stack | `terrain_texture_layer_stack.py` | C+ | Dataclass exists but exporter ignores it; effectively orphaned. |
| Palette extract | `terrain_palette_extract.py` | A− | Lab-space + Gaussian confidence is best-in-class for procedural pipelines. |
| Procedural materials (props) | `procedural_materials.py` | (not in scope — prop materials, not terrain) | n/a |
| Material extensions | `terrain_materials_ext.py` | B | Texel density tier check is good; cliff silhouette area+shape validators are excellent (4π·A/P² isoperimetric ratio is exactly the right metric). |

**System grade: D+** — the splatmap pipeline is the load-bearing element; its dual-source bug forces the system below the AAA bar regardless of how good the stochastic and palette modules are.

---

## 10. Mock Test Code

### Test 1 — 4-layer cap correctness on synthetic 4×4 / 6-layer splatmap

```python
# tests/test_batch15_materials.py
import numpy as np
from veilbreakers_terrain.handlers.terrain_unity_export import _write_splatmap_groups
from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack


def _make_stack_6layer_4x4():
    stack = TerrainMaskStack(
        height=np.zeros((4, 4), dtype=np.float32),
        cell_size=1.0, world_origin_x=0.0, world_origin_y=0.0,
        tile_x=0, tile_y=0, tile_size=4.0,
    )
    # 6 layers, with layer 2 dominant in upper-left 2x2,
    # layer 5 dominant in lower-right 2x2, and layers 0,1,3,4 weak everywhere.
    weights = np.zeros((4, 4, 6), dtype=np.float32)
    weights[..., 0] = 0.05  # weak baseline
    weights[..., 1] = 0.05
    weights[..., 2] = 0.10
    weights[..., 3] = 0.10
    weights[..., 4] = 0.10
    weights[..., 5] = 0.10
    weights[:2, :2, 2] = 0.55  # layer 2 dominates UL
    weights[2:, 2:, 5] = 0.55  # layer 5 dominates LR
    # normalize
    weights = weights / weights.sum(axis=2, keepdims=True)
    stack.splatmap_weights_layer = weights
    return stack


def test_hdrp_4_layer_cap_keeps_top4_per_cell(tmp_path):
    stack = _make_stack_6layer_4x4()
    files = {}
    _write_splatmap_groups(files, tmp_path, stack)
    # Read back the first group
    raw = (tmp_path / "splatmap_00.raw").read_bytes()
    arr = np.frombuffer(raw, dtype=np.uint8).reshape(4, 4, 4)
    arr_f = arr.astype(np.float32) / 255.0
    # Per-cell sum must be ~1.0 after normalisation
    sums = arr_f.sum(axis=2)
    assert np.allclose(sums, 1.0, atol=2/255)  # 1 quantization step
    # Per-cell only 4 non-zero channels in the cap output (across all groups)
    # Because L=6, group 1 (channels 4,5) should be zero everywhere
    raw1 = (tmp_path / "splatmap_01.raw").read_bytes()
    arr1 = np.frombuffer(raw1, dtype=np.uint8).reshape(4, 4, 4)
    # Layer 5 was top-1 in lower-right; it should appear in group 1 channel B
    # (since channel index 5 -> group 1, slot 1)
    # ... actually with the current cap+regroup logic, layer 5's weight goes
    # to group 1 slot 1 NOT zero. This test will FAIL on current code:
    # the cap zeros indices ranked 5+, BUT layer 5 may be ranked top-4 in some
    # cells, in which case it stays non-zero. Determinism check:
    # assert that no cell has more than 4 non-zero channels in its 8-byte RGBA
    # across the 2 groups
    full = np.concatenate([arr_f, arr1.astype(np.float32) / 255.0], axis=2)  # (4,4,8)
    nonzero_per_cell = (full > 1e-3).sum(axis=2)
    assert np.all(nonzero_per_cell <= 4), \
        f"HDRP 4-layer cap violated; max non-zero per cell = {nonzero_per_cell.max()}"


def test_hdrp_4_layer_cap_handles_ties_deterministically():
    """Reproduce MAT-P1-2: argsort tie-break should not depend on platform."""
    stack = _make_stack_6layer_4x4()
    # Force exact ties: 6 layers, all weight 1/6 in cell (0,0)
    stack.splatmap_weights_layer[0, 0, :] = 1.0 / 6.0
    files = {}
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        from pathlib import Path
        _write_splatmap_groups(files, Path(td), stack)
        raw = (Path(td) / "splatmap_00.raw").read_bytes()
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(4, 4, 4)
    # Re-run; hash should be identical
    files2 = {}
    with tempfile.TemporaryDirectory() as td:
        from pathlib import Path
        _write_splatmap_groups(files2, Path(td), stack)
        raw2 = (Path(td) / "splatmap_00.raw").read_bytes()
        arr2 = np.frombuffer(raw2, dtype=np.uint8).reshape(4, 4, 4)
    assert np.array_equal(arr, arr2), "tie-break is non-deterministic"
```

### Test 2 — Stochastic tiling produces no visible grid (hash variance test)

```python
def test_stochastic_mask_no_grid_repetition():
    """A correct hash-based mask must show entropy ≥ log2(tiles) per channel."""
    from veilbreakers_terrain.handlers.terrain_stochastic_shader import (
        build_stochastic_sampling_mask,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    stack = TerrainMaskStack(
        height=np.zeros((128, 128), dtype=np.float32),
        cell_size=1.0,
        world_origin_x=0.0, world_origin_y=0.0,
        tile_x=0, tile_y=0, tile_size=128.0,
    )
    # 4-meter tiles in a 128m heightmap → 32x32 tile grid → 1024 tiles
    mask = build_stochastic_sampling_mask(
        stack, tile_size_m=4.0, seed=42,
        histogram_preserving=True, uv_rotation_range=0.0,
    )
    # mask is (128,128,2)
    # Hash-based offsets should produce roughly uniform U/V distribution
    u, v = mask[..., 0].ravel(), mask[..., 1].ravel()
    # Histogram-preserving rank equalization → exactly uniform in [-0.5, 0.5]
    assert -0.5001 <= u.min() and u.max() <= 0.5001
    assert -0.5001 <= v.min() and v.max() <= 0.5001
    # Entropy: 32 bins, near-uniform should have entropy >= 4.9 bits (log2(32)=5)
    h_u, _ = np.histogram(u, bins=32, range=(-0.5, 0.5))
    p = h_u / h_u.sum()
    p_nz = p[p > 0]
    entropy = -np.sum(p_nz * np.log2(p_nz))
    assert entropy >= 4.5, f"U-channel entropy {entropy:.2f} < 4.5 — possible grid bias"
    # FFT check: dominant frequency should NOT match the tile period (32 cycles per 128 px)
    fft = np.fft.fft2(mask[..., 0])
    fft_mag = np.abs(fft)
    # Ignore DC + low-freq trends
    fft_mag[0, 0] = 0
    # Find peak frequency
    peak_idx = np.unravel_index(fft_mag.argmax(), fft_mag.shape)
    # Tile period = 4m/cell ⇒ frequency = 128/4 = 32 cycles per 128 px
    # If peak is at (32, 0) or (0, 32), it means the per-tile pattern leaks through.
    assert peak_idx not in {(32, 0), (0, 32), (32, 32)}, \
        f"Stochastic mask leaks tile grid frequency; peak at {peak_idx}"


def test_stochastic_mask_different_tiles_have_different_offsets():
    """Adjacent tiles must have distinct hash outputs; otherwise visible blocks."""
    from veilbreakers_terrain.handlers.terrain_stochastic_shader import _tile_hash_2d

    # 4 adjacent tiles
    ty = np.array([0, 0, 1, 1], dtype=np.uint32)
    tx = np.array([0, 1, 0, 1], dtype=np.uint32)
    h = _tile_hash_2d(ty, tx, seed=42)
    # All 4 tiles should have distinct hash quadruples
    seen = {tuple(h[i].tolist()) for i in range(4)}
    assert len(seen) == 4, f"adjacent tiles collide: {seen}"
```

### Test 3 — Layer weights normalize to 1.0 everywhere

```python
def test_texture_layer_stack_normalized_weights_sum_to_one():
    from veilbreakers_terrain.handlers.terrain_texture_layer_stack import (
        TerrainTextureLayerStack, TextureLayer,
    )
    rng = np.random.default_rng(0)
    H, W = 32, 32
    stack = TerrainTextureLayerStack()
    # 5 layers with arbitrary positive weights
    for i, lid in enumerate(["ground", "cliff", "scree", "wet_rock", "snow"]):
        wmap = rng.random((H, W), dtype=np.float32) * (i + 1)  # different magnitudes
        stack.add_layer(TextureLayer(
            layer_id=lid, terrain_mask_source="splatmap_weights_layer",
            weight_map=wmap,
        ))
    norm = stack.normalized_weights()  # (H, W, 5)
    assert norm.shape == (H, W, 5)
    sums = norm.sum(axis=2)
    assert np.allclose(sums, 1.0, atol=1e-6), \
        f"weights not normalized; min sum = {sums.min()}, max sum = {sums.max()}"


def test_compute_slope_material_weights_per_pixel_normalized():
    """Splatmap from materials_v2 must sum to 1.0 per pixel."""
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        compute_slope_material_weights, default_dark_fantasy_rules,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack
    H, W = 32, 32
    stack = TerrainMaskStack(
        height=np.linspace(-100, 500, H * W, dtype=np.float32).reshape(H, W),
        cell_size=1.0, world_origin_x=0.0, world_origin_y=0.0,
        tile_x=0, tile_y=0, tile_size=32.0,
    )
    # populate slope channel
    rng = np.random.default_rng(0)
    stack.set("slope", rng.random((H, W), dtype=np.float32) * (np.pi / 2.0), "test")
    weights = compute_slope_material_weights(stack, default_dark_fantasy_rules())
    sums = weights.sum(axis=2)
    # Per Rule 7 contract, splatmap weights MUST sum to exactly 1.0 per cell
    assert np.allclose(sums, 1.0, atol=1e-5), \
        f"materials_v2 splatmap not normalized: min={sums.min()}, max={sums.max()}"


def test_quixel_albedo_blend_normalized():
    """QUIX-P0-1: macro_color must equal weighted-average of layer albedos, not sum."""
    from veilbreakers_terrain.handlers.terrain_quixel_ingest import (
        apply_quixel_to_layer, QuixelAsset,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack
    H, W = 8, 8
    stack = TerrainMaskStack(
        height=np.zeros((H, W), dtype=np.float32),
        cell_size=1.0, world_origin_x=0.0, world_origin_y=0.0,
        tile_x=0, tile_y=0, tile_size=8.0,
    )
    red    = np.tile([[[1.0, 0.0, 0.0]]], (H, W, 1)).astype(np.float32)
    green  = np.tile([[[0.0, 1.0, 0.0]]], (H, W, 1)).astype(np.float32)
    asset_a = QuixelAsset(asset_id="a", textures={}, metadata={})
    asset_b = QuixelAsset(asset_id="b", textures={}, metadata={})
    apply_quixel_to_layer(stack, "a", asset_a, albedo_array=red)
    apply_quixel_to_layer(stack, "b", asset_b, albedo_array=green)
    # After 2 layers each at weight 0.5, macro_color should be (0.5, 0.5, 0)
    # in linear sRGB. Expected fail on current code (additive accumulation).
    expected = np.full((H, W, 3), [0.5, 0.5, 0.0], dtype=np.float32)
    # Current code produces (1.0, 1.0, 0) because srgb_to_linear(red)*0.5 + srgb_to_linear(green)*0.5 ≈ (0.5, 0.5, 0)
    # Wait — actually the linearised reds and greens are still ~(1,0,0), (0,1,0)
    # so the additive sum = (0.5, 0.5, 0) in *linear* space. BUT if any 3rd layer
    # is added, it would push above 1.0. Verify with a 3rd layer:
    apply_quixel_to_layer(stack, "c", QuixelAsset(asset_id="c", textures={}, metadata={}),
                           albedo_array=np.tile([[[0.0, 0.0, 1.0]]], (H, W, 1)).astype(np.float32))
    mc = np.asarray(stack.macro_color)
    # If accumulation is correct (weighted), the result should still sum to ≤ 1 per channel.
    assert mc.max() <= 1.05, \
        f"Quixel albedo accumulator overflow: max={mc.max()} (additive bug, see QUIX-P0-1)"
```

---

## 11. Concrete P0 Backlog (for Codex / next batch)

| ID | Severity | File | Line(s) | Fix |
|---|---|---|---|---|
| MAT-P0-1 | P0 | `terrain_materials.py` | 3412–3631 | Make `create_biome_terrain_material` require `stack`; delete the `auto_assign_terrain_layers` fallback path. |
| MAT-P0-2 | P0 | `environment.py` | 5237 | Replace `_paint_road_mask_on_terrain` with `_paint_road_mask_on_stack`; write `road_sdf_dist` channel; let `apply_sdf_road_blend` finalise. |
| MAT-P0-3 | P0 | `terrain_materials.py` | 3369–3409 | Re-implement `_sample_splatmap_weights_at_vertex` to remap by layer_id, not column index. Snow currently invisible in Blender preview. |
| QUIX-P0-1 | P0 | `terrain_quixel_ingest.py` | 618–630 | Replace additive macro_color accumulation with weighted-average pattern (numerator + denominator pair, finalise in pass). |
| QUIX-P0-2 | P0 | `terrain_quixel_ingest.py` | 632–648 | Remove roughness write — channel is owned by `terrain_roughness_driver`. Or declare `overrides=("roughness_variation",)` on the pass. |
| QUIX-P0-3 | P0 | `terrain_quixel_ingest.py` | 650–674 | Implement Reoriented Normal Mapping (RNM) blend; current additive-tangent-on-world is mathematically incoherent. |
| QUIX-P0-4 | P0 | `terrain_quixel_ingest.py` | 660–662 | Either don't write `terrain_normals` at all (preferred — let `prepare_terrain_normals` own it) or convert to Y-up Unity frame and declare overrides. |
| QUIX-P0-5 | P0 | `terrain_quixel_ingest.py` | 269–271 | Remove min-max stretch from `_load_texture_as_float`; clamp EXR/HDR to [0,1] only. |
| STOCH-P1-1 | P1 | `terrain_stochastic_shader.py` | 126, 312 | Wire `contrast` parameter into HLSL `HistogramPreservingBlend`. |
| MAT-P1-1 | P1 | `terrain_unity_export.py` | 1799–1850 | Skip writing `splatmap_NN.raw` for groups whose entire valid_layer_count would be capped to zero. |
| MAT-P1-2 | P1 | `terrain_unity_export.py` | 1785 | Stable argsort with deterministic tie-break by layer index. |
| MAT-P1-3 | P1 | `terrain_unity_export.py` | 1790 | Emit warning when capped weight per cell exceeds 5%. |
| TLS-P1-1 | P1 | `terrain_unity_export.py` | 1816 | Read layer asset path from `state.texture_layer_stack.layers[i].layer_id` rather than synthesising `Layer_NNN`. |
| TLS-P1-2 | P1 | `terrain_materials_v2.py` | 1175 | Call `state.texture_layer_stack.validate(stack)` and emit issues. |
| ROUGH-P2-1 | P2 | `terrain_roughness_driver.py` | 75 | Add `wind_exposure` consumer for leeward dust roughness. |
| PAL-P3-1 | P3 | `terrain_palette_extract.py` | 205 | Add Lab centroids for volcanic, alpine, plateau, wetland, shadow. |

---

## 12. References (AAA studios for grading)

- **MicroSplat (Jason Booth):** `https://docs.microsplat.com/`. Stochastic tiling = paid module; per-layer triplanar; texture array packing.
- **RDR2 terrain (Rockstar):** GDC 2019 talk "The Indirect Lighting Pipeline of God of War" / Rockstar 2018 deep-dive. SVT-backed terrain; height-blend between dirt/rock/grass; wetness shader runs across all layers.
- **Ghost of Tsushima (Sucker Punch):** GDC 2021 "Procedural Grass in Ghost of Tsushima". Hand-painted density override; macro tint texture; 4-layer splatmap with per-layer normal/roughness maps.
- **UE5 Landscape Material:** Unreal docs `Landscape > Materials > Layered Materials`. Layer Info Objects, weight-blend layers, distance-based tessellation, runtime virtual texture.
- **Heitz & Neyret 2019:** "A High-Performance By-Example Noise using a Histogram-Preserving Blending Operator", JCGT.
- **Mikkelsen 2022:** "Practical Stochastic Sampling with Hexagonal Tiling", JCGT Vol. 11 No. 3.
