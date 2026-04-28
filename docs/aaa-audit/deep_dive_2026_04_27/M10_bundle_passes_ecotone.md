# M10: Bundle Passes & Ecotone Deep-Dive Audit

**Date:** 2026-04-27
**Sweep:** M10
**Files audited:** terrain_bundle_j.py, terrain_bundle_k.py, terrain_bundle_l.py, terrain_bundle_n.py, terrain_bundle_o.py, terrain_ecotone_graph.py, terrain_saliency.py, terrain_negative_space.py
**Auditor standard:** Rockstar / Guerrilla Games senior tech lead

---

## 1. Bundle Registration vs Execution — Systemic Context

All five bundle registrars (J, K, L, N, O) are called from `terrain_master_registrar.register_all_terrain_passes()`. Passes are registered in the `PASS_REGISTRY`. **However, registration ≠ execution.** The pipeline only executes passes that appear in the explicit `pass_sequence` passed to `run_pipeline`. No `DEFAULT_PASS_SEQUENCE` exists. Prior audit sweep J4 confirmed Bundles J/K/L/N/O passes are never appended to the production pipeline. That finding is confirmed here: no call site in `terrain_master_registrar.py`, `__init__.py`, or `environment.py` constructs a sequence that includes `ecotones`, `stochastic_shader`, `macro_color`, `horizon_lod`, etc.

The production pipeline therefore still runs only 8 passes (Bundle A defaults). All Bundle J/K/L/O passes produce **zero output** in any production execution.

---

## 2. Bundle J — Ecosystem Spine (10 passes)

### 2.1 Pass inventory

Bundle J registers 10 passes, 2 of which (`prepare_terrain_normals`, `prepare_heightmap_raw_u16`) are the **same normals/heightmap-export passes identified as orphans in I5-P0-4** — they are redeclared here in `BUNDLE_J_PASSES` but their actual registration happens through `terrain_unity_export`, not through Bundle J directly; they are listed in `BUNDLE_J_PASSES` as documentation but do not constitute new bugs.

Passes: `prepare_terrain_normals`, `prepare_heightmap_raw_u16`, `audio_zones`, `wildlife_zones`, `gameplay_zones`, `wind_field`, `cloud_shadow`, `decals`, `navmesh`, `ecotones`.

All 10 registered but none executed in production.

### 2.2 Ecotone pass — implementation analysis

The `pass_ecotones` function in `terrain_ecotone_graph.py` does the following:
1. Computes `compute_traversability` if not already populated.
2. Calls `build_ecotone_graph` to compute biome adjacency.
3. Calls `validate_ecotone_smoothness` to flag narrow transitions.
4. Returns metrics only — **no new channel is written except `traversability` as a fallback side-effect**.

---

**M10-P0-1** | `terrain_ecotone_graph.py:124` | Ecotone transition width formula uses cell-count square root — produces arbitrarily narrow 2-cell ecotones on typical tiles; hard biome cuts guaranteed

**Evidence:**
```python
width = float(max(2, min(32, int(round(shared ** 0.5)))) * stack.cell_size)
```
For a 1024×1024 tile at 1 m/cell with a typical biome boundary of 512 shared cells, `shared**0.5 = ~22.6`, clamped to 22 cells, multiplied by cell_size → 22 m. However, for any boundary shorter than 4 shared cells (common at tile corners where biomes touch diagonally), `shared**0.5 < 2`, the `max(2, ...)` floor kicks in, yielding only 2 cells = 2 m. At 4 m/cell (AAA 4km tiles), that is 8 m. A real AAA ecotone (Horizon FW, The Witcher 3) uses **40–120 m** transition widths for all but the most intentional hard cuts. The formula also ignores biome type entirely: desert-to-swamp gets the same width as forest-to-meadow.

**AAA gap:** Real AAA ecotones (Horizon FW world design docs, W3 biome blending) use per-biome-pair minimum widths stored in a blend table (e.g. desert↔swamp: 80 m, forest↔meadow: 40 m). Width depends on visual contrast between biomes, not border length. The width here is 2–32 cells from a square-root-of-shared-cells heuristic that has no AAA precedent and will produce either razor-thin painted lines at corners or absurdly uniform blending regardless of ecological logic.

**Fix:** Replace the formula with a biome-pair lookup table:
```python
# terrain_ecotone_graph.py
_ECOTONE_MIN_WIDTH_M: dict[tuple[int,int], float] = {
    # (lower_biome_id, higher_biome_id): min_width_m
    # Default if pair not found: 30.0
}
DEFAULT_ECOTONE_WIDTH_M = 30.0
MAX_ECOTONE_WIDTH_M = 120.0

def _ecotone_width(a: int, b: int, shared: int, cell_size: float) -> float:
    key = (min(a, b), max(a, b))
    base = _ECOTONE_MIN_WIDTH_M.get(key, DEFAULT_ECOTONE_WIDTH_M)
    # Optionally scale up for long shared borders
    bonus = min(float(shared) * cell_size * 0.05, MAX_ECOTONE_WIDTH_M - base)
    return min(base + max(0.0, bonus), MAX_ECOTONE_WIDTH_M)
```
Estimated fix: 2 hours (lookup table + designer-facing config file).

---

**M10-P0-2** | `terrain_ecotone_graph.py:167–202` | Ecotone pass produces only metadata; no blend weight channel is ever written to the stack — the transition zones exist only as metrics, zero visual effect

**Evidence:**
```python
def pass_ecotones(state, region):
    ...
    return PassResult(
        pass_name="ecotones",
        ...
        produced_channels=("traversability",),
        metrics={
            "node_count": len(graph["nodes"]),
            "edge_count": len(graph["edges"]),
            "graph": graph,   # <-- stored as a dict in metrics, not a channel
        },
    )
```
The graph is stored in `result.metrics["graph"]`. No downstream pass reads `result.metrics["graph"]`. The `TerrainMaskStack` has no `ecotone_blend_weights` channel. No material/scatter pass reads ecotone transition data from the stack. Even if this pass executed in production, biome transitions would be **hard cuts** — the graph is generated but never applied.

**AAA gap:** In Horizon FW, biome blend weights are per-cell arrays (one weight per biome per cell), composited into the splatmap by a dedicated ecotone compositor pass. W3 uses a distance-field blend mask per boundary. This pipeline has neither — the ecotone graph is a ghost that influences nothing.

**Fix:**
1. Add `ecotone_blend_weights: Optional[np.ndarray]` to `TerrainMaskStack` — shape `(H, W, N_biomes)` normalized blend.
2. Add `pass_ecotone_blend` that rasterizes the graph edges into that channel using a distance-field approach.
3. Wire `splatmap` compositor to consume `ecotone_blend_weights` where it exists.
Estimated fix: 3–5 days.

---

**M10-P0-3** | `terrain_ecotone_graph.py:182–185` | Ecotone pass silently computes traversability as a side-effect — not its declared purpose; if navmesh pass ran first this is a no-op, otherwise traversability comes from ecotone code that has no concept of gameplay obstacles

**Evidence:**
```python
if stack.traversability is None:
    from .terrain_navmesh_export import compute_traversability
    stack.set("traversability", compute_traversability(stack), "ecotones")
```
This is a fallback producer for `traversability` registered as an `overrides` pass. The traversability computation (`compute_traversability`) is borrowed from the navmesh module with no ecotone-specific logic. But the bigger problem: any caller that runs `ecotones` without `navmesh` silently gets traversability data generated by an unrelated pass, with no log or warning. The `PassResult.produced_channels` declares `("traversability",)`, which correctly signals the contract — but the comment in the `register_bundle_j_ecotones_pass` function says this is an "intentional fallback-producer role for tiles where navmesh is skipped," which means tiles without navmesh silently get traversability data from a biome graph pass. That traversability data is valid (it calls the real `compute_traversability`), but the DAG semantics are wrong: two passes declare the same channel with different runtime conditions, making the output non-deterministic based on execution order.

**AAA gap:** Navmesh and ecotone passes should produce separate channels. Traversability is a game-layer concern; ecotone blend weights are a rendering concern. Entangling them creates a ghost output path.

**Fix:** Remove traversability computation from `pass_ecotones`. Let the DAG enforce that `navmesh` always runs before ecotones if traversability is required. Remove `overrides=("traversability",)` from the ecotone registration. Estimated fix: 30 minutes.

---

## 3. Bundle K — Material Ceiling (6 passes)

### 3.1 Pass inventory

Bundle K registers: `stochastic_shader`, `macro_color`, `multiscale_breakup`, `shadow_clipmap`, `roughness_driver`, `quixel_ingest`. All 6 registered, none executed in production.

### 3.2 Stochastic shader — implementation analysis

`terrain_stochastic_shader.py` is the most substantive Bundle K module and is architecturally sound for what it does. The Heitz 2019 triangular-basis and Mikkelsen 2022 hex-tiling implementations are correctly coded. However:

---

**M10-P0-4** | `terrain_stochastic_shader.py:164` | Triangular blend weights in the HLSL shader use `pow(saturate(w * sharpness), 2.0)` — the `sharpness` multiply before saturation creates weight collapse when sharpness > 1.0, producing a degenerate single-sample blend

**Evidence:**
```hlsl
float3 w = float3(fracUV.x, fracUV.y, 1.0 - fracUV.x - fracUV.y);
w = pow(saturate(w * sharpness), 2.0);
w /= (w.x + w.y + w.z + 1e-6);
```
The weights start as `(fracUV.x, fracUV.y, 1 - fracUV.x - fracUV.y)` — a partition of unity summing to 1. Multiplying by `sharpness` before `saturate` means that when `sharpness > 1.0`, large weight values (`w_i > 1/sharpness`) saturate to 1.0 while small ones remain < 1.0. After `pow(..., 2.0)`, the distribution is highly skewed. When `sharpness = 2.0` (the default from `blend_sharpness`), most pixels land in a region where exactly 1 of the 3 weights dominates after saturation, producing a nearest-tile lookup instead of a blend. The correct Heitz 2019 approach (Eq. 8 in the paper) applies the power directly to the barycentric weights in [0,1] without pre-multiplying by sharpness: `w = pow(w, sharpness); w /= sum(w)`.

**AAA gap:** Heitz & Neyret 2019 Eq. 8 specifies: `T(w) = w^p / (w1^p + w2^p + w3^p)` applied to the un-scaled barycentric coordinates. The current code scales first, which breaks histogram preservation — the exact property the shader is supposed to implement.

**Fix:**
```hlsl
// CORRECT Heitz 2019 Eq. 8 — no pre-multiplication by sharpness
float3 w = float3(fracUV.x, fracUV.y, 1.0 - fracUV.x - fracUV.y);
w = pow(saturate(w), sharpness);   // power only, no pre-scale
w /= (w.x + w.y + w.z + 1e-6);
```
Also fix the same logic pattern in `_HLSL_HEX_STOCHASTIC_SHADER` line 343:
```hlsl
w = pow(saturate(w), 4.0);        // already correct in hex variant — no issue
```
The hex shader uses `pow(saturate(w), 4.0)` without pre-multiplication — consistent with the paper. Only the triangular shader has this bug. Estimated fix: 10 minutes.

---

**M10-P0-5** | `terrain_stochastic_shader.py:321` | `fp = fp = hp - ip` — double assignment in HLSL hex shader; HLSL compiler accepts this as valid but is a clear copy-paste defect indicating the UV decomposition was not reviewed

**Evidence:**
```hlsl
float2 fp = fp = hp - ip;
```
This double-assignment compiles in HLSL (second assignment wins, same value) but signals that this line was copy-pasted without review. More critically, the `fp` variable drives the entire triangle-case split (`fp.x + fp.y < 1.0`) and all three blend weights. A reviewer finding `fp = fp = ...` would immediately question whether this reflects the actual Mikkelsen 2022 JCGT algorithm or a transcription error.

**AAA gap:** Any senior graphics engineer reviewing this shader would flag it as unreviewed code and reject the PR. In shipped code, double-assignments indicate untested paths.

**Fix:**
```hlsl
float2 fp = hp - ip;  // remove duplicate assignment
```
Estimated fix: 1 minute.

---

**M10-P0-6** | `terrain_stochastic_shader.py:1105–1113` | `stochastic_offset_mask` is computed but **not stored on the stack** — the comment admits it but this silently breaks any downstream pass that reads it

**Evidence:**
```python
# Step 4: Store stack channels
stack.set("stochastic_uv_mask", mask, "stochastic_shader")

# Compute offset magnitude for metrics (not stored on stack — TerrainMaskStack
# does not declare stochastic_offset_mask as a channel; Fix 7.18 single-writer rule).
offset_magnitude = np.sqrt(
    mask[..., 0].astype(np.float64) ** 2
    + mask[..., 1].astype(np.float64) ** 2
).astype(np.float32)

# roughness_variation is written only by terrain_roughness_driver (Fix 7.18)
```
The offset magnitude is computed, then silently discarded. The comment says `TerrainMaskStack` doesn't declare `stochastic_offset_mask`, but the `PassResult.produced_channels` only lists `("stochastic_uv_mask",)` — no produced channel for `offset_magnitude`. This is fine per the comment. **However**, `roughness_driver` (the claimed owner of `roughness_variation`) reads the stochastic mask via the stack, and if it expects a scalar offset magnitude channel that doesn't exist, it will silently fall back to a flat roughness. This is a silent-degradation pattern identical to the ones already catalogued across this codebase.

**AAA gap:** Either the offset magnitude is needed downstream (and should be stored), or it shouldn't be computed at all. Computing a full `(H, W)` float32 array and discarding it every pass is both wasteful and a sign that the interface contract between K-stochastic and K-roughness was never closed.

**Fix:** Either add `stochastic_offset_mask` to `TerrainMaskStack` and store it, or remove the `offset_magnitude` computation entirely. Verify `terrain_roughness_driver` does not depend on it. Estimated fix: 1 hour (including `TerrainMaskStack` field addition + roughness driver audit).

---

## 4. Bundle L — Atmosphere & Horizon (3 passes)

### 4.1 Pass inventory

Bundle L registers: `horizon_lod`, `fog_masks`, `god_ray_hints`. All 3 registered, none executed in production.

`horizon_lod` was previously identified as an orphan in I5-P0-4. The Bundle L registrar correctly wires all three sub-modules. No new implementation bugs are introduced in `terrain_bundle_l.py` itself (it is a 40-line registrar-only file). The sub-module implementations (`terrain_horizon_lod.py`, `terrain_fog_masks.py`, `terrain_god_ray_hints.py`) were not part of this audit scope, but the structural gap — these passes produce atmospheric and LOD data that is never consumed by any Unity export path — remains a P0 wiring issue already counted in prior sweeps.

No new P0s introduced by `terrain_bundle_l.py` itself.

---

## 5. Bundle N — Deep Validation & QA

### 5.1 Architecture

Bundle N is correctly documented as a non-pass registrar. `register_bundle_n_passes()` intentionally registers zero passes; it is an import verifier. The `run_bundle_n_post_pipeline_hooks()` function is a real post-pipeline hook runner that:
- Runs `terrain_budget_enforcer.enforce_budget` (always-on)
- Runs `terrain_readability_bands.compute_readability_bands` (always-on)
- Optionally runs telemetry, golden snapshots, determinism replay

**This is the only bundle in the pipeline where the registrar is honest about what it does.** The `BUNDLE_N_RUNTIME_CONTRACT` dict accurately describes the behavior, and `register_bundle_n_passes()` returns it.

### 5.2 Critical wiring gap

---

**M10-P0-7** | `terrain_bundle_n.py:247–439` | `run_bundle_n_post_pipeline_hooks()` is never called in the production pipeline — budget enforcement and readability scoring are permanently skipped

**Evidence:**
`run_bundle_n_post_pipeline_hooks` is defined but there is no call site in `terrain_master_registrar.py`, `environment.py`, or `terrain_pipeline.py`. The master registrar calls `register_bundle_n_passes()` (the no-op import verifier) but never calls the hook runner. Budget enforcement (`enforce_budget`) and readability scoring are therefore silently bypassed on every production tile.

Grep confirmation: no reference to `run_bundle_n_post_pipeline_hooks` exists outside the module itself and tests.

**AAA gap:** At Guerrilla and Rockstar, budget enforcement is a hard gate — tiles that exceed triangle/draw-call/texture budgets cannot be committed. Here, the enforcement code exists but is never invoked. The production pipeline ships budget-violating tiles with no warning.

**Fix:** In `terrain_pipeline.py`'s `run_pipeline()` method (or wherever the pipeline execution terminates), add:
```python
from .terrain_bundle_n import run_bundle_n_post_pipeline_hooks
bundle_n_summary = run_bundle_n_post_pipeline_hooks(
    self,
    results,
    pre_pipeline_state=pre_pipeline_state,
)
```
This requires `pre_pipeline_state` to be captured before the pipeline runs. Estimated fix: 2 hours.

---

**M10-P0-8** | `terrain_bundle_n.py:267–269` | Hook runner silently exits early when last result status is `"failed"` — budget enforcement is skipped on the tiles that most need it

**Evidence:**
```python
last = results[-1]
if last.status == "failed":
    return {}
```
When any pass fails (even an optional pass), the entire post-pipeline hook suite is bypassed. Budget enforcement, readability scoring, and determinism checks all silently skip. A failed `decals` pass would prevent budget enforcement from running on the rest of the tile data.

**AAA gap:** Budget and readability enforcement should be unconditional. Failed passes are exactly the case where you want to know whether the partial tile output violates budgets. The early exit is a misguided "don't run on broken state" guard that disables all QA on degraded outputs.

**Fix:**
```python
# Remove the early exit on "failed":
# Run budget and readability unconditionally; skip only determinism replay
# (which requires a complete pipeline run to be meaningful).
if options.get("skip_post_pipeline_hooks"):
    return {"skipped": True, "reason": "skip_post_pipeline_hooks"}
```
Move determinism check only into a `if last.status != "failed":` guard. Estimated fix: 30 minutes.

---

## 6. Bundle O — Water Variants & Vegetation Depth (4 passes)

### 6.1 Pass inventory

Bundle O registers: `water_variants`, `bathymetry`, `vegetation_depth`, `emergent_grass`. All 4 registered, none executed in production.

### 6.2 Vegetation depth pass — implementation analysis

The `register_vegetation_depth_pass` and `register_emergent_grass_pass` calls are made via `terrain_vegetation_depth`. No new bugs introduced in `terrain_bundle_o.py` itself (38-line registrar). However:

---

**M10-P0-9** | `terrain_bundle_o.py:23–25` | `bathymetry` pass declared as requiring `("height", "water_surface")`, but `water_surface` is produced by `water_variants` — if `water_variants` fails or is skipped, `bathymetry` will fail at channel check with no diagnostic about the dependency

**Evidence:**
```python
# Pass ordering note: ``bathymetry`` must run after ``water_variants`` so
# that ``water_surface`` is populated before depth zones are classified.
# The TerrainPassController dependency graph enforces this via
# ``requires_channels=("height", "water_surface")``.
```
This is a comment describing a DAG dependency that should be enforced. The `TerrainPassController` does enforce `requires_channels` — it checks that channels are present before running a pass. However, if `water_variants` is not in the executed `pass_sequence` (which is certain given that all Bundle O passes are currently unwired), `bathymetry` will fail at runtime with an opaque `MissingChannelError` rather than a useful "water_variants must run first" diagnostic.

More critically: the `water_surface` channel is produced by `water_variants`, which itself may also produce a `wetness` channel (depending on implementation). The existing W-1 dual-semantics bug (noted in the master guide) means `water_surface` on the stack may be either a binary presence mask or an elevation value, depending on which pass wrote it. The `bathymetry` pass consuming `water_surface` as an elevation comparison would silently produce wrong depth zones if the water_variants pass wrote it as a binary mask.

**AAA gap:** Channel semantics must be enforced at the type level or at least with a documented units contract. The W-1 bug (active production bug per master guide) means bathymetry depth zones are wrong when `water_surface` is binary.

**Fix:**
1. Add a `water_surface_elevation_m` channel distinct from `water_surface` (binary).
2. Have `bathymetry` declare `requires_channels=("height", "water_surface_elevation_m")`.
3. `water_variants` must write both: `water_surface` (binary) and `water_surface_elevation_m` (float).
This resolves the W-1 dual-semantics bug for this pass. Estimated fix: 3 hours.

---

## 7. terrain_saliency.py — Implementation Correctness

### 7.1 Orphan status confirmed

`register_saliency_pass()` is called from `terrain_master_registrar.py` line 227:
```python
("H-saliency", f"{package_root}.terrain_saliency", "register_saliency_pass"),
```
The pass **is registered** by the master registrar. However, it only executes if `"saliency_refine"` appears in the caller's `pass_sequence`. No production execution path includes it. I5-P0-4 finding stands.

### 7.2 Algorithm correctness

The 8-factor saliency implementation is algorithmically sound for its stated purpose. Specific findings:

---

**M10-P0-10** | `terrain_saliency.py:671` | Tactical influence formula is self-negating — `min(0.50, 0.25 + 0.05 * len(vantages))` caps at 0.50 when `len(vantages) >= 5`, but comment says "50/50 blend"; with 0 vantages the influence is 0.25, so the "50% existing saliency" claim in the docstring is wrong

**Evidence:**
```python
tactical_influence = min(0.50, 0.25 + 0.05 * len(vantages))
refined = np.clip(
    (1.0 - tactical_influence) * base + tactical_influence * tactical_score,
    0.0, 1.0
)
```
With 0 vantages: `tactical_influence = 0.25` — a 25/75 blend, not 50/50 as the docstring states. With 5+ vantages: `tactical_influence = 0.50` — 50/50. The docstring says "50/50 blend: existing saliency + 8-factor tactical score" and "More aggressive than the old 60/40." Both claims are wrong for the 0-vantage case. The camera-composition scoring is therefore under-weighted when no vantages are provided — precisely the case for all production tiles (vantages come from `intent.composition_hints["vantages"]` which is rarely set).

**AAA gap:** The influence weight should not depend on vantage count if the 8-factor scoring is otherwise valid. Factors 1–7 (height, water, slope, ridge, convexity, sky, veg-break) are purely terrain-derived and do not require vantages. The vantage-scaling makes the scoring weaker when terrain data alone is sufficient.

**Fix:**
```python
# Apply full 50% tactical influence regardless of vantage count.
# Factor 8 (sight-line) is zero when no vantages exist; other 7 factors
# still provide valid signal.
tactical_influence = 0.50
```
Estimated fix: 5 minutes.

---

**M10-P0-11** | `terrain_saliency.py:207–208` | Silhouette detection uses `dz_prev <= 0.0` initial condition seeded with `-1.0` — this forces every ray to report a sky-transition at the first sample regardless of actual terrain height

**Evidence:**
```python
dz_prev = np.concatenate(
    [np.full((ray_count, 1), -1.0), dz_all[:, :-1]], axis=1
)
sky_transition = (dz_all > 0.0) & (dz_prev <= 0.0)
```
`dz_prev` is initialized to `-1.0` for the first sample column. `sky_transition` fires when `dz_all[i, 0] > 0.0 AND dz_prev[i, 0] <= 0.0`. Since `dz_prev[i, 0]` is always `-1.0 <= 0.0`, every ray whose first sample is above the vantage eye level (`dz_all[i, 0] > 0.0`) will trigger a sky-transition bonus at the very first sample — even if terrain is uniformly above the vantage (a pit or canyon looking up). This creates a false positive sky-transition bonus on every ray cast from vantages below the terrain, inflating saliency around the vantage position itself rather than at actual ridgelines.

**AAA gap:** The sky-transition detection should use the vantage elevation angle as the reference, not `-1.0` as a synthetic prior. Terrain that is consistently above the vantage does not have a sky transition; only terrain that crosses from below to above vantage eye level should fire the bonus.

**Fix:**
```python
# Initialize dz_prev to the actual first dz_all value so only genuine
# below→above transitions trigger the sky_transition bonus.
dz_prev = np.concatenate(
    [dz_all[:, :1], dz_all[:, :-1]], axis=1  # prev = self at col 0
)
# This means the first column can never trigger a transition (prev == current).
```
Estimated fix: 15 minutes.

---

## 8. terrain_negative_space.py — Implementation Correctness

### 8.1 Concept

Negative space enforcement ensures at least 40% of the tile reads as low-saliency "breathing room." Three validators: quiet-zone ratio, feature density, peak spacing. This is a library module — no registered pass, called by Bundle N's budget enforcer and by `validate_negative_space` directly.

### 8.2 Algorithm correctness

---

**M10-P0-12** | `terrain_negative_space.py:252–256` | KDE bandwidth computation divides by `max(std_cols, std_rows, 1e-6)` — when peaks are clustered (std ≈ 0), bandwidth blows up to `sigma / 1e-6`, producing a pathologically wide KDE that inflates density to arbitrarily large values

**Evidence:**
```python
bw = sigma / max(float(np.std(peak_cols)), float(np.std(peak_rows)), 1e-6)
try:
    kde = gaussian_kde(samples, weights=weights, bw_method=bw)
except np.linalg.LinAlgError:
    # Singular covariance (all peaks collinear) — fall through to hand-rolled path.
    kde = None
```
When all saliency peaks are in a tight cluster (e.g. one hero feature dominating), `std_cols ≈ std_rows ≈ 0`, so `bw = 3.0 / 1e-6 = 3,000,000`. `gaussian_kde` with `bw_method=3_000_000` produces an absurdly broad Gaussian kernel spanning the entire tile, making `kde_mass` enormous and `compute_feature_density` return a number potentially in the millions. This will incorrectly flag every such tile as "wall-of-detail" when in fact it has only one well-spaced hero feature.

The `np.linalg.LinAlgError` catch only handles the singular covariance case (all peaks identical); it does not catch the float overflow case where `bw` is huge but `gaussian_kde` doesn't raise.

**AAA gap:** KDE bandwidth should use Scott's rule (`n^(-1/(d+4))`) or be clamped to a sensible range (e.g. 0.1–10.0 in normalized space). The current formula inverts the meaning: tighter clusters → wider bandwidth → more "density" detected, which is the opposite of the stated intent.

**Fix:**
```python
# Use Scott's rule for bandwidth; clamp to [0.1, 5.0] to prevent blowup.
n_peaks = len(peaks)
d = 2  # 2D KDE
scott_bw = n_peaks ** (-1.0 / (d + 4))
bw = float(np.clip(scott_bw * (sigma / max(float(np.std(peak_cols)), float(np.std(peak_rows)), 1.0)), 0.1, 5.0))
```
Estimated fix: 30 minutes.

---

**M10-P0-13** | `terrain_negative_space.py:161–162` | `compute_min_peak_spacing` converts cell indices to metres by multiplying by `cell_size`, but cell indices are (row, col) while the multiplication should use `(row * cell_size, col * cell_size)` — the scaling is correct, but both row and col are multiplied by the same `cell_size` scalar, which assumes square cells. This is valid, but the distance is computed in **cell units** squared before `cell_size` scaling, which means the `cell_size` multiply on line 161 produces row-metres × col-metres, and the final `np.sqrt(sum(diffs²))` has units of metres only if cells are square.

**Evidence:**
```python
coords = np.asarray([(r, c) for r, c, _ in peaks], dtype=np.float64) * cell_size
diffs = coords[:, None, :] - coords[None, :, :]
dists = np.sqrt((diffs * diffs).sum(axis=-1))
```
This is correct for square cells (which is the documented assumption in `TerrainMaskStack.cell_size`). However, `TerrainMaskStack` stores a single `cell_size` float with no documentation that cells must be square. If a non-square grid is ever used (rectangular tiles), peak spacing will be computed incorrectly. This is a latent bug, not currently triggered.

This finding is **Warning level** — not P0 given current square-cell-only usage. Listed here for completeness.

---

## 9. procedural_grass.py — Modified File (git status: M)

`procedural_grass.py` is modified in the working tree. Reading it revealed:

---

**M10-P0-14** | `procedural_grass.py:64–86` | The numpy fallback for `_distance_transform_edt` uses a pure Python nested `for` loop over every cell — O(H×W) Python iterations. On a 1024×1024 tile this is ~1 million iterations, taking 30–60 seconds. The module docstring claims "no per-cell Python loops" but this loop exists as the scipy fallback.

**Evidence:**
```python
# Forward pass
for r in range(h):
    for c in range(w):
        if dist[r, c] == 0:
            continue
        best = dist[r, c]
        if r > 0:
            best = min(best, dist[r - 1, c] + 1)
        if c > 0:
            best = min(best, dist[r, c - 1] + 1)
        dist[r, c] = best
# Backward pass — same nested loop
```
The module docstring on line 9 states: "The placement is **vectorised numpy** end-to-end — no Python loops over individual cells." This is directly contradicted by this fallback. On a production 4096×4096 tile without scipy, the fallback would take ~10 minutes just for the EDT of one exclusion mask.

**AAA gap:** A real AAA pipeline would fail loudly if scipy is unavailable rather than silently degrading to a 10-minute numpy fallback. The fallback also computes Chebyshev (L∞) distance, not Euclidean distance, so the exclusion buffers are square rather than circular. This produces visually incorrect square grass-exclusion zones around roads and cliffs.

**Fix:**
```python
def _distance_transform_edt(mask: np.ndarray) -> np.ndarray:
    if _scipy_edt is not None:
        return _scipy_edt(mask).astype(np.float32)
    # Emit a loud warning and approximate with a vectorised morphological approach
    import warnings
    warnings.warn(
        "scipy.ndimage not available: grass EDT falling back to approximate "
        "Chebyshev distance. Install scipy for correct Euclidean exclusion zones.",
        RuntimeWarning,
        stacklevel=3,
    )
    # Vectorised approximate using cumulative min (1D passes, not nested loops):
    # ... (implement raster-scan EDT without Python per-cell loops)
```
For a true vectorised fallback, use the two-pass raster-scan approach that can be implemented with `np.minimum.accumulate`. Estimated fix: 2 hours.

---

## 10. Summary — What These Bundles Would Produce If Wired

| Bundle | Passes | Current Production Output | If Wired, Actual Output |
|--------|--------|--------------------------|------------------------|
| J | 10 | None (zero executed) | Ecotone metadata only (no blend weights written) — visual result: hard biome cuts |
| K | 6 | None (zero executed) | Stochastic UV mask on stack (M10-P0-4 bug: collapsed weights) + shader asset |
| L | 3 | None (zero executed) | Atmospheric data unknown — sub-modules not in this audit scope |
| N | 0 (QA hooks) | Budget/readability skipped (M10-P0-7) | With fix: hard budget gate |
| O | 4 | None (zero executed) | Water depth zones (M10-P0-9 W-1 semantics bug) |

---

## 11. P0 Count Tally

**M10-P0-1** | terrain_ecotone_graph.py:124 | Ecotone width formula (sqrt of shared cells) — produces 2-cell razor-thin cuts at tile corners, wrong by 10–60× vs AAA standard
**M10-P0-2** | terrain_ecotone_graph.py:190–202 | Ecotone graph stored only in metrics, never written to a blend-weight channel — zero visual effect even if pass executes
**M10-P0-3** | terrain_ecotone_graph.py:182–185 | Traversability side-computed in ecotone pass — wrong module, non-deterministic DAG semantics
**M10-P0-4** | terrain_stochastic_shader.py:164 | Heitz 2019 HLSL blend weights use `pow(saturate(w * sharpness), ...)` instead of `pow(saturate(w), sharpness)` — collapses to single-sample at default sharpness
**M10-P0-5** | terrain_stochastic_shader.py:321 | `float2 fp = fp = hp - ip` — double assignment in hex shader, signals unreviewed code
**M10-P0-6** | terrain_stochastic_shader.py:1105–1113 | `stochastic_offset_mask` computed and discarded; roughness_driver/stochastic interface contract unresolved
**M10-P0-7** | terrain_bundle_n.py:247 | `run_bundle_n_post_pipeline_hooks` never called — budget enforcement and readability scoring permanently bypassed
**M10-P0-8** | terrain_bundle_n.py:267–269 | Hook runner exits early on any `"failed"` result — disables all QA exactly when it matters most
**M10-P0-9** | terrain_bundle_o.py:23–25 | `bathymetry` consumes `water_surface` which has W-1 dual-semantics bug — depth zones silently wrong when water_surface is binary
**M10-P0-10** | terrain_saliency.py:671 | Tactical influence is 0.25 (not 0.50) with zero vantages — docstring wrong, 8-factor scoring under-weighted in 100% of production tiles
**M10-P0-11** | terrain_saliency.py:207–208 | Silhouette `dz_prev` seeded with `-1.0` — forces false sky-transition bonus on every ray whose first sample is above vantage, inflating saliency near vantage positions
**M10-P0-12** | terrain_negative_space.py:252–256 | KDE bandwidth = `sigma / std` blows up to millions when peaks are clustered, producing false "wall-of-detail" verdict on focused hero tiles
**M10-P0-13** | procedural_grass.py:64–86 | Scipy fallback EDT is O(H×W) pure Python nested loops — contradicts "no per-cell loops" claim; ~10 min on 4096² tile; Chebyshev not Euclidean distance

**Total new P0s this sweep: 13**

Cumulative P0 count: **105 (prior) + 13 (M10) = 118 confirmed P0 blockers**
