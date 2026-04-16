# Context7 Round 2 — Per-Function Exhaustive Verification Results

**Status:** IN PROGRESS — 5 of 8 agents complete
**Date:** 2026-04-16

---

## RUNNING TOTALS

| Metric | Count |
|--------|:-----:|
| Functions audited | 170 |
| PASS | 133 |
| PARTIAL | 27 |
| FAIL | 10 |
| NEW bugs found | 5 |

---

## Agent 1: terrain_advanced.py — COMPLETE

**25 functions audited | 8 PASS | 14 PARTIAL | 3 FAIL**

### FAIL (3 — actual bugs)

| Function | File:Line | Issue |
|----------|-----------|-------|
| `apply_stamp_to_heightmap` | terrain_advanced.py:1311 | **BUG-01 CONFIRMED:** `blend = edge_falloff * (1-falloff) + edge_falloff * falloff` simplifies to `edge_falloff`. Falloff param has ZERO effect. Fix: `blend = (1.0 - falloff) + edge_falloff * falloff` |
| `handle_snap_to_terrain` | terrain_advanced.py:1432 | **NEW BUG-33:** `depsgraph = bpy.context.evaluated_depsgraph_get()` assigned to `_` (discarded). `ray_cast` on unevaluated object ignores modifiers (subdivision, displacement). Fix: use `terrain.evaluated_get(depsgraph)` |
| `handle_terrain_flatten_zone` | terrain_advanced.py:1677 | **NEW BUG-34:** `target_height` normalized to [0,1] but grid contains world-space Z. Produces garbage blend. Fix: pass target_height as-is. Also 6 lines of dead computation (lines 1696-1700). |

### PARTIAL (14 — perf issues, not correctness)

All 14 PARTIAL verdicts share common patterns:
- `.astype(np.float64).copy()` redundancy (4 occurrences) — use `np.array(x, dtype=np.float64, copy=True)`
- bmesh vertex iteration instead of `foreach_get` (5 handlers) — bmesh lacks foreach_get, architecturally unavoidable
- Python nested loops for erosion/flow/stamps (4 functions) — should vectorize with `np.roll`/`np.meshgrid`
- `compute_flow_map` (line 999) — correct algorithm but triple-nested Python loop, ~500x slower than vectorized

### KEY PASS: `flatten_terrain_zone` (line 1496) — exemplary vectorized numpy with `meshgrid(indexing="ij")`, smoothstep, broadcasting

---

## Agent 2: terrain_sculpt.py + terrain_features.py + coastline.py + atmospheric_volumes.py — COMPLETE

**40 functions audited | 29 PASS | 9 PARTIAL | 2 FAIL**

### FAIL (2 — critical bugs)

| Function | File:Line | Issue |
|----------|-----------|-------|
| `handle_sculpt_terrain` | terrain_sculpt.py:326 | **NEW BUG-35:** Missing `bm.normal_update()` before `bm.to_mesh()`. Context7 docs show this is REQUIRED after vertex edits. Without it, face normals are stale — causes broken shading, lighting artifacts, shadow errors in-game. CRITICAL for AAA. |
| `generate_ice_formation` | terrain_features.py:1867 | **BUG-03 CONFIRMED:** `kt` references stale outer loop value (always ~1.0). ALL stalactite faces get blue_ice material. Gradient frosted→clear→blue never varies. Fix: recompute `face_kt = k / max(cone_rings-1, 1)` per face. |

### PARTIAL (9)

| Function | File:Line | Issue |
|----------|-----------|-------|
| `compute_stamp_displacements` | terrain_sculpt.py:226 | Nearest-neighbor heightmap sampling — bilinear interpolation would eliminate staircasing |
| `generate_natural_arch` | terrain_features.py:951 | Dead code: `_ = random.Random(seed)` |
| `generate_geyser` | terrain_features.py:1147,1231,1269 | Dead code: unused rng + 2 dead variables |
| `generate_sinkhole` | terrain_features.py:1429 | Dead code: `_ = len(vertices)` |
| `_generate_shoreline_profile` | coastline.py:134 | Dead code: `_ = random.Random(seed)` |
| `_compute_material_zones` | coastline.py:423 | Dead code: `_z_avg` computed never used |
| `apply_coastal_erosion` | coastline.py:625 | Hardcoded wave_dir=0.0 ignores actual wave conditions |
| `compute_atmospheric_placements` | atmospheric_volumes.py:219 | Volume area 4x overestimate (spheres) — under-placement |
| `compute_volume_mesh_spec` | atmospheric_volumes.py:332 | Inconsistent box face winding (mixed normals) |

---

## Agent 3: Water systems — PENDING

---

## Agent 4: Cliffs + masks + biome + banded — PENDING

---

## Agent 5: _terrain_noise.py + _terrain_erosion.py + terrain_erosion_filter.py — COMPLETE

**37 functions audited | 32 PASS | 1 PARTIAL | 4 FAIL**

### FAIL (4 — all same root cause: legacy RandomState)

| Function | File:Line | Issue |
|----------|-----------|-------|
| `_build_permutation_table` | _terrain_noise.py:57 | `np.random.RandomState(seed & 0x7FFFFFFF)` — Context7: legacy/frozen, use `default_rng` |
| `_PermTableNoise.__init__` | _terrain_noise.py:138 | Inherits RandomState |
| `_OpenSimplexWrapper.__init__` | _terrain_noise.py:177 | Inherits RandomState |
| `hydraulic_erosion` | _terrain_noise.py:943 | Independent RandomState occurrence |

### PARTIAL (1)

| Function | File:Line | Issue |
|----------|-----------|-------|
| `finite_difference_gradient` | terrain_erosion_filter.py:78 | Reimplements `np.gradient(h, cell_size)` manually — correct but redundant |

### PASS highlights

- `np.meshgrid` default 'xy' indexing verified correct for (height, width) layout
- `np.gradient(heightmap, row_spacing, col_spacing)` — correct 2-scalar spacing
- `np.errstate + np.where` — canonical safe-division pattern throughout
- `erosion_filter` — fully vectorized multi-octave analytical erosion, crown jewel
- No scipy imports — all spatial ops pure numpy, correct for scope

---

## Agent 6: environment.py + environment_scatter.py + terrain_materials.py — COMPLETE

**68 functions audited | 64 PASS | 4 PARTIAL | 0 FAIL**

### PARTIAL (4 — all ShaderNodeMixRGB deprecation)

| Function | File | Occurrences |
|----------|------|:-----------:|
| `_assign_scatter_material` | environment_scatter.py:194,209 | 2 |
| `_build_terrain_recipe` | terrain_materials.py:2260,2312,2348 | 3 |
| `handle_create_water` | environment.py:3991,4005 | 2 |
| Total ShaderNodeMixRGB in these files | | **7** |

**Context7 finding:** `ShaderNodeMixRGB` deprecated since Blender 3.4 but Python API class still works in 4.2+. Migration to `ShaderNodeMix(data_type='RGBA')` with updated socket names (`"A"`, `"B"`, `"Factor"`) should be tracked.

### Confirmed modern APIs in use (PASS)

- `mesh.color_attributes` (not deprecated `vertex_colors`)
- `ShaderNodeSeparateColor` (not deprecated `ShaderNodeSeparateRGB`)
- `group.interface.new_socket()` with <4.0 fallback
- Principled BSDF 4.0+ socket names throughout
- Collection instancing via shared `template.data`
- bmesh lifecycle consistently correct (new→from_mesh→ensure_lookup_table→to_mesh→free)

---

## Agent 7: procedural_meshes.py + _mesh_bridge.py + _terrain_depth.py + LOD — PENDING

---

## Agent 8: pipeline + semantics + caves + glacial + karst + morphology + stratigraphy — PENDING

---

## NEW BUGS DISCOVERED (Round 2)

| Bug # | File:Line | Severity | Description |
|-------|-----------|----------|-------------|
| BUG-33 | terrain_advanced.py:1432 | HIGH | `handle_snap_to_terrain` discards depsgraph, ray_cast on unevaluated object ignores modifiers |
| BUG-34 | terrain_advanced.py:1677 | HIGH | `handle_terrain_flatten_zone` normalizes target_height to [0,1] but grid is world-space Z — produces garbage |
| BUG-35 | terrain_sculpt.py:326 | CRITICAL | `handle_sculpt_terrain` missing `bm.normal_update()` — stale normals, broken shading/lighting |

## CONFIRMED BUGS (matching Round 1)

| Bug # | Status |
|-------|--------|
| BUG-01 (falloff dead code) | CONFIRMED by Context7 — blend formula is algebraic no-op |
| BUG-03 (ice formation kt) | CONFIRMED by Context7 — stale outer loop variable, all faces blue |
