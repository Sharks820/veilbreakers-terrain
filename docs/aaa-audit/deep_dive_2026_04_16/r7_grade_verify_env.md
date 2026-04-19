# R7 Grade Verification — environment.py
Date: 2026-04-17
Auditor: Claude Opus (R7 independent verification)
Source: C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\veilbreakers_terrain\handlers\environment.py (5435 lines)
CSV: C:\Users\Conner\OneDrive\Documents\veilbreakers-terrain\docs\aaa-audit\GRADES_VERIFIED.csv (68 env.py rows: IDs 58-72, 301-310, 1107-1108, 1430-1470)

## Executive Summary
- Functions in source (top-level `def`): **68**
- Functions in CSV: **68**
- Coverage gap (in source, not in CSV): **0**
- Grades verified correct: **62**
- Grades too generous (CSV higher than actual): **0**
- Grades too harsh (CSV lower than actual): **2** (IDs 1450, 1463 — minor)
- BUG descriptions inaccurate / overstated: **4** (iteration counts inflated for BUG-186; weakness wording inaccurate for IDs 1445, 1450, 1463)
- Confirmed bugs: **BUG-186 triple-loop CONFIRMED**, **BUG-187 triple-loop CONFIRMED (twice)**, all 6 Phase 4.3 hotspots CONFIRMED, both seam-critical export guards CONFIRMED

## BUG-186 Verification (_apply_road_profile_to_heightmap)
**Location:** lines 2778-2833
**Loop structure CONFIRMED as triple-nested Python:**
- **Outer loop** (line 2798): `for (r0, c0), (r1, c1) in zip(path, path[1:]):` → iterates N-1 segments where N = path length
- **Middle loop** (line 2806): `for rr in range(r_min, r_max + 1):` → segment bbox rows
- **Inner loop** (line 2807): `for cc in range(c_min, c_max + 1):` → segment bbox columns

Variables: `r_min/r_max/c_min/c_max` derived from `outer_radius = road_half_width + shoulder_width` (lines 2795-2804). Inner body calls `_point_segment_distance_2d` (pure Python) and `_smootherstep` (Python).

**Iteration count assessment:**
- For a 1024² terrain with 500-segment path, width_cells=5, shoulder=5 → outer_radius=7.5 → ~15×15=225 cells per bbox → 500×225 = **112,500 iterations**
- For width_cells=10, shoulder=10 → outer_radius=15 → 31×31 = 961 cells per bbox → 500×961 = **480,500 iterations**
- The master-audit "~25M iterations" figure is **overstated** for typical inputs; the realistic range is 100K–5M. Still catastrophically slow for a triple-Python-loop on a hot path. **Triple-loop claim CONFIRMED.**

CSV grade B+ is fair given the loops are correctness-correct, just slow. VERDICT: **CONFIRMED — structure accurate, iteration count in prior writeup inflated.**

## BUG-187 Verification (_apply_river_profile_to_heightmap)
**Location:** lines 2836-2932
**Loop structure CONFIRMED as TWO separate triple-nested Python loops:**

**First pass — carve channel (lines 2862-2894):**
- **Outer** (line 2862): `for (r0, c0), (r1, c1) in zip(path, path[1:]):` → segments
- **Middle** (line 2870): `for rr in range(r_min, r_max + 1):`
- **Inner** (line 2871): `for cc in range(c_min, c_max + 1):`

**Second pass — bank smoothing (lines 2908-2930):**
- **Outer** (line 2908): `for (r0, c0), (r1, c1) in zip(path, path[1:]):`
- **Middle** (line 2913): `for rr in range(r_min, r_max + 1):`
- **Inner** (line 2914): `for cc in range(c_min, c_max + 1):`

Both triple-loops run per river-carve call. The `neighborhood_mean` computation at 2896-2907 uses vectorized NumPy (9-sample mean via np.pad + slicing — GOOD), but the application loop at 2908-2930 is Python. CSV evidence says "double Python loop" — **DISPUTED — it is actually two triple-nested Python loops, strictly worse than the "double loop" framing.** The weakness description in CSV should be upgraded to "double TRIPLE-nested Python loop" to match BUG-186 framing.

Grade B+ matches — same severity as BUG-186.

## Phase 4.3 Hotspot Verification
| Function | In Source? | Line | Loop Type | Current Grade in CSV | Grade Correct? |
|---|---|---|---|---|---|
| `_create_terrain_mesh_from_heightmap` | YES | 1040 | Single Python `for vert in bm.verts:` at line 1074 w/ bilinear interp (cols×rows) | A- | YES |
| `handle_paint_terrain` | YES | 2497 | Double Python `for face in bm.faces:` × `for rule in biome_rules:` (lines 2571, 2584) | B | YES |
| `_paint_road_mask_on_terrain` | YES | 3159 | Triple-equivalent: `for poly in polygons:` + `for loop_idx in loop_indices:` + `for (ax,ay),(bx,by) in zip(...)` (lines 3218, 3241, 3250) AND separate `for loop in mesh.loops:` + `for (ax,ay),(bx,by) in zip(...)` (lines 3253, 3268) | B+ | YES |
| `_build_level_water_surface_from_terrain` | YES | 4281 | Multiple double loops (lines 4329, 4349 BFS 3×3, 4365, 4413) | B+ | YES |
| `handle_carve_water_basin` | YES | 5002 | Two double Python loops (lines 5042, 5113) | B | YES |
| `_compute_vertex_colors_for_biome_map` | YES | 5390 | Single Python `for v in mesh.vertices:` at 5405 with silent bare `except Exception: pass` at 5426-5427 | B+ | YES |

All 6 hotspots exist, all have the claimed loop structure, all grades accurate.

## Seam Helper Verification
### _resolve_height_range (line 783)
**CONFIRMED** — `allow_local_fallback: bool = True` kwarg at line 787; guard at lines 814-815:
```python
if not allow_local_fallback:
    return None
```
Returns `None` when no explicit range is provided AND local fallback is disabled. Docstring (lines 789-802) explicitly documents this as the tiled-world safety mechanism. Grade A CORRECT.

### _resolve_export_height_range (line 823)
**CONFIRMED** — At lines 836-847:
```python
if params.get("tiled_world") or params.get("use_global_height_range"):
    resolved = _resolve_height_range(
        params, heightmap, allow_local_fallback=False
    )
    if resolved is None:
        raise ValueError(
            "tiled_world / use_global_height_range requires an explicit "
            "'height_range' ..."
        )
```
Raises ValueError if tiled_world=True without explicit range. The fail-fast behavior is present and correct. Grade A CORRECT.

## New Rows Verification (IDs 1430-1470, 41 rows verified)
| ID | Function | CSV Grade | R7 Grade | MATCH? | Notes |
|---|---|---|---|---|---|
| 1430 | _run_height_solver_in_world_space | A- | A- | YES | WorldHeightTransform wrapping confirmed (lines 137-161); clean |
| 1431 | _normalize_altitude_for_rule_range | A | A | YES | Correct normalization with epsilon guard (line 171) |
| 1432 | _resolve_noise_sampling_scale | A- | A- | YES | Priority cascade correct; KeyError silent fallback confirmed (line 188) |
| 1433 | _enhance_heightmap_relief | A- | A- | YES | p5/p95 percentile stretch; sign-aware (line 209 center calc) |
| 1434 | _temper_heightmap_spikes | A- | A- | YES | tanh compression + neighborhood blend; gate via `_SPIKE_PRONE_TERRAIN` at line 224 |
| 1435 | _apply_biome_season_profile | A- | A- | YES | Season overlay correct (lines 524-543); no season-key validation |
| 1436 | get_vb_biome_preset | A- | A- | YES | Deepcopy + season + tripo manifest injection; tripo manifest gated on `scatter_rules` presence not export_context (line 565) |
| 1437 | _validate_terrain_params | A | A | YES | Resolution/terrain_type/erosion validation with clear messages (lines 587-608) |
| 1438 | _resolve_terrain_tile_params | A- | A- | YES | Mutual-constraint enforcement (lines 647-649); world_origin assumes square tiles (line 658-659) |
| 1439 | _export_heightmap_raw | A | A | YES | float64→uint16 LE + flipud + shared range (lines 684-727) |
| 1440 | _export_splatmap_raw | A- | A- | YES | 4-channel normalize-sum + flipud + uint8; no warning on >4 channel input (line 737 raises on <4) |
| 1441 | _export_world_tile_artifacts | A- | A- | YES | Clean artifact aggregation (lines 751-780); no file size assertion |
| 1442 | _resolve_height_range | A | A | YES | See seam helper section above |
| 1443 | _resolve_export_height_range | A | A | YES | See seam helper section above |
| 1444 | _resolve_water_path_points | A | A | YES | Fail-fast on bad arity via ValueError (lines 917-920); 2D/3D both handled |
| 1445 | _smooth_river_path_points | A- | A- | YES on grade; NO on weakness | **Weakness description INACCURATE**: CSV says "No handling for degenerate paths with fewer than 2 points". The function at line 938 has explicit guard `if len(path_points) < 3: return ...`. Guard EXISTS — weakness needs rewording. Grade still A-. |
| 1446 | _clamp01 | A | A | YES | max(0, min(1, float(x))) |
| 1447 | _smootherstep | A | A | YES | x * x * x * (x * (x * 6.0 - 15.0) + 10.0) confirmed (line 2754). C2 continuous Perlin smootherstep. |
| 1448 | _point_segment_distance_2d | A | A | YES | Dot-product clamped t; returns (dist, t) |
| 1449 | _derive_river_surface_levels | A- | A- | YES | Monotonic downhill constraints (lines 2958-2962); no flat-terrain detection |
| 1450 | _sample_path_indices | A- | A | **MISMATCH** | **Weakness description INACCURATE**: CSV says "Forced intermediate indices not supported — only start/end forced". Code at line 2971 accepts `forced_indices: set[int] | None = None` and at line 2983 checks `if idx in forced`. **Forced intermediate indices ARE supported.** Grade should be upgraded to A. |
| 1451 | _collect_bridge_spans | A- | A- | YES | +1 padding and clearance calc (lines 3025-3029) |
| 1452 | _ensure_grounded_road_material | B+ | B+ | YES | **CONFIRMED** — presets dict at lines 3086-3107 has exactly 3 entries (mud/trail/dirt). Palette in `_paint_road_mask_on_terrain` at lines 3185-3196 has 10 surface types. Material-coverage gap verified. |
| 1453 | _paint_road_mask_on_terrain | B+ | B+ | YES | O(N×M) loop confirmed (see Phase 4.3 section); BUG-187-adjacent |
| 1454 | _build_road_strip_geometry | A- | A- | YES | Central-diff normals; quad faces; no UV gen |
| 1455 | _create_bridge_object_from_spec | B+ | B+ | YES | Silent `except: pass` on material failure at lines 3340-3341 |
| 1456 | _create_mesh_object_from_spec | B+ | B+ | YES | No MeshSpec validation before delegation to `_mesh_bridge.mesh_from_spec` (lines 3358-3364) |
| 1457 | _sanitize_waterfall_chain_id | A | A | YES | re.sub + fallback |
| 1458 | _serialize_validation_issues | A | A | YES | getattr-safe dict serializer |
| 1459 | _coerce_point3 | A | A | YES | Safe float coerce with fallback |
| 1460 | _offset_point3 | A | A | YES | Pure 3-tuple translate |
| 1461 | _resolve_waterfall_chain_id | A- | A- | YES | Three-tier fallback with deterministic hash |
| 1462 | _infer_waterfall_functional_positions | A- | A- | YES | 7 anchors derived; hardcoded offsets |
| 1463 | _publish_waterfall_functional_objects | B+ | A- | **MISMATCH** | **Weakness description INACCURATE**: CSV says "bpy.context.collection hardcoded — empties always land in active collection regardless of waterfall parent collection". Code at lines 3530-3534 actually resolves parent's `users_collection[0]` when parent is present: `if parent is not None: user_collections = getattr(parent, "users_collection", None); if user_collections: collection = user_collections[0]`. The function DOES use parent's collection when available. Grade should be A-. |
| 1464 | _ensure_water_material | A- | A- | YES | Complete node graph; `material_name` param differentiates per caller; but all callers using preview_fast=False get same shader tuning |
| 1465 | _apply_water_object_settings | A- | A- | YES | Cycles shadow disable; no EEVEE props (correct for Blender 4.x which uses material-level shadow_method) |
| 1466 | _build_terrain_world_height_sampler | A | A | YES | Bilinear grid sampler (lines 4124-4173); auto grid-dim detection |
| 1467 | _resolve_river_bank_contact | A- | A- | YES | 16-step march at line 4193; bisection fallback at lines 4220-4227 |
| 1468 | _resolve_river_terminal_width_scale | A- | A- | YES | Linear taper with min_scale clamp; usable_taper clamping (line 4248-4251) |
| 1469 | _compute_vertex_colors_for_biome_map | B+ | B+ | YES | Per-vertex Python loop at 5405; silent `except Exception: pass` at 5426-5427 confirmed |
| 1470 | _stable_seed_offset | A | A | YES | zlib.crc32 & 0xFFFF |

## B+ Grade Detailed Verification

### _ensure_grounded_road_material (ID 1452, line 3075)
**Code inspection (lines 3086-3107):**
```python
presets = {
    "mud": {...},
    "trail": {...},
    "dirt": {...},
}
```
**Only 3 presets: mud, trail, dirt.** Fallback at line 3109: `preset = presets.get(road_material_key, presets["dirt"])`.

**`_paint_road_mask_on_terrain` palette (lines 3185-3196):** 10 distinct surface types:
- trail, path, dirt, dirt_path, mud, muddy, gravel, stone, cobblestone_floor, cobblestone

**`handle_generate_road` `road_material_key` mapping (lines 3639-3651):** 11 entries, but after mapping only 4 unique material_keys emerge: dirt, trail, mud, cobblestone_floor.

**VERIFIED BUG:** `cobblestone_floor` is used by handle_generate_road but NOT present in `_ensure_grounded_road_material` presets → falls through to dirt default. That's a legitimate bug. Grade B+ CONFIRMED.

### _paint_road_mask_on_terrain (ID 1453, line 3159)
**Actual loop structure:**
1. Polygon pass (lines 3218-3251):
   - `for poly in polygons:` (N polygons)
     - `for vertex_index in vertex_indices:` (3-4 per polygon) — compute center
     - `for (ax,ay,_),(bx,by,_) in zip(path_world, path_world[1:]):` (M path segments) — min distance
     - `for loop_idx in loop_indices:` (3-4 per polygon) — blend color
2. Per-loop pass (lines 3253-3276):
   - `for loop_idx, loop in enumerate(mesh.loops):` (N loops)
     - `for (ax,ay,_),(bx,by,_) in zip(path_world, path_world[1:]):` (M path segments)

**Confirmed O(N×M)** where N = mesh loops/polygons, M = path segments. For a 1024² terrain with 200-segment road: 4M × 200 = 800M comparisons in the per-loop pass alone. Grade B+ CONFIRMED.

### _create_bridge_object_from_spec (ID 1455, line 3311)
**Silent except CONFIRMED** at lines 3340-3341:
```python
try:
    mat = create_procedural_material(object_name, material_key)
    if mat is not None:
        mesh_data.materials.append(mat)
except Exception:
    pass  # noqa: L2-04 best-effort non-critical attr write
```
Material failure silently swallowed — bridges render with no material. Grade B+ CONFIRMED.

### _create_mesh_object_from_spec (ID 1456, line 3345)
**No spec validation CONFIRMED** at lines 3358-3364:
```python
obj = mesh_from_spec(
    spec,
    name=object_name,
    location=location,
    ...
)
```
No `if not spec.get("vertices") or not spec.get("faces"): raise` before delegation. Bad MeshSpec produces degenerate mesh silently. Also silent material except at 3374-3375. Grade B+ CONFIRMED.

### _publish_waterfall_functional_objects (ID 1463, line 3518)
**CSV weakness description is INACCURATE.** Code at lines 3530-3534:
```python
collection = bpy.context.collection
if parent is not None:
    user_collections = getattr(parent, "users_collection", None)
    if user_collections:
        collection = user_collections[0]
```
The function DOES resolve to the parent's collection when parent is present and has user_collections. Only when parent is None OR parent has no user_collections does it fall back to `bpy.context.collection`. This is **reasonable fallback behavior**, not a bug.

**R7 Verdict: Grade should be A-, not B+.** The only genuine weakness is that when parent is None, empties land in active context (but this is acceptable for un-parented waterfall authoring).

### _compute_vertex_colors_for_biome_map (ID 1469, line 5390)
**Both weaknesses CONFIRMED:**
- Per-vertex Python loop at line 5405: `for v in mesh.vertices:`
- Silent `except Exception: pass` at lines 5426-5427:
```python
except Exception:
    pass  # noqa: L2-04 best-effort non-critical attr write
```
For a 512² terrain = 262K iterations of Python per-vertex biome lookup. HIGH perf hotspot confirmed. Silent except hides biome config mismatches. Grade B+ CONFIRMED.

## Grade Mismatches (CSV ≠ R7)
| ID | Function | CSV Grade | R7 Grade | Correction Reason |
|---|---|---|---|---|
| 1450 | _sample_path_indices | A- | A | Weakness ("forced intermediate indices not supported") contradicts actual code which accepts and uses `forced_indices: set[int]` param at line 2971 and line 2983 |
| 1463 | _publish_waterfall_functional_objects | B+ | A- | Weakness claims collection is "hardcoded" but code explicitly resolves parent's users_collection[0] at lines 3530-3534 before falling back to context.collection |

Both mismatches are MINOR (half-grade difference) and affect weakness DESCRIPTIONS more than the grade-severity tier. Neither changes the audit's overall story.

## Additional Weakness-Description Corrections (grade unchanged)
| ID | Function | Issue | Correction |
|---|---|---|---|
| 1445 | _smooth_river_path_points | Weakness says "No handling for degenerate paths with fewer than 2 points". | Guard at line 938: `if len(path_points) < 3: return [...]` — degenerate paths ARE handled. Remove from weakness list. |
| 305 (row 306) | _apply_river_profile_to_heightmap | Evidence says "double Python loop". | It's TWO separate TRIPLE-nested Python loops (lines 2862-2894 and 2908-2930). Should be labeled as aggressive as BUG-186. |
| — | BUG-186 iteration count | Master audit cites "~25M iterations per 1km road". | Realistic bounds: 100K–5M depending on width/shoulder params. Structure is correct; magnitude is conservative (should say "millions of iterations per road"). |

## Missing from CSV (in source, not audited)
**NONE.** All 68 top-level `def` functions in environment.py are present in the CSV with grades. Diff of function-name sets produced zero missing entries.

## Handle-Function Coverage Check (task prompt)
- `handle_generate_road` → PRESENT in CSV (ID 65, line 3617, grade B+) ✓
- `handle_carve_river` → PRESENT in CSV (ID 59, line 2609, grade B+). **Note:** no function named `handle_build_river` exists in source; the river handler is named `handle_carve_river`.
- `handle_generate_waterfall` → PRESENT in CSV (ID 68, line 2184, grade A-) ✓
- `handle_build_bridge` → **DOES NOT EXIST** in environment.py. Bridge creation is handled inside `handle_generate_road` (which calls `_collect_bridge_spans` + `_create_bridge_object_from_spec`). Not a coverage gap; the design is embedded-in-road-handler.
- `handle_scatter_vegetation` → **lives in `environment_scatter.py` line 1266**, outside environment.py scope. Correctly out of this audit.

## Confirmed Correct (no changes needed)
IDs 58 (A-), 59 (B+), 60 (B), 61 (B), 62 (B+), 63 (A-), 64 (B+), 65 (B+), 66 (A-), 67 (B+), 68 (A-), 69 (B+), 70 (B), 71 (A-), 72 (B+), 301 (A), 302 (B+), 303 (A-), 304 (B+), 305 (B+), 306 (B+), 307 (A-), 308 (B+), 309 (A), 310 (B-), 1107 (A), 1108 (A-), 1430 (A-), 1431 (A), 1432 (A-), 1433 (A-), 1434 (A-), 1435 (A-), 1436 (A-), 1437 (A), 1438 (A-), 1439 (A), 1440 (A-), 1441 (A-), 1442 (A), 1443 (A), 1444 (A), 1446 (A), 1447 (A), 1448 (A), 1449 (A-), 1451 (A-), 1452 (B+), 1453 (B+), 1454 (A-), 1455 (B+), 1456 (B+), 1457 (A), 1458 (A), 1459 (A), 1460 (A), 1461 (A-), 1462 (A-), 1464 (A-), 1465 (A-), 1466 (A), 1467 (A-), 1468 (A-), 1469 (B+), 1470 (A).

**Total: 66 of 68 exact matches.** Remaining 2 (IDs 1450, 1463) are weakness-description corrections where grade should nudge one step higher, not systematic misgrades.

## Additional Observations (not grade-affecting)
1. **BUG-186 / BUG-187 parallel structure.** Both functions share identical triple-nested-loop architecture over bbox-bounded segments. A single vectorization approach (NumPy masked stamping + np.where) would fix both. The FIXPLAN treating them as separate bugs is editorially correct but they should be fixed in one atomic commit.

2. **`_point_segment_distance_2d` is the hot function.** It is called N³ times inside both triple-loops. Making it a NumPy-vectorized `_point_segment_distance_2d_batch(points, segments) -> (dist, t)` is the single highest-leverage optimization target.

3. **`_ensure_grounded_road_material` material gap is a visible-defect bug.** `handle_generate_road` maps "gravel", "stone", "cobblestone" → `cobblestone_floor`, but `_ensure_grounded_road_material` has no `cobblestone_floor` preset. Roads with those surface keys silently get the "dirt" preset. This IS a B+ / user-visible bug, not just a polish item — consider upgrading severity to "important".

4. **Silent-except discipline.** Across env.py there are ~15 `except Exception: pass` or `except Exception: logger.debug(...)` blocks. Most are justified "best-effort non-critical attr write" for Blender stub compatibility, but the material-creation ones (IDs 1455, 1456, and the one in `handle_generate_multi_biome_world` line 5351) would benefit from explicit fallback material instead of silent skip.

5. **Coverage is complete.** No missed top-level functions. The 68 entries match the 68 source-level `def` declarations exactly. Nested helpers (`_to_bbox`, `_serialize`, `_coerce_facing_direction`, `_edge_vertices`, `_blend_loop_color`, `_shore_factor`, `_sample`, `_candidate_score`) are intentionally not audited as they are local closures.
