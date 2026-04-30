# K6 — Grass Pipeline Audit (2026-04-27)

**Auditor:** K6
**Scope:** `veilbreakers_terrain/handlers/procedural_grass.py` (modified file) + the full grass generation pipeline end-to-end (placement → channel → export → Unity).
**Verdict:** **NO NEW P0s.** All previously known P0s (I2-P0-1, I2-P0-2, I2-P0-3) are confirmed still active. The current modification is a correct two-line bug-fix and introduces no regression. The pipeline as a whole is non-functional in production but that is already counted.

---

## 1. The current modification

Commit `d003e25` ("Fix procedural_grass: zero-weight guard + numpy-safe drainage fallback"), now committed (working tree clean — the snapshot in the git status was stale by the time of audit).

**Diff:** 7 insertions, 1 deletion against `veilbreakers_terrain/handlers/procedural_grass.py`.

### 1.1 `_sample_positions` zero-weight guard (lines 433-437)

```python
flat = weight.ravel().astype(np.float64)
nonzero = int((flat > 0).sum())
if nonzero == 0:
    return np.zeros((0, 2), dtype=np.int64)
target_count = min(target_count, nonzero)
flat /= flat.sum()
idx = self.rng.choice(flat.size, size=target_count, replace=False, p=flat)
```

**Verdict: correct.** Without this guard, when the eligibility mask has fewer non-zero cells than `target_count`, `np.random.Generator.choice(replace=False, p=flat)` raises `ValueError: Fewer non-zero entries in p than size`. The fix is the canonical pattern. It also short-circuits when the entire mask is zero (which can happen for a species that fails biome filter on a tile) — previously that would still fall through `total_weight <= 0` because `sum() > 0`, but a degenerate single-cell mask with 1 nonzero entry and target_count=2 would have crashed.

The two guard layers (lines 423-431 sum check, 434-437 nonzero count) are belt-and-suspenders but not redundant: `total_weight > 0` does not imply `(flat > 0).sum() == flat.size` — float underflow can produce a positive sum from 1-2 dominant cells while target_count, computed from `density_per_sqm * total_weight * cell_area`, asks for many more.

### 1.2 Drainage fallback (lines 496-499)

```python
drainage_arr = _stack_attr(stack, "drainage")
if drainage_arr is None:
    drainage_arr = _stack_attr(stack, "wetness")
```

**Verdict: correct.** The previous expression `_stack_attr(stack, "drainage") or _stack_attr(stack, "wetness")` is unsafe because when `drainage` is a populated numpy array, `bool(arr)` raises `ValueError: The truth value of an array with more than one element is ambiguous`. Replacing the short-circuit `or` with explicit `is None` is the standard numpy-safe pattern. The same pattern was already correct on lines 386-388 inside `_eligibility_mask`, so this is just bringing `generate_grass_placement` into alignment.

### 1.3 Regression risk

Zero. Both changes are strictly defensive; they only alter behaviour in cases that previously raised `ValueError`. No happy-path semantics change.

---

## 2. Pipeline trace — end-to-end

### 2.1 The two parallel grass systems

There are **two completely disconnected grass systems** in the codebase:

| # | Module | Output | Wiring |
|---|---|---|---|
| 1 | `veilbreakers_terrain/handlers/procedural_grass.py` (770 lines) | `GrassPlacementRecord` instances → JSON manifest (Wave 5 schema) | **0 production imports.** Only `tests/test_procedural_grass.py` imports it. |
| 2 | `pass_emergent_grass` in `veilbreakers_terrain/handlers/terrain_vegetation_depth.py:1760` | `stack.grass_density_map` (H×W float32 texture) | Registered via Bundle O → `terrain_master_registrar`. **Output never serialised to disk.** |

Neither reaches Unity. There is also a third, **independent** Blender-side scatterer at `scripts/build_scene_v3.py:2475` (`scatter_grass_clumps`) that places mesh clumps directly inside Blender — it does not import `procedural_grass.py` and writes nothing to the Unity tile bundle.

### 2.2 Trace of `pass_emergent_grass`

```
splatmap_weights_layer (channel) ──> compute_emergent_grass_density ──> grass_density_map (channel)
   (assumes layer 0 is grass)         (multiplies by GRASS_DENSITY_SCALE = 5.0)        │
                                                                                       ▼
                                                                              [DROPPED ON FLOOR]
                                                                  not in terrain_unity_export.py:1261-1279 tuple
```

Verified at `veilbreakers_terrain/handlers/terrain_unity_export.py:1261-1279`. The export tuple does not contain `"grass_density_map"`. `terrain_semantics.py:616` lists it in `EXPORT_CHANNEL_NAMES` (the schema), so the schema thinks it ships, but the actual `_write_raw_array` loop never sees it. **I2-P0-2 is reaffirmed verbatim — no new P0 needed.**

### 2.3 Trace of `procedural_grass.ProceduralGrassSystem`

`generate_grass_placement` reads `stack.height`, `slope`, `cliff_label`, `hero_exclusion`, `poi_mask`, `water_surface_elevation_m` (or `water_surface_mask`), `road_sdf_dist`, `bathymetry`, `drainage`/`wetness`, `biome_id`. All of these channels exist in production. The module is *plumbed* to consume the stack but **no pass, no handler, no script, no MCP route ever calls it**. Confirmed via `grep "from veilbreakers_terrain.handlers.procedural_grass\|import procedural_grass"` returning only the test file.

2026-04-29 refresh: the retired DCC hook was removed from grass manifests. `write_grass_manifest` now emits runtime-facing mesh entries with `render_batch_key` plus `unity_render_mode: detail_prototype | gpu_instancer`; full Unity foliage importer consumption still needs editor-side E2E proof.

This is **I2-P0-1 / D1**, already counted.

### 2.4 Net status

There is no grass data of any kind reaching Unity:

| Path | Output | Reaches Unity? |
|---|---|---|
| `pass_emergent_grass` → `grass_density_map` channel | computed every tile | **No** — not in export tuple |
| `procedural_grass.ProceduralGrassSystem` → JSON manifest | never invoked | **No** — orphan |
| `scripts/build_scene_v3.scatter_grass_clumps` → Blender mesh clumps | runs in scene_v3 | Blender-only (not the Unity tile path) |

**This is fully captured by I2-P0-1 + I2-P0-2.**

---

## 3. Density math — does the formula place grass correctly?

### 3.1 `pass_emergent_grass` formula

```python
grass_map = (splatmap[..., 0] * GRASS_DENSITY_SCALE).astype(np.float32)  # GRASS_DENSITY_SCALE = 5.0
```

This is **trivially wrong** as a "grass density" formula, but the bug is documented:
- It uses splatmap layer 0 as a "grass proxy". The comment at `terrain_vegetation_depth.py:1729-1731` explicitly says "Replace with a structural label index after Fix 10.10 lands." So this is a stub.
- It does **not** account for slope — grass would be placed on cliff faces.
- It does **not** account for biome — grass would be placed in volcanic / arctic / underwater biomes.
- It does **not** account for moisture except indirectly via splat layer weight.

**However**, this is masked from being a P0 because:
1. The output is never exported (I2-P0-2), so the wrong formula has zero in-game effect.
2. The code is explicitly labelled as a Fix 10.10 placeholder.

The real grass formula belongs in `procedural_grass._eligibility_mask` (lines 306-408), which is correctly multi-channel: slope cap, height band, water exclusion (W-1-aware), road SDF, cliff SDF, water-edge SDF, wetness affinity, biome filter. **That formula is high-quality** — it would place grass correctly *if it were ever invoked*. See section 5.1 for the qualitative review.

**No new P0** — the wrong formula is in dead-from-Unity-export code, and the right formula is in dead-from-production code.

### 3.2 Edge-case check on `procedural_grass._eligibility_mask`

Verified by reading lines 306-408:

| Concern | Handled? |
|---|---|
| Cliff faces excluded | Yes — `cliff_label == 0` hard exclude (line 335) plus SDF buffer (line 376). |
| Underwater excluded | Yes — `height >= water_surface_elevation_m` if elevation present (line 352), else `water_surface_mask <= 0` (line 359). W-1-aware. |
| Roads excluded with buffer | Yes — `road_sdf_dist >= sdf_road_min_m` (line 364), with EDT fallback if only `road_mask` is present (line 370). |
| Hero / POI exclusion | Yes — `hero_exclusion == 0` (line 340), `poi_mask == 0` (line 343). |
| Biome filter | Yes — bitmap-OR over `biome_id_map` (lines 397-406). |
| Slope cap | Yes — `slope <= species.slope_max_deg` (line 330). |
| Wetness affinity | Yes — `1 - |drainage_norm - species.wetness_affinity|` (line 391). |
| Height band | Yes — `(height >= lo) & (height <= hi)` (line 325). |

This is correct AAA-grade gating logic. **No P0 in the formula itself.**

---

## 4. GPU instance generation

`generate_grass_placement` produces world-space `(x, y, z)` triples, a per-instance Y-rotation, a uniform scale jitter, biome name, and moisture (lines 545-561). It also computes `position_terrain_norm` in `0..1` Unity convention. This is enough for Unity/GPU foliage manifest ingestion, but:

- **No LOD-distance information** beyond a fixed `lod_level=2` (records-level field, line 218). No per-instance LOD tier or screen-size hint computed from camera-relative distance.
- **No Y-up vs Z-up axis annotation.** The `position_world` tuple is `(wx, wy, wz)` where `wz = height[rows, cols]` — the height channel is the height (Z in world), but the Unity convention varies by import path. There is no explicit `axis_up: "Y" | "Z"` marker in the manifest. This is a contract gap with Unity but **not a P0** because the manifest is never read.
- **`lod_hint_sampler_tier: 2`** is hardcoded (line 704). No camera-aware LOD selection.

These are **P2 quality concerns** dependent on first wiring the module in. Not new P0s.

---

## 5. Quality review of `procedural_grass.py` itself

### 5.1 Strengths

- Vectorised numpy throughout `_eligibility_mask` and `_sample_positions`. No per-cell Python loops in the hot path. Documented memory peak: one float32 array per species at stack resolution.
- `_distance_transform_edt` has a scipy → numpy fallback. The fallback is L∞ Chebyshev (acknowledged in docstring), acceptable for the cell-scale exclusion checks.
- Atomic write pattern (tmp + `os.replace`) at lines 636-639 and 720-725 — race-safe for parallel pass execution.
- `GrassSpecies` is `frozen=True` — hashable, safe to share across passes.
- W-1 aware: water exclusion prefers `water_surface_elevation_m` over the dual-semantics `water_surface_mask` (lines 348-359). Aligned with the recent W-1 fix.

### 5.2 Weaknesses

- **`_poisson_thin` is approximate.** Bucket-sort by spatial hash (lines 446-460) — keeps the *first* sample per bucket. This is not a true Poisson disk; two samples in adjacent buckets at distance < min_spacing both survive. Acceptable only as a coarse prepass before downstream blue-noise validation/refinement; sub-AAA if used as the final pass.
- **Per-instance Python loop at lines 545-561.** The records-list build is the only Python loop, after vectorisation. For 200,000 max instances per species × 6 species this could be 1.2M append calls. Should be replaced by a vectorised dataclass batch or numpy structured array. Not a P0.
- **Inconsistent norm axes:** `norm_x = cols * cell_size / extent_x` (correct), `norm_z = rows * cell_size / extent_y`, `norm_y = (wz - height_min) / height_span`. The records' `position_terrain_norm = (norm_x, norm_y, norm_z)` mixes XZ-on-ground with Y-as-height. No axis convention is declared in the manifest schema. Sub-AAA but not regressive.
- **Per-cell biome name lookup (line 547)** uses `_biome_id_to_name` which does a linear `dict.items()` scan per instance. For 1.2M instances this is O(N × |biomes|) = 1.2M × 14 = 16.8M ops. Should be vectorised via an inverse-map array indexed by biome_id. Not a P0.
- **Default `wetness_affinity` 0.3** (line 121) seems odd as a default — it puts all "*" species at moderately-dry preference rather than neutral. If a species fails to set it, they'll cluster on dry slopes regardless of their real ecology.
- **`density_per_sqm * total_weight * cell_area_m2`** (line 428) overcounts: `total_weight` is already a sum-of-probability-weights in [0..1] not a count. The intended formula is `density_per_sqm * (number-of-eligible-cells) * cell_area_m2`. Because the eligibility mask values are in [0..1] not {0,1}, the resulting count is biased low — a cell at 50% wetness affinity contributes 0.5 to total_weight, not 1. This produces sparser scatter than intended for partial-affinity cells. **Sub-AAA but not a P0** because the scatter is dead code.

### 5.3 Tests

`tests/test_procedural_grass.py` covers basic placement, height requirement, biome filter, slope cap, wetness affinity comparison, and atomic manifest write (~15 cases). Coverage is reasonable for a module that has no production caller.

---

## 6. Interaction with `vegetation_system.py`

`procedural_grass.py` references `vegetation_system.py` only in a comment at line 252 ("Default biome id map mirrors handlers/vegetation_system.py BIOME_VEGETATION_SETS keys"). It does **not** import the module. The biome-id map is duplicated by hand in `DEFAULT_BIOME_ID_MAP`.

Since both modules are unwired in production (I2-P0-1 covers `vegetation_system.py`), this is not a duplicate active grass system — it is two dead grass systems sitting in parallel. The duplication of biome name keys is a synchronization risk if either side adds a biome, but **not a P0** since neither runs.

---

## 7. Findings summary

| ID | Severity | Status |
|---|---|---|
| I2-P0-1 | P0 | **Confirmed unchanged.** `procedural_grass.py` still has zero production imports. |
| I2-P0-2 | P0 | **Confirmed unchanged.** `grass_density_map` still absent from `terrain_unity_export.py:1261-1279` tuple. |
| I2-P0-3 | P0 | (`horizon_elevation_angles` — same export omission, same pattern, also confirmed.) |
| K6-mod-1 | (info) | The d003e25 modification is a correct, narrow bug-fix. No regression. |
| K6-Q-1 | P2 | `pass_emergent_grass` density formula is a stub (splat layer 0 × 5.0). Documented as Fix 10.10 placeholder. |
| K6-Q-2 | P2 | `procedural_grass.ProceduralGrassSystem._sample_positions` density formula uses sum-of-affinity instead of count-of-eligible-cells (line 428). Underestimates instance count. |
| K6-Q-3 | P2 | `_poisson_thin` is approximate bucket-sort, not true Poisson disk. |
| K6-Q-4 | P2 | Per-instance Python loop at `procedural_grass.py:545-561` for record construction. O(N) appends, not vectorised. |
| K6-Q-5 | P3 | Three parallel grass systems coexist (`pass_emergent_grass`, `procedural_grass`, `scripts/build_scene_v3.scatter_grass_clumps`) with no shared contract. |

**No new P0s. No new P1s.** All P0-grade findings are already counted in I2.

---

## 8. Recommended fixes (do NOT promote any to new P0; these are already covered by I2)

1. Add `"grass_density_map"` to the export tuple at `terrain_unity_export.py:1265-1279`. (Already prescribed by I2-03.)
2. Wrap `ProceduralGrassSystem` as `pass_procedural_grass` PassDefinition with `requires_channels=("height","slope","biome_id","drainage","road_sdf_dist","cliff_label","water_surface_elevation_m")` and `produces_channels=("grass_instance_points",)`. (Already prescribed by I2-01.)
3. After (1)+(2), fix the density-formula stub in `pass_emergent_grass` to consume the same eligibility logic as `procedural_grass._eligibility_mask`. Or, better, delete `pass_emergent_grass` once `procedural_grass` is wired — the latter subsumes the former.

---

## 9. Files referenced

- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\procedural_grass.py` (770 lines, modified file)
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_vegetation_depth.py` (lines 1722-1810: `pass_emergent_grass` + registrar)
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_bundle_o.py` (registers emergent_grass)
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_unity_export.py` (lines 1261-1279: export channel tuple — `grass_density_map` missing)
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_semantics.py` (line 413: schema field; line 616: `EXPORT_CHANNEL_NAMES`)
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\vegetation_system.py` (1758-line orphan, only related by biome-id mirror comment)
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\scripts\build_scene_v3.py` (line 2475: independent `scatter_grass_clumps` Blender path)
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\tests\test_procedural_grass.py` (sole importer of `procedural_grass`)
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\docs\aaa-audit\deep_dive_2026_04_27\I2_scatter_vegetation_lod_audit.md` (prior audit; this report extends, does not duplicate)
