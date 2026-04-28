# J2 — compose_map: ACTUAL Production Pipeline (Audit 2026-04-27)

**Auditor:** Opus deep-dive J2
**Date:** 2026-04-27
**Scope:** Map the EXACT ordered sequence of passes that runs on every production tile, line-numbered against `veilbreakers_terrain/handlers/environment.py`, and identify which AAA terrain features are produced versus which are silently absent.

---

## TL;DR — Severity Assessment

The "compose_map" referenced in prior audit notes is a misnomer. **There is no function named `compose_map` in the codebase.** The string `"compose_map"` only appears in `environment.py:2012` as the literal `reviewer` string that gets stamped into `controller_scene_read["reviewer"]` for the `TerrainSceneRead`. The actual pipeline construction lives inline in `handle_generate_terrain` (`environment.py:~1940-2150`) and in `_execute_terrain_pipeline` (`environment.py:2755-3104`).

Production tiles run through the **controller path** (`use_controller=True` is hard-set at `environment.py:8358` in the biome-driven generator). Under the realistic default invocation (`erosion="hydraulic"`, no caves, cliff_overlays default `True`) the **actual ordered sequence is exactly seven passes**:

```
1. macro_world
2. structural_masks
3. pass_hydrology
4. erosion
5. structural_masks         (registered second time, replaces step 2 outputs)
6. cliffs
7. emit_overhang_meshes
8. validation_minimal
```

**No** materials/splatmap, **no** navmesh, **no** Unity export prep, **no** waterfalls, **no** caves (caves only run when scene_read provides cave_candidates AND `controller_apply_caves=True` — both default to False from `handle_generate_terrain`), **no** vegetation/scatter, **no** saliency, **no** LOD, **no** river/delta convergence. These passes are all *registered* via `register_all_terrain_passes()` but never appended to the production pipeline list.

**Confirmed absent from every production tile**: bathymetry, river flow speed, delta fans, splatmap/material weights, vegetation scatter, navmesh, terrain normals (Unity), heightmap raw u16, saliency, LOD/horizon sampling, waterfalls, caves (under default usage).

---

## Step 1 — Exact Ordered Sequence (controller path)

Source: `veilbreakers_terrain/handlers/environment.py`, function `handle_generate_terrain`, branch `if use_controller:` at line 1975.

| # | Pass name | Append line | Always-on? | Conditional |
|---|---|---|---|---|
| 1 | `macro_world` | 2005 (literal in initial list) | YES | none — base of `pipeline = ["macro_world", "structural_masks"]` |
| 2 | `structural_masks` | 2006 (literal in initial list) | YES | none |
| 3 | `pass_hydrology` | 2017 | conditional | `if erosion in ("hydraulic", "thermal", "both") or cave_candidates` (line 2009). **Default** in `handle_generate_terrain_aaa` flow: `erosion="hydraulic"` (line 8355), so present. |
| 4 | `erosion` | 2018 | conditional | same gate as #3 |
| 5 | `structural_masks` (second occurrence) | 2019 | conditional | same gate — **re-runs after erosion** to refresh slope/curvature/ridge/etc. against the eroded height |
| 6 | `caves` | 2026 | conditional | `if cave_candidates and controller_apply_caves` (line 2025). **Default**: `controller_apply_caves=False` at line 2008 AND `cave_candidates=[]` unless `params["scene_read"]["cave_candidates"]` is non-empty. Both rarely true → **caves almost never runs in production**. |
| 7 | `integrate_deltas` | 2027 | conditional | same gate as caves |
| 8 | `cliffs` | 2029 | conditional | `if params.get("cliff_overlays", True)` (line 2028). **Default True** → present in production. |
| 9 | `emit_overhang_meshes` | 2031 | conditional | `if ("caves" in pipeline or "cliffs" in pipeline) and "emit_overhang_meshes" not in pipeline` (line 2030). With cliffs on by default → present. |
| 10 | `emit_particle_systems` | 2033 | conditional | `if "waterfalls" in pipeline and "emit_particle_systems" not in pipeline` (line 2032). **`"waterfalls"` is never appended to `pipeline` anywhere in this function** → this branch is dead code. |
| 11 | `validation_minimal` | 2034 | YES | unconditional terminal append |

After this list is built it is then mutated by `_execute_terrain_pipeline` (lines 3062-3095) which can inject `emit_overhang_meshes`, `emit_particle_systems`, and the four export-prep passes — but only under conditions that production never satisfies (see Step 2).

### Reality table — what actually runs on a default production tile

Default invocation comes from `handle_generate_terrain_aaa` (the AAA biome generator that is the public entrypoint), `environment.py:8348-8359`:

```python
terrain_params = {
    ...
    "erosion": params.get("erosion", "hydraulic"),
    "use_controller": True,
}
```

No `scene_read`, no `cave_candidates`, no `cliff_overlays` override (so default True). Resulting pipeline list (post line 2034):

```
['macro_world', 'structural_masks', 'pass_hydrology', 'erosion',
 'structural_masks', 'cliffs', 'emit_overhang_meshes', 'validation_minimal']
```

Then in `_execute_terrain_pipeline`:
- Line 3064-3076: cliffs in pipeline AND `emit_overhang_meshes` not in pipeline? → **already present, no-op**.
- Line 3077-3089: waterfalls in pipeline? → No, no-op.
- Line 3090-3095: `validation_full` in pipeline? → **No** (controller path appends only `validation_minimal`), so **none of `materials_v2`, `navmesh`, `prepare_terrain_normals`, `prepare_heightmap_raw_u16` are ever injected**.

**Final actually-executed sequence on a production tile: 8 passes** (same as the list above).

---

## Step 2 — Conditionals & Defaults

| Conditional (line) | Gate | Default in `handle_generate_terrain_aaa` flow | Runs? |
|---|---|---|---|
| L2009: `erosion in ("hydraulic","thermal","both") or cave_candidates` | gates `pass_hydrology` + `erosion` + 2nd `structural_masks` | `erosion="hydraulic"` (L8355) | **Yes** |
| L2025: `cave_candidates and controller_apply_caves` | gates `caves` + `integrate_deltas` | `cave_candidates=[]` (no scene_read) AND `controller_apply_caves=False` (L2008) | **No** |
| L2028: `params.get("cliff_overlays", True)` | gates `cliffs` | not overridden → **True** | **Yes** |
| L2030: cliffs or caves in pipeline | gates `emit_overhang_meshes` | cliffs on | **Yes** |
| L2032: waterfalls in pipeline | gates `emit_particle_systems` | `"waterfalls"` is **never appended anywhere in this function** — gate is **structurally unreachable** | **No (dead branch)** |
| L3064 (in `_execute_terrain_pipeline`): inject emit_overhang_meshes | already present | already present | no-op |
| L3077: inject emit_particle_systems | requires `"waterfalls" in pipeline` | controller path never adds it | **No** |
| L3090: inject materials_v2/navmesh/prepare_terrain_normals/prepare_heightmap_raw_u16 | requires `"validation_full" in pipeline` AND `not unity_export_opt_out` | controller path appends only `validation_minimal` | **No — all four export-prep passes are NEVER injected on the production controller path** |

### Conditions that can NEVER be true under default `TerrainIntent`

1. **`emit_particle_systems`** — `"waterfalls"` is never appended in `handle_generate_terrain`'s controller branch. The append site at L2033 only fires *if* a prior line added `"waterfalls"`, but no such line exists in this function. Dead branch.
2. **`materials_v2`, `navmesh`, `prepare_terrain_normals`, `prepare_heightmap_raw_u16`** — gated on `"validation_full" in pipeline` (L3090). The controller path appends only `validation_minimal` (L2034). Production NEVER hits this branch unless a caller manually constructs a pipeline list with `"validation_full"` in it (the controller path wired by `handle_generate_terrain` does not).
3. **`caves` / `integrate_deltas`** — require both a non-empty `cave_candidates` array AND `controller_apply_caves=True` (defaults False). Default callers don't supply scene_read with cave_candidates, so this is **functionally dead** for AAA tile generation.

---

## Step 3 — Minimal Always-Runs Sequence

Passes that run on **every** tile regardless of intent:

```
macro_world  →  structural_masks  →  validation_minimal
```

That's it. Three passes are guaranteed. Everything else (hydrology, erosion, cliffs, caves, overhang meshes) is conditionally gated.

If a caller passes `erosion="none"` and `cliff_overlays=False`, the entire pipeline collapses to:

```
['macro_world', 'structural_masks', 'validation_minimal']
```

Heightmap with slope/curvature masks and a smoke-test validator. No water, no erosion, no cliffs, no overhangs, no materials, no anything else. This is the worst-case minimal tile — and is the actual contract any consumer of `handle_generate_terrain` can rely on.

---

## Step 4 — AAA Feature Coverage Table

For each AAA feature, ✓ = produced by a pass that runs on the default production tile; ✗ = absent from production output.

| AAA Feature | Pass that produces it | In production pipeline? | Status |
|---|---|---|---|
| Hydraulic erosion (mass transport) | `erosion` (`_terrain_world.pass_erosion`) | yes (gated on erosion arg, default hydraulic) | ✓ — but see [E-1, E-2 in A3 audit](A3_terrain_shape_erosion.md) — erodibility 1000× bug, stratigraphy delta never applied |
| Thermal erosion | folded into `erosion` pass via `erosion_profile="arid"` | yes if `erosion="thermal"` only | ✓ partial (off by default; default profile is "temperate" hydraulic) |
| Water flow direction (D8/D∞) | `WaterNetwork.from_heightmap` (L2986 in `_execute_terrain_pipeline`) | yes — built into controller state ALWAYS | ✓ but **not exposed as a mask channel** — only inside `state.water_network` Python obj, not in `mask_stack` for downstream passes |
| Flow accumulation | same as above | controller state only | ✓ in-memory, ✗ on mask_stack |
| Bathymetry (water depth) | NONE | — | **✗ ABSENT** |
| River flow speed | NONE — speed is a property of `pass_water` (Bundle C) which is not in production | — | **✗ ABSENT** |
| River convergence / delta fans | NONE — would require a delta-fan pass in Bundle C | — | **✗ ABSENT** |
| Cliff geometry | `cliffs` pass + `emit_overhang_meshes` | yes (cliff_overlays default True) | ✓ |
| Cave system | `caves` pass | gated on cave_candidates AND `controller_apply_caves` (both default False) | **✗ ABSENT under defaults** |
| Splatmap / material weights | `materials_v2` | gated on `validation_full in pipeline` — NEVER true on controller path | **✗ ABSENT** |
| Vegetation scatter | Bundle E `terrain_assets` passes — registered, but no append in controller pipeline | none in compose | **✗ ABSENT** |
| Navmesh / traversability | `navmesh` | same gate as materials_v2 (validation_full) | **✗ ABSENT** |
| Terrain normals (Unity export) | `prepare_terrain_normals` | gated on validation_full | **✗ ABSENT — confirms world-space normals export is broken (matches Audit Status 2026-04-27)** |
| Heightmap raw u16 (Unity export) | `prepare_heightmap_raw_u16` | gated on validation_full | **✗ ABSENT** |
| Saliency / feature refinement | Bundle H-saliency `register_saliency_pass` | not appended to controller pipeline | **✗ ABSENT** |
| LOD / horizon sampling | Bundle K/L/N/O passes | none appended | **✗ ABSENT** |
| Stratigraphy / banded geology | Bundle G `terrain_banded` | not appended | **✗ ABSENT (matches A3 E-2 finding)** |
| Waterfalls (mesh + particle) | `pass_water` from Bundle C, `emit_particle_systems` | `"waterfalls"` never appended; emit_particle_systems gate unreachable | **✗ ABSENT (dead code)** |
| Materials_v2 splat | `materials_v2` | only if `validation_full in pipeline` | **✗ ABSENT** |
| Geology validator | Bundle I | not appended | ✗ |
| Asset emission (Bundle E) | terrain_assets passes | not appended | ✗ |

### Score: 3 ✓ (with caveats), 14 ✗

Of 17 critical AAA features, **only 3 are produced** by the default production pipeline (erosion, cliffs, water-network-as-Python-object). The other 14 are either explicitly absent or behind dead/unreachable conditionals.

---

## Step 5 — `_terrain_world.py` separate pipeline?

**No.** `_terrain_world.py` (1498 lines) defines pass *implementations* — `pass_macro_world`, `pass_generate_low_freq_hmap`, `pass_generate_high_freq_detail`, `pass_composite_hmap`, `pass_structural_masks`, `pass_erosion`, `pass_validation_minimal`, plus utilities like `extract_tile`, `validate_tile_seams`, `erode_world_heightmap`. **It contains no `pipeline.append`, no pipeline orchestration**, confirmed by grep returning zero matches for `pipeline\s*=` and `pipeline\.append` across the file.

Every consumer of these passes goes through `terrain_pipeline.register_default_passes` (which wraps the `_terrain_world` functions in `PassDefinition` objects, registers them in `TerrainPassController.PASS_REGISTRY`) and then through `_execute_terrain_pipeline` in `environment.py`. The orchestration is **only** in `environment.py`.

Conclusion: `_terrain_world.py` is a *function library*, not a pipeline. The production pipeline is unambiguously the one assembled in `handle_generate_terrain` (lines 2004-2034) and post-processed by `_execute_terrain_pipeline` (lines 3050-3095).

---

## Cross-References

- [A3 Terrain Shape & Erosion](A3_terrain_shape_erosion.md) — E-1 erodibility bug, E-2 stratigraphy delta loss, E-3 pure-Python loop unfit at AAA scale. All confirmed against the `erosion` pass that runs in the production sequence above.
- [I1 Delta Application Audit](I1_delta_application_audit.md)
- [I5 Pass Ordering Audit](I5_pass_ordering_audit.md) — note the pipeline observed there matches what we recovered here.
- [project_audit_status_2026_04_27](../../../C:/Users/Conner/.claude/projects/.../project_audit_status_2026_04_27.md) — confirms 30 P0 blockers including "sim/ package entirely bypassed in production" and "world-space normals export broken". Both are corroborated by this audit: sim/ passes are not in the controller pipeline, and `prepare_terrain_normals` is gated behind validation_full and never injected.

---

## Severity (P0 candidates from this audit)

1. **P0 — Splatmap/materials never produced.** `materials_v2` is gated on `validation_full in pipeline`, but the controller path appends only `validation_minimal`. No production tile gets a splatmap. Unity import gets terrain with one default material.
2. **P0 — Unity export prerequisites never run on production tiles.** `prepare_terrain_normals` and `prepare_heightmap_raw_u16` share the same dead gate. Confirms the "world-space normals export broken" entry in MASTER_AUDIT.
3. **P0 — Vegetation scatter never executes.** Bundle E passes are registered but never appended. AAA terrain ships with zero foliage from the pipeline.
4. **P0 — Saliency / LOD / Bundle K/L/N/O all dead.** Registered, never appended. The bundles exist in code but contribute nothing to a tile.
5. **P0 — `emit_particle_systems` gate is unreachable.** Waterfall particle systems can never be emitted by the controller path because `"waterfalls"` is never appended. The append-site at L2033 is dead code.
6. **P1 — Caves are practically dead.** Only run if a caller manually wires `scene_read.cave_candidates` AND `controller_apply_caves=True`. The standard AAA biome flow at L8348-8359 supplies neither.
7. **P1 — `structural_masks` registered twice in pipeline.** Lines 2006 and 2019 both append it. The controller's PASS_REGISTRY allows re-execution; the cost is correctness-neutral but doubles work, and the second invocation refreshes against eroded height (which is the intent — but it should be commented as such).
8. **P2 — `compose_map` is a misnomer.** No function bears that name. Future audits should refer to `handle_generate_terrain` controller branch + `_execute_terrain_pipeline` injection logic. Suggest renaming the literal `"compose_map"` reviewer string at L2012 to match what it actually represents (it's the ID logged in scene_read to signal "this scene_read was authored by the inline pipeline composer").

---

## Files Read

- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\environment.py` (lines 1940-2240, 2755-3104, 8340-8395)
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\_terrain_world.py` (function index only — no pipeline orchestration found)
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_pipeline.py` (lines 1137-1260, `register_default_passes`)
- `C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\terrain_master_registrar.py` (bundle registration order)
