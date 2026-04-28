# F1 — AAA Implementation Substitution Audit

**Date:** 2026-04-27
**Scope:** Audit `veilbreakers_terrain/` for cases where a higher-quality, well-engineered implementation exists in one module, but production code silently routes to a different, simpler, or lower-quality duplicate.

**Pattern template (known confirmed):** `sim/foam.py` contains AAA Froude/Kelvin/shoreline foam — production handlers only import it in tests. `terrain_waterfalls.py:1636` defines a same-named `generate_foam_mask` that production actually calls.

---

## Verdict Summary

| # | Substitution | AAA module (file:line) | Substitute called in production (file:line) | Severity |
|---|--------------|------------------------|---------------------------------------------|----------|
| F1-1 | Foam mask | `sim/foam.py:158` `generate_foam_mask` | `terrain_waterfalls.py:1636` `generate_foam_mask` (delegates to `_water_network_ext.compute_foam_mask`) | **P0** (already known, baseline) |
| F1-2 | Catenary rope geometry | `sim/catenary.py:19` `solve_catenary` (cosh closed-form) | `procedural_meshes.py:17488` `generate_rope_bridge_mesh` (half-sine approx) | **P0** |
| F1-3 | Cloth/banner/flag baking | `sim/pbd_cloth.py` (XPBD Macklin 2016) | `animation_environment.py:1071/1141` analytical sinusoid, `:1218` SHM pendulum | **P0** |
| F1-4 | Stochastic histogram blend (HLSL) | CPU rank equalisation `terrain_stochastic_shader.py:705-708, 866-869` | HLSL `HistogramPreservingBlend(...) = mean + (blended - mean) * contrast` `terrain_stochastic_shader.py:126-135` | **P0** (already in MASTER GUIDE — confirmed) |
| F1-5 | Cotangent Laplacian | **MISSING** — no AAA implementation exists | `mesh_smoothing.py:52-79` uniform graph Laplacian (`w = 1.0 / len(nb)`) | **N/A — not a substitution, just absent** |
| F1-6 | A* road routing | `road_network._astar_24dir` (24-dir, world-space) | `_terrain_noise.py:1683` `_legacy_astar` (8/24 grid) — gated behind `VEILBREAKERS_ROAD_STRICT=0` only | **OK** (not substitution; opt-in fallback that emits `DeprecationWarning`) |

| # | Item checked | Result |
|---|--------------|--------|
| F1-A | `terrain_materials_v2.py` vs `terrain_materials.py` | Both are alive in production, **different scopes** (legacy: biome palettes / RGBA splatmap; v2: mask-stack splatmap_weights_layer). Not substitution — coexist. |
| F1-B | `_bridge_mesh.py` vs `_mesh_bridge.py` | **Different scopes**, no overlap. `_bridge_mesh.py` = terrain bridge geometry, `_mesh_bridge.py` = MeshSpec→Blender wiring tables. Both used in production. |
| F1-C | `terrain_legacy_bug_fixes.py` (AUDITOR_MODULE) | **NOT imported by any handler**, only by `test_bundle_bcd_supplements.py`. No production dependency on audit artifact. |

---

## F1-1 — Foam Mask (Baseline / Reference Case)

**AAA implementation:** `veilbreakers_terrain/sim/foam.py:158` `generate_foam_mask(...)`
- Five physically distinct sources: A) obstacle-proximity (EDT-based), B) shoreline depth-fade (Roystan / UE5 / Unity convention), C) Froude whitecaps (PMC9363398 hydraulic-jump regimes, ramp 1.7 → 4.5), D) vorticity / convergence from `np.gradient` of velocity field, E) Kelvin chevron wakes behind explicit rocks (sin θ = 1 / (3·Fr_rock), 19.47° subcritical). Combined 40/25/20/15 then σ=0.8 Gaussian.
- Module docstring explicitly cites Bifrost, Wikipedia/Harvard Kelvin wake, Roystan, Halisavakis, Valve SIGGRAPH 2010.
- Imported only by `tests/test_sim_modules.py` (lines 152, 161, 175, 181, 187, 193, 200).

**Production call site:** `veilbreakers_terrain/handlers/terrain_waterfalls.py:1636-1659`
- Same name `generate_foam_mask(chain, stack)`. Combines `_generate_local_waterfall_foam_mask` (terrain_waterfalls.py:1500) with `_water_network_ext.compute_foam_mask` (`_water_network_ext.py:711`) via `np.maximum`. Source 3-layer model: waterfall impact pool, rapids (acc × slope), wave-break / coastal froth. **No Froude, no Kelvin, no proper shoreline depth-fade FBM, no vorticity/convergence.**
- Called from `terrain_waterfalls.py:2293` (`wf_chain_foam = np.maximum(wf_chain_foam, generate_foam_mask(chain, _preview_stack))`) — confirms production wiring.

**Quality lost:** No supercritical-flow whitecap modulation; no V-shaped wake foam behind in-stream rocks; no stochastic FBM-thresholded shoreline edge → foam edges are just radial falloffs from a single pool centroid. Visual ceiling roughly KCD1, not KCD2/RDR2.

**Fix:** Have `terrain_waterfalls.generate_foam_mask` import from `sim.foam` (or, better, build adapter inputs — `flow_speed` grid, `water_depth` grid, `rock_mask`, `flow_dir`) and call the AAA function. Then `np.maximum` with `_generate_local_waterfall_foam_mask` only for plunge-pool supplementation. Delete the `_water_network_ext.compute_foam_mask` 3-layer model (or keep as fallback for stacks missing flow_speed).

---

## F1-2 — Catenary Rope/Chain Geometry

**AAA implementation:** `veilbreakers_terrain/sim/catenary.py:19` `solve_catenary(p0, p1, rope_length, n_points)`
- Closed-form transcendental solve via `scipy.optimize.brentq` for the catenary `a` parameter, then `v = a·cosh((u − p_shift)/a) + q_shift`. Handles vertical anchor offsets, rejects rope_length ≤ Euclidean distance, returns world-space points (n,3).
- Also exposes `arc_length_uv` for correct texture tiling and `catenary_with_sag` convenience wrapper.
- Cites Alan Zucconi, Bryson Lee UE5 GPU rope, Wikipedia.
- Imported only by `tests/test_sim_modules.py` (lines 15, 25, 34, 42, 49, 59, 70).

**Production substitute 1:** `veilbreakers_terrain/procedural_meshes.py:17488` `generate_rope_bridge_mesh(...)`
- Lines 17511-17527: `sag = -math.sin(t * math.pi) * span * sag_factor` for both planks and handrails. **Half-sine** approximation, not cosh.
- Wired into MeshSpec generator map at `procedural_meshes.py:22685` `"rope_bridge": generate_rope_bridge_mesh` — production rope-bridge prop generator.

**Production substitute 2:** `veilbreakers_terrain/handlers/animation_environment.py:1218` `generate_chain_swing_keyframes(...)`
- Comment on line 1232 advertises "catenary rest shape", but line 1255-1269 use `sag_total = 0.12` constant and `rest_angle = sag_total * frac` — a **linear ramp** of small-angle approximation, not catenary cosh.
- Same pattern in `generate_rope_sway_keyframes` (line 1290).

**Quality lost:** Half-sine and linear-ramp approximations diverge from the true catenary at moderate-to-heavy sag (>10%). For VeilBreakers iron chains and rope bridges (sag 12-25%) the visible curve flattens too aggressively at the centre and rises too steeply at the anchors — looks like a parabola, not a hung chain. KCD2/RDR2 rope bridges use true catenaries.

**Fix:** Make `generate_rope_bridge_mesh` import `from veilbreakers_terrain.sim.catenary import catenary_with_sag` and replace the `math.sin` plank/handrail loop with sampled cosh points. For animation, derive bone rest angles by sampling `solve_catenary` and converting tangent → angle per link.

---

## F1-3 — XPBD Cloth / Banner / Flag

**AAA implementation:** `veilbreakers_terrain/sim/pbd_cloth.py:147` `simulate_cloth(params, pin_mask, n_steps)` + `pbd_cloth.py:220` `bake_static_drape(...)`
- Full XPBD (Macklin 2016) with structural / shear / bend constraints, Maya nCloth-equivalent stiffness, vectorised `_project_xpbd` projection, aerodynamic wind force `F = c_wind · (n̂ · (w − v_centre)) · n̂` per face.
- Presets: `BANNER_PARAMS`, `CURTAIN_PARAMS`, `FLAG_PARAMS` with carefully tuned stiffness/mass/wind ranges.
- Imported only by `tests/test_sim_modules.py` (lines 83, 89, 103, 120, 128).

**Production substitute:** `veilbreakers_terrain/handlers/animation_environment.py:1071` `generate_flag_wind_keyframes`, `:1141` `generate_banner_wind_keyframes`
- Three-band sinusoid: `val += a_seg * rel_amp * math.sin(omega·t + phase)` summed over (1.0 Hz, 2.3 Hz, 5.7 Hz). Amplitude `eff_amp = base / (1 + C_d · v²)` (Stokes drag).
- Per-bone phase shift `i·π/n` mimics travelling wave but does **not** simulate constraint dynamics, no collision response, no proper variable wind gust.
- These are wired into `ENV_ANIM_GENERATOR_MAP` at `animation_environment.py:1971-1972` — production keyframe pipeline.

**Quality lost:** Banner/flag motion is an open-loop trigonometric oscillator, never resolves cloth collision against wind, never produces non-periodic gust ripple, never holds an authentic static drape shape (fabric draped over an object). The XPBD module *can* bake both static drape rest meshes and animation shape keys — neither is wired.

**Fix:** For static prop drape (banners hanging in dungeons, curtains in ruined fortresses) call `bake_static_drape(BANNER_PARAMS)` at asset-generation time and store the result as the rest mesh. For animation, run `simulate_cloth` once at bake time with `n_steps=60` and emit the position history as shape-key keyframes; replace the analytical sinusoid path with this baked sequence.

---

## F1-4 — Stochastic Histogram-Preserving Blend (Heitz 2019)

**AAA implementation (CPU):** `veilbreakers_terrain/handlers/terrain_stochastic_shader.py:705-708` and `:866-869`
```
rank = np.empty(n, dtype=np.float32)
order = np.argsort(chan)
rank[order] = np.linspace(-0.5, 0.5, n, dtype=np.float32)
result[..., ch] = rank.reshape(result.shape[:2])
```
- Correct rank-based equalisation per Heitz & Neyret 2018: replace each pixel value with its rank position in `[-0.5, 0.5]`, which inverts the CDF to a uniform distribution. Graded **A−** in `G4_grades.json:236`.

**Production substitute (HLSL):** `terrain_stochastic_shader.py:126-135`
```
float4 HistogramPreservingBlend(float4 c0, float4 c1, float4 c2, float3 w, float contrast)
{
    float4 blended = c0 * w.x + c1 * w.y + c2 * w.z;
    float4 mean = (c0 + c1 + c2) / 3.0;
    return mean + (blended - mean) * contrast;
}
```
- This is **contrast expansion around the mean**, not Heitz CDF inversion. The exported Unity shader does NOT receive the rank-equalised LUT computed by the CPU bake.
- Already documented as a confirmed bug in `VERIFICATION_REPORT.md:28`.

**Quality lost:** GPU-side stochastic tiling never preserves the source-texture variance — visible as luminance compression / colour smearing in the blended overlap region. CPU tests pass (rank result is correct), GPU shipped to Unity is wrong.

**Fix:** (a) Pre-compute per-channel inverse CDF as a 256×1 R8 LUT in CPU bake, (b) export `_T_inv_LUT` and `_T_LUT` textures alongside the shader template, (c) replace `HistogramPreservingBlend` in HLSL with `tex2D(_T_LUT, ...)` → triangular blend → `tex2D(_T_inv_LUT, ...)` per Heitz 2019 §3.3.

---

## F1-5 — Cotangent Laplacian (NOT a substitution — outright missing)

**Investigated:** `veilbreakers_terrain/handlers/mesh_smoothing.py:36-79`
- `_build_adjacency` builds 1-ring; `_build_laplacian` produces `L = D⁻¹A − I` with **uniform** weight `w = 1.0 / len(nb)`.
- No callers pass cotangent weights anywhere — the function does not accept a weight scheme parameter.
- Searched repo-wide for `cotangent | cot_weight | cotan` — only documentation/audit references; no implementation exists.

**Verdict:** This is a **gap, not a substitution**. Cotangent Laplacian (Pinkall & Polthier 1993, `w_ij = (cot α + cot β)/2`) is the AAA reference but no AAA implementation lives in this repo. Already tracked as **P0-A6-3** in `MASTER_AUDIT_2026_04_27.md`. Out of scope for this F1 audit — no substitution to fix, only an absence to fill.

---

## F1-6 — A* Road Routing (NOT a substitution — opt-in fallback)

**Reviewed:** `_terrain_noise.py:1683` `_legacy_astar` and `:1969` `generate_road_path_grid_legacy`.
- Both emit `DeprecationWarning` at call time.
- Production default `VEILBREAKERS_ROAD_STRICT=1` routes through `road_network._astar_24dir` (proper 24-direction, world-space, Rune's exact cost formula).
- Legacy is invoked only at `environment.py:6090-6102` inside an `except`/STRICT=0 fallback block that explicitly warns the user.

**Verdict:** Not a silent substitution — this is a documented, opt-in fallback for disaster recovery. No fix needed beyond eventually deleting the legacy path once the 24-dir solver is bulletproof.

---

## Items Checked and Cleared

### F1-A — terrain_materials.py vs terrain_materials_v2.py

Both alive in production, with **distinct responsibilities**:

| Module | Role | Production callers |
|--------|------|--------------------|
| `terrain_materials.py` | Biome palette + RGBA splatmap (`compute_world_splatmap_weights`) for legacy biome-name keyed flow | `environment.py:70, 2412` (export_splatmaps path), `_biome_grammar.py:58, 167`, `terrain_materials_ext.py` |
| `terrain_materials_v2.py` | Mask-stack envelope rules → `splatmap_weights_layer` + `material_weights` (Bundle B) | `terrain_pipeline.py:922` (snow line), `procedural_materials.py:1100` (MaterialChannel), `terrain_unity_export.py:795`, `terrain_validation.py:765`, `terrain_materials_ext.py:19` (MaterialChannel) |

`terrain_materials_v2.py` docstring explicitly states "DOES NOT modify the legacy `terrain_materials` module — it coexists as `_v2` so old tests stay green." Confirmed coexistence by design. **Not a substitution.**

### F1-B — _bridge_mesh.py vs _mesh_bridge.py

| Module | Role | Production callers |
|--------|------|--------------------|
| `_bridge_mesh.py` | Generates bridge geometry over rivers/canyons (terrain feature) | `_terrain_depth.py:1278` `from ._bridge_mesh import generate_terrain_bridge_mesh` |
| `_mesh_bridge.py` | MeshSpec→Blender wiring (VEGETATION_GENERATOR_MAP, PROP_GENERATOR_MAP, `mesh_from_spec`) | `environment.py:5385`, `environment_scatter.py:60`, `vegetation_system.py:853` |

Names collide visually, scopes do not. **Not a substitution.**

### F1-C — terrain_legacy_bug_fixes.py

Searched all of `veilbreakers_terrain/` — only importer is `tests/test_bundle_bcd_supplements.py:60`. No handler imports it. The module is a static-grep auditor (BUG-109 tracks staleness of its hardcoded line numbers), but it is **not on the production import graph**, so the audit-as-runtime concern does not apply. Safe.

---

## Other sim/ Modules

`veilbreakers_terrain/sim/__init__.py` lists exactly three modules: `catenary`, `pbd_cloth`, `foam`. All three confirmed above. No other sim/ modules exist.

---

## Aggregate Production-Wiring Status of `sim/`

| Module | Production handlers that import it | Tests that import it |
|--------|------------------------------------|----------------------|
| `sim/foam.py` | **0** | 1 (`test_sim_modules.py`) |
| `sim/catenary.py` | **0** | 1 (`test_sim_modules.py`) |
| `sim/pbd_cloth.py` | **0** | 1 (`test_sim_modules.py`) |

The entire `sim/` package is dead code in production. All three modules contain peer-reviewed, properly cited AAA implementations. All three are bypassed by simpler in-handler substitutes.

---

## Recommended Wiring Plan (priority order)

1. **F1-1 Foam (P0)** — wire `sim.foam.generate_foam_mask` into `terrain_waterfalls.generate_foam_mask` as the primary contributor; keep `_generate_local_waterfall_foam_mask` only for plunge-pool peak. Effort: 4 hours (build adapter for `water_depth` and `flow_dir` from existing stack channels).
2. **F1-4 Histogram LUT (P0)** — pre-bake CDF inverse LUT in CPU `pass_stochastic_shader` and emit alongside HLSL template. Replace `HistogramPreservingBlend` body with two LUT samples + triangular blend. Effort: 3 hours.
3. **F1-2 Catenary (P0)** — replace half-sine in `generate_rope_bridge_mesh` with `catenary_with_sag` sample loop. Effort: 1 hour.
4. **F1-3 XPBD Cloth (P0)** — replace analytical flag/banner keyframe generators with `simulate_cloth(FLAG_PARAMS)` shape-key bake. Effort: 4 hours (asset-side wiring + shape-key animation export).

Total: ~12 hours to retire all `sim/` dead code and lift production foam/cloth/rope from approximation to AAA reference.
