# K7 — Road / Path Wiring Deep Dive

**Date:** 2026-04-27
**Auditor:** K7
**Scope:** Whether the road/path generation system actually deforms the terrain heightmap and exports usable road data to Unity. Find ADDITIONAL wiring bugs beyond J7-P1 / J3-P0-2.

**Source files audited:**
- `veilbreakers_terrain/handlers/road_network.py` (~1742 lines)
- `veilbreakers_terrain/handlers/terrain_path_contracts.py` (205 lines)
- `veilbreakers_terrain/handlers/environment.py::handle_generate_road` (lines 5955-6393)
- `veilbreakers_terrain/handlers/terrain_twelve_step.py::_generate_road_mesh_specs / Step 9` (lines 758-881, 1178-1233)
- `veilbreakers_terrain/handlers/environment_scatter.py` road exclusion (lines 3220-3315)
- `veilbreakers_terrain/handlers/terrain_materials_v2.py::apply_sdf_road_blend` (lines 403-450, 715-720)
- `veilbreakers_terrain/handlers/terrain_unity_export.py` and `terrain_unity_export_contracts.py` (full)

---

## Headline finding

The repo contains **two parallel road systems** with one critical wiring fork:

1. **`terrain_twelve_step.run_twelve_step_world_terrain` (Step 9)** — full Rune pipeline (24-dir A* → smooth → 3-zone carve), writes `road_mask` + `road_sdf_dist` onto every per-tile `TerrainMaskStack`, and discards road mesh specs to a return field. **Production callers: ZERO.** Only 2 test files import it (`test_adjacent_tile_contract.py`, `test_live_readiness_regressions.py`).

2. **`environment.handle_generate_road` (`env_generate_road` MCP command)** — production entry point. Carves the Blender mesh's vertex Z values (real heightmap deformation), paints the `VB_TerrainSplatmap` vertex-color attribute, builds `road_mask`/`road_sdf_dist` arrays, and **never writes them to a `TerrainMaskStack`**. They are only returned in the response dict if `return_road_channels=True`.

The result: in production, road heightmap deformation does happen (✓), but every downstream consumer that reads `stack.road_mask` or `stack.road_sdf_dist` sees `None` (✗). This pile-drives J3-P0-2 and adds K7-P0-1 below.

---

## Findings

### K7-P0-1 (P0) — `handle_generate_road` never persists `road_mask`/`road_sdf_dist` to the TerrainMaskStack

**File:** `veilbreakers_terrain/handlers/environment.py:6137`
**Severity:** P0

`handle_generate_road` is the **only production entry point** for road generation (`env_generate_road` MCP command, registered in `blender_server.py:50`). At line 6137 it builds `road_mask, road_sdf_dist = _build_road_mask_and_sdf(...)`. These arrays are then used in only 4 ways:

```python
# Line 6262-6263, 6376-6377: scalar metadata in response dict
"road_mask_shape": list(road_mask.shape),
"road_mask_nonzero": int(road_mask.sum()),

# Line 6277-6278, 6391-6392: full tensor only when caller passes a flag
if bool(params.get("return_road_channels", False)):
    result["road_mask"] = road_mask.tolist()
    result["road_sdf_dist"] = road_sdf_dist.tolist()
```

**Verified absence:** A grep for `stack\.set\(.*road_(mask|sdf)` across `veilbreakers_terrain/handlers/` finds exactly two production hits — both inside `terrain_twelve_step.py:1263-1264`. Zero hits in `environment.py`, `road_network.py`, or anywhere else in the production runtime. No fixture, helper, or post-pass writes the channels onto the live stack after `handle_generate_road` returns.

**Downstream consumers that go silent:**

| Reader | File:Line | Behaviour when channels are `None` |
| --- | --- | --- |
| `environment_scatter._stack_value("road_mask")` | `environment_scatter.py:3239` | Falls back to bpy name-string scan ("road" in obj.name). Soft P1 — works only when a mesh strip exists, useless for `terrain_only` paths/trails (lines 6248-6279). |
| `environment_scatter._stack_value("road_sdf_dist")` | `environment_scatter.py:3244` | SDF clearance check is silently skipped — trees / rocks / scatter can place flush against road edges with zero buffer. |
| `procedural_grass._stack_attr("road_sdf_dist")` | `procedural_grass.py:362` | Falls back to deriving SDF on-the-fly from `road_mask`; if both are `None`, grass placement ignores roads entirely. |
| `terrain_materials_v2.apply_sdf_road_blend` | `terrain_materials_v2.py:718-720` | `if road_sdf_dist is not None` guard → entire road-edge gravel/cobble blend is silently skipped. The Unity-exported `splatmap_weights_layer` therefore has **no road texture** at road locations in production. |
| `terrain_wildlife_zones`, `terrain_semantics`, `terrain_caves`, `_terrain_depth`, `_terrain_noise` | various | Various other reads via `stack.get("road_sdf_dist")` — all degrade silently. |

**Fix:** After `_build_road_mask_and_sdf` in `handle_generate_road`, call `stack.set("road_mask", road_mask, "generate_road")` and `stack.set("road_sdf_dist", road_sdf_dist, "generate_road")` on the active `TerrainMaskStack` for `terrain_name`. This requires `handle_generate_road` to look up the stack via the same controller registry the other handlers use (already present — `environment.py:2078` writes `mask_stack.set("height", ...)`).

---

### K7-P0-2 (P0) — Road data is NEVER exported to Unity

**Files:** `veilbreakers_terrain/handlers/terrain_unity_export.py`, `terrain_unity_export_contracts.py`
**Severity:** P0

Verified by `grep -i "road|path_network|spline"` against both files: **zero hits**. The Unity export pipeline writes:
- 16-bit RAW heightmaps
- Packed RAW splatmap groups (RGBA uint8) sourced from `stack.splatmap_weights_layer`
- RAW detail layers
- A few binary support files

But it does **not** export:
1. **Road splines / centerlines** — `routes`, `path` (the `final_pts` lists from `road_network.compute_road_network`) are computed and returned in handler response only.
2. **Road mesh** — the `_Road` mesh object built by `_build_road_strip_geometry` (`environment.py:5289`) lives in `bpy.data.objects` but is not in any Unity export path. Searched `terrain_unity_export.py` for `_Road` / `road_obj` / `road_mesh` — **zero hits**.
3. **Road mask / SDF** — even if K7-P0-1 were fixed, `road_mask` and `road_sdf_dist` are not in the export channel list. They could be exported as detail-layer RAW files but are not.
4. **Bridge meshes** — `bridge_object_names` is populated in `handle_generate_road` response (line 6361) but not collected by the Unity manifest.
5. **`PathNetworkContract`** — the AI-readable contract (`terrain_path_contracts.py`) is built (`environment.py:6216`) and returned in the handler response, but `terrain_unity_export.py` has no consumer.

Unity therefore has **no knowledge of any road**. NavMesh bake (`terrain_navmesh_export.py`) also has no road import. The road system is, from Unity's perspective, **dead on arrival**.

**Fix:** Add a `roads.json` (spline list with width, road_type, surface key, switchback metadata, bridge spans) and/or a `road_mask.raw` detail-layer file to the Unity manifest writer. Wire `result["path_network_contract"]` through `handle_export_for_unity` → manifest.

---

### K7-P0-3 (P0) — Splatmap road texture is painted on a dead vertex-color channel that doesn't reach Unity

**File:** `veilbreakers_terrain/handlers/environment.py:5117-5257` (`_paint_road_mask_on_terrain`) + `terrain_unity_export.py:1061+` (`_write_splatmap_groups`)
**Severity:** P0

`handle_generate_road` calls `_paint_road_mask_on_terrain` (line 6195), which writes road texture weights into the `VB_TerrainSplatmap` **vertex-color attribute** on the terrain mesh (`environment.py:5130-5135`). This is a Blender preview channel.

Unity's splatmap export (`terrain_unity_export.py:1061-1138, 1259, 1522-1526`) reads from `stack.splatmap_weights_layer` (a 3-D numpy array on the `TerrainMaskStack`). These two pipelines are **completely disconnected**:

```
Blender preview path:   handle_generate_road → _paint_road_mask_on_terrain → mesh.color_attributes["VB_TerrainSplatmap"]
                                                                              (END — never read by Unity exporter)

Unity export path:      terrain_materials_v2.compute_splatmap_weights → stack.set("splatmap_weights_layer")
                            ↑ apply_sdf_road_blend depends on stack.road_sdf_dist (None — see K7-P0-1)
                                                              → terrain_unity_export._write_splatmap_groups → splatmap_NN.raw
```

`apply_sdf_road_blend` (`terrain_materials_v2.py:715-720`) gracefully no-ops when `road_sdf_dist` is `None`, which it always is in production (K7-P0-1). So the Unity-bound `splatmap_weights_layer` contains zero road material. Visually in Unity, the road bed will be the same texture as the surrounding biome — grass, dirt, rock — even though the heightmap has been carved (so there's a flat grass strip cutting across the hills).

**Fix:** Either
(a) make `_paint_road_mask_on_terrain` ALSO write directly into `stack.splatmap_weights_layer` on the road-channel index, or
(b) ensure K7-P0-1 fix lands so `apply_sdf_road_blend` actually fires before the Unity export reads `splatmap_weights_layer`.

Option (b) is the cleaner architectural answer.

---

### K7-P1-1 (P1) — Production road system is duplicated and divergent from the canonical Rune pipeline

**Files:** `environment.handle_generate_road` vs `terrain_twelve_step._generate_road_mesh_specs`
**Severity:** P1

Both code paths claim to be "the" road system but differ in non-trivial ways:

| Step | `terrain_twelve_step` (Step 9, **test-only**) | `environment.handle_generate_road` (**production**) |
| --- | --- | --- |
| Cost map | `_build_road_cost_map(hmap, rock_hardness, water_surface)` — derived from erosion delta + flow accumulation | `_resolve_road_cost_context(params, heightmap=...)` — opaque, mostly external |
| Routing | `road_network._astar_24dir` directly | `_solve_road_path_with_network` wrapping `compute_road_network` |
| Smoothing | `_terrain_noise.smooth_road_path(samples_per_segment=10)` — Catmull-Rom | RDP simplification + `enforce_turn_radius` + 5 m subdivision (no Catmull-Rom) |
| Carve | `_apply_road_profile_to_heightmap` (3-zone cosine + linear + cosine feather) — **carves on numpy heightmap, returns carved + mask + sdf** | `_apply_road_profile_to_heightmap` from same module, but called via different signature; result writes back to mesh vertices, not stack |
| Stack writes | `stack.set("road_mask", ...)`, `stack.set("road_sdf_dist", ...)` | None |
| Mesh build | `road_specs` dict — **no actual mesh object** | `bpy.data.meshes.new(road_mesh_name)` — full bmesh strip |
| Splatmap | None — relies on `apply_sdf_road_blend` reading stack | `_paint_road_mask_on_terrain` vertex-color paint (K7-P0-3) |

Two `_apply_road_profile_to_heightmap` implementations exist (one in each file — `CALLABLE_DUPLICATE_REVIEW.json:6` flags this). They are NOT identical — `environment.py` version operates in world-space and writes to mesh; `terrain_twelve_step.py` version operates in grid-space and returns mask/SDF.

**Risk:** any future fix to one is forgotten in the other. The test suite covers `terrain_twelve_step` heavily (`test_road_channels.py`, `test_road_pipeline.py`) but `handle_generate_road` runs through different mocked paths.

**Fix:** Pick one (`terrain_twelve_step._generate_road_mesh_specs` is the more correct architecturally — operates on `world_eroded` BEFORE tile extraction, so seam continuity is automatic) and migrate `handle_generate_road` to delegate to it. Then the Step 9 production gap closes.

---

### K7-P1-2 (P1) — `path_network_contract` is built but `path_network_contract_issues` are not enforced

**Files:** `road_network.py:1258`, `terrain_path_contracts.py:140-195`, `environment.py:6216-6229`
**Severity:** P1

`validate_path_network_contract` returns a list of issue dicts including codes like `path_grade_exceeds_budget`, `bridge_clearance_too_low`, `deep_water_crossing_requires_bridge`. Both `road_network.compute_road_network` (line 1258) and `environment._build_generated_road_path_contract` build the contract and validation issues.

Both production handlers return the issues in the response dict (`path_network_contract_issues`). **No code reads them.**

```bash
$ grep -r "path_network_contract_issues" --include="*.py" veilbreakers_terrain/
# Only writers (environment.py, road_network.py, tests). No reader.
```

The contract validation is pure decoration — failing road grades, missing bridge clearance, water crossings without bridges all generate issue codes but never raise, never warn, never block export. A road that exceeds 18% grade on a `paved_road` (where AASHTO max is 8%) will ship to Unity unmodified.

**Fix:** Add a strict-mode env flag (mirror `VEILBREAKERS_ROAD_STRICT`) that raises on any contract issue with severity ≥ warning. At minimum, log issues at WARNING level rather than silently dropping them in the response dict.

---

### K7-P1-3 (P1) — `_paint_road_mask_on_terrain` re-normalises blended weights, mutating non-road splatmap channels even on cells distant from the road

**File:** `environment.py:5232-5235`
**Severity:** P1

```python
mixed = cur * (1.0 - m) + target_color[None, :] * m
totals = mixed.sum(axis=1, keepdims=True)
mixed = np.where(totals > 1e-6, mixed / np.where(totals > 1e-6, totals, 1.0), mixed)
colors[loop_indices] = mixed.astype(np.float32)
```

The blend zone is gated by `total_radius * 1.12` (line 5240), so only loops within ~9 m of the path centreline are touched. But within that zone, the existing splatmap weights are **renormalised to sum to 1** even when the road blend mask `m` is near zero (e.g. at the edge of the influence radius). For a cell that previously had `(grass=0.6, rock=0.0, road=0.0, snow=0.0)` (sum 0.6, expected — partially-covered loops in CORNER domain), the renormalisation turns it into `(grass=1.0, rock=0.0, road=0.0, snow=0.0)`, **destroying the snow / rock contribution at adjacent cells**.

This is doubly bad because the layer is `VB_TerrainSplatmap` which is a vertex-color preview; the Unity export reads `splatmap_weights_layer` instead — so the corruption is invisible in Unity but visible in Blender preview, exactly the wrong way around for QA.

**Fix:** Skip the renormalisation when `m < 1e-3` and clamp to original weights when `cur.sum() < 0.5` (likely uninitialised loop).

---

### K7-P1-4 (P1) — Production road carving never runs through the world heightmap before tile extraction

**Files:** `environment.handle_generate_road` (line 6125), tile extraction in `terrain_twelve_step.py:1234`
**Severity:** P1

`handle_generate_road` operates **per-Blender-object** (one terrain at a time, one road at a time). The carve happens on `heightmap = heights.reshape(rows, cols)` extracted from a single object's bmesh. There is no world-level orchestration: a road that crosses a tile boundary in production is generated independently on each tile, with no shared waypoint state, no shared cost map, no seam continuity.

Compare to `terrain_twelve_step.py:1180-1233` (test-only) which carves `world_eroded` BEFORE per-tile extraction at line 1245. That ordering is the only correct one for tile-spanning roads.

**Risk:** when the production pipeline scales to >1 tile (it currently doesn't, but the world orchestrator pretends to), road continuity across tile boundaries is undefined. A road crossing tile (0,0)→(1,0) will simply terminate at the seam.

**Fix:** Tied to K7-P1-1 — migrating production to the Step 9 architecture solves this for free.

---

### K7-P2-1 (P2) — Path is **not contour-following at the production-mesh level**; A* path-following ends at the carve step

**File:** `environment.py:6125-6162`
**Severity:** P2

The 24-dir A* in `road_network._astar_24dir` IS contour-following with the AASHTO cost function (slope penalty + cross-slope penalty) — confirmed at lines 277-303 of `road_network.py`. Good.

But after the path is found, `_apply_road_profile_to_heightmap` **flattens the road bed** (zone 1 cosine blend toward `nearest_road_elev`, `terrain_twelve_step.py:949-952`) — which is correct AASHTO behaviour for vehicles. The contour-following property only manifests in *where the road runs in the XY plane*, not in *how Z is preserved*. So the road follows hillside contours horizontally but flattens its own bed vertically. This is the Witcher 3 / KCD2 standard and the implementation matches.

**However**: the carve writes `nearest_road_elev` from `path_elevs[idx_flat]` which samples the **pre-carve** heightmap at the path cell. On a steep grade, the path cell's pre-carve elevation may already exceed the AASHTO max — the carve preserves that bad elevation rather than re-grading. The switchback insertion (`_generate_switchback_points`) tries to compensate by inserting hairpins, but the carve doesn't know about them — switchbacks affect the route geometry, not the carve.

This is partial: not P0 because vehicles can still drive over 15% grades; not even fully broken because the AAA cost function discourages such routes upstream. Flag as P2.

---

### K7-P2-2 (P2) — `handle_generate_road` legacy fallback doesn't write `road_mask` either

**File:** `environment.py:6090-6102` (legacy fallback path)
**Severity:** P2

Tied to J7-P1: when `VEILBREAKERS_ROAD_STRICT=0`, the legacy `generate_road_path_grid_legacy` fallback runs. Even after the K7-P0-1 fix, the legacy branch needs the same `stack.set` calls — otherwise users in legacy mode silently skip downstream wiring.

---

### K7-P3-1 (P3) — `road_network.compute_road_network` writes nothing; it's pure data

This is by design — `road_network.py` is the math kernel. The wiring is the caller's responsibility (`environment.handle_generate_road`). Not a bug, but worth documenting that the file is intentionally side-effect-free.

---

## Confirmed (not new — already in audit ledger)

- **J3-P0-2** (active-pass silent-degradation cascade for `road_sdf_dist`): K7-P0-1 above is the upstream root cause. Every downstream `stack.get("road_sdf_dist") is not None` guard fires silently in production.
- **J7-P1** (road fallback to legacy 8-dir A*): confirmed at `environment.py:6090-6102`. K7-P2-2 extends this with an additional silent-degradation observation in the legacy branch.
- **J6** (`apply_collision_exclusion` unused in `environment_scatter.py`): independently confirmed via grep — function is imported (line 57) but only called in `_scatter_engine.py:1297`. Not strictly road-related but does intersect with the scatter→road interaction; trees/rocks have no inter-instance collision pruning either.

## NOT confirmed P0

- "Roads float above terrain": **NO** — `handle_generate_road` does write carved Z values back to `mesh.vertices.foreach_set("co", co_road)` at line 6162 (`environment.py`). Heightmap deformation is real in Blender. The road BED matches the carved terrain.
- "Roads sink below terrain": **NO** — same write happens. Plus the Blender road strip mesh (`environment.py:5289 _build_road_strip_geometry`) is offset +0.01-0.03 m above the carved terrain (line 6191) so the strip never z-fights with the terrain.

The P0s are about *export* and *channel persistence*, not heightmap deformation per se.

---

## Summary table

| ID | Severity | File | Issue |
| --- | --- | --- | --- |
| K7-P0-1 | P0 | environment.py:6137 | `handle_generate_road` builds `road_mask`/`road_sdf_dist` but never writes them to TerrainMaskStack — every downstream consumer sees `None` |
| K7-P0-2 | P0 | terrain_unity_export.py | No road export to Unity (no splines, no mesh, no mask, no SDF, no contract) |
| K7-P0-3 | P0 | environment.py:5117 + terrain_materials_v2.py:715 | Splatmap road texture painted on `VB_TerrainSplatmap` vertex-color preview channel; Unity-exported `splatmap_weights_layer` gets no road texture because `apply_sdf_road_blend` no-ops when `road_sdf_dist` is None |
| K7-P1-1 | P1 | environment.py vs terrain_twelve_step.py | Two divergent road implementations; production uses the wrong one (test-only Step 9 has the correct stack writes) |
| K7-P1-2 | P1 | road_network.py:1258 | `path_network_contract_issues` validated and returned but never read or enforced |
| K7-P1-3 | P1 | environment.py:5232 | `_paint_road_mask_on_terrain` renormalises splatmap weights even at near-zero road influence, mutating distant cells' material distribution |
| K7-P1-4 | P1 | environment.py:6125 | Production road carving runs per-object, never on world heightmap before tile extraction; tile-spanning roads are undefined |
| K7-P2-1 | P2 | terrain_twelve_step.py:949 | Carve uses pre-carve `nearest_road_elev`; sub-budget grades on path cells preserved verbatim, switchback geometry not reflected in Z carve |
| K7-P2-2 | P2 | environment.py:6090 | Legacy fallback (J7-P1 path) also doesn't write stack — same silent degradation |

**3 new P0s, 4 new P1s, 2 new P2s.**

---

## Suggested remediation priority

1. **K7-P0-1 first** — single-line fix surface (`stack.set("road_mask", ...)`, `stack.set("road_sdf_dist", ...)` after line 6141 in `environment.py`). Closes 4 downstream silent-degradation paths in one commit.
2. **K7-P0-3 follows automatically** once K7-P0-1 lands — `apply_sdf_road_blend` will start firing and Unity will get road texture.
3. **K7-P0-2** requires new export code — add `roads.json` writer to `terrain_unity_export.py` consuming `result["path_network_contract"]`.
4. **K7-P1-1** is the architectural cleanup — migrate `handle_generate_road` to call `_generate_road_mesh_specs` from `terrain_twelve_step.py`. Solves K7-P1-4 and K7-P2-2 simultaneously.

Counter-recommendation: do NOT try to fix K7-P1-1 first — the architectural migration is multi-day work; the K7-P0-1 single-line fix unblocks 80% of the downstream visual quality.
