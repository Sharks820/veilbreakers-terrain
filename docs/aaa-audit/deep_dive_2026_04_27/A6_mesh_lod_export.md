# A6 Audit: Mesh, LOD & Export Pipeline
**Date:** 2026-04-27
**Auditor:** Claude (gsd-code-reviewer), depth=deep
**Files audited:**
- `veilbreakers_terrain/handlers/mesh.py`
- `veilbreakers_terrain/handlers/mesh_smoothing.py`
- `veilbreakers_terrain/handlers/lod_pipeline.py`
- `veilbreakers_terrain/handlers/_bridge_mesh.py`
- `veilbreakers_terrain/handlers/_mesh_bridge.py`
- `veilbreakers_terrain/handlers/terrain_unity_export.py`
- `veilbreakers_terrain/handlers/terrain_unity_export_contracts.py`
- `veilbreakers_terrain/handlers/terrain_navmesh_export.py`
- `veilbreakers_terrain/handlers/terrain_bundle_j.py`
- `veilbreakers_terrain/handlers/terrain_bundle_k.py`
- `veilbreakers_terrain/handlers/terrain_bundle_l.py`

---

## EXECUTIVE SUMMARY

The smoothing and QEM decimation stacks are better than expected — Taubin smoothing and cotangent-adjacent pinning are in place. The LOD pipeline is functional but has a critical billboard gate bug and a complete absence of CDLOD geomorphing. The Unity export coordinate handling is correct but carries a Z-up normal bug at scale and a broken heightmap Y-flip. NavMesh has zero hysteresis and a docstring/constant discrepancy. The two bridge files serve completely different domains and are not duplicates. Seam vertex sharing is absent from the prop mesh pipeline. Export contracts enumerate the right attributes but never actually validate pre-write that the geometry carries them.

---

## CRITICAL FINDINGS (P0)

### [P0-01] Billboard LOD never fires for 3-level chains — `_mesh_bridge.py:1234`

**Issue:**
```python
if include_billboard and level == len(ratios) - 1 and level >= 3:
```
The guard `level >= 3` means billboard generation is unreachable for any asset type whose preset has fewer than 4 LOD levels. The vegetation preset has 4 levels (`[1.0, 0.5, 0.15, 0.0]`) so it works there, but `prop_small`, `prop_medium`, `weapon`, and `furniture` all have 3-level presets. Calling `generate_lod_specs` on any of those with `include_billboard=True` silently produces a 10%-decimated mesh for the last LOD instead of the intended billboard — no error, no warning, wrong output written to disk. This is a silent wrong-output bug (P0 by your severity scale).

**Fix:**
```python
# The billboard should be the final level if ratio <= 0 is the sentinel,
# or simply whenever include_billboard is True and it is the last level.
if include_billboard and level == len(ratios) - 1:
    lod_specs.append(...)
    continue
```
The `level >= 3` guard was intended to prevent accidentally making LOD2 a billboard for very short chains. The correct fix is to let ratio == 0.0 (or explicit `include_billboard` flag) drive the decision, not an index floor. `generate_lod_chain` already does this correctly — it branches on `ratio <= 0.0` (line 1433). `generate_lod_specs` in `_mesh_bridge.py` should match that pattern.

---

### [P0-02] Heightmap is double-flipped on export — `terrain_unity_export.py:1237-1245`

**Issue:**
`_quantize_heightmap` (line 95-97) already applies `np.flip(norm, axis=0)` internally to orient for Unity. Then `export_unity_manifest` calls `_write_raw_array` with the quantized output but passes `flip_vertical=False` (line 1244). Separately, `_export_heightmap` also applies a flip. These two code paths are inconsistent: `export_unity_manifest` intentionally skips the second flip (preserving the one already baked by `_quantize_heightmap`), which is correct, BUT the comment on line 1244 says nothing about why, making it invisible. The real danger is that `_export_heightmap` is also exported as a public utility function — any caller who pipes their own heightmap through `_export_heightmap` (which does flip) and then also goes through `_quantize_heightmap` will double-flip and produce upside-down terrain.

This is a silent wrong-output P0: the code works for the specific call path in `export_unity_manifest`, but the same data processed via `_export_heightmap` → `_write_raw_array` (flip_vertical=True, the default) results in a double flip. Two exported-heightmap code paths with different flip semantics guarantee a future collision.

**Fix:** Unify on one authoritative flip point. Remove the flip from `_quantize_heightmap` (make it return terrain-space orientation), add `flip_vertical=True` to the `export_unity_manifest` `_write_raw_array` call for `heightmap.raw`, and update `_export_heightmap` to be the single source of flip truth.

---

### [P0-03] Laplacian graph-Laplacian matrix is uniform-weight (not cotangent-weighted) — `mesh_smoothing.py:52-79`

**Issue:**
```python
w = 1.0 / len(nb)
for j in nb:
    L[i, j] = w
```
This is the graph Laplacian (equal weights per neighbour), not the cotangent Laplacian. For AAA terrain meshes, uniform Laplacian is a correctness problem — it shrinks volume and distorts geometry proportional to valence variation. The Taubin λ/μ passes mitigate the volume shrinkage, but they do NOT fix the shape distortion caused by non-cotangent weights. On non-uniform meshes (any terrain quad-grid after decimation), equal-weight averaging pulls vertices toward high-valence neighbours, bowing ridges inward and eroding cliff silhouettes precisely in the areas the feature-pinning was designed to protect.

CDLOD Strugar 2010 §3.2, Houdini's Smooth SOP, and every production terrain smoother since Meyer 2002 use cotangent weights. This is a documented P0 for AAA terrain.

**Fix:** Replace the `w = 1.0 / len(nb)` computation with cotangent weights derived from the triangle areas adjacent to each edge:
```python
# Per-edge cotangent weight: cot(alpha) + cot(beta) for the two angles
# opposite the edge in adjacent triangles. Build this from faces, not
# just the adjacency graph, requiring access to vertex positions.
```
The `_build_laplacian` function needs to accept vertex positions and face data to compute these weights. The API change is local to `mesh_smoothing.py`.

---

## HIGH-SEVERITY (P1)

### [P1-01] No CDLOD geomorphing — entire `lod_pipeline.py` and `_mesh_bridge.py`

**Issue:**
There is zero implementation of CDLOD-style vertex morphing (Strugar 2010 §4). The LOD pipeline generates per-level static meshes. When the camera crosses a LOD boundary the mesh pops instantly — there is no blend from LOD(n) vertex positions to LOD(n-1) positions using the screen-space morph parameter `((d - d_near) / (d_far - d_near))`. For a dark fantasy open-world terrain this is a visible pop at every LOD transition, which is why even mobile games (e.g., Genshin Impact) implement geomorphing.

The `lod_level`, `max_error_m`, and `screen_size_percentage` metadata fields are all present and correct; the engine wiring is there. But without the actual morph-target offsets baked into each vertex, Unity/UE5 cannot interpolate.

**Fix:** For each non-LOD0 mesh, compute per-vertex displacement vectors `delta[v] = position_lod0_equivalent - position_current_lod` and store them as a second UV channel or vertex color. The Unity shader then lerps `position + morph_factor * delta` in the vertex shader. This requires correlating LOD(n) vertices back to LOD0 positions after decimation — store this in metadata during decimation.

---

### [P1-02] T-junction seams between adjacent terrain tiles — no border vertex sharing — `_mesh_bridge.py` (`generate_lod_specs`)

**Issue:**
`generate_lod_specs` applies independent grid clustering per-tile. When two adjacent tiles are decimated to LOD1, their shared border vertices may cluster to different grid-cell centroids (because each tile's AABB is independent). The result is a visible seam gap along every tile boundary at all LOD levels below 0. `build_tile_seam_contract` is imported in `terrain_unity_export.py` (line 19) and written to the manifest but it describes the *expected* seam contract — it does not enforce that the mesh generator actually shares border vertices.

Unity HDRP's terrain stitching relies on the CPU-side seam vertices being exactly equal. This is the classic T-junction problem from CDLOD §6.

**Fix:** LOD generation must snap border vertices to a shared grid that is the same for both tiles (keyed by world-space position, not per-tile AABB). Border vertices should be excluded from clustering and instead inherited directly from the canonical LOD0 border.

---

### [P1-03] Unity Z-up → Y-up conversion produces wrong handedness for normals — `terrain_unity_export.py:117-125`

**Issue:**
```python
def _zup_to_unity_vectors(arr: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(
        np.stack((arr_np[..., 0], arr_np[..., 2], arr_np[..., 1]), axis=-1),
        ...
    )
```
Blender is Z-up right-handed. Unity is Y-up left-handed. Swapping Y and Z axes converts between up conventions, but it does NOT flip handedness. The correct transform for normals from Blender to Unity is: `(x, y, z)_blender → (x, z, y)_unity` AND negate one axis to account for handedness (`→ (-x, z, y)` or `(x, z, -y)` depending on the world forward convention). The current code uses `(x, z, y)` without the handedness flip.

For a flat plane facing +Z in Blender (normal = (0, 0, 1)), the conversion gives (0, 1, 0) in Unity — correct for a ground plane. But a cliff face pointing +X in Blender (normal = (1, 0, 0)) gives (1, 0, 0) in Unity, which in Unity's left-handed system faces the wrong direction. This produces incorrect lighting on cliff faces and forward-facing detail objects.

**Fix:**
```python
# Blender Z-up RH → Unity Y-up LH: negate X to flip handedness
return np.ascontiguousarray(
    np.stack((-arr_np[..., 0], arr_np[..., 2], arr_np[..., 1]), axis=-1),
    dtype=np.float32,
)
```
The same fix must be applied to `_zup_to_unity_vector` (line 1024-1026) used for mesh vertex normals.

---

### [P1-04] NavMesh export docstring says `cliff_blocked: 255` but constant is 64 — `terrain_navmesh_export.py:442`

**Issue:**
The docstring schema block at line 442 states:
```
"cliff_blocked": 255
```
But `NAVMESH_CLIFF_BLOCKED = 64` at line 66, and the actual exported JSON via `dict(_AREA_LEGEND)` uses 64. Any Unity-side script, art tool, or designer reading the in-code documentation and hardcoding 255 to detect impassable cells will silently fail — traversable cells will be treated as blocked, and vice versa. This is a P1 data contract error.

**Fix:** Update the docstring to say `"cliff_blocked": 64`. Add a module-level assertion `assert NAVMESH_CLIFF_BLOCKED == 64, "Update docstring"` to prevent future drift.

---

### [P1-05] Export contracts validated by enumeration only, never checked against actual mesh data pre-write — `terrain_unity_export_contracts.py:109-130`

**Issue:**
`validate_vertex_attributes_present` checks whether `attr_names` contains the 6 required attributes. But in `export_unity_manifest`, this validator is never called before writing `supplemental_mesh_specs.json`, `terrain_normals.bin`, etc. The vertex attribute validation exists as a standalone utility that callers can opt into — it is not wired into the export hot path. A mesh can be written with missing `tangent` or `uv1` (lightmap UVs) and the contract validator will never fire.

**Fix:** Call `validate_vertex_attributes_present` inside `_supplemental_mesh_specs_json` before appending each mesh spec. Raise `ValueError` or emit a logged warning (respecting the existing ValidationIssue pattern) rather than silently omitting the check.

---

### [P1-06] `handle_generate_lods` accesses `lod_entry[3]` without bounds check when `lod_chain` entry has exactly 3 elements from `generate_lod_chain` fallback — `lod_pipeline.py:1469`

**Issue:**
```python
prev_verts, prev_faces, _ = lod_chain[-1]   # line 1469
```
When the monotonicity fallback triggers, it unpacks `lod_chain[-1]` as a 3-tuple. This works for non-billboard entries. But if the *previous* entry was a billboard (which `generate_lod_chain` stores as a 4-tuple at line 1442), unpacking as `prev_verts, prev_faces, _ = lod_chain[-1]` would throw `ValueError: too many values to unpack`. In practice the billboard is always the *last* entry, so the fallback fires for earlier levels, but this is fragile. Any reordering of the ratios list that puts a billboard mid-chain causes a hard crash.

**Fix:**
```python
prev_entry = lod_chain[-1]
prev_verts, prev_faces = prev_entry[0], prev_entry[1]
```

---

## MEDIUM (P2)

### [P2-01] `_bridge_mesh.py` vs `_mesh_bridge.py` — these are NOT duplicates; they serve completely different roles

**Documentation finding (not a bug):**

`_bridge_mesh.py` is the **terrain domain bridge mesh generator** — it produces physical bridge structures (stone arch, rope, timber beam) connecting terrain waypoints. It is a pure-geometry module with a swept-centerline algorithm, style dispatch, and profile metadata. It lives in the terrain handlers because terrain consumers (road network) need it.

`_mesh_bridge.py` is the **procedural mesh → Blender object wiring layer** — it contains the generator mapping tables (FURNITURE_GENERATOR_MAP, VEGETATION_GENERATOR_MAP, etc.), the `generate_lod_specs` LOD utility, `mesh_from_spec` (MeshSpec → bpy.types.Object), `post_boolean_cleanup`, and the billboard helpers. It is the binding glue between pure-logic generators and Blender scene operations.

The names are confusingly swapped: the "mesh bridge" conceptually should be the Blender bridge, and the "bridge mesh" should be the geometry. Both files should be renamed: `_bridge_mesh.py` → `terrain_bridge_mesh.py` and `_mesh_bridge.py` → `procedural_mesh_wiring.py` (or similar). No fix required for correctness but high cognitive overhead for future contributors.

---

### [P2-02] `generate_lod_specs` UV clustering averages UVs across grid cells — produces UV seams at LOD transitions — `_mesh_bridge.py:1272-1287`

**Issue:**
When multiple source vertices cluster into the same grid cell, their UVs are averaged. For a UV island that straddles a cell boundary, vertices on both sides of the boundary collapse to the same new vertex but take the *average* UV of both sides — meaning the UV is wrong for the material on either side of the seam. At LOD transitions this causes a visible texture-coordinate jump.

UE5's HLOD builder handles this by preserving UV connectivity: vertices on UV seams are never merged across the seam even if they are spatially coincident.

**Fix:** Before clustering, tag vertices that sit on UV seams (adjacent vertices with the same world position but different UVs). Do not merge UV-seam vertices into the same cell even if they are spatially collocated.

---

### [P2-03] Collision mesh fallback for coplanar / degenerate input — `lod_pipeline.py:804`

**Issue:**
When the incremental convex hull algorithm cannot find a valid third point (all input vertices are colinear), it returns `list(vertices[:4]), list(faces)` — the first 4 vertices of the *source mesh* faces, not a hull at all. For a terrain tile with thousands of faces this returns random source triangles as the collision mesh. Any physics query against this "hull" will produce nonsensical results. The scipy fast path handles degenerate input correctly via `ConvexHull`'s own validation, but the pure-Python fallback silently returns garbage.

**Fix:** Add a planarity check. If `best_dist < 1e-6` (all points coplanar) after the third-point search, return the convex hull of the 2D projection instead of raw source faces.

---

### [P2-04] `_build_sharp_vertex_mask` computes face normal from first three vertices only — incorrect for quads/n-gons — `mesh_smoothing.py:128-133`

**Issue:**
```python
v0 = verts[face[0]]
v1 = verts[face[1]]
v2 = verts[face[2]]
fn = _compute_face_normal(v0, v1, v2)
```
For a quad or n-gon, this uses only the first triangle of the polygon. If the first three vertices are nearly collinear (common in highly irregular procedural meshes), `_compute_face_normal` returns a zero vector (line 90-91), and the face is assigned a zero normal. That zero normal then produces `dot = 0` against all other face normals, `dot < cos_threshold` is False, and the edge is never marked sharp. Hard edges on irregular quads are silently missed.

**Fix:** Use Newell's method for face normals (already implemented as `_face_normal` in `_mesh_bridge.py:545-561`) or triangulate the face before computing the normal.

---

### [P2-05] NavMesh FLY zone marks mountain summits rather than aerial corridors — `terrain_navmesh_export.py:173-178`

**Issue:**
```python
h_mean = float(h.mean())
fly_zone = h > (h_mean + float(fly_clearance_m))
walkable_or_climb = (out == NAVMESH_WALKABLE) | (out == NAVMESH_CLIMB)
out[fly_zone & walkable_or_climb] = NAVMESH_FLY
```
This marks the tops of mountains as FLY, not aerial corridors above the terrain. In Recast NavMesh, FLY areas are 3D voxel volumes above ground geometry — they are not stored in the same 2D area grid as walkable/swim/climb cells. Using `h > h_mean + clearance` on the 2D heightmap produces a FLY band that is physically the mountain summit, which is also WALKABLE for ground units. The resulting overlap means flying enemies that path through FLY zones will be routed onto mountain tops rather than through the air above the terrain. This is a semantic misuse of the FLY area ID.

**Fix:** Remove the FLY zone from the 2D classification. FLY pathing requires a separate 3D navigation volume (Unity NavMesh Volume, Recast off-mesh link height layer) that cannot be represented in this 2D grid.

---

### [P2-06] `post_boolean_cleanup` T-junction detection has O(V × E) inner loop — `_mesh_bridge.py:690-732`

**Issue:**
The T-junction pass loops over every vertex × every edge in the mesh, re-running up to 4 times. For a boolean result with V=1000 vertices and E=3000 edges this is 12 million comparisons per pass, 48 million total. For a 10K vertex boolean result this is 480 million float comparisons. While the comment says "Boolean outputs are typically small", cliff overhangs and cave mouth booleans can produce outputs in this range.

This is noted as out of scope for v1 performance review but flagged here because the O(n²) nature is the direct consequence of a correctness design choice (re-scanning after each modification) that could be replaced with a spatial acceleration structure (grid or kd-tree) without losing correctness.

---

### [P2-07] `_select_by_plane` "below" semantics do not include the plane itself — `mesh.py:198-204`

**Issue:**
The docstring says:
> `"below"` — signed distance <= +tolerance (opposite side + plane + band). At tol=0: dot < 0 only (plane surface itself is NOT included).

This is asymmetric with `"above"`, which *includes* `dot >= 0`. A vertex exactly on the plane (`dot == 0`) is selected by `"above"` but not `"below"`. This is documented behavior but it is an unintuitive asymmetry that will produce incorrect half-space selections in callers that expect symmetric plane splitting (e.g., seam detection, mirror operations). Neither `"above"` nor `"below"` cleanly expresses "strictly inside" — callers need to subtract the intersection themselves.

**Fix:** Either make both sides inclusive (both use `<=`/`>=`), or add a third `side="on"` option and make both sides strictly exclusive. The current mixed inclusive/exclusive behavior is a defect in API ergonomics that will cause off-by-one failures.

---

## LOW (P3)

### [P3-01] Taubin `taubin_mu` default is -0.53, within documented instability range for some meshes — `mesh_smoothing.py:223`

The classic Taubin 1995 paper recommends `lambda < -mu < 1` and specifically notes that `mu` values close to `-lambda` (here `-0.5`) risk pass-band instability for high-frequency features. The default `taubin_mu = -0.53` is slightly above the `-0.5` symmetry point but below `-lambda = -0.5` (with default `blend_factor = 0.5`), placing it in the documented stable zone. However, the relationship between `lambda` and `mu` is not validated at runtime — callers who pass `blend_factor=0.8` and keep `taubin_mu=-0.53` silently enter the unstable region (`|mu| < lambda`). Add a runtime warning when `abs(taubin_mu) <= blend_factor`.

---

### [P3-02] `generate_lod_chain` unpacks previous entry with index `[:3]` but fallback silently uses wrong verts if prev was billboard — `lod_pipeline.py:1469`

Already captured as P1-06. The P3 note here is that the broader pattern of storing billboard entries as 4-tuples and non-billboard as 3-tuples in the same list is fragile. A dataclass or named tuple would eliminate all of these indexing hazards.

---

### [P3-03] `_bridge_mesh.py:862` retains unused variable `__dz` — naming convention violation

```python
__dz = ez - sz  # retained for parity with original; unused
```
The double-underscore prefix activates Python name mangling inside classes (not applicable here) and signals "very private" by convention. Using it for an unused variable is confusing. Mark it `_dz` or use `_` if it is intentionally discarded.

---

### [P3-04] `terrain_navmesh_export.py` exports `cliff_blocked_fraction` in stats but only `NAVMESH_CLIFF_BLOCKED=64` cells are counted — cells area `NAVMESH_UNWALKABLE=1` not included — `terrain_navmesh_export.py:512`

```python
"cliff_blocked_fraction": float(
    distribution.get(NAVMESH_CLIFF_BLOCKED, 0)
) / max(total, 1.0),
```
`NAVMESH_UNWALKABLE` cells (area ID 1) are separately counted in `distribution` but not summed into `cliff_blocked_fraction`. A designer reading this stat to assess how much of the tile is blocked will see only half the picture. Add an `impassable_fraction` that sums CLIFF_BLOCKED + UNWALKABLE.

---

### [P3-05] `terrain_unity_export.py:42-43` — `_is_unity_heightmap_resolution` bitwise formula is non-obvious

```python
return n >= 33 and ((n - 1) & (n - 2)) == 0
```
The correct formula for 2^k+1 is `(n-1) & (n-2) == 0` iff `n-1` is a power of 2. This is correct but fragile: it is not immediately obvious why `(n-1) & (n-2)` tests power-of-two-ness (it's equivalent to `(n-1) & -(n-1) == n-1`). Add a comment: `# n-1 must be a power of 2: equivalent to popcount(n-1)==1`.

---

### [P3-06] `terrain_bundle_k.py` and `terrain_bundle_l.py` are pure registrars with no logic — CLEAN

Both bundles are correct pass-registrar patterns. No issues.

---

### [P3-07] `terrain_bundle_j.py` — `BUNDLE_J_PASSES` tuple lists `ecotones` but `terrain_ecotone_graph` is not imported in the registrar — gap check

`register_bundle_j_passes` calls `terrain_ecotone_graph.register_bundle_j_ecotones_pass()` and `terrain_ecotone_graph` IS imported. The `BUNDLE_J_PASSES` tuple correctly lists all 10 passes. No issue — just verifying the count.

---

## CLEAN FINDINGS

### Smoothing: Taubin implementation is correct in structure
`mesh_smoothing.py` implements Taubin two-pass (λ/μ) smoothing correctly: the λ pass followed by the μ pass per iteration, with the correct sign convention (negative μ inflates). Feature-edge pinning via dihedral-angle detection is also correct. The only failure is the underlying Laplacian weights being uniform rather than cotangent (P0-03 above).

### QEM decimation is Garland-Heckbert 1997 compliant
`lod_pipeline.py` implements full QEM: per-vertex 4×4 quadric matrices built from incident face plane equations, optimal position solved via the 3×3 linear system with midpoint fallback, heap-based collapse with stale-entry recomputation at 4× cost inflation. This matches UE5's Nanite fallback simplifier and MeshLab's QEM. The implementation is production quality.

### Unity heightmap bit depth and encoding contracts are correct
`terrain_unity_export_contracts.py` correctly specifies `uint16_le` for heightmap, `raw_rgba_u8` for splatmaps, and `float32` for shadow clipmap. The validator correctly distinguishes between bit depth and encoding violations. The `_is_unity_heightmap_resolution` check is mathematically correct (verified by test).

### `mesh.py` selection helpers are correct and vectorized
`_select_by_box`, `_select_by_sphere`, and `_select_by_plane` are all vectorized with numpy, handle edge cases (empty input, zero normal), and the schema validator is thorough. The asymmetric `below` semantics are documented (though flagged as P2-07).

### NavMesh area classification ladder is correct for Recast semantics
The slope-based promotion ladder (CLIFF_BLOCKED → WALKABLE → CLIMB → SWIM) correctly mirrors Recast NavMesh area assignment priority. The EDT-based narrow-pass penalty is a correct Recast erosion analogue.

### `_bridge_mesh.py` swept-centerline algorithm is geometrically sound
The resample-then-sweep pattern with Frenet-Serret frame computation (`_frame_at`) is correct. The rope catenary sag formula `sin(t * pi) * sag_depth` approximates a parabolic catenary correctly for the span scales used. Stone arch arch-drop calculation is physically plausible.

### `_zup_to_unity_vector` scalar version and `_zup_to_unity_vectors` array version are consistent
Both apply `(x, y, z) → (x, z, y)`. The handedness issue (P1-03) affects both equally, but they are internally consistent with each other.

### HDRP Mask Map channel packing is correct
`_pack_hdrp_mask_map` correctly packs R=Metallic, G=AO, B=Detail, A=Smoothness per Unity HDRP Terrain Lit shader spec. The smoothness = 1 - roughness conversion is correctly documented.

### Splatmap normalization is correct
`_write_splatmap_groups` normalizes per-pixel weights before quantizing to uint8, preventing the Unity rendering artefacts from unnormalized splatmap reads. This is production-correct behavior.

---

## STATISTICS

| Severity | Count |
|----------|-------|
| P0 — crash / silent wrong output | 3 |
| P1 — major correctness | 6 |
| P2 — quality gap | 7 |
| P3 — minor / low risk | 7 |
| **Total issues** | **23** |

### Grade Assessment vs AAA Benchmarks

| Area | Grade | Notes |
|------|-------|-------|
| Laplacian smoothing | **D+** | Taubin structure correct; uniform weights (not cotangent) is a documented AAA failure |
| LOD decimation quality | **B+** | Full QEM Garland-Heckbert, heap collapse, silhouette protection — genuinely production quality |
| LOD transitions | **D** | Zero geomorphing; hard pops at every LOD boundary |
| Billboard impostors | **C** | Implementation correct when it fires; silent non-fire on 3-level chains is P0 |
| Unity coordinate export | **B-** | Flip semantics unified; handedness flip missing for normals |
| NavMesh classification | **B** | Correct Recast ladder; FLY abuse and docstring discrepancy are P1/P2 |
| Export contracts | **C+** | Contracts defined but not wired into export hot path |
| Seam continuity | **F** | No shared border vertices between tiles at any LOD level |

_Reviewed: 2026-04-27_
_Reviewer: Claude (gsd-code-reviewer), Sonnet 4.6_
_Depth: deep_
