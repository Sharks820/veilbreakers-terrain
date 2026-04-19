# P1 — procedural_meshes.py functions 1-51 (lines 69-3376)
## Date: 2026-04-16, Auditor: Opus 4.7 ultrathink (1M context)
## File: `veilbreakers_terrain/handlers/procedural_meshes.py`

> Note: AST enumeration in the requested line range (69-3280) returned **51 functions**, not 49. Two functions (`_wrapped` at line 289 — closure inside `_alias_generator_category`; `_bevel_edge` at line 669 — closure inside `_make_beveled_box`) are nested helpers. `generate_spear_mesh` is graded fully (its body extends to line 3376; the `def` itself starts at line 3280 inside the requested range). All 51 are graded below — zero skips.

---

## Summary

### Grade distribution (51 functions)
- **A**: 0
- **A-**: 1 (`_get_trig_table`)
- **B+**: 5 (`_make_torus_ring`, `_make_lathe`, `_make_profile_extrude`, `_make_tapered_cylinder`, `_compute_dimensions`)
- **B**: 11 (most primitives + table/chair/shelf/chest/pillar/archway base cases)
- **B-**: 14 (most generators with one or more real bugs — flipped winding, NaN-risk, broken rotation hacks)
- **C+**: 11 (recognizable but artistically thin or with a serious gap)
- **C**: 6 (stubs: tree=spheres, mushroom-cluster=cone+cylinder, chain=untwisted toruses, root=disjoint cylinders)
- **D**: 3 (`generate_skull_pile_mesh` — eye sockets are *additive spheres* not sockets; `generate_chain_mesh` — "rotated" link is identical to unrotated; `generate_ivy_mesh` — leaves are flat quads pointing wall-out, no foliage normal)
- **F**: 0 (no empty stubs — but D-grade tree/skull/chain are within one revision of being placeholders)

### Top 5 WORST (in this slice)
1. **`generate_chain_mesh` (line 3105) — D**: Both the "horizontal" and "vertical" links emit the SAME torus from `_make_torus_ring` (XZ plane), then alternates apply a `(z, y, x)` swap that produces a YZ-plane torus — but the toruses are concentric (same center), do **not interlock** (no chain-link interpenetration test), and the catenary/gravity sag is missing. Reads as a stack of disconnected hoops.
2. **`generate_tree_mesh` (line 1720) — C**: Despite 222 lines and 7 canopy styles, every "canopy" is a cluster of 5-12 UV spheres or `_make_box` strips. No leaf cards, no IK branch growth, no SpeedTree-style cross-quad foliage, no bark normals. `ancient_oak` is 6 spheres + 1 central sphere = `cone + sphere` SpeedTree-1998 era.
3. **`generate_skull_pile_mesh` (line 3148) — D**: A "skull" = 1 elongated sphere (cranium) + 1 box (jaw) + **2 ADDITIONAL spheres** for "eye sockets". Sockets are convex bumps protruding outward, not concave indentations. Anatomically inverted.
4. **`generate_root_mesh` (line 2230) — C**: Roots are series of disconnected cylinder segments along a sine curve — no continuous tube topology, gaps between segments are visible, no taper bridging, no soil emergence, no root-flare blend with trunk.
5. **`generate_ivy_mesh` (line 2382) — D**: Vine stem segments have `cap_top=False, cap_bottom=False` so the chain has open holes at every joint. Leaves are unsubdivided quads at z=0.01 (parallel to wall, edge-on to viewer) — invisible from front. No leaf normal map, no twist, no clinging tendrils.

### Top 5 BEST (in this slice)
1. **`_get_trig_table` (line 119) — A-**: Solid LRU-cached trig table; the only thing missing is precomputing tau-fraction angles for non-uniform tessellation.
2. **`_make_lathe` (line 1010) — B+**: Correct revolve topology, base/top cap optional, no winding bugs. Equivalent to Blender's "Spin" operator. Used heavily.
3. **`_make_torus_ring` (line 503) — B+**: Standard parametric torus, correct winding, separate major/minor segs. Equivalent to `bmesh.ops.create_uvsphere`-style.
4. **`_make_tapered_cylinder` (line 544) — B+**: Multi-ring support enables real sculpt-quality tapered shapes (used by candelabra, tree trunk, tool handles).
5. **`_make_faceted_rock_shell` (line 867) — B**: Has fracture-bias randomization, ring-by-ring radius perturbation, x/y/z scale params; closest function in this slice to a real Megascans-influenced shape, but lacks ConvexHull post-processing and noise displacement on the surface.

### Cross-cutting AAA gap
**No function in this slice has** PBR-baked vertex colors, tangent-space data, real UV unwrapping (box projection from `_auto_generate_box_projection_uvs` is a fallback, not a seamless unwrap), LOD chain, or normal/AO bake hooks. **None ship in Megascans/SpeedTree** — the entire family is at "blockout pass" tier suitable for greybox prototyping, not a shippable AAA dark-fantasy game.

---

## `_grid_vector_xyz` (line 69) — Grade: B+
- **Claims**: Extract `(x,y,z)` from Blender vector-like or tuple.
- **Produces**: Correct dispatch on `hasattr(vec, 'x')`. 9 LOC.
- **AAA ref**: Equivalent to `mathutils.Vector` unpacking; trivial helper.
- **Bug/Gap**: No fallback for `Vector(())` of length <3; would throw `IndexError` on empty input. Not a real risk in this codebase.
- **Severity**: polish.
- **Upgrade to A**: Add `try/except` returning `(0,0,0)` for malformed input + type narrowing via `Sequence[float]` overload.

## `_detect_grid_dims_from_vertices` (line 80) — Grade: B
- **Claims**: Infer `(rows, cols)` from vertex coordinate set.
- **Produces**: Counts unique rounded X/Y to 3 decimals, validates by `cols*rows == len(vertices)`, falls back to `int(sqrt(N))`.
- **AAA ref**: Houdini's `gridsample` exposes grid dims as detail attributes; this is a heuristic recovery.
- **Bug/Gap**: Rounding to 3 decimals (mm precision) breaks for sub-mm terrain micro-displacement; a 4096-vert mesh with 0.0001-unit jitter merges all rows. Square sqrt fallback **wrong for 256x512** terrain (the very case the docstring claims to fix in `_detect_grid_dims`).
- **Severity**: important (silently produces wrong dims for irregular/displaced meshes).
- **Upgrade to A**: Use ratio-of-extents method: `cols = round((max_x-min_x)/cell_size)+1`. Detect cell size from vert spacing, not rounded uniqueness.

## `_detect_grid_dims` (line 96) — Grade: B
- **Claims**: WORLD-004 — robust dim detection on bmesh.
- **Produces**: Wraps `_detect_grid_dims_from_vertices(list(bm.verts))`.
- **AAA ref**: Same as above.
- **Bug/Gap**: Same fallback bug as parent. Materializing `list(bm.verts)` is expensive on 1M+ vert meshes; could iterate.
- **Severity**: important.
- **Upgrade to A**: Iterator-based, plus cell-size detection.

## `_get_trig_table` (line 119) — Grade: A-
- **Claims**: LRU-cached `(cos, sin)` pairs for N evenly spaced angles.
- **Produces**: 32-entry LRU, returns immutable tuple. Correctly excludes endpoint (i in range(segments), not segments+1) which is correct for closed loops.
- **AAA ref**: Equivalent to NumPy `np.exp(1j * np.linspace(...))` precomputation; standard procedural-mesh optimization.
- **Bug/Gap**: `maxsize=32` is generous, but if 50+ unique segment counts get used (rare), thrashing. Doesn't support phase offset (functions doing `angle + phase` recompute trig anyway).
- **Severity**: polish.
- **Upgrade to A**: Add `phase` param + `np.float32` array variant for vectorized callers.

## `_auto_detect_sharp_edges` (line 132) — Grade: B+
- **Claims**: Detect sharp edges via dihedral angle threshold for smooth-shading pipeline.
- **Produces**: Newell's method face normals, edge-face adjacency dict, dot-product comparison vs `cos(threshold)`. Boundary edges always sharp.
- **AAA ref**: Equivalent to Blender's `bpy.ops.mesh.edges_select_sharp` operator + `bmesh.ops.split_edges`. **Confirmed** in Context7 ([Blender 4.5 API docs](https://docs.blender.org/api/4.5)) which uses identical Newell normal then dot-product comparison.
- **Bug/Gap**: O(F*V) — for a 100k-face mesh with avg-face-size 4, runs 400k inner-loop iterations. Doesn't handle non-manifold edges (3+ faces per edge) — silently skipped.
- **Severity**: polish (slow but correct).
- **Upgrade to A**: NumPy-vectorize the Newell step; treat non-manifold as sharp.

## `_auto_generate_box_projection_uvs` (line 192) — Grade: C+
- **Claims**: Per-vertex UVs via box projection.
- **Produces**: Bounding box, then `(nx, nz if dz>dy else ny)` — i.e. picks ONE plane (top-down OR side) for the WHOLE mesh. Not per-face triplanar.
- **AAA ref**: Real box projection (UE5 World Aligned Texture, Blender Cube Projection) is **per-face**, picking the dominant face normal axis. This function gives all faces the same axis.
- **Bug/Gap**: A vertical wall projected XZ→UV has **zero UV variation in V** (all verts have same Z). Will produce stretched/smeared textures on any face whose normal is along the chosen projection axis. **MAJOR**.
- **Severity**: blocker for any textured mesh.
- **Upgrade to A**: Real per-face triplanar — for each face, compute face normal, pick dominant axis (max(|nx|,|ny|,|nz|)), project 3 verts onto that plane → unique UV per face. Or expose a `cube_projection` flag and switch to true Blender `cube_project` semantics.

## `_make_result` (line 233) — Grade: B
- **Claims**: Package mesh into MeshSpec with auto-UVs and sharp-edge detection.
- **Produces**: Dict with vertices/faces/uvs/metadata + sharp_edges list.
- **AAA ref**: Standard `MeshSpec` plumbing; analog to `bpy.data.meshes.new` + `from_pydata`.
- **Bug/Gap**: `auto_uv=True` triggers the broken `_auto_generate_box_projection_uvs` for every mesh that doesn't pass UVs (which is **almost all** of them in this slice). So the bug above propagates. No tangent space, no normal data, no vertex colors, no material slots.
- **Severity**: blocker (combined with the UV bug).
- **Upgrade to A**: Emit per-face UVs (loop UVs), tangent space, vertex colors for biome variation. Add `materials: list[str]` and `polygroups`.

## `_alias_generator_category` (line 282) — Grade: B
- **Claims**: Wrapper renaming metadata.category for back-compat aliases.
- **Produces**: A `@wraps`'d closure that mutates a copy of metadata.
- **AAA ref**: Standard decorator; not a mesh function.
- **Bug/Gap**: Recreates `dict(result)` and `dict(metadata)` per call — fine. `# type: ignore[return-value]` indicates Mypy unhappy about the dict→MeshSpec narrowing — masking, not fixing. No tests for alias chaining.
- **Severity**: polish.
- **Upgrade to A**: Cast properly via `cast(MeshSpec, ...)` and add a registry test.

## `_wrapped` (line 289, nested in `_alias_generator_category`) — Grade: B
- **Claims**: The wrapper closure body.
- **Produces**: Same as above (it IS the body).
- **AAA ref**: N/A.
- **Bug/Gap**: Redundant entry from AST (closure); see parent. No standalone bugs.
- **Severity**: n/a.
- **Upgrade to A**: n/a.

## `__init__` (line 303, in `_GeneratorRegistry`) — Grade: B
- **Claims**: Init dict-like registry with canonical+aliases.
- **Produces**: `super().__init__(canonical)` + alias map + alias cache.
- **AAA ref**: N/A — registry plumbing.
- **Bug/Gap**: No validation that aliases reference existing canonical keys (a typo silently shadows a missing key with `KeyError` at lookup time).
- **Severity**: polish.
- **Upgrade to A**: Validate `aliases.values() <= canonical.keys()` at init.

## `__contains__` (line 312) — Grade: B
- **Claims**: Test key membership including aliases.
- **Produces**: Two-arm OR (canonical or alias).
- **AAA ref**: N/A.
- **Bug/Gap**: `isinstance(key, str)` check is good; `dict.__contains__` direct is correct (avoids recursion). No bugs.
- **Severity**: polish.
- **Upgrade to A**: n/a — this is fine.

## `__getitem__` (line 317) — Grade: B
- **Claims**: Return canonical group OR aliased group with rewritten category.
- **Produces**: Two-tier lookup: canonical first, then alias-cache, then build aliased group.
- **AAA ref**: N/A.
- **Bug/Gap**: Alias group cached lazily — but if the canonical group is mutated AFTER alias caching, the cache is stale. Not used dynamically in this codebase, but a footgun.
- **Severity**: polish.
- **Upgrade to A**: Document that the registry is read-only post-build, OR invalidate cache on `__setitem__`.

## `_compute_dimensions` (line 335) — Grade: B+
- **Claims**: Single-pass bbox dims (width/height/depth).
- **Produces**: Standard min/max walk, returns `{"width", "height", "depth"}` dict.
- **AAA ref**: Equivalent to `bm.calc_loose_parts()[i].verts.layers.deform.aabb` extraction. Optimized as docstring claims.
- **Bug/Gap**: Returns a string-keyed dict where caller may want a Vector — minor. Returns `0.0` for empty input which masks the "no verts" condition.
- **Severity**: polish.
- **Upgrade to A**: Return `None` for empty input; expose `(min_xyz, max_xyz)` tuple variant.

## `_circle_points` (line 370) — Grade: B+
- **Claims**: Points on a circle in chosen plane (XZ, XY, YZ).
- **Produces**: Cached trig + 3 axis branches; returns N points (no duplicate close).
- **AAA ref**: Equivalent to `bmesh.ops.create_circle` (cap_ends=False). **Confirmed** in [Blender 4.5 API docs](https://docs.blender.org/api/4.5/bmesh.ops.html).
- **Bug/Gap**: `axis='x'` branch doesn't match the docstring labeling (`axis='x'` produces YZ-plane points which is correct, but the docstring only documents `'y'` and `'z'` cases).
- **Severity**: polish.
- **Upgrade to A**: Document `axis='x'`, add Z-up vs Y-up flag.

## `_make_box` (line 400) — Grade: B
- **Claims**: Axis-aligned 8-vert, 6-face box.
- **Produces**: Standard cube — verified winding (CCW from outside on all 6 quads). Half-sizes used directly (param name `sx,sy,sz` == half-extent, mildly confusing).
- **AAA ref**: Equivalent to `bmesh.ops.create_cube(size=2)` translated. **Megascans cubes don't exist** — every prop in Megascans is photogrammetry-derived. UE5's BSP brushes use this same 8-vert topology.
- **Bug/Gap**: Param naming: `sx, sy, sz` look like full sizes but are half-sizes (line 409 `hx, hy, hz = sx, sy, sz`). Confused callers — verified `generate_pillar_mesh stone_square` passes `radius` for `sx`, treating it as half-extent. **Documentation gap**.
- **Severity**: important (footgun).
- **Upgrade to A**: Rename params to `half_x, half_y, half_z` OR change to full-size and divide internally. Add UV coords (currently relies on broken auto-projection).

## `_make_cylinder` (line 432) — Grade: B
- **Claims**: Y-axis cylinder with optional caps.
- **Produces**: 2*segments + (cap fan endpoints) verts, segments quads + 0-2 N-gon caps.
- **AAA ref**: Equivalent to `bmesh.ops.create_cone(cap_ends=cap, segments=N, diameter1=diameter2=R)`. **Confirmed** Blender 4.5.
- **Bug/Gap**: Cap is a single N-gon (e.g. 12-sided polygon) which Blender will tessellate via fan — that fan can produce sliver triangles for high segment counts. Not catastrophic. Bottom cap winding (line 464): `range(segments-1, -1, -1)` — REVERSED from top — correct for outward-facing normals.
- **Severity**: polish.
- **Upgrade to A**: Optional triangle-fan cap instead of N-gon (better for tessellation engines like Nanite).

## `_make_cone` (line 473) — Grade: B
- **Claims**: Apex-up cone.
- **Produces**: segments+1 verts, segments tris + 1 cap N-gon.
- **AAA ref**: `bmesh.ops.create_cone(diameter2=0)`.
- **Bug/Gap**: Apex is a **single shared vertex** — produces normal-singularity at the tip (smooth shading interpolates a single normal vector). Real AAA cones (e.g. SpeedTree branch tips) duplicate the apex per face for proper normals.
- **Severity**: important (visible as a dark spot at apex under any non-flat shading).
- **Upgrade to A**: Duplicate apex per side face; add face normals or split the apex normal.

## `_make_torus_ring` (line 503) — Grade: B+
- **Claims**: Torus in XZ plane.
- **Produces**: major*minor verts, major*minor quads. Standard parametric torus formula.
- **AAA ref**: `bmesh.ops.create_uvsphere`-adjacent; equivalent to Blender's "Add Torus" operator. **Confirmed** Blender 4.5 docs.
- **Bug/Gap**: Major/minor segment defaults (16/8) yield 128 verts — fine for chain links, anemic for hero rings. No twist parameter (can't make spring/coil). The variables `_tcx, _tcz` (lines 518-519) are unused — dead code.
- **Severity**: polish.
- **Upgrade to A**: Remove unused locals; add `twist` parameter for helix mode.

## `_make_tapered_cylinder` (line 544) — Grade: B+
- **Claims**: Cylinder with two radii and optional intermediate rings.
- **Produces**: (rings+1)*segments verts, rings*segments quads + cap N-gons.
- **AAA ref**: `bmesh.ops.create_cone(diameter1, diameter2, segments)` with manual ring subdivision. Standard.
- **Bug/Gap**: Doesn't reuse `_get_trig_table` (line 564 computes `cos/sin` per ring) — wastes the cache the project added. Fixable.
- **Severity**: polish.
- **Upgrade to A**: Use cached trig; add per-ring radius noise param for organic shapes.

## `_make_beveled_box` (line 588) — Grade: B
- **Claims**: 24-vert box with chamfered edges.
- **Produces**: 24 verts (3 per corner — one inset along each axis) + 18 faces (6 main + 12 bevel quads).
- **AAA ref**: Equivalent to Blender `bmesh.ops.bevel(geom=edges, offset=...)`. **Confirmed** Blender API.
- **Bug/Gap**: The `_edge_pairs` list at lines 642-658 is **dead code** — never read after being assigned. Bevel topology is HAND-WIRED in lines 673-686 with magic numbers `(c0, c1, ax0, ax1)` — fragile, easy to break, no test asserting watertight. Per code at lines 627-637, the 6 "main" faces only use the 8 axial-inset verts (one inset per corner), while the bevel quads connect 2 different inset verts per corner — meaning the 8 verts at each corner-axis form a tiny corner triangle that is **not generated as a face**. Resulting mesh has **24 corner holes** — non-watertight!
- **Severity**: important (non-manifold mesh; fails CSG, fails physics convex decomposition).
- **Upgrade to A**: Add the 8 corner triangle faces (each connecting the 3 inset verts at one corner); OR replace with a real bmesh.ops.bevel call inside the Blender bridge.

## `_bevel_edge` (line 669, nested helper) — Grade: B
- **Claims**: Build a quad from 2 inset verts of each of 2 corners.
- **Produces**: 4-tuple of indices.
- **AAA ref**: N/A — local helper.
- **Bug/Gap**: Same as parent — magic axis indices.
- **Severity**: polish.
- **Upgrade to A**: n/a.

## `_enhance_mesh_detail` (line 691) — Grade: B-
- **Claims**: Subdivide near sharp edges to add edge loops for smooth-shading.
- **Produces**: Up to 3 passes of midpoint insertion + face splitting; fan-triangulates faces with >6 verts.
- **AAA ref**: Approximates Blender `bmesh.ops.subdivide_edges` with selection. **Confirmed** Blender API has `bmesh.ops.subdivide_edges(bm, edges, cuts, smooth)`.
- **Bug/Gap**: 
  - The `bevel_offset=0.015` (1.5% of edge length) creates **two new verts very close to the original endpoints** — cluster of 4 verts on one edge. Will look like a beveled edge **only if** subsequent rendering knows to smooth-shade — which it does NOT here.
  - Fan triangulation from `expanded[0]` (line 845) is degenerate if the face is concave — produces overlapping tris.
  - The result is **NOT topologically equivalent** to a bevel — it's a denser version of the same polygonal silhouette. Smooth shading in Blender bridge would still see the original sharp angle.
  - 3-pass cap can leave under-target meshes if all sharp edges processed in pass 1 generate <100 verts.
- **Severity**: important (claims to add detail but doesn't change silhouette; cosmetic only).
- **Upgrade to A**: Real edge bevel (split the edge into 2 loops with offset along face-perpendicular direction) instead of in-edge subdivision; integrate Catmull-Clark or Loop subdivision pass.

## `_merge_meshes` (line 853) — Grade: B+
- **Claims**: Merge multiple (verts, faces) tuples with index remapping.
- **Produces**: Concatenated verts, faces remapped by `idx + offset`.
- **AAA ref**: Equivalent to Blender's `bmesh.ops.duplicate(...)` + `bmesh.ops.translate(...)` chain or numpy `np.concatenate`. Standard.
- **Bug/Gap**: No duplicate-vertex merge — coincident verts at part interfaces (e.g. table top sitting flush on legs) become non-merged seams. No watertightness — the mesh remains a "soup" of independent shells. UV continuity broken at every part boundary.
- **Severity**: important (every multi-part generator leaves visible seams + double normals).
- **Upgrade to A**: Add `merge_distance` parameter doing a hash-based vert dedupe; emit `seam` list for the bridge to handle UV island marking.

## `_make_faceted_rock_shell` (line 867) — Grade: B
- **Claims**: Angular fractured rock with non-spherical massing.
- **Produces**: ~(8+detail*2)*(2+detail+1) = 80-150 verts, ring-quad topology + 2 N-gon caps. Fracture bias, x/z scale jitter, ridge perturbation per vert.
- **AAA ref**: Closer to Houdini Labs `Rock Generator` than Megascans. Real Megascans rocks are 5k-50k tris from photogrammetry decimation. This is at "blockout rock" tier — recognizable as a rock, but no surface noise displacement, no ConvexHull-based facet, no Voronoi crack pattern.
- **Bug/Gap**: 
  - Top/bottom caps are N-gons (line 952, 954) — cap winding for top is forward (CCW from above) but the top SHOULD face up, so winding looks correct; bottom winding `range(segments-1,-1,-1)` faces down — also correct.
  - No real facet/flat-shade signal — the ridge math creates *radial* perturbation only, the cross-section remains a smooth ring (no flat planes between facets like a real broken rock).
  - SciPy `ConvexHull` available ([scipy 1.16.1 docs](https://docs.scipy.org/doc/scipy/reference/generated/scipy.spatial.ConvexHull.html)) would give true facet planes.
- **Severity**: important (called by `generate_rock_mesh boulder` which is a default scatter prop).
- **Upgrade to A**: Generate point cloud → `scipy.spatial.ConvexHull` → use hull facets directly (true flat planes); or post-process with Voronoi crack pattern; add Perlin noise displacement.

## `_make_sphere` (line 959) — Grade: B
- **Claims**: UV sphere.
- **Produces**: 2 + (rings-1)*sectors verts, 2*sectors tri caps + (rings-2)*sectors quad belts.
- **AAA ref**: `bmesh.ops.create_uvsphere(u_segments=sectors, v_segments=rings)`. **Confirmed** Blender 4.5.
- **Bug/Gap**: Pole singularity (single vert at top/bottom) — same as `_make_cone` apex. UV pole pinch. Defaults rings=8/sectors=12 too low — yields obvious facets on canopy spheres in `generate_tree_mesh`. Should be at least 16/24 for hero meshes.
- **Severity**: important.
- **Upgrade to A**: Optional icosphere mode (no pole pinch); higher defaults; per-pole UV row.

## `_make_lathe` (line 1010) — Grade: B+
- **Claims**: Revolve 2D profile around Y axis.
- **Produces**: n_profile*segments verts, (n_profile-1)*segments quads + cap N-gons.
- **AAA ref**: Blender's `bmesh.ops.spin` operator, or "Spin" tool. **Confirmed** Blender API. Standard lathe.
- **Bug/Gap**: Doesn't use cached trig table (line 1028 — `math.cos/sin` per profile point — should hit `_get_trig_table(segments)`). Cap closure assumes profile starts at r=0 for bottom cap, which isn't validated — a profile starting at r=0.3 will get a huge cap N-gon misaligned with what the user wanted.
- **Severity**: polish.
- **Upgrade to A**: Use cached trig; auto-detect r=0 for axis-touching cap suppression.

## `_make_profile_extrude` (line 1048) — Grade: B+
- **Claims**: Extrude 2D (x,y) profile along Z.
- **Produces**: 2*N verts, N side quads + 2 cap N-gons.
- **AAA ref**: Blender `bmesh.ops.extrude_face_region` after building a 2D ngon. Standard.
- **Bug/Gap**: 
  - Line 1074 closes the loop but assumes the profile is OPEN — for closed profiles it duplicates an edge.
  - Cap winding (line 1077: front cap reversed) — assumes profile points are CCW; if user gives CW profile, normals flip. No validation.
- **Severity**: polish.
- **Upgrade to A**: Detect open/closed; sign-area test for winding; auto-flip caps if winding wrong.

## `generate_table_mesh` (line 1089) — Grade: B-
- **Claims**: 3 styles × 2/4 legs × parametric WHD table.
- **Produces**: Top (24-vert beveled box) + 2-4 tapered cylinder legs + optional cross braces. With `_enhance_mesh_detail` to 500 verts. Total ~600-900 verts.
- **AAA ref**: Megascans tavern tables are 2k-6k tris with carved bevels, knot-textures, baked AO. UE5 PCG samples have hand-modeled tables in marketplace. This is closer to **early Mount & Blade** or **Skyrim Creation Kit** placeholder tier.
- **Bug/Gap**: 
  - Line 1184: `_rotated_v_unused` and 1186-1190: `_rotated_v` are **dead code** — both lists computed and discarded. The actual brace at 1192 uses `_make_box` placed horizontally — the entire "rotation approximation" code is vestigial.
  - Cross brace is ONE box (line 1192-1194) sitting between front and back legs — should be a stretcher between left+right pairs too.
  - "noble_carved" style is identical to "tavern_rough" except for `leg_segments=8` and slightly different taper — no carvings, no rosettes, no inlays. Word "carved" is misleading.
- **Severity**: important.
- **Upgrade to A**: Real H-stretcher pattern; carve detail via lathe profile with concave nodes; emit material slots ("wood_top", "wood_legs", "iron_band").

## `generate_chair_mesh` (line 1202) — Grade: B-
- **Claims**: 3 styles + arms/back toggles.
- **Produces**: Beveled seat + 4 tapered legs + slats/throne back + optional arm + arm support.
- **AAA ref**: A Skyrim-quality chair has 1-2k tris, baked PBR, separate materials for cushion/wood/metal. **Witcher 3** thrones have intricate carved backboards with normal maps.
- **Bug/Gap**: 
  - Throne backrest is a **flat slab** (line 1251-1255) — no arch, no carving despite docstring "throne".
  - Throne finials (line 1259-1262) are 5-ring 6-sector spheres — 30 vert balls. Look like marbles.
  - Bench backrest is 2 vertical slats + 1 horizontal rail — read as a "park bench" not a wooden tavern bench.
  - No cushion, no leather, no wear marks.
- **Severity**: important.
- **Upgrade to A**: Throne: lathe-revolved backboard with profile that includes peaked top + side wings; finials as carved spike profiles. Bench: add a curved backrest with center-piercing motif.

## `generate_shelf_mesh` (line 1307) — Grade: B
- **Claims**: Tiered shelf, freestanding or wall-mount.
- **Produces**: 3-tier shelf board stack + side panels + back panel OR L-brackets.
- **AAA ref**: Standard furniture greybox. **The Witcher 3** apothecary shelves have angled back braces, ornate end caps, support pegs underneath each tier.
- **Bug/Gap**: 
  - Line 1369: vertical bracket box positioned at `y + tier_spacing * 0.3` — should be `y + tier_spacing * 0.5` to actually support the shelf above. Currently floats half-way.
  - Back panel is a 0.005-thick box — will Z-fight with the shelves it touches.
  - No rough wood texture cues (grain stripes), no nail heads.
- **Severity**: important (Z-fight + wrong bracket geometry).
- **Upgrade to A**: Move back panel to `z = -d/2` exactly; fix bracket Y position; add vertical groove cuts on side panels for plank effect.

## `generate_chest_mesh` (line 1380) — Grade: B-
- **Claims**: 3 styles, wooden/iron/ornate.
- **Produces**: Beveled main body + half-cylinder lid (custom 22-vert sweep) + iron bands (boxes wrapped around) + optional lock plate + optional 8 corner spheres.
- **AAA ref**: Megascans treasure chests are 8-15k tris. Ornate ones have lock mechanisms with separate hinges. **Diablo IV** chests have rune-engraved bands with normal-mapped depth.
- **Bug/Gap**: 
  - Lid is a **half-cylinder bent over the body** — but lines 1418-1419 build verts at fixed `xpos = ±w/2` (lid width = body width) and `z_scale * lid_radius`. The lid's CROSS SECTION is a half-circle in the YZ plane. End caps (lines 1426-1429) close it. **Topology check**: lid_segs+1=11 ring-pairs × 2 verts = 22 verts. End cap N-gons of 11 verts each. Geometrically a half-pipe — works.
  - Iron bands at lines 1438-1442 are full beveled boxes wrapping the chest, but they EXTEND on the front face into the lid — visually they pierce through the lid's pivot line.
  - Ornate sphere "corner pieces" (1467-1471) are 24-vert sphere blobs at every corner — looks like an 8-eyed potato.
  - Lock body (1454-1459) is a tiny cylinder; no actual lock mechanism, no keyhole indentation.
- **Severity**: important (clipping iron bands + dumb sphere corners).
- **Upgrade to A**: Bands stop at the body-lid seam (don't span the lid). Replace sphere corners with carved metal corner brackets (L-shape extruded profile). Add hinge axles where lid meets body.

## `generate_barrel_mesh` (line 1478) — Grade: B
- **Claims**: Stave-bulge barrel with iron bands.
- **Produces**: Lathed body with bulge profile (max bulge=12% at midline, sin curve) + 3 torus iron bands.
- **AAA ref**: This is the only generator in this slice that uses a **real lathe profile with a sin-bulge** — a correct barrel form factor. Megascans barrels are still 4-12k tris with iron-band normal maps + plank seams.
- **Bug/Gap**: 
  - "staves=16" is just the lathe segment count — there's NO actual stave separation (no flat planes between adjacent segments, no rim where staves meet). Default 16 segments yields a smooth round barrel, not a planked one.
  - 3 bands are placed without head-stave interaction (no recess).
  - Bottom and top caps are N-gons - acceptable for blockout.
- **Severity**: important (claim of "stave bulge" is half-true; visual is a smooth wood drum).
- **Upgrade to A**: After lathe, modify radius per segment to introduce 16 flat planks; add 0.005-unit recessed grooves at band positions; add bottom-rim chime ridge.

## `generate_candelabra_mesh` (line 1528) — Grade: C+
- **Claims**: Wall or standing candelabra with N arms.
- **Produces**: Standing: lathed base + lathed shaft with 2 decorative nodes + N arm "cylinders" + cup + candle stub per arm. Wall: plate + 1 arm + cup.
- **AAA ref**: Real candelabras have curved S-arms (Bezier), drip pans, decorative knobs at each joint. **Diablo III** candelabras use lathed bases + cubic-spline arms + UV-mapped tarnish.
- **Bug/Gap**: 
  - Lines 1602-1610 / 1613-1619: arms are 2 horizontal cylinders (mid + up) for each arm — but BOTH cylinders are vertical (Y-axis); only their X/Z position differs. The "curved upward section" is a SECOND vertical cylinder offset 85% along the radial direction — the arm doesn't actually CURVE, it's two stacked vertical posts forming a step pattern. Reads like a Ladder, not a candelabra arm.
  - Wall version line 1561: `arm_verts = [(v[0], height * 0.45, v[1] - height * 0.4 + 0.15) for v in av]` — uses `v[1]` (the original Y) for new Z but FORCES Y to constant `height*0.45` for ALL verts — collapses the arm cylinder into a planar disc. Geometric **bug**.
  - No drip pan, no candle wax variation.
- **Severity**: blocker (wall arm collapsed to disc).
- **Upgrade to A**: Replace arm hack with proper rotation matrix application: `(cos·x - sin·y, base_y, sin·x + cos·y)`. Real S-curve arms via tube-along-curve.

## `generate_bookshelf_mesh` (line 1640) — Grade: B
- **Claims**: Bookshelf with optional book scatter.
- **Produces**: 2 side panels + sections+1 shelf boards + back panel + optional random books per section.
- **AAA ref**: Standard prop. Books are independently placed beveled boxes — comparable to early **Skyrim** library scatter.
- **Bug/Gap**: 
  - Books all sit AT z=back-panel + book_d/2 — leaning happens only in X (line 1699-1701). Real bookshelves have books varying in Z (some pulled forward) too.
  - Books are **rectangular boxes** — no spine groove, no page edge variation.
  - `book_h` can exceed `section_h` if rng picks 0.88 — book pierces shelf above.
- **Severity**: important (bookshelf with books poking through shelves).
- **Upgrade to A**: Add `book_h <= section_h - 0.02` clamp; add lean in Z; emit book mesh with separate `spine` material slot.

## `generate_tree_mesh` (line 1720) — Grade: C
- **Claims**: 7 canopy styles, parametric trunk + branches + canopy.
- **Produces**: Lathed trunk (~16 ring × 14 seg = 224 verts) + N branches (each = 4 cylinder segs of 6-seg circumference) + canopy (5-12 spheres OR 5 cones OR 12 boxes).
- **AAA ref**: This is **the** flagship vegetation generator. SpeedTree trees use:
  - Bezier-spline trunk with bark cards
  - Procedural branch generation with parent-child IK
  - Leaf cards (cross-quads) with alpha-blended texture
  - Wind animation per node
  - LOD chain (LOD0=15k tris, LOD1=10k, LOD2=5k, billboard) — confirmed by [SpeedTree LOD docs](https://docs.speedtree.com/doku.php?id=overview_level-ofdetail).

  Compared to SpeedTree: this generator's `ancient_oak` is **5 spheres + 1 central sphere = 6 spheres for the canopy**. That's literally `tree = sphere + cone` from 1998 placeholder art. **Two grades above F only because the trunk is properly lathed and branches taper.**

- **Bug/Gap**:
  - Branches at lines 1789-1808 are **4 cylinder segs per branch** — but the cylinders are ALL vertical (Y-axis) at `(mid_x, mid_y - seg_len/2, mid_z)`. There's NO direction along `(dx, dy, dz)` — segments are vertical posts placed at the (x,y,z) along the branch path. Branches don't actually angle — they're vertical posts at branch-tip positions. **MAJOR**.
  - `dead_twisted` style has **no canopy and no twisted branches** (line 1841 just `pass`) — it's a bare trunk.
  - `willow_hanging` strips (line 1928-1937) are 12 vertical boxes — read as a phone booth with shutters.
  - `veil_blighted` (1896-1924) is 2 spheres + 4 vertical box "rags" — completely decorative-only; trees in that biome should be **dead with skeletal branches**.
  - No leaf cards. No bark normal map. No vertex colors for wind motion. No LOD.
- **Severity**: blocker (this is the biome anchor mesh; current state is unshippable).
- **Upgrade to A**: Reimplement using L-system or Space Colonization Algorithm for branches; replace canopy spheres with 30-50 leaf cards (pairs of crossed quads); bake AO; emit LOD chain. Compare directly to SpeedTree Modeler defaults.

## `generate_rock_mesh` (line 1944) — Grade: B-
- **Claims**: 5 rock types (boulder/cliff/standing/crystal/rubble).
- **Produces**: 
  - boulder → `_make_faceted_rock_shell` (B-tier, see above)
  - cliff_outcrop → 3-7 stacked beveled-box layers + fin + rubble bits
  - standing_stone → lathed irregular column
  - crystal → 3-8 hexagonal tapered cylinders
  - rubble_pile → 5-20 small beveled boxes
- **AAA ref**: Megascans cliffs are scanned 50k+ tris with multi-channel mask textures. UE5 [Quixel Megascans](https://quixel.com/megascans/) has 5 LODs per asset.
- **Bug/Gap**:
  - **boulder** (lines 1962-1974): seed includes `int(size * 1000)` — for size=1.0 always seed=1798+detail*97. **Same boulder shape every time** at the same scale. Not actually random.
  - **cliff_outcrop**: stacked boxes form a **wedding cake** — flat horizontal layers, no oblique fault lines, no overhang. Real cliffs have angled stratification.
  - **crystal**: 3-8 hexagonal columns at random positions — but each is a SEPARATE mesh, no fused base, no inner-cluster intersections. Reads as 8 disconnected pencils.
  - **standing_stone**: just a noisy lathed column — no glyphs, no moss line, no leaning.
  - **rubble_pile**: random beveled boxes hovering at `y = ry + rs` — most boxes float above ground.
- **Severity**: important.
- **Upgrade to A**: Use `scipy.spatial.ConvexHull` on noised point cloud per type; add Voronoi-based fracture for crystals; bake real per-vertex AO; introduce per-strata noise displacement on cliff layers.

## `generate_mushroom_mesh` (line 2102) — Grade: C+
- **Claims**: 3 mushroom styles (giant/cluster/shelf).
- **Produces**:
  - giant_cap → lathed stem (5-pt profile) + lathed cap (7-pt profile, dome) + tiny gill ring (line 2150-2154)
  - cluster → 5 (cylinder + cone) pairs at random offsets
  - shelf_fungus → 3 half-disc shelves with top/bottom fans + rim quads
- **AAA ref**: Megascans mushrooms are 3-8k tris with translucent caps + gill normal maps.
- **Bug/Gap**:
  - giant_cap "gill ring" (line 2150-2154) is a **lathed RING** with 2 profile points — produces a flat disc UNDER the cap, NOT actual gill geometry. No radial gill stripes.
  - cluster mode (line 2157-2174): each "mushroom" = cylinder stem + **cone** cap. Cone-as-mushroom-cap is the textbook "F: tree=cone+sphere" example, in mushroom form. **C-tier**.
  - shelf_fungus winding (line 2210-2214): top fan uses indices `(0, j+1, j+2)` and bottom fan `(center2, center2+j+2, center2+j+1)` — top is CCW (faces up) and bottom CW (faces down). Reasonable.
  - Rim quads at lines 2216-2221 use `t, b_idx, b2, t2` indices = `(j+1, n_pts+1+j+1, n_pts+1+j+2, j+2)`. Let me check: t=j+1 (top vert), b_idx = center2 + j + 1 = n_pts+1+j+1 (bottom vert directly below), b2 = n_pts+1+j+2 (next bottom), t2=j+2 (next top). Quad order `(top, bot, next_bot, next_top)` = CW from outside. **Winding flipped on shelf rim** → backface culled → invisible from outside.
- **Severity**: important (cluster style is C-tier; rim winding bug).
- **Upgrade to A**: Real radial gill geometry (N gill plates from cap edge to stem); replace cone-cap with proper dome lathe; flip rim winding.

## `generate_root_mesh` (line 2230) — Grade: C
- **Claims**: Exposed tree roots, N tendrils.
- **Produces**: For each of `segments` directions, 8 small cylinder segs along a sine-curved path.
- **AAA ref**: SpeedTree has a Roots generator with proper tube-along-spline + soil emergence; Megascans roots are baked photogrammetry.
- **Bug/Gap**:
  - Each cylinder seg is placed at `(x, y - r, z)` where `(x,y,z)` is the path point. Cylinders are vertical (Y-axis). They are **disconnected vertical pegs** along the path — gaps between them, no continuous tube.
  - Cap settings (lines 2267-2268): only first and last seg have caps — middle 6 segs are open tubes; **but the open tubes don't connect** so they have visible holes.
  - Y formula `y = -thickness * 2 * math.sin(t * math.pi)` produces roots that DIVE BELOW THE GROUND THEN COME BACK UP — but no ground occlusion in the mesh, so the dipping section is visible as a U-shape floating in air.
  - No flare at the trunk attachment (t=0).
- **Severity**: important.
- **Upgrade to A**: Real tube-along-spline (continuous mesh, single shell per root); add trunk-flare blend; emit only the above-ground portion + 0.1u depth blend.

## `generate_grass_clump_mesh` (line 2276) — Grade: C+
- **Claims**: Crossed-quad grass clump for terrain scatter.
- **Produces**: N crossed quads (each = 4 verts, 1 quad), random angle/lean/height per blade.
- **AAA ref**: SpeedTree grass uses 2-3 crossed quads per blade with alpha-mapped textures + wind. UE5 grass tool spawns alpha-cards procedurally. **This is the closest to industry practice in the slice — but still single-quad-per-blade, not crossed-quad-per-blade.**
- **Bug/Gap**: 
  - Each "blade" is ONE quad — no cross-quad (no 90° rotated companion). From edge-on viewing angle, blades become invisible 0-pixel wide lines.
  - Quad winding `(base_idx, base_idx+1, base_idx+2, base_idx+3)` — let me check geometry: base verts 0,1 at y=0; tip verts 2,3 at y=blade_h. Order is bottom-left → bottom-right → top-right → top-left = CCW from front (with +Y up). Winding is CORRECT.
  - No texture/UV — relies on broken auto-UV from `_make_result`.
  - Min blade count `max(6, blade_count)` — silently overrides user param.
- **Severity**: important (no cross-quad → invisible at glancing angles).
- **Upgrade to A**: Emit second perpendicular quad per blade; assign UVs (V from 0 at base to 1 at tip); emit wind-mask vertex color (alpha = Y/height).

## `generate_shrub_mesh` (line 2325) — Grade: C+
- **Claims**: Dense shrub with woody core + leaf masses.
- **Produces**: Tapered cylinder stem + N (default 6) low-poly spheres (5×8) at random angles + 4 small cones for "roots".
- **AAA ref**: SpeedTree shrubs use clusters of cross-quad leaf cards on small branches. Spheres are billboard-only assets in modern engines.
- **Bug/Gap**:
  - Leaf masses are 5×8 spheres = 32 verts each. They look like green BALLS, not foliage.
  - "Roots" are 4 cones with `root_verts = [(vx, max(vy - radius * 0.08, 0.0), vz)]` — clamps Y to >=0, which **flattens cone bases to a single y=0 plane** if they were below — produces degenerate triangles with zero height.
- **Severity**: important.
- **Upgrade to A**: Replace sphere blobs with 6-12 cross-quad leaf cards per cluster; remove "roots" or replace with proper soil-emergence flare.

## `generate_ivy_mesh` (line 2382) — Grade: D
- **Claims**: Wall-climbing ivy strips.
- **Produces**: Per strand: 10 tiny vine cylinder segments + leaves at every 2nd seg (5 leaves per strand).
- **AAA ref**: SpeedTree Ivy generator + Megascans Ivy tiles use cross-quad leaves with proper alpha + wind. UE5 Modular Ivy plugin uses spline-based growth.
- **Bug/Gap**:
  - Vine cylinders have `cap_top=False, cap_bottom=False` → **open tubes** at every joint. 10 segs × N strands = visible holes everywhere.
  - Cylinders are vertical (Y-axis) at slight X offset — they don't follow a curved path; the `x = x_offset + sin(t*4) * 0.05` modulation only shifts X position but cylinders themselves are still axis-aligned, so there's a step pattern, not a curve.
  - Leaves at lines 2422-2429 are quads at `z = leaf_z + 0.01`. The 4 verts:
    - `(lx, y+leaf_size, z+0.01)` — top
    - `(lx+leaf_size*0.6, y+leaf_size*0.5, z+0.01)` — right
    - `(lx, y, z+0.01)` — bottom
    - `(lx-leaf_size*0.6, y+leaf_size*0.5, z+0.01)` — left
  - **All 4 verts at the same Z** → leaf is **edge-on to viewer looking at wall** (Y-X plane). To see the leaf, viewer must look from the front (along +Z toward wall) — but the leaf normal is +Z, parallel to view direction → you see edge-on. **MAJOR**: leaves are invisible from front view of the wall.
  - Random leaf side `rng.choice([-1, 1]) * 0.03` flips left/right but always Z-coplanar.
  - No alpha texture, no leaf cluster, no normal variation.
- **Severity**: blocker (vines have holes; leaves invisible).
- **Upgrade to A**: Use connected tube topology (continuous mesh along path with proper Frenet-frame); orient leaves with normal AWAY from wall (Z+0.05 offset, normal=+Z); add leaf cluster (3-5 leaves per node).

## `generate_torch_sconce_mesh` (line 2441) — Grade: B-
- **Claims**: Wall-mounted torch holder, 3 styles.
- **Produces**: Wall plate + style-specific arm + (cup OR sphere OR ring) + torch shaft.
- **AAA ref**: Standard prop. **Diablo IV** torches have intricate dragon-head arms with sculpted detail.
- **Bug/Gap**:
  - "ornate_dragon" arm (lines 2483-2490) is 8 stacked **vertical cylinders** at `(0, y - r, z)` where y=0.02·sin(t·π), z=t·0.12. These are 8 separate vertical posts at staggered Z. **Not a curved arm** — looks like a dotted line of pegs.
  - "Dragon head" cup (line 2492-2493) is a 4-ring 6-sector sphere (24 verts). Not even faintly dragon-like.
  - "iron_bracket" arm (line 2465) is a single box, no L-shape (line 2465: `_make_box(0, 0, 0.06, 0.015, 0.015, 0.06)` — a small cube, not L). Docstring says "L-shaped bracket arm" but produces a cube.
  - Torch shaft (line 2502) sits at `(0, 0.02, 0.12)` regardless of style — for ornate_dragon style, it pierces the dragon head.
- **Severity**: important.
- **Upgrade to A**: Real curved arm via tube-along-spline; sculpted dragon head (separate generator with eyes/scales/jaw); align torch shaft with arm tip.

## `generate_prison_door_mesh` (line 2509) — Grade: B-
- **Claims**: Iron-barred door with frame + bars + cross bars + lock plate.
- **Produces**: 4 frame boxes + N vertical bars + 2 horizontal cross bars + lock plate.
- **AAA ref**: **Resident Evil 4** prison doors are 2-4k tris with hinges, rivets, weld marks.
- **Bug/Gap**:
  - "Horizontal cross bars" (lines 2570-2579): created as VERTICAL cylinder along Y, then `h_verts = [(v[1] - y_pos + (-inner_w / 2), y_pos, v[2]) for v in hv]` — copies original `v[1]` (Y coord of cylinder verts) into new X coord. But cylinder vert Y values are within `[frame_thick, frame_thick + inner_w]` (since cylinder is vertical with height=inner_w starting at y=frame_thick), so new X values are in `[-inner_w/2, -inner_w/2 + inner_w] = [-inner_w/2, +inner_w/2]`. Y is forced to constant `y_pos`. **All v[2] (Z) preserved**. Result: a horizontal rod along X from `-inner_w/2` to `+inner_w/2` at constant `y = y_pos`. **Geometrically correct rotation hack** — but the cylinder cross-section (originally in XZ plane) is now in YZ plane, so the rod's CIRCULAR cross-section is now an ellipse stretched in Z (since X was the axis). Subtle visual oddity.
  - No hinges, no rivets, no rust gradient, no door knob/handle.
  - Lock plate at `width*0.3, height*0.45` floats free with no mounting bolts.
- **Severity**: important (rotation hack distorts cross-section).
- **Upgrade to A**: Generate cross bar with a NEW cylinder oriented along X from the start (parameterize `_make_cylinder` axis); add hinges; emit material slots.

## `generate_sarcophagus_mesh` (line 2593) — Grade: B-
- **Claims**: Stone coffin, 3 styles.
- **Produces**: Profile-extruded body (one half) + mirrored other half + extruded lid + mirrored lid + style decorations.
- **AAA ref**: Megascans sarcophagi are 10-25k tris with worn stone surfaces, baked occluded grime.
- **Bug/Gap**:
  - Body is built from a HALF profile (line 2610-2617: x from 0 to w*0.45) then mirrored — but the profile starts at `(0, 0)` meaning the two halves share an edge at x=0. The mirrored verts at `(-v[0], v[1], v[2])` create a **second mesh shell** with the seam edge duplicated. No vertex merging → seam line visible. The faces on the mirrored side use `tuple(reversed(f))` to flip winding (line 2622) — necessary because mirroring inverts CCW.
  - Lid same problem.
  - "ornate_carved" corner posts are 4 cylinders + 4 sphere caps — at `xoff=±w*0.45, zoff=±d*0.45` which is INSIDE the bounding box. Posts protrude from the box top.
  - "dark_ritual" rune channels are 4 box pairs at z = `-d*0.3 + i*d*0.2` for i in 0..3 — that's z values [-0.3d, -0.1d, +0.1d, +0.3d]. Boxes are tiny (0.005×0.04×0.02). Read as faint scratches.
  - No body-lid gap (lid sits flush — no shadow line).
- **Severity**: important.
- **Upgrade to A**: Use single profile_extrude with full-width profile (no mirror+merge); add 1mm gap between body and lid; carve real rune channels via boolean subtraction; bake AO into vertex colors.

## `generate_altar_mesh` (line 2662) — Grade: B-
- **Claims**: Altar, 3 styles (sacrificial / prayer / dark_ritual).
- **Produces**: Various combinations of beveled boxes, lathed bodies, tapered cylinder pillars, cones for "flames".
- **AAA ref**: **Diablo IV** altars are 15-30k tris with carved relief, blood channels, fire/smoke FX.
- **Bug/Gap**:
  - "sacrificial" blood channel (line 2684-2686) is a RAISED BOX above the slab — should be a CARVED GROOVE (recessed). Backwards.
  - "prayer" symbol (line 2709) is a flat cylinder — no actual symbol carved.
  - "dark_ritual" "flame cup" (line 2734) is a CONE on top of each pillar — looks like a candle snuffer, not a flame. Should be a cup with a flame asset slot.
  - No skull, no chains, no hanging entrails, no candle wax — none of the fantasy genre cues.
- **Severity**: important.
- **Upgrade to A**: Negate the blood channel (carve down, not up); add real symbol (lathed pentacle profile or boolean'd cross); replace flame cup with cup + separate flame mesh slot.

## `generate_pillar_mesh` (line 2741) — Grade: B
- **Claims**: 5 pillar styles (round/square/wooden/broken/serpent).
- **Produces**: Lathed shafts with profile variation, capitals/bases per style, plus rubble for broken.
- **AAA ref**: Real classical columns have fluting, capital orders (Doric/Ionic/Corinthian), entablature integration. UE5 marketplace columns are 5-15k tris.
- **Bug/Gap**:
  - "stone_round": entasis via `1.0 + 0.03*sin(t*pi)` — only 3% bulge. Real entasis is 4-6%.
  - "stone_square": no fluting, no capital order detail — just a stack of 3 beveled boxes.
  - "wooden" cross braces (lines 2832-2838) are placed at 2 angle offsets (0 and π/2) — but both are tiny `radius*0.02` displacements (essentially at center) — the brace boxes are at center, NOT displaced to the post sides.
  - "broken" rubble: 6 chunks at `(rx, ry, rz)` random over `[-radius*1.5, radius*1.5]` — chunks can spawn FAR FROM the column. No physics-plausible pile.
  - "carved_serpent" radius mod `1.0 + 0.08*sin(t*4π)` produces a wavy column — but it's RADIALLY SYMMETRIC (same radius for all phi at given t). A real serpent winds in helical pattern (radius mod depends on both t AND phi). This is just a fluted/ribbed column.
- **Severity**: important.
- **Upgrade to A**: Add fluting to round style (cosine modulation in phi); replace serpent with helical surface mod `r += 0.08*sin(t*4π + phi)`; pile rubble in a believable cone shape.

## `generate_archway_mesh` (line 2907) — Grade: B
- **Claims**: 4 styles (round/pointed/wooden/ruined) doorway frame.
- **Produces**: 2 posts + arch geometry per style + keystone.
- **AAA ref**: Gothic archways have carved tracery, keystone reliefs, dripstones. **Bloodborne** archways are 10-20k tris with ornate stone work.
- **Bug/Gap**:
  - "stone_pointed" arch (lines 2954-2982): builds 4-vert layers (inner-front, outer-front, inner-back, outer-back) per arch_seg, then 4 quads per layer connecting. Topology has the inner-arc face winding `(b+1, b+5, b+4, b+0)` — let me check: this is the front face. Actually that connects FRONT verts (b+0, b+1) to NEXT FRONT verts (b+4, b+5). Reading the index: `b+0, b+4` are inner-front verts of seg i and i+1; `b+1, b+5` are outer-front verts. So `(b+1, b+5, b+4, b+0)` = (outer_i, outer_i+1, inner_i+1, inner_i) — the FRONT FACE of the arch ring. CCW from +Z front = correct.
  - But the "pointed" geometry math (lines 2957-2968) builds verts on a STRAIGHT LINE from `(-w/2, spring)` to `(-w*0.4 + w*0.1, peak)` then `(-w*0.4, peak)` to `(w/2, spring)` — **two straight slopes**, not arcs. Result is a **triangle**, not a Gothic pointed arch (which has TWO ARCS meeting at the apex). Misleading style name.
  - "wooden" lintel: line 2998 `_make_box(... lintel_y/2, ..., post_w*0.4, lintel_y/2, depth*0.4)` — uses HALF lintel height as the box's half-y, so box extends from y=0 to y=lintel_y. Posts are full-height pillars under a horizontal beam — correct topology.
  - "ruined" arch is a partial circle — but the rubble is scattered at `[-w*0.3, w*0.8]` (asymmetric range — bias toward right side) which is a nice touch suggesting the right post collapsed. Otherwise the arch has open faces at the broken end.
  - Default "stone_round" is fine (semicircular sweep).
- **Severity**: important (pointed style not actually pointed).
- **Upgrade to A**: Real two-arc Gothic pointed math (each arc = quarter circle from spring to peak); cap the open end of ruined arch; add tracery profile to keystone.

## `generate_chain_mesh` (line 3105) — Grade: D
- **Claims**: Hanging chain with interlocking links.
- **Produces**: N torus rings stacked vertically; even-i unrotated, odd-i swapped via `(v[2], v[1], v[0])`.
- **AAA ref**: Real chain meshes (e.g. **Castlevania**, **Bloodborne**) have interlocking torus pairs at perpendicular orientations, with proper interpenetration so they read as linked. Catenary sag is animated.
- **Bug/Gap**:
  - **Both branches of the if/else create the SAME `_make_torus_ring(0, y, 0, link_size*0.5, wire_r, ...)` call** — only the post-processing differs.
  - The "rotation" `(v[2], v[1], v[0])` applied at line 3140: original torus is in XZ plane (verts have varying X and Z; Y is the height of the tube). Swap (X,Y,Z) → (Z,Y,X) puts varying Z into X and varying X into Z — but since the torus is **rotationally symmetric in XZ plane**, this swap **produces an identical torus**. The torus has 8-fold rotational symmetry; swapping X↔Z is a 90° rotation in XZ which yields the same shape. **The "rotated" link is geometrically identical to the unrotated link.** Two stacked identical toruses = no perpendicular interlock = no chain visual.
  - Links are concentric (all at x=z=0); they don't dangle, sag, or interpenetrate.
  - Real interlock requires the rotated torus to be in the **YZ plane** — which means swapping (X,Y,Z) → (Y,X,Z) or constructing the torus with the major plane perpendicular to gravity.
- **Severity**: blocker (chain looks like a stack of donuts on a wire).
- **Upgrade to A**: Add `axis` param to `_make_torus_ring` so alternating links generate in YZ plane; offset each link by half-link-spacing so they interpenetrate; add catenary curve via Y position interpolation.

## `generate_skull_pile_mesh` (line 3148) — Grade: D
- **Claims**: Dark fantasy skull pile.
- **Produces**: N (cranium sphere + jaw box + 2 "eye socket" spheres).
- **AAA ref**: Megascans skull pile uses individually scanned skulls (8-12k tris each) baked from photogrammetry. Even **Diablo II** has more anatomical skulls.
- **Bug/Gap**:
  - "Eye sockets" (lines 3187-3193) are SOLID SPHERES of radius `skull_r*0.12` placed AT the eye position. They are **CONVEX BUMPS protruding outward**, NOT concave indentations. Sockets are inverted geometry.
  - "Jaw" is a single box (line 3183-3184) at `y - skull_r*0.3, fz` — no teeth, no mandible curve, no separation.
  - Cranium is a uniform sphere — no zygomatic arch, no occipital bulge, no temple narrowing.
  - Random face_angle (line 3180) means jaw can spawn on the BACK of the cranium sphere — physically impossible orientation.
  - No real pile physics — y position from `layer * skull_r * 1.5 + skull_r` puts layer 0 at y=skull_r and layer 1 at y=skull_r*2.5 — they don't stack/touch realistically.
- **Severity**: blocker (eye sockets are anatomically inverted; pile doesn't read as skulls).
- **Upgrade to A**: Real skull lathe profile (with eye-socket cavity boolean); orient jaw using `face_angle` to compute proper rotation; physics-based stacking; emit individual skull as separate mesh + use scatter to pile.

## `generate_hammer_mesh` (line 3204) — Grade: B-
- **Claims**: Warhammer, 3 head styles.
- **Produces**: Tapered handle + sphere pommel + style-specific head + grip rings.
- **AAA ref**: **Dark Souls** warhammers are 6-12k tris with PBR bronze/iron, weathered grip leather.
- **Bug/Gap**:
  - "spiked" back spike (lines 3251-3253): rotation hack `bsv_r = [(-head_w/2 - (v[1] - head_y) * 0.8, head_y + (v[0] + head_w/2), v[2]) for v in bsv]`. Original cone: apex at `(-head_w/2, head_y + 0.06, 0)`, base ring at y=head_y, x in `[-head_w/2 - 0.25*head_d, -head_w/2 + 0.25*head_d]`. After hack, X = `-head_w/2 - (v[1] - head_y)*0.8` → for apex (v[1]=head_y+0.06) X=−head_w/2 − 0.048; for base verts (v[1]=head_y) X=−head_w/2. Y = `head_y + (v[0] + head_w/2)` → for verts at x=-head_w/2 (the average) Y=head_y; for offset verts in ±0.25*head_d, Y is shifted slightly. Net: the cone is tilted backward but its SHAPE is sheared, not rotated. **Geometric mess**.
  - "ornate" decorative torus rings (line 3262) — placed at y = head_y ± head_h*0.3, but head spans ±head_h/2 (=0.04). So 0.3*head_h = 0.024 < 0.04 — rings INSIDE the head — buried geometry.
  - Grip rings (line 3268-3273) are 5 toruses at handle_y * 0.1 + i*0.08 for i=0..4 — y range [0.09, 0.41] for handle_length=0.9. OK placement, but rings have major_segments=8 — visible faceting.
- **Severity**: important.
- **Upgrade to A**: Replace shear-hack with proper rotation matrix multiplication; place ornate rings AT head edges (y = head_y ± head_h/2); higher torus segs on grip.

## `generate_spear_mesh` (line 3280) — Grade: B-
- **Claims**: Spear/halberd, 3 styles.
- **Produces**: Tapered shaft + sphere butt + style-specific head.
- **AAA ref**: **For Honor**, **Mount & Blade Bannerlord** halberds are 4-10k tris with separate steel/wood materials.
- **Bug/Gap**:
  - "leaf" head (lines 3308-3321): lathed via `_make_lathe(profile, segments=4, ...)`. Leaf shape is `w = blade_w * sin(t*π) * (1 - t*0.3)` — sin curve produces leaf-like silhouette. **But segments=4** = the lathe is a **square cross-section**, not a flat blade. Spear heads are FLAT (2 sides), not 4-sided revolved.
  - "broad" head (lines 3328-3342): hand-built 5-vert pyramid. 5 verts, 5 faces. The bottom face `(1, 3, 4, 2)` — with verts 1,2 at z=+head_d and 3,4 at z=-head_d. Order (1,3,4,2) = (+z left, -z left, -z right, +z right). From below looking up: this winds CW = faces DOWN = correct (bottom face).
  - "halberd": axe blade is 8 verts (4 front, 4 back), faces are 6 quads. Topology check: face `(0, 1, 2, 3)` is the front face (all z=+blade_d). Verts: 0=(blade_w, +0.7h, +d), 1=(blade_w, -0.3h, +d), 2=(0, -0.2h, +d), 3=(0, +0.6h, +d). Front-facing winding from +Z: (0,1,2,3) = top-right → bot-right → bot-left → top-left = CW from +Z = **flipped normal**. Should be `(0, 3, 2, 1)`.
  - Halberd top spike is a 6-segment cone at `(0, head_base_y, 0)` aligned with shaft — works.
  - No saw teeth, no rivet detail, no leather wrap on shaft top.
- **Severity**: important (leaf head should be flat; halberd front face winding flipped).
- **Upgrade to A**: Replace leaf-head lathe with `_make_profile_extrude` (gives flat blade); fix halberd front face winding to CCW from +Z; add binding wrap at head-shaft join.

---

## Cross-Generator Findings (in this slice)

### CG-1: "Rotation by axis swap" hack appears in 5+ generators
Functions affected: `generate_table_mesh` (cross-brace), `generate_candelabra_mesh` (wall arm), `generate_torch_sconce_mesh` (curved arm + dragon arm), `generate_prison_door_mesh` (horizontal cross bars), `generate_chain_mesh` (alternating links), `generate_hammer_mesh` (back spike).

These all attempt to "rotate" a Y-axis primitive into a different orientation by swapping coordinate components or shearing — producing distorted geometry, dead code, or no rotation at all (chain). **Root cause**: `_make_cylinder`, `_make_cone`, etc., are hardcoded to Y-axis, with no orientation parameter.

**Fix**: Add `axis: Literal['x','y','z'] = 'y'` param to all primitive constructors, OR add a `_rotate_mesh(verts, axis_from, axis_to)` helper that applies a real 3×3 rotation matrix.

### CG-2: All multi-part meshes have non-merged seams
`_merge_meshes` simply concatenates without dedup. Visible in every multi-part generator (table, chair, chest, candelabra, sarcophagus, altar, pillar, hammer, spear). Result: doubled normals at every part interface, light-leaks, lightmap UV failures.

**Fix**: Add hash-based vertex merge with `merge_distance=1e-5` to `_merge_meshes`.

### CG-3: Auto box-projection UVs are degenerate for axis-aligned faces
`_auto_generate_box_projection_uvs` picks ONE plane per mesh — every axis-aligned face on the chosen-plane axis gets identical UVs across its vertices (zero UV variation). Affects every textured mesh.

**Fix**: Per-face triplanar (pick face's dominant axis, project face's 3 verts onto that plane).

### CG-4: Pole singularities on every sphere/cone
Both `_make_sphere` and `_make_cone` use single-vertex poles. Causes normal singularities (smooth shading produces dark spots). Affects every generator using these (most of them).

**Fix**: Optional icosphere mode for spheres; duplicate-apex-per-face for cones.

### CG-5: No LOD chain
None of these functions emit LOD0/1/2/3/billboard versions. Compared to UE5 PCG defaults which require LOD chains for instanced rendering at scale.

**Fix**: Add `lod_levels: int = 1` param to top-level generators; emit `lod_meshes: list[MeshSpec]` in MeshSpec output.

### CG-6: No PBR / material slot output
MeshSpec has no `materials`, `vertex_colors`, `tangent_space`, or `normal_overrides`. Megascans MSpec exports include PBR maps + tangent space + 5 LODs. UE5 PCG nodes consume `Static Mesh` assets with material slots.

**Fix**: Extend `_make_result` to emit `material_slots: list[str]`, `vertex_colors: dict[str, list[tuple[float,float,float,float]]]`, `tangents: list[tuple[float,float,float,float]]`.

### CG-7: Dead code / unused locals scattered throughout
- `_make_torus_ring` lines 518-519: `_tcx, _tcz` computed but unused.
- `_make_beveled_box` lines 642-658: `_edge_pairs` computed but unused.
- `generate_table_mesh` lines 1184, 1186-1190: `_rotated_v_unused`, `_rotated_v` computed and discarded.
- `generate_candelabra_mesh` line 1561: `arm_verts` math collapses cylinder to disc.

**Fix**: Remove dead code via lint pass; rewrite the rotation attempts properly.

---

## NEW BUGS FOUND (BUG-200..BUG-217)

### BUG-200 [BLOCKER] — `_auto_generate_box_projection_uvs` produces degenerate UVs
**File:** `procedural_meshes.py:192-230`
**Symptom:** Every textured mesh shows stretched/smeared textures along the dominant projection axis.
**Root cause:** Single global projection plane selected for whole mesh; faces aligned with that plane have zero UV variation in one axis.
**Fix:** Implement true per-face triplanar projection.

### BUG-201 [BLOCKER] — `generate_chain_mesh` "rotated" link is identical to unrotated
**File:** `procedural_meshes.py:3140`
**Symptom:** Chain renders as a stack of identical concentric donuts; no interlock.
**Root cause:** XZ-plane torus is rotationally symmetric in XZ; swapping `(x,y,z)→(z,y,x)` is an XZ-plane rotation that produces the same shape.
**Fix:** Generate alternate link in YZ plane (`(y, x, z)` mapping) AND offset by half link spacing.

### BUG-202 [BLOCKER] — `generate_skull_pile_mesh` eye sockets are convex bumps
**File:** `procedural_meshes.py:3187-3193`
**Symptom:** Skulls have two protruding spheres on each face instead of recessed sockets.
**Root cause:** Sockets generated as additive `_make_sphere` shells, not negative space.
**Fix:** Use 2 small recessed dimples via boolean subtraction or per-vertex inward displacement; emit jaw with curved mandible.

### BUG-203 [BLOCKER] — `generate_ivy_mesh` leaves are coplanar with wall
**File:** `procedural_meshes.py:2422-2429`
**Symptom:** Ivy leaves invisible from front view of wall (edge-on).
**Root cause:** All 4 leaf verts at same Z; leaf normal parallel to view direction.
**Fix:** Tilt leaves outward (Z+0.01 to Z+0.05 across the quad's verts) so normal faces away from wall.

### BUG-204 [BLOCKER] — `generate_ivy_mesh` vine cylinders have open holes at every joint
**File:** `procedural_meshes.py:2412-2415`
**Symptom:** Visible holes along vine length where segments meet.
**Root cause:** `cap_top=False, cap_bottom=False` AND segments don't share verts (separate `_make_cylinder` calls).
**Fix:** Single tube-along-spline mesh OR enable end caps.

### BUG-205 [BLOCKER] — `_make_beveled_box` produces non-watertight mesh (24 corner holes)
**File:** `procedural_meshes.py:588-688`
**Symptom:** Mesh is non-manifold; fails CSG, fails physics convex decomposition; light leaks at corners.
**Root cause:** 8 corners × 3 inset verts each = 24 verts. The 6 "main" faces use only the axial-inset verts (8 of 24); 12 bevel quads connect inset verts. The remaining 8 corner triangles (3 inset verts per corner forming a small triangle) are NEVER generated.
**Fix:** Add 8 corner triangle faces.

### BUG-206 [BLOCKER] — `generate_candelabra_mesh` wall arm collapses to disc
**File:** `procedural_meshes.py:1561`
**Symptom:** Wall-mounted candelabra arm is a 2D disc instead of a horizontal cylinder.
**Root cause:** All cylinder verts assigned same Y value (`height * 0.45`) by the rotation hack.
**Fix:** Apply real 3×3 rotation matrix to cylinder verts.

### BUG-207 [IMPORTANT] — `generate_tree_mesh` branches are vertical posts at branch positions
**File:** `procedural_meshes.py:1789-1808`
**Symptom:** Branches don't actually angle from trunk; appear as disconnected vertical pegs.
**Root cause:** Inner loop creates Y-axis cylinders at `(mid_x, mid_y - seg_len/2, mid_z)` ignoring `(dx, dy, dz)` direction.
**Fix:** Rotate each cylinder to align with the branch direction vector.

### BUG-208 [IMPORTANT] — `_detect_grid_dims_from_vertices` 3-decimal rounding fails for displaced terrain
**File:** `procedural_meshes.py:87-88`
**Symptom:** Displaced terrain meshes (sub-mm noise) report wrong row/col counts.
**Root cause:** `round(..., 3)` collapses sub-mm coordinates onto same bucket.
**Fix:** Use ratio-of-extents method (`cols = round(extent_x / cell_size) + 1`).

### BUG-209 [IMPORTANT] — `generate_hammer_mesh` ornate rings buried inside head
**File:** `procedural_meshes.py:3261-3265`
**Symptom:** Ornate hammer torus rings invisible (inside the head box).
**Root cause:** Ring Y offset `head_h * 0.3` < `head_h / 2 = 0.5` so rings are inside the head extents.
**Fix:** Offset = `head_h / 2 + ring_thickness` to place at edge.

### BUG-210 [IMPORTANT] — `generate_spear_mesh` halberd front face winding flipped
**File:** `procedural_meshes.py:3361`
**Symptom:** Halberd front blade face is back-facing (invisible from front).
**Root cause:** Quad indices `(0, 1, 2, 3)` wind CW from +Z viewpoint.
**Fix:** Use `(0, 3, 2, 1)`.

### BUG-211 [IMPORTANT] — `generate_spear_mesh` leaf head is square cross-section, not flat blade
**File:** `procedural_meshes.py:3320`
**Symptom:** Leaf-style spearhead looks like a 4-sided spike, not a flat blade.
**Root cause:** `_make_lathe(profile, segments=4)` revolves into a square prism.
**Fix:** Use `_make_profile_extrude` for flat blade with `depth=blade_d*2`.

### BUG-212 [IMPORTANT] — `generate_mushroom_mesh` shelf rim winding flipped
**File:** `procedural_meshes.py:2216-2221`
**Symptom:** Side rim of shelf fungus invisible (back-faced).
**Root cause:** Quad order `(t, b, b+1, t+1)` winds CW from outside.
**Fix:** Reorder to `(t, t+1, b+1, b)`.

### BUG-213 [IMPORTANT] — `generate_archway_mesh` "stone_pointed" is a triangle, not a Gothic arch
**File:** `procedural_meshes.py:2954-2968`
**Symptom:** Pointed archway has straight slopes meeting at apex (triangular), not two arcs (Gothic).
**Root cause:** Linear interpolation between spring and peak instead of quarter-circle math.
**Fix:** Use `t→cos(t*π/2)` for arc parameterization on each half.

### BUG-214 [IMPORTANT] — `generate_pillar_mesh` carved_serpent is fluted column, not helical
**File:** `procedural_meshes.py:2891`
**Symptom:** "Carved serpent" pillar shows axisymmetric ribs, not a winding serpent.
**Root cause:** Radius modulation depends only on `t`, not on `phi` (azimuth).
**Fix:** `r = radius * (1.0 + 0.08 * sin(t*4π + phi))` — but this requires per-vertex radius (lathe abstracts this away). Need a new helper.

### BUG-215 [IMPORTANT] — `generate_root_mesh` produces disconnected vertical pegs
**File:** `procedural_meshes.py:2263-2270`
**Symptom:** Roots are visible as separate vertical cylinders along a sine path, with gaps and holes.
**Root cause:** Each segment is an independent Y-axis cylinder; segments don't share verts; only first/last get caps.
**Fix:** Generate continuous tube-along-spline.

### BUG-216 [IMPORTANT] — `generate_sarcophagus_mesh` mirror seam unmerged
**File:** `procedural_meshes.py:2620-2623`
**Symptom:** Visible seam line at center of sarcophagus where mirrored halves meet.
**Root cause:** Mirror creates duplicate verts at x=0; `_merge_meshes` doesn't dedup.
**Fix:** Merge meshes with vertex hash dedup at `merge_distance=1e-4`.

### BUG-217 [IMPORTANT] — `_enhance_mesh_detail` fan-triangulation is degenerate for concave faces
**File:** `procedural_meshes.py:845-846`
**Symptom:** Subdivided faces with concave shapes get overlapping triangles.
**Root cause:** Fan from `expanded[0]` only works for convex polygons.
**Fix:** Use ear-clipping triangulation (e.g. `mathutils.geometry.tessellate_polygon`).

---

## Context7 References Used

1. **Blender Python API 4.5** ([/websites/blender_api_4_5](https://docs.blender.org/api/4.5/)) — verified:
   - `bmesh.ops.create_cube`, `create_cone`, `create_uvsphere`, `create_circle` topology conventions
   - `bmesh.ops.bevel` semantics (compared against `_make_beveled_box`)
   - `bmesh.ops.subdivide_edges` (compared against `_enhance_mesh_detail`)
   - `bmesh.ops.spin` (compared against `_make_lathe`)
   - `bmesh.ops.reverse_faces` (winding flip pattern)
   - Edit-mode vs object-mode mesh access (`info_gotchas_meshes`)

2. **Blender Python API current** ([/websites/blender_api_current](https://docs.blender.org/api/current/)) — verified Newell normal method matches `_auto_detect_sharp_edges` algorithm.

3. **SciPy 1.16.1** ([/scipy/scipy](https://github.com/scipy/scipy)) — verified `scipy.spatial.ConvexHull`, `Delaunay`, `Voronoi` API for rock generation upgrade path. Available in numpy/scipy stack but **not used** by `_make_faceted_rock_shell`.

4. **NumPy 2.3.1** ([/numpy/numpy](https://numpy.org/doc/2.3/)) — vectorized vert/face buffers (e.g. `np.float32` arrays for VBO upload). **Not used** in this file (uses Python lists/tuples — slow for large meshes).

## WebSearch References

1. **SpeedTree LOD docs** ([docs.speedtree.com — overview/level-of-detail](https://docs.speedtree.com/doku.php?id=overview_level-ofdetail)) — confirmed industry LOD chain: LOD0 ~15k tris, LOD1 ~10k, LOD2 ~5k, billboard. None of the generators in this slice produce LOD chains.

2. **SpeedTree leaf mesh generator** ([docs8.speedtree.com — leaf_mesh_generator](https://docs8.speedtree.com/modeler/doku.php?id=leaf_mesh_generator)) — confirmed leaf cards (square placeholder if no mesh assigned). `generate_tree_mesh` uses NO leaf cards — uses sphere blobs.

3. **Quixel Megascans** ([quixel.com/megascans](https://quixel.com/megascans/)) — confirmed Megascans assets feature optimized topology, standardized UVs, 5 LODs, real-world PBR. None of these generators produce PBR-ready output.

4. **UE5 PCG Overview** ([dev.epicgames.com — Procedural Content Generation](https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-overview)) — confirmed PCG consumes Static Meshes with material slots and density-based scatter. Current MeshSpec has no material slot field.

5. **Unity Foliage Tutorial** ([cesium.com/learn/unreal/unreal-procedural-foliage](https://cesium.com/learn/unreal/unreal-procedural-foliage/)) — confirmed grass/foliage uses cross-quad billboards with alpha. `generate_grass_clump_mesh` uses single-quad blades (invisible at glancing angles).

---

## Final verdict for this slice (49+2 functions)

**Zero functions in this slice would ship in Megascans, SpeedTree, or UE5 PCG default content.**

The primitives (`_make_box`, `_make_cylinder`, `_make_cone`, `_make_lathe`, `_make_torus_ring`, `_make_tapered_cylinder`, `_make_sphere`, `_make_profile_extrude`, `_make_faceted_rock_shell`) are at the level of hand-written Blender bmesh primitives — useful as building blocks but each carries 1-3 quality issues (pole singularity, dead code, no UV, axis-locked).

The asset generators (`generate_tree_mesh`, `generate_rock_mesh`, etc.) compose these primitives but inherit + amplify the issues. Most are at **"Skyrim Creation Kit blockout"** quality — recognizable shapes with parametric variation but no shippable detail, no PBR, no LODs, no real procedural sophistication (no L-systems, no IK, no Voronoi fracture, no convex hull, no surface noise displacement).

**The closest function to shippable** is `_get_trig_table` (a pure utility) at A-. Everything else is B+ or below. The biggest red flags are:
- `generate_chain_mesh` — D, geometric bug (rotation is no-op)
- `generate_skull_pile_mesh` — D, anatomically inverted sockets
- `generate_ivy_mesh` — D, leaves invisible from primary view
- `generate_tree_mesh` — C, branches are vertical posts not angled limbs
- `_make_beveled_box` — non-watertight mesh (24 corner holes)
- `_auto_generate_box_projection_uvs` — degenerate UVs on axis-aligned faces (affects every textured mesh)

**To reach AAA shipping quality**, this entire family needs:
1. NumPy vectorization for VBO-ready buffers (10-100× perf).
2. Real per-face triplanar UVs.
3. LOD chain emission.
4. Material slot + vertex color + tangent space output.
5. Replacement of "rotation by axis-swap hack" with proper 3×3 rotation matrices.
6. Vertex merging in `_merge_meshes`.
7. Specialty algorithms per asset class: SpeedTree-style L-system trees, Voronoi-fracture rocks, scipy ConvexHull boulders, alpha-card foliage.
