# M4 Deep-Dive Audit: Stratigraphy & Geological Systems
**Date:** 2026-04-27
**Sweep:** M (post-L)
**Files audited (every line read):**
- `veilbreakers_terrain/handlers/terrain_stratigraphy.py`
- `veilbreakers_terrain/handlers/terrain_geology_validator.py`
- `veilbreakers_terrain/handlers/terrain_banded.py`
- `veilbreakers_terrain/handlers/terrain_banded_advanced.py`

**Cross-referenced:** `terrain_pipeline.py`, `terrain_delta_integrator.py`, `terrain_master_registrar.py`, `environment.py`, `terrain_validation.py`

---

## Executive Summary

The stratigraphy system is architecturally ambitious but operationally broken at every output boundary. Seven P0 blockers confirmed. The known E-2 bug (delta never applied to height) is the most visible symptom of a deeper pattern: the stratigraphy pass computes real geological data but none of it reaches a functioning output. The production pipeline bypasses the pass entirely (L2-P0-1 confirmed again), the delta integration path has a prerequisite ordering hole, the unconformity detection algorithm is geologically invalid, dike geometry is only 2D with no height dimension, the geology validators are never called inside the pass, and strike angle is decoupled from dip azimuth making the orientation vectors internally inconsistent. Grade: **D**.

---

## P0 Findings

---

**M4-P0-1** | `terrain_stratigraphy.py:985-991` | `strat_erosion_delta` stored as a channel but `stack.height` is NEVER updated — E-2 confirmed unfixed

**Evidence:**
```python
# pass_stratigraphy, lines 985–991
erosion_delta = apply_differential_erosion(
    stack,
    strat_stack=strat_stack,
    max_erosion_fraction=max_erosion_frac,
    undercutting_strength=undercut_strength,
)
stack.set("strat_erosion_delta", erosion_delta, "stratigraphy")
# ← stack.height never touched here
```

The delta is filed under `"strat_erosion_delta"` and later picked up by `pass_integrate_deltas` in `terrain_delta_integrator.py`. But `integrate_deltas` is registered by `register_integrator_pass()`, which is called inside `register_default_passes()` — **Bundle A only**. `register_bundle_i_passes()` does NOT call `register_integrator_pass()`. If a caller activates stratigraphy without going through the full master registrar (unit tests, partial pipelines, the MCP bridge), `integrate_deltas` may not be in the registry and the delta is silently discarded.

Worse: `environment.py`'s production pipeline sequence (lines 2004–2034) never adds `"stratigraphy"` or `"integrate_deltas"` to the controller pipeline. All 7 steps of `pass_stratigraphy` run to completion with zero effect on terrain height.

**AAA gap:** Houdini Heightfield Erode applies differential erosion to the height field in the same node that computes it. The delta approach only works if the integrator is guaranteed to run after every delta producer. That guarantee is not enforced here.

**Fix:** Inside `pass_stratigraphy`, apply the delta directly: `stack.set("height", (h + erosion_delta).astype(h.dtype), "stratigraphy")`. Keep `strat_erosion_delta` as an output channel for downstream diagnostics but do not rely on the deferred integrator path. Estimated time: 1 hour.

---

**M4-P0-2** | `environment.py:2004-2034` | Production pipeline never includes `"stratigraphy"` — geological layering absent from all generated terrain (L2-P0-1 re-confirmed with new evidence)

**Evidence:**
```python
# environment.py, lines 2004-2034 — the full production pipeline assembly
pipeline = [
    "macro_world",
    "structural_masks",
]
# then conditionally adds: pass_hydrology, erosion, structural_masks, caves,
#                           integrate_deltas, cliffs, emit_overhang_meshes,
#                           emit_particle_systems, validation_minimal
# "stratigraphy" is NEVER appended regardless of terrain_type, quality_profile,
# or composition_hints.
```

`register_bundle_i_passes()` registers the stratigraphy pass on the controller, but `environment.py`'s pipeline list never requests it. Every terrain tile generated through `compose_map` has `rock_hardness = None`, `strata_orientation = None`, `strata_cross_section = None`. The cliff pass (`terrain_cliffs.py`) falls back to default hardness=0.9 everywhere (K2-P0-6). The karst pass has no hardness to read. Unity receives no material stratification data.

**AAA gap:** World Machine, Gaea, and Houdini all run geological layering before erosion so erosion rates are spatially modulated. Running erosion without rock hardness produces uniform sediment rates — mud everywhere, no caprock mesa formation, no differential weathering profiles.

**Fix:** Add `"stratigraphy"` to the `environment.py` pipeline just after `"structural_masks"` and before `"erosion"`, so hardness modulates the erosion pass. Also add `"integrate_deltas"` after stratigraphy if not already present. Estimated time: 30 minutes.

---

**M4-P0-3** | `terrain_stratigraphy.py:457-521` | Unconformity detection algorithm is geologically invalid — uses erosion depth vs layer thickness to derive a "truncation angle" via arcsin, which has no geological meaning

**Evidence:**
```python
# detect_unconformities, lines 510-518
ratio = np.clip(
    erosion_depth / np.where(cell_thickness < 1e-6, 1e-6, cell_thickness),
    0.0, 1.0
)
truncation_angle = np.arcsin(ratio)   # ← "arcsin(erosion/thickness)" is not an angle
UNCONFORMITY_THRESHOLD_RAD = 0.1047
unconformity_mask = (truncation_angle >= UNCONFORMITY_THRESHOLD_RAD).astype(np.float32)
```

`arcsin(erosion_depth / layer_thickness)` is dimensionally incoherent. An angular unconformity is defined by the angular discordance between truncated beds and overlying strata — it requires comparing bedding-plane dip angles across the erosion surface, not depth/thickness ratios. The formula `arcsin(ratio)` here simply reclassifies the ratio into the range `[0, π/2]` via a monotone function; the threshold of 0.1047 rad is equivalent to `ratio ≥ sin(6°) ≈ 0.1045` which is nearly identical to just `ratio ≥ 0.10`. The arcsin adds no geometric content.

**Real definition:** An angular unconformity exists where `|dip_above - dip_below| > threshold_angle`. This requires comparing the dip of the eroded layer against the dip of the newly deposited or exposed layer — information the function never accesses (it reads `erosion_delta` only, not `strata_orientation`).

**AAA gap:** Gaea's Stratify node marks unconformities by comparing folded bed orientations at the erosion surface. Houdini's Height Field Layer node uses the structural discordance angle between strata as the unconformity metric. Neither uses depth/thickness arithmetic.

**Fix:** Replace with dip-angle discordance: for each cell, compare the dip of the layer at `h - |erosion_depth|` against the dip of the surface layer. Mark as unconformity where `|dip_lower - dip_upper| > 6°`. This requires reading `strata_orientation` computed in step 2 of `pass_stratigraphy`, which is already on the stack. Estimated time: 3 hours.

---

**M4-P0-4** | `terrain_stratigraphy.py:582-602` | Dike geometry is 2D-only — dikes have no height extent, no topographic expression, and do not cut through the geological column

**Evidence:**
```python
# simulate_intrusions, lines 582-602
for _ in range(n_intrusions):
    cx = float(rng.uniform(0.1, 0.9) * tile_width_m)
    a  = float(rng.uniform(w_min, w_max))          # dike half-width (X)
    b  = tile_height_m * 0.5                        # ← b is tile Y half-extent, not height
    # ...
    dx  = xs[np.newaxis, :] - cx                   # X offset in world space
    # Ellipse test: only checks X distance — no Z dimension used at all
    footprint = np.clip(1.0 - (dx_adj / max(a, 1e-6)) ** 2, 0.0, 1.0)
    weight = np.sqrt(footprint).astype(np.float32)
    intrusion_mask = np.maximum(intrusion_mask, weight)
```

A real dike is a sub-vertical sheet intrusion cutting through the geological column. Its key properties are: (a) near-vertical orientation in the Z (elevation) axis, (b) a finite depth extent from the intrusive source to the eroded surface, (c) topographic expression — resistant dikes stand proud of softer surrounding rock after erosion. The implementation only computes a horizontal (XY) footprint band. The variable `b` is labelled "dike half-height = half tile height" but it is never used in the ellipse calculation — the ellipse test is `(dx/a)^2 <= 1` which is a 1D band test, not an ellipse. No height information is read or written; dikes produce the same footprint regardless of local elevation.

The hardness mutation at line 620 (`np.where(intrusion_mask > 0.5, 0.88, rh)`) applies a flat hardness everywhere the 2D band exists, including deep valleys that the dike would not reach after erosion has removed the overlying rock.

**AAA gap:** A UE5 Landscape dike feature has vertical extent computed from the dike bottom depth to the surface, so dike-hardened cells only appear where the dike intersects the elevation slice. World Machine's intrusion node gates the surface effect by `if h > dike_root_depth`.

**Fix:** Clip the intrusion mask by depth: a dike rooted at `dike_root_z` should only appear where `stack.height > dike_root_z`. Sample `dike_root_z` from a fraction of `strat_stack.base_elevation_m + strat_stack.total_thickness()`. The footprint weight should be multiplied by a vertical decay term `exp(-max(0, (dike_root_z - h) / dike_half_height))`. Also fix the ellipse formula: the correct test is `(dx_adj/a)^2 + (dy/b)^2 <= 1`, not just the X term. Estimated time: 4 hours.

---

**M4-P0-5** | `terrain_stratigraphy.py:63,847,864-865` | `strike_angle_rad` is sampled independently of `azimuth_rad`, violating the geological constraint that strike is always perpendicular to dip direction (strike = azimuth + π/2)

**Evidence:**
```python
# StratigraphyLayer dataclass, line 63
strike_angle_rad: float = 0.0   # separate field, no enforcement

# _default_strat_stack_from_hints, line 847
azimuth_rad=float(rng.uniform(0.0, 2.0 * np.pi)),
# ...
strike_angle_rad=(
    strike if isinstance(mat, dict) else
    float(rng.uniform(0.0, np.pi))   # ← independent random, not azimuth + π/2
),

# fallback 7-layer column, lines 864-865
az_fn  = lambda: float(rng.uniform(0.0, 2.0 * np.pi))
str_fn = lambda: float(rng.uniform(0.0, np.pi))
# Each layer calls both independently — no constraint between them
```

Geological law: strike is the direction of the line of intersection between a bedding plane and a horizontal surface. It is always perpendicular to the dip direction (dip azimuth). Therefore `strike_angle_rad = azimuth_rad + π/2` (modulo π). Sampling them independently can produce a layer where dip and strike are parallel — geologically impossible.

The downstream `compute_strata_orientation` function at line 144 ignores `strike_angle_rad` entirely (it only uses `dip_rad` and `azimuth_rad` to build the bedding-plane normal vector). So `strike_angle_rad` is written to the cross-section export and to Unity but is computed incorrectly. Any Unity shader using the strike vector for anisotropic weathering will get wrong data.

**AAA gap:** Every geological modelling tool (Move, Petrel, Midland Valley MOVE) enforces the strike-perpendicular-to-dip constraint as a hard invariant. Gaea's strata node derives strike automatically from the azimuth field.

**Fix:** Remove `strike_angle_rad` as an independent field. Compute it deterministically: `strike_angle_rad = (azimuth_rad + math.pi / 2) % math.pi`. Apply this in `StratigraphyLayer.__post_init__` or derive it on-demand as a property. Remove all independent strike sampling from `_default_strat_stack_from_hints`. Estimated time: 2 hours.

---

**M4-P0-6** | `terrain_geology_validator.py:26-96` | `validate_strata_consistency` is never called inside `pass_stratigraphy` — the pass produces zero validation issues regardless of geological correctness

**Evidence:**
```python
# pass_stratigraphy, lines 944-946
t0 = time.perf_counter()
stack = state.mask_stack
issues: List[ValidationIssue] = []    # ← always empty at end of function

# The entire function body (lines 947-1068) never calls:
# - validate_strata_consistency()
# - validate_karst_plausibility()
# - validate_glacial_plausibility()
# PassResult at line 1052 always has issues=[]
```

`terrain_geology_validator.py` defines `validate_strata_consistency`, `validate_glacial_plausibility`, and `validate_karst_plausibility`. These are three domain-specific geological plausibility checks. None of them is imported or called inside `pass_stratigraphy`. The `issues` list in `pass_stratigraphy` is populated at declaration and never written to again; the `PassResult` always reports zero issues.

`validate_strata_consistency` IS wired into `DEFAULT_VALIDATORS` in `terrain_validation.py` (line 1920), so it runs during the full validation pass — but only when `strata_orientation` has been populated. Since stratigraphy is not in the production pipeline (M4-P0-2), `strata_orientation` is always `None` and the validator returns immediately with a `STRATA_MISSING` soft issue that is silently lost.

`validate_strahler_ordering` in `terrain_geology_validator.py` is not in `DEFAULT_VALIDATORS` at all and has no callers.

**AAA gap:** Gaea's Strata node runs internal plausibility checks (bed count, thickness coherence, dip consistency) as part of the node evaluation and surfaces them as node warnings. These are not optional post-hoc validations.

**Fix:** Call `validate_strata_consistency(stack)` inside `pass_stratigraphy` after step 2, append the returned issues to the local `issues` list, and pass them through to `PassResult.issues`. Wire `validate_strahler_ordering` into `DEFAULT_VALIDATORS` or remove it to eliminate dead code. Estimated time: 1 hour.

---

**M4-P0-7** | `terrain_stratigraphy.py:457-521` + `terrain_stratigraphy.py:985-994` | `detect_unconformities` uses pre-erosion height but the `erosion_delta` passed in was computed from the same pre-erosion height — the unconformity mask is computed against a never-updated elevation, producing a self-referential mask that changes nothing about the geology

**Evidence:**
```python
# pass_stratigraphy lines 985-994
erosion_delta = apply_differential_erosion(stack, ...)  # computed from stack.height (pre-erosion)
stack.set("strat_erosion_delta", erosion_delta, "stratigraphy")  # stored but NOT applied to height

unconformity_mask = detect_unconformities(stack, strat_stack, erosion_delta)
# detect_unconformities reads stack.height at line 496:
#   h = np.asarray(stack.height, dtype=np.float64)
# This is the same pre-erosion height used to compute erosion_delta.
# The surface layer index (idx) is computed from pre-erosion elevation.
```

Because the erosion delta is never applied to `stack.height` before `detect_unconformities` is called (M4-P0-1), both the erosion delta computation and the unconformity detection use the same unmodified `stack.height`. The unconformity mask therefore represents: "where would unconformities exist if erosion occurred" rather than "where unconformities exist after erosion". Since the erosion does not actually occur in the height field, the mask has no correspondence to anything real in the terrain. Any Unity material reading `unconformity_mask` to place angular unconformity rock textures will find unconformities in the wrong places — at pre-erosion layer boundaries rather than at post-erosion exposed surfaces.

**AAA gap:** An unconformity surface in Houdini Heightfield is always computed on the post-erosion height because it is the erosion itself that creates the truncated-bed exposure. Gaea's UnconformitySolver explicitly takes the output of the Erosion node as input.

**Fix:** This is a cascade dependency of M4-P0-1. Fix M4-P0-1 first (apply delta to height in-place inside the pass), then call `detect_unconformities` after the height update. The fix is embedded in the M4-P0-1 fix. Estimated time: included in M4-P0-1.

---

## Warning-Level Findings (not P0 but contribute to D-grade)

**WR-1** | `terrain_stratigraphy.py:432-444` | The undercutting calculation uses `np.pad(hardness, ((0, 1), (0, 0)), mode="edge")[1:]` to get `hardness_above`, but this pads the BOTTOM of the array and then slices off the TOP — it gives the hardness of the cell to the south (larger row index), not "above" in world elevation. Row index increases downward in the grid, not upward. The comment says "hardness immediately above a cell" but the array access gives the cell below. The undercut term is applied in the wrong direction; hard-over-soft (mesa profiles) would actually produce soft-over-hard results.

**WR-2** | `terrain_banded.py:929-1026` | `pass_banded_macro` is registered under Bundle G but its pass output is entirely dependent on `state.intent.noise_profile`, which is an attribute that doesn't exist on `TerrainIntentState` per `terrain_semantics.py`. Line 978 uses `getattr(state.intent, "noise_profile", "dark_fantasy_default")` — this silently falls back to the default on every call, so biome-specific band weights are never respected in production. The `banded_macro` pass always generates `dark_fantasy_default` weights regardless of what the intent specifies.

**WR-3** | `terrain_banded_advanced.py:384-423` | `_anisotropic_kuwahara_filter` has a correctness issue at lines 401-402: the nearest integer sampling `np.clip(np.round(dx).astype(np.int32), -r, r)` rounds continuous per-pixel rotated offsets to integers, quantizing the elliptical kernel to a coarse grid of radius steps. At small radii (r=2), this degrades to at most 5 unique sample positions per pixel regardless of the rotation angle, making the "anisotropic" filter nearly identical to a classic box at small scales. The paper (Papari/Kyprianidis) requires sub-pixel bilinear interpolation for the kernel to actually resolve directionality at small radii.

**WR-4** | `terrain_geology_validator.py:99-393` | `validate_strahler_ordering` is a 295-line function exported in `__all__` but has no callers in the codebase (confirmed via grep: 0 call sites outside tests). It is dead production code.

---

## Cross-File Analysis

### Stratigraphy → Material Assignment Pipeline

`export_strata_cross_section` builds a `surface_material_id` (H,W) int32 array and stores it in a `numpy.object_` wrapper on the stack. `terrain_macro_color.py` (line 71) and `terrain_caves.py` (line 2865) both read it. The access pattern works but has a silent failure mode: the wrapper is a `(1,)` object array whose only element is the dict. Both consumers call `stack.get("strata_cross_section")` and then check `[0]` on the result. If the stratigraphy pass is skipped (M4-P0-2), `stack.get(...)` returns `None` and both consumers skip material stratification silently with no warning. Unity gets flat-material tiles.

### terrain_banded.py Production Status

Bundle G (`banded_macro`) is registered via `terrain_master_registrar.py` line 217 and is **opt-in** (not in default 8 passes). The pass has a functional implementation. The strata band in `_generate_strata_band` is the only banded noise component that models sedimentary layering. It is disconnected from `terrain_stratigraphy.py` — the banded strata band uses cosine-based layer synthesis with log-normal thickness distribution (cosmetically correct), while the stratigraphy pass uses a real geological column with hardness, age, and rock type. These two systems are parallel and never communicate. The banded strata band cannot drive rock hardness; the stratigraphy hardness field cannot drive banded band blending.

### terrain_banded_advanced.py Production Status

`terrain_banded_advanced.py` is imported nowhere in the production pipeline. It is not referenced in `terrain_banded.py`, `terrain_master_registrar.py`, or any handler. It is dead code in production. `terrain_banded.py` implements its own versions of `compute_anisotropic_breakup` (lines 243-358) and `apply_anti_grain_smoothing` (lines 462-504) — a different, simpler implementation with a different API signature. Both files export functions of the same name with incompatible signatures. Callers would import from whichever module they import first. Currently `terrain_banded.py`'s version is the one used; `terrain_banded_advanced.py`'s versions are unused.

### Fault / Thrust / Normal Fault Geometry

Zero implementation. There is no code anywhere in the four audited files for:
- Normal faults (graben/horst geometry)
- Thrust faults (compression, nappe stacking)
- Strike-slip faults
- Fault scarp height calculation
- Fault drag folds (beds bent near fault plane)

`simulate_fold_deformation` (terrain_stratigraphy.py:367) implements a single Fourier fold (syncline/anticline). This is one geological structure out of six that VeilBreakers' dark fantasy setting would require for credible ancient geology. Gaea Pro has 9 tectonic structure nodes. World Machine has 4. The absence of fault geometry means cliffs, escarpments, and mountain ridges all look like erosion features rather than tectonic features — fundamentally wrong for a dark fantasy landscape built on ancient violence.

---

## P0 Count Tally

**7 new P0 blockers confirmed in M4 sweep:** M4-P0-1 through M4-P0-7 (M4-P0-7 is a cascade of M4-P0-1, counted separately because it produces an independent incorrect output channel).

Running total across all sweeps: **112 confirmed P0 blockers** (105 prior + 7 M4).
