# A4 — procedural_meshes.py — Function-by-Function Grades (296 functions)
## Date: 2026-04-16  |  Auditor: Opus 4.7 ultrathink  |  Method: AST enumeration + Read-by-chunks + cross-pattern verification

**Source:** `veilbreakers_terrain/handlers/procedural_meshes.py` (22,607 lines, 296 functions per AST walk — file header claims 293 top-level generators).

---

## Summary

### Grade distribution
| Grade | Count | % | Notes |
|-------|-------|---|-------|
| A+ | 0 | 0% | Nothing here would ship in Megascans/SpeedTree as-is |
| A  | 0 | 0% | Nothing matches UE5 PCG default quality |
| A- | 4 | 1.4% | `_get_trig_table`, `_make_result`, `_alias_generator_category`, `_compute_dimensions` — pure utility helpers, well-coded |
| B+ | 18 | 6% | Solid primitives + a handful of unusually layered generators (rock_cliff_outcrop branch, faceted rock shell, beveled_box) |
| B  | 78 | 26% | Recognizable shapes built from primitives — silhouette reads, but blockout-tier vs. AAA |
| B- | 145 | 49% | Recognizable + at least one structural bug (broken rotation math, axis swaps that mangle geometry, misuse of mirror-as-rotate, double-vertex sharp edges that produce non-manifold seams, no parameter respect, capped open cylinders, etc.) |
| C+ | 32 | 11% | Partially correct (fox snout rotation produces flipped cone; cart axles use 1D-translation instead of rotation; throne, bookshelf books, candelabra arms all "approximated" with wrong-axis cylinders) |
| C  | 14 | 5% | Stub-quality — the named asset is suggested but not delivered (rabbit hind leg = sphere+stub; bola = 3 spheres; cobweb = strands without sheet topology; whip = box chain) |
| D  | 5 | 2% | Wrong shape entirely (`generate_skull_pile_mesh` skull = sphere+box+sphere-eyes; `generate_cobweb_mesh` not actually a web; `generate_dripping_water_mesh` is a stalactite, not water; `generate_iron_maiden_mesh` doesn't open; `generate_living_wood_shield_mesh` branches don't grow) |
| F  | 0 | 0% | No empty stubs found — every function returns geometry |

Net composite: **B-** average. Compared to AAA targets (Megascans hero asset ~50-200K tris with 4K PBR, SpeedTree procedural with wind/SSS, UE5 PCG with collision LODs and material instances) **everything here is blockout-tier**. The library is internally consistent and parameter-respecting at the silhouette level; it is nowhere near ship quality.

### Top 10 WORST functions (must-fix before shipping anything player-facing)
1. **`generate_cobweb_mesh` (line 18810)** — 117 lines, doesn't actually produce a web sheet; produces stretched cylinders and disconnected diagonal lines. Severity: blocker.
2. **`generate_iron_maiden_mesh` (line 18460)** — Sealed box, no pivoting door, no internal spike volume. Severity: blocker for prop interactivity.
3. **`generate_skull_pile_mesh` (line 3148)** — Each "skull" = sphere + 1 box + 2 protruding spheres for eyes (which stick OUT of the head, not into sockets). Severity: blocker — silhouette wrong.
4. **`generate_dripping_water_mesh` (line 19106)** — Function name promises water; implementation produces a stalactite + small spheres labeled "drops" with no fluid volume. Severity: important.
5. **`generate_bola_mesh` (line 5660)** — 3 spheres + 3 stretched boxes labeled "rope". Reads as "three balls floating together." Severity: blocker.
6. **`generate_whip_mesh` (line 3587)** — Stack of boxes, no chain articulation, no taper variation, no curl. Severity: important.
7. **`generate_living_wood_shield_mesh` (line 14081)** — Branches modeled as straight cylinders welded to a disc. No organic growth pattern. Severity: important.
8. **`generate_chain_mesh` (line 3105)** — Even-indexed and odd-indexed links use IDENTICAL torus orientation (line 3132 `else:` branch generates same torus then "rotates" by tuple swap that *only works for axis-aligned rings*). Visual will show all links coplanar, no interlock. Severity: important. *Additional bug:* axis swap `(v[2],v[1],v[0])` is a 90° around-Y, not the perpendicular-link orientation chains require.
9. **`generate_torch_sconce_mesh` (line 2441)** — `style="ornate_dragon"` is a curved cylinder + sphere; no dragon morphology. Severity: important (false advertising).
10. **`generate_spider_web_mesh` (line 9201)** — Geometric spokes-and-rings; no sheet polygon, no irregular spans. Renders as a metal grate, not a web. Severity: important.

### Top 10 BEST functions (still B+, none reach A)
1. **`_make_faceted_rock_shell` (line 867)** — Real ring/segment fracturing with seeded RNG, ridge falloff, top/base flattening. Closest to a Quixel small-prop blockout among all generators.
2. **`_make_beveled_box` (line 588)** — Proper 24-vertex chamfered box with 6 main + 12 bevel-edge faces. Clean topology.
3. **`_make_lathe` (line 1010)** — Solid revolve primitive supporting close_top/close_bottom flags. Foundation of dozens of decent generators.
4. **`_enhance_mesh_detail` (line 691)** — Adaptive sharp-edge midpoint subdivision with Newell normals. Real algorithm, not placeholder.
5. **`_auto_detect_sharp_edges` (line 132)** — Newell normal + dihedral threshold, handles boundary edges correctly.
6. **`generate_rock_mesh` "cliff_outcrop" branch (line 1976)** — Layered tilted slabs + fin + scattered base rocks; reads like an actual rock formation.
7. **`generate_rune_stone_mesh` (line 14279)** — 127 lines per-brand geometry, six unique silhouettes, the most ambitious per-variant generator in the file.
8. **`generate_temple_mesh` "gothic" branch (line 21879)** — Walls + columns + pointed roof + altar; recognizable temple shell.
9. **`generate_harbor_dock_mesh` "wooden" (line 22071)** — Pier + piles + finger berths + crane + warehouse; multi-system composition.
10. **`generate_archway_mesh` "stone_pointed" (line 2944)** — Real Gothic two-arc construction with keystone.

### Cross-cutting verdict
The library is a **"primitive composition" engine**. Every generator is `_make_box` / `_make_cylinder` / `_make_sphere` / `_make_lathe` / `_make_torus_ring` glued together, then `_merge_meshes` + `_enhance_mesh_detail`. There is **no organic deformation** (no displacement, no noise other than RNG vertex jitter), **no PBR material binding** (only category strings), **no LOD chain**, **no UV unwrap** beyond box-projection, and **no collision proxy generation**. Megascans/SpeedTree/UE5 PCG would reject every mesh as "still in blockout."

Critically, **rotation operations are pervasively broken**. The pattern `# Rotate by swapping axes` appears ~30 times (e.g. line 1184, 2578, 5187, 7590) but the swap is incorrect for arbitrary angles — they perform tuple permutations that produce 90° rotations only, often around the wrong axis. Wherever a function comments "approximate by axis swap" or "Rotate to angle outward", inspect that geometry — it is probably mangled.

---

## Function-by-Function Grades

### 1. `_grid_vector_xyz` (line 69) — Grade: **A-**
- **Claims:** Extract (x,y,z) from Vector or tuple.
- **Produces:** 3-tuple of floats; supports both bpy Vector and plain sequence.
- **AAA reference:** Houdini hou.Vector3 conversion helper.
- **Bug/Gap:** None — minimal, robust.
- **Severity:** polish.
- **Upgrade to A:** Add type annotation for the `Any` parameter (Protocol with x/y/z attributes).

### 2. `_detect_grid_dims_from_vertices` (line 80) — Grade: **B+**
- **Claims:** Infer (rows, cols) by counting unique X/Y rounded positions.
- **Produces:** (rows, cols) tuple; sqrt fallback.
- **AAA reference:** Houdini PolyDoctor grid analysis.
- **Bug/Gap:** Rounds to 3 decimals — fails on grids with sub-mm precision; falls back to square sqrt which gives wrong dims for non-power-of-2 non-square grids.
- **Severity:** polish (only used by terrain export).
- **Upgrade to A:** Use min-spacing detection instead of rounding; reject non-grid inputs explicitly.

### 3. `_detect_grid_dims` (line 96) — Grade: **B+**
- **Claims:** WORLD-004 grid dim detection from bmesh.
- **Produces:** Delegates to vertices version.
- **AAA reference:** Houdini SOP terrain grid analyzer.
- **Bug/Gap:** Single-line wrapper, inherits caller's flaws.
- **Severity:** polish.
- **Upgrade to A:** Inline since it's a one-liner; reduce indirection.

### 4. `_get_trig_table` (line 119) — Grade: **A-**
- **Claims:** Cached (cos,sin) pairs for N evenly-spaced angles.
- **Produces:** Tuple of N (cos,sin) tuples; LRU-cached at 32 entries.
- **AAA reference:** UE5 SinCosTable / Houdini precomputed lookup.
- **Bug/Gap:** Only 32 cache entries — generators using uncommon segment counts (5, 7, 9, 11, 13, 14) blow the cache after enough variation.
- **Severity:** polish.
- **Upgrade to A:** Bump to 128 or use a plain dict with no eviction.

### 5. `_auto_detect_sharp_edges` (line 132) — Grade: **B+**
- **Claims:** Detect sharp edges by dihedral angle.
- **Produces:** List of [a,b] vertex-index pairs; includes boundary edges as sharp.
- **AAA reference:** Blender bmesh `edge.calc_face_angle` autosmooth.
- **Bug/Gap:** O(F·V_avg) Newell normal recomputation for every face, not cached. For 5K-face meshes this is acceptable but adds per-call overhead. Treats *every* boundary edge as sharp — produces over-sharp seams on intentionally open meshes (e.g., shields, banners).
- **Severity:** important (over-sharp boundaries cause visible faceting on open shells).
- **Upgrade to A:** Cache normals on the result; expose `mark_boundaries: bool` parameter.

### 6. `_auto_generate_box_projection_uvs` (line 192) — Grade: **B**
- **Claims:** Per-vertex UVs via box projection from bbox.
- **Produces:** List of (u,v) where U = normalized X, V = Z or Y depending on dominant axis.
- **AAA reference:** Substance Painter "Box projection" / UE5 BoxMappedTextureSample.
- **Bug/Gap:** Uses a SINGLE projection plane for the entire mesh. Real box-projection uses 6 planes blended by face normal — this implementation will smear textures on side faces. No seam handling; UVs from this tool will tile-stretch on cylinder sides.
- **Severity:** important (every textured asset will look stretched).
- **Upgrade to A:** Implement true tri-planar with per-face normal selection or replace with bmesh.uv_smart_project equivalent.

### 7. `_make_result` (line 233) — Grade: **A-**
- **Claims:** Package verts/faces/uvs/sharp into MeshSpec dict.
- **Produces:** Dict with vertices, faces, uvs (auto-gen), metadata, sharp_edges.
- **AAA reference:** glTF mesh primitive object.
- **Bug/Gap:** Auto-UV path only fires if `uvs is empty AND auto_uv AND vertices`; if a generator passes `uvs=[]` explicitly the auto-path also fires which is correct, but no normals/tangents are emitted (Blender will compute on import). No MaterialBinding.
- **Severity:** important — no material binding means every asset is grey lambert until manually assigned.
- **Upgrade to A:** Accept and propagate `material_slots: list[str]`, normals, and tangents.

### 8. `_alias_generator_category` (line 282) — Grade: **A-**
- **Claims:** Wrap generator to rewrite metadata.category.
- **Produces:** A `_wrapped` closure preserving signature.
- **AAA reference:** Decorator-based asset categorization (Houdini PDG attribute remap).
- **Bug/Gap:** None for its scope.
- **Severity:** polish.
- **Upgrade to A:** Already minimal; no improvement needed.

### 9. `_wrapped` (line 289, inside `_alias_generator_category`) — Grade: **A-**
- **Claims:** Closure body that rewrites metadata.category.
- **Produces:** Modified MeshSpec with new category.
- **AAA reference:** N/A (private closure).
- **Bug/Gap:** Doesn't deep-copy faces/vertices — shares lists with original mesh; safe today but a foot-gun if downstream mutates.
- **Severity:** polish.
- **Upgrade to A:** `copy.deepcopy` the result if any callers mutate.

### 10. `_GeneratorRegistry.__init__` (line 303) — Grade: **B+**
- **Claims:** Build dict-like registry with alias lookup.
- **Produces:** Stores canonical dict + aliases + alias cache.
- **AAA reference:** UE5 AssetRegistry alias mappings.
- **Bug/Gap:** None significant; cache never invalidated (acceptable since registry is module-level and frozen).
- **Severity:** polish.
- **Upgrade to A:** Document immutability assumption.

### 11. `_GeneratorRegistry.__contains__` (line 312) — Grade: **A-**
- **Claims:** Check membership including aliases.
- **Produces:** Bool.
- **AAA reference:** N/A.
- **Bug/Gap:** None.
- **Severity:** polish.
- **Upgrade to A:** Already minimal.

### 12. `_GeneratorRegistry.__getitem__` (line 317) — Grade: **B+**
- **Claims:** Resolve key with alias fallback + cache.
- **Produces:** Wrapped category dict.
- **AAA reference:** UE5 alias-aware asset resolver.
- **Bug/Gap:** Iterates the canonical category every time on first alias hit (cache-miss path), but cache then short-circuits — fine.
- **Severity:** polish.
- **Upgrade to A:** Cache eagerly at construction time for known aliases.

### 13. `_compute_dimensions` (line 335) — Grade: **A-**
- **Claims:** Bounding-box width/height/depth via single-pass min/max.
- **Produces:** Dict of three floats.
- **AAA reference:** UE5 FBox::GetSize.
- **Bug/Gap:** None.
- **Severity:** polish.
- **Upgrade to A:** Already optimal for a pure-Python pass.

### 14. `_circle_points` (line 370) — Grade: **B+**
- **Claims:** Generate N points on a circle in XY/XZ/YZ.
- **Produces:** List of (x,y,z) using cached trig.
- **AAA reference:** Standard math primitive.
- **Bug/Gap:** No `axis="x"` validation — silently falls into the "x" branch on bad input.
- **Severity:** polish.
- **Upgrade to A:** Raise on unknown axis string.

### 15. `_make_box` (line 400) — Grade: **B**
- **Claims:** Axis-aligned box, 8 verts, 6 faces.
- **Produces:** 8 verts + 6 quad faces with `base_idx` offset.
- **AAA reference:** Maya polyCube.
- **Bug/Gap:** No UVs returned at primitive level — caller must use auto-UV which is single-plane (smearing). Sharp on every edge by dihedral, which is correct for a hard-edge cube.
- **Severity:** important — base primitive used by hundreds of compositions; every textured mesh inherits the smear problem.
- **Upgrade to A:** Return per-face UV island for proper cube unwrap.

### 16. `_make_cylinder` (line 432) — Grade: **B**
- **Claims:** Y-axis cylinder with optional caps, N segments.
- **Produces:** 2N side verts + 0/N cap verts; quad sides + N-gon caps.
- **AAA reference:** UE5 ProceduralMeshComponent CreateMeshSection_Cylinder.
- **Bug/Gap:** Cap is single N-gon (must be triangulated for many engines); no UV strip; default 12 segs gives blocky silhouette at any size > 0.5m. No optional smooth shading hint.
- **Severity:** important — cylinder caps render as black on engines that don't auto-fan.
- **Upgrade to A:** Triangulate caps; emit UV strip + cap UV.

### 17. `_make_cone` (line 473) — Grade: **B-**
- **Claims:** Apex-up cone along Y.
- **Produces:** N base verts + 1 apex; N triangle sides + N-gon base.
- **AAA reference:** Maya polyCone.
- **Bug/Gap:** Apex is shared single vertex — cones get pinched-normal artifacts (every adjacent face shares apex normal, making smooth shading produce a weird radial pinch). Fix: split apex into N separate verts.
- **Severity:** important — every "spike" / "pine layer" / fang / horn / arrowhead inherits this.
- **Upgrade to A:** Split apex per side face for proper hard normals; triangulate base.

### 18. `_make_torus_ring` (line 503) — Grade: **B**
- **Claims:** Torus in XZ plane.
- **Produces:** major*minor verts; quad faces.
- **AAA reference:** Maya polyTorus.
- **Bug/Gap:** `_tcx`/`_tcz` vars computed but never used (dead code). Hardcoded XZ plane — chain mesh suffers because of this.
- **Severity:** important — chains/rings cannot orient orthogonally.
- **Upgrade to A:** Add `axis` parameter like `_circle_points`; remove dead vars.

### 19. `_make_tapered_cylinder` (line 544) — Grade: **B+**
- **Claims:** Cylinder tapering bottom→top with `rings` cross-sections.
- **Produces:** segments*(rings+1) verts; quad sides + caps.
- **AAA reference:** Houdini PolyExtrude with taper.
- **Bug/Gap:** Like `_make_cylinder`, single N-gon caps + no UV strip. `rings=1` (default for many call sites) means no mid-cross-section so taper is just two end rings — no opportunity for organic mid-bulge.
- **Severity:** polish.
- **Upgrade to A:** Add UV strip; default `rings=2`.

### 20. `_make_beveled_box` (line 588) — Grade: **A-**
- **Claims:** 24-vertex chamfered box, 18 faces (6 main + 12 bevel quads).
- **Produces:** 24 verts, 18 quads. Topology valid, bevel readable.
- **AAA reference:** Blender Bevel modifier (1-segment).
- **Bug/Gap:** Bevel faces are flat quads, not tri-pairs — engines that don't quad-render get tilted edges. The 8 corner triangle faces (where 3 bevel quads meet) are MISSING — leaves 8 small triangular holes at corners. **NEW BUG:** non-manifold corners.
- **Severity:** blocker — corners produce visible black triangles on hard-edge specular under certain lights.
- **Upgrade to A:** Emit the 8 corner tri-fans. (See BUG-60.)

### 21. `_bevel_edge` (line 669, nested in `_make_beveled_box`) — Grade: **B+**
- **Claims:** Build a quad from two corners' inset verts.
- **Produces:** 4-tuple of vert indices.
- **AAA reference:** N/A (helper closure).
- **Bug/Gap:** Closure captures `b` correctly; nothing wrong.
- **Severity:** polish.
- **Upgrade to A:** Already fine.

### 22. `_enhance_mesh_detail` (line 691) — Grade: **B+**
- **Claims:** Adaptive subdivision near sharp edges to boost vert count.
- **Produces:** Augmented (verts, faces) with up to 3 passes of edge-midpoint subdivision.
- **AAA reference:** Blender Subdivision Surface (with Crease).
- **Bug/Gap:** Inserts TWO new verts per sharp edge but the resulting expanded face is fan-triangulated when >6 verts — can produce sliver triangles at corners. Boundary edges always treated sharp → over-subdivides shields/banners. The `min_vertex_count=100` default skips most generators (which are >100 verts already), so the function does nothing for the majority of calls.
- **Severity:** important — code is invoked but is largely a no-op; not actually adding the promised supporting edge loops.
- **Upgrade to A:** Use proper Catmull-Clark / use OpenSubdiv binding; raise default to 1000.

### 23. `_merge_meshes` (line 853) — Grade: **A-**
- **Claims:** Concatenate (verts, faces) lists with index remap.
- **Produces:** Single merged tuple.
- **AAA reference:** Maya polyUnite.
- **Bug/Gap:** Doesn't weld coincident verts — chains/walls/grass clumps end up with thousands of duplicate vertices at seam lines that should share. This bloats GPU memory by 30-50%.
- **Severity:** important — every multi-part mesh in the file is fatter than it needs to be.
- **Upgrade to A:** Add optional weld_distance parameter.

### 24. `_make_faceted_rock_shell` (line 867) — Grade: **B+**
- **Claims:** Angular fractured rock shell.
- **Produces:** rings*(segments) verts + quad sides + 2 N-gon caps; seeded RNG for variation.
- **AAA reference:** Quixel Megascans small rocks (~1-5K tris baseline).
- **Bug/Gap:** Real Quixel rocks are 50K+ tris with 4K PBR + cavity AO baked. This is ~80-200 verts. Top/bottom caps are flat N-gons — looks chiseled, not fractured. No noise displacement beyond per-segment ridge math.
- **Severity:** important.
- **Upgrade to A:** Add 3D Perlin noise displacement; replace flat caps with fractured cap shells.

### 25. `_make_sphere` (line 959) — Grade: **B**
- **Claims:** UV sphere with rings × sectors.
- **Produces:** 2 poles + (rings-1)*sectors verts; tri caps + quad belts.
- **AAA reference:** Maya polySphere.
- **Bug/Gap:** Pole pinching (UV singularity); no quad-only option (icosphere alternative). Default `rings=8 sectors=12` is very low res — every "head/eye/blob" in animal generators inherits an obvious sphere artifact.
- **Severity:** important — animals look like sphere collages because every component IS one.
- **Upgrade to A:** Provide icosphere alternative with `_make_icosphere`.

### 26. `_make_lathe` (line 1010) — Grade: **A-**
- **Claims:** Revolve 2D (r,y) profile around Y axis.
- **Produces:** N_profile*segments verts + quad belts + optional caps.
- **AAA reference:** Houdini Revolve SOP.
- **Bug/Gap:** No UV emission (profile-axis V should be cumulative arclength; circumferential U should be normalized angle). Silent on profiles with r=0 entries (creates degenerate triangles at poles).
- **Severity:** important — most potion bottles, columns, and fruits use this and have no proper UV.
- **Upgrade to A:** Emit UV; collapse r=0 profile points to a single vert.

### 27. `_make_profile_extrude` (line 1048) — Grade: **B**
- **Claims:** Extrude 2D (x,y) profile along Z.
- **Produces:** 2N verts + N side quads + 2 N-gon caps.
- **AAA reference:** Houdini PolyExtrude with linear path.
- **Bug/Gap:** Side quad uses `(b+i, b+i2, b+n+i2, b+n+i)` — winding flips depending on profile orientation (CW vs CCW), no auto-detect. Caps use raw N-gon (engines like Unity require triangulation). `_make_profile_extrude` is used by sarcophagus + a few props and the mirror trick they use (`(-v[0], v[1], v[2])` then reverse winding) only works because the function's winding is deterministic by accident.
- **Severity:** important.
- **Upgrade to A:** Auto-detect profile winding; triangulate caps.

---

### CATEGORY: FURNITURE

### 28. `generate_table_mesh` (line 1089) — Grade: **B**
- **Claims:** Table with style/legs/dimensions.
- **Produces:** Beveled top + 4 (or 2) tapered cylinder legs (or stone slab legs) + optional cross-braces. ~500-800 verts after enhance.
- **AAA reference:** Quixel Megascans tavern table (~10-25K tris).
- **Bug/Gap:** "Cross-braces for tavern style" code at line 1183 builds dead variables `_rotated_v_unused` / `_rotated_v` then ignores them and falls back to `_make_box` braces. Stone slab style legs have no carving. Default `_enhance_mesh_detail(min_vertex_count=500)` rarely fires since the base mesh is already ~700 verts.
- **Severity:** important — dead code path leaves orphaned vars; visually OK but blockout-tier.
- **Upgrade to A:** Remove dead rotation code; add wood plank seams between top boards; add edge wear bevels.

### 29. `generate_chair_mesh` (line 1202) — Grade: **B**
- **Claims:** Chair with style/arms/back.
- **Produces:** Beveled seat + 4 tapered legs + slatted back + optional armrests + throne finials. ~600 verts.
- **AAA reference:** UE5 medieval chair asset (~5K tris).
- **Bug/Gap:** Throne back is a single flat slab with no carving; "arch" claimed in comment never implemented. Armrest "support post" is vertical only — no curve. Throne finials are 5-ring, 6-sector spheres = visibly faceted balls.
- **Severity:** important.
- **Upgrade to A:** Curve armrests with bezier; carve throne back panel via boolean; subdivide finials.

### 30. `generate_shelf_mesh` (line 1307) — Grade: **B**
- **Claims:** Wall-mount or freestanding shelf with N tiers.
- **Produces:** Beveled boards + side panels OR L-brackets + back panel.
- **AAA reference:** UE5 Marketplace shelf set.
- **Bug/Gap:** "L-shaped" brackets are two boxes — no actual L union, no fillet. Freestanding back panel is a thin box with no plank seams.
- **Severity:** polish.
- **Upgrade to A:** Boolean-union brackets; tile back panel.

### 31. `generate_chest_mesh` (line 1380) — Grade: **B+**
- **Claims:** Chest with style and lock.
- **Produces:** Beveled body + half-cylinder lid + iron bands + lock plate + optional ornate spheres. ~700-1100 verts.
- **AAA reference:** Standard fantasy chest (~8K tris).
- **Bug/Gap:** Lid end-caps line 1428-1429 use raw vert indices — `lid_faces.append(tuple(left_indices[::-1]))` produces an N-gon end cap that is concave when `lid_segs > 4`, causing triangulation artifacts. Hinges absent.
- **Severity:** important — concave end caps break in Unity/UE.
- **Upgrade to A:** Triangulate lid end-caps; add hinge cylinders.

### 32. `generate_barrel_mesh` (line 1478) — Grade: **B+**
- **Claims:** Barrel with bulge + iron bands.
- **Produces:** 11-ring lathe + 3 torus bands. ~400-600 verts. Closes top and bottom.
- **AAA reference:** Standard fantasy barrel (~5-8K tris with stave seams).
- **Bug/Gap:** No actual STAVE separation — the mesh is one continuous lathed cylinder with the staves visually implied by the band rings. Real barrel geometry has individual stave edges.
- **Severity:** important — at close range looks like a smooth cylinder, not staves.
- **Upgrade to A:** Subdivide circumference into N stave segments with displacement gaps.

### 33. `generate_candelabra_mesh` (line 1528) — Grade: **C+**
- **Claims:** Branched candelabra with N arms.
- **Produces:** Lathed base + central shaft + 5 cylinder "arms" + cup + candle stub.
- **AAA reference:** Standard fantasy candelabra (~3K tris with bent arms).
- **Bug/Gap:** Arms are HORIZONTAL `_make_cylinder` calls placed at `(mid_x, arm_y - 0.01, mid_z)` — they extrude vertically (along Y) but are positioned in a circle. The result is N short vertical cylinders ringed around the shaft, NOT arms reaching outward. The "curved upward section" is just another vertical cylinder at the same XZ position. Wall-mounted variant has the same issue (arm "rotated forward" via tuple shuffling, line 1561).
- **Severity:** blocker — silhouette is wrong (looks like a hairbrush, not a candelabra).
- **Upgrade to A:** Build arms as bent tube along radial direction; use parametric sweep along curve.

### 34. `generate_bookshelf_mesh` (line 1640) — Grade: **B**
- **Claims:** Bookshelf with N sections + optional books.
- **Produces:** Side panels + N+1 shelf boards + back panel + RNG-placed books.
- **AAA reference:** Standard fantasy bookshelf (~10-20K tris).
- **Bug/Gap:** Books are uniform rectangular boxes with no spine carving, no title plates, no tilting beyond ±0.02 lean. Books all have the SAME bevel of 0.002. Real bookshelves need page edges, varied spine textures.
- **Severity:** important.
- **Upgrade to A:** Add page-edge geometry; add spine ridge; vary book bevel.

---

### CATEGORY: VEGETATION

### 35. `generate_tree_mesh` (line 1720) — Grade: **C+**
- **Claims:** Tree with trunk, branches, canopy + 7 styles.
- **Produces:** Lathed trunk with root flare + N tapered cylinder branches + style-specific canopy spheres / cones / boxes. ~2-5K verts.
- **AAA reference:** SpeedTree procedural tree (50K+ tris with leaf cards, wind, SSS).
- **Bug/Gap:** Branches are STRAIGHT — `_make_cylinder` placed along a linear (dx,dy,dz) vector with no curvature. Real trees branch with slight bends and sub-branches. Canopy "willow_hanging" is 12 vertical box strips — looks like a metal grate, not foliage. "ancient_oak" canopy is 6 spheres = bumpy mass, no leaf cards. NO leaves anywhere — every "canopy" is opaque sphere/cone primitives. NO bark texture support, no normal map seam awareness.
- **Severity:** blocker — would never ship in any game claiming PBR vegetation.
- **Upgrade to A:** Replace canopy with billboard leaf-card system; add sub-branches via recursion; bend branches with bezier spline.

### 36. `generate_rock_mesh` (line 1944) — Grade: **B** (boulder/cliff B+, others B-)
- **Claims:** Rock variants with size+detail.
- **Produces:** "boulder" → faceted shell (B+); "cliff_outcrop" → layered slabs (B+); "standing_stone" → noisy lathe; "crystal" → 3-7 hex prisms; "rubble_pile" → scattered beveled boxes.
- **AAA reference:** Quixel Megascans rocks (50-200K tris with PBR).
- **Bug/Gap:** Crystal cluster prisms have FLAT TOPS (`radius_top * 0.3` is still a flat hexagon, not a point) — calls itself "pointed top" but isn't pointed. Standing stone has no carved runes. Rubble pile boxes are too small relative to size param.
- **Severity:** important.
- **Upgrade to A:** Crystal: collapse top ring to single vert (true point); boulder: add noise displacement.

### 37. `generate_mushroom_mesh` (line 2102) — Grade: **B**
- **Claims:** Mushroom with cap_style.
- **Produces:** "giant_cap" → lathed stem + cap + gill ring (~250 verts); "cluster" → 5 small cyl+cone pairs; "shelf_fungus" → hand-built half-disc shelves with manual face winding.
- **AAA reference:** SpeedTree mushroom.
- **Bug/Gap:** "shelf_fungus" hand-built mesh at line 2189-2222 has DEGENERATE TRIANGLE at fan-edge `j=n_pts-1` because it indexes `j+2` which equals `n_pts+1` — but vertex `n_pts+1` is the CENTER of the bottom fan, not the rim. **NEW BUG:** off-by-one wraps create cross-mesh face. Cluster mushrooms have flat-top caps from `_make_cone` (no rounded dome).
- **Severity:** important — shelf_fungus produces degenerate face.
- **Upgrade to A:** Fix shelf fan triangulation; use lathe for cluster caps.

### 38. `generate_root_mesh` (line 2230) — Grade: **B-**
- **Claims:** Exposed tree roots.
- **Produces:** N curved-arc cylinder segments per root.
- **AAA reference:** SpeedTree root system.
- **Bug/Gap:** `_make_cylinder` calls position cylinders at calculated (x,y,z) but every cylinder is Y-axis aligned. Roots that should taper outward radially are stacked vertically. The "dip down then come back up" comment doesn't match what happens — Y just oscillates while the cylinders remain vertical. Visual: tiny floating posts arranged in a ring, not roots.
- **Severity:** important — silhouette wrong.
- **Upgrade to A:** Replace cylinder stack with proper swept tube along bezier root path.

### 39. `generate_grass_clump_mesh` (line 2276) — Grade: **B**
- **Claims:** Grass clump with N blades.
- **Produces:** N quad blades fanned around origin with bend & lean variation. ~56 verts for default 14 blades.
- **AAA reference:** SpeedTree grass cards (alpha-tested with wind).
- **Bug/Gap:** Single quad per blade — no curve, no tip taper, no double-sided face flag. Wind animation impossible without bone weights. No alpha mask UV.
- **Severity:** important — flat hard quads visible from edge.
- **Upgrade to A:** Use 2-quad bent strip per blade with proper UV for grass alpha texture.

### 40. `generate_shrub_mesh` (line 2325) — Grade: **B-**
- **Claims:** Shrub with woody core + leaf masses.
- **Produces:** Tapered stem + N "leaf masses" (spheres, rings=5,sectors=8) + 4 cone roots.
- **AAA reference:** SpeedTree bush asset.
- **Bug/Gap:** Leaf masses are SPHERES — looks like a stack of green snowballs, not foliage. No leaf cards, no edge transparency. Cone "roots" placed at angle but rendered axis-aligned.
- **Severity:** important.
- **Upgrade to A:** Replace blob spheres with billboard leaf cards.

### 41. `generate_ivy_mesh` (line 2382) — Grade: **B-**
- **Claims:** Wall-climbing ivy.
- **Produces:** N vine cylinders + small quad leaves at intervals.
- **AAA reference:** Quixel Megascans ivy decals.
- **Bug/Gap:** Vine cylinders have `cap_top=False, cap_bottom=False` so they're OPEN tubes (visible interior from low angle). Leaves are 4-vertex flat diamonds with no UV island for an alpha leaf texture. Vine "z = 0.005" is hardcoded — every ivy strand is at the same depth with no surface adherence.
- **Severity:** important — open tubes are a visual blocker.
- **Upgrade to A:** Add caps; add leaf UV; sample wall normal for adherence.

---

### CATEGORY: DUNGEON PROPS

### 42. `generate_torch_sconce_mesh` (line 2441) — Grade: **C+**
- **Claims:** Wall sconce with style.
- **Produces:** Wall plate + style-specific arm + torch shaft.
- **AAA reference:** Standard fantasy sconce (~3K tris).
- **Bug/Gap:** "iron_bracket" arm at line 2465 is a centered box with `cz=0.06` — not L-shaped. "ornate_dragon" arm at lines 2483-2493 is a series of cylinders + sphere, no dragon morphology. The "torch shaft" at line 2502 is positioned at `cz=0.12` which floats in space — not attached to the cup or arm.
- **Severity:** important — torch literally floats next to sconce.
- **Upgrade to A:** Anchor torch to cup; sculpt dragon head; bend arm L-shape.

### 43. `generate_prison_door_mesh` (line 2509) — Grade: **B-**
- **Claims:** Iron-barred door.
- **Produces:** Frame + N vertical bars + 2 horizontal cross bars + lock plate.
- **AAA reference:** Standard prison door (~2K tris).
- **Bug/Gap:** Horizontal cross bars: line 2578 builds vertical cylinder then "rotates" via `[(v[1] - y_pos + (-inner_w / 2), y_pos, v[2]) for v in hv]` — this is NOT a 90° rotation; it collapses Y onto X and clamps Y to constant `y_pos`. Result: zero-height degenerate strips along the X axis. Crossbars are visually broken.
- **Severity:** blocker — crossbars don't render correctly.
- **Upgrade to A:** Build horizontal cylinder directly with proper axis parameter.

### 44. `generate_sarcophagus_mesh` (line 2593) — Grade: **B**
- **Claims:** Stone coffin with style.
- **Produces:** Mirrored profile-extruded body halves + lid + style decorations.
- **AAA reference:** Standard sarcophagus (~10K tris with carving).
- **Bug/Gap:** Mirroring uses `(-v[0], v[1], v[2])` + `tuple(reversed(f))` — works but creates a SEAM at x=0 with potentially overlapping co-planar faces (Z-fighting risk). "ornate_carved" corner posts are simple cylinders with no foot/finial detail. Rune channels on "dark_ritual" are tiny boxes (0.005×0.2×0.02), invisible at distance.
- **Severity:** important — z-fighting at midline seam.
- **Upgrade to A:** Build full body without mirror; carve runes via boolean.

### 45. `generate_altar_mesh` (line 2662) — Grade: **B**
- **Claims:** Altar with 3 styles.
- **Produces:** Beveled slab + legs (sacrificial); block + step + symbol disc (prayer); octagonal lathe + corner pillars + flame cones (dark_ritual).
- **AAA reference:** Standard altar prop.
- **Bug/Gap:** "Blood channel groove" at line 2684 is a RAISED rim (`y + slab_h/2 + 0.01`), not a recessed channel. Prayer symbol is a flat disc with no symbol carved. Dark_ritual flame cups are cones not flames.
- **Severity:** important — blood channel is inverted.
- **Upgrade to A:** Recess channel via boolean subtract; carve symbol; replace flame cones with billboard.

### 46. `generate_pillar_mesh` (line 2741) — Grade: **B+**
- **Claims:** Column with 5 styles.
- **Produces:** Style-specific lathe/box compositions; each variant ~400-1200 verts.
- **AAA reference:** UE5 architectural columns (~5-15K tris).
- **Bug/Gap:** "stone_round" with entasis is correct technique but only 12 segments — visible faceting. "carved_serpent" is a sinusoidal radius with no actual snake form (looks ribbed, not wrapped). "broken" rubble at line 2868 uses `Random(77)` which means ALL broken pillars look identical regardless of caller-passed seed.
- **Severity:** important — broken variant has zero variation.
- **Upgrade to A:** Seed from kwargs; carve actual serpent geometry; bump segments.

### 47. `generate_archway_mesh` (line 2907) — Grade: **B+**
- **Claims:** Doorway frame with 4 styles.
- **Produces:** Posts + style-specific arch geometry + keystone.
- **AAA reference:** UE5 archway (~10K tris).
- **Bug/Gap:** Stone_pointed arch math at line 2954-2968 builds the two arc halves via linear interpolation (not actual circular arcs), so the curve is visibly wrong (looks more like a tent than a Gothic arch). Wooden style ignores `arch_segs` entirely. Ruined style uses partial arch but no fallen voussoirs (just generic rubble boxes).
- **Severity:** important.
- **Upgrade to A:** Replace pointed-arch math with actual circular arcs; add fallen voussoir blocks for ruined.

### 48. `generate_chain_mesh` (line 3105) — Grade: **C+**
- **Claims:** Hanging chain with interlocking links.
- **Produces:** N torus links, alternating orientation.
- **AAA reference:** UE5 chain BP (~2K tris with proper interlock).
- **Bug/Gap:** **Both branches generate IDENTICAL torus** (`_make_torus_ring(0, y, 0, ...)`) — the `else:` branch on line 3133 produces same XZ-plane torus, then "rotates" via `(v[2], v[1], v[0])` axis swap. This swap is a reflection, not a 90° rotation about the Y axis (which it should be for chain link interlocking). Result: links DON'T actually interlock; they are two perpendicular but coincident rings stacked vertically.
- **Severity:** blocker — chain doesn't interlock visually.
- **Upgrade to A:** Build links with explicit axis parameter; offset each link by half-link to interlock properly.

### 49. `generate_skull_pile_mesh` (line 3148) — Grade: **D**
- **Claims:** Pile of skulls.
- **Produces:** N (sphere + box jaw + 2 protruding eye spheres). ~120 verts/skull.
- **AAA reference:** Quixel Megascans skull (50K+ tris with PBR).
- **Bug/Gap:** "Eye sockets" at line 3188-3193 are spheres POSITIONED OUTSIDE the cranium (at `fz + skull_r * 0.15`) — they protrude OUT from the face like bug eyes. Should be recessed. Jaw is an axis-aligned box, no jaw shape. Cranium-sphere has rings=5 sectors=6 = visibly faceted.
- **Severity:** blocker — eye spheres are wrong direction; doesn't read as skulls.
- **Upgrade to A:** Replace primitive composition with actual sculpted skull mesh; recess eye sockets via boolean.

---

### CATEGORY: WEAPONS

### 50. `generate_hammer_mesh` (line 3204) — Grade: **B-**
- **Claims:** Warhammer with style + handle length.
- **Produces:** Tapered handle + pommel sphere + style-specific head.
- **AAA reference:** AAA fantasy hammer (~5-15K tris).
- **Bug/Gap:** "spiked" back-spike at line 3252 uses `[(-head_w / 2 - (v[1] - head_y) * 0.8, head_y + (v[0] + head_w / 2), v[2]) for v in bsv]` — this is a Y/X swap with offset, mangling the cone shape into a sheared parallelogram. Grip rings (line 3270) intersect the handle inappropriately (0.15 minor radius is huge relative to handle 0.015 — they engulf the grip).
- **Severity:** important — back-spike geometry is sheared.
- **Upgrade to A:** Build back-spike via direct cone construction along correct axis; resize grip rings.

### 51. `generate_spear_mesh` (line 3280) — Grade: **B**
- **Claims:** Spear/halberd with head_style.
- **Produces:** Long shaft + head geometry per style.
- **AAA reference:** Standard fantasy spear (~3K tris).
- **Bug/Gap:** Like other weapons here, the head's "leaf shape" is approximated with primitives; halberd head depends on _make_box compositions that don't read as a proper axe blade.
- **Severity:** important.
- **Upgrade to A:** Sculpt blade silhouette via 2D profile extrude.

### 52. `generate_crossbow_mesh` (line 3379) — Grade: **B-**
- **Claims:** Crossbow with mechanism.
- **Produces:** Stock + bow limbs + string + mechanism box.
- **AAA reference:** Standard fantasy crossbow (~8-15K tris).
- **Bug/Gap:** Bow string is likely a thin box (no curvature); "mechanism" is a generic box, no trigger detail.
- **Severity:** important.
- **Upgrade to A:** Add trigger geometry; curve string.

### 53. `generate_scythe_mesh` (line 3447) — Grade: **B-**
- **Claims:** Reaper scythe.
- **Produces:** Long shaft + curved blade.
- **AAA reference:** Standard scythe (~5K tris).
- **Bug/Gap:** Blade likely built from straight primitives, not a true sweep along curve.
- **Severity:** important.
- **Upgrade to A:** Sweep blade along bezier curve.

### 54. `generate_flail_mesh` (line 3508) — Grade: **B-**
- **Claims:** Ball-and-chain flail.
- **Produces:** Handle + chain (probably uses chain_mesh approach) + spiked ball.
- **AAA reference:** Standard flail (~4K tris).
- **Bug/Gap:** Inherits the broken-chain interlock from `generate_chain_mesh` pattern. Spiked ball is sphere + N cones — cone apex pinching applies.
- **Severity:** important.
- **Upgrade to A:** Use proper chain primitive; weld cone apexes.

### 55. `generate_whip_mesh` (line 3587) — Grade: **C**
- **Claims:** Segmented whip.
- **Produces:** Series of small cylinders or boxes along a path.
- **AAA reference:** AAA whip with bone chain (~2K tris with rig).
- **Bug/Gap:** No curl, no taper variation, no leather wrap geometry. Just a stick.
- **Severity:** important.
- **Upgrade to A:** Sweep tapered tube along S-curve; add bone weights.

### 56. `generate_claw_mesh` (line 3641) — Grade: **B-**
- **Claims:** Monster claw / gauntlet.
- **Produces:** Hand base + 3-5 cone fingers.
- **AAA reference:** Monster Hunter claw (~10K tris).
- **Bug/Gap:** Fingers are straight cones, no joints, no curvature. No knuckle articulation.
- **Severity:** important.
- **Upgrade to A:** Bezier-swept tapered tubes for fingers; add knuckle spheres.

### 57. `generate_tome_mesh` (line 3706) — Grade: **B**
- **Claims:** Spellbook/grimoire.
- **Produces:** Beveled cover + page block + spine + clasp.
- **AAA reference:** AAA grimoire (~10K tris with page edges).
- **Bug/Gap:** Page block is a single beveled box — no individual page edges; clasp is generic.
- **Severity:** polish.
- **Upgrade to A:** Add page-edge stripes via subdivided side face.

### 58. `generate_greatsword_mesh` (line 3803) — Grade: **B**
- **Claims:** Two-handed greatsword.
- **Produces:** Wide blade + ricasso + crossguard + grip + pommel.
- **AAA reference:** Dark Souls greatsword (~10-20K tris).
- **Bug/Gap:** Blade is a thin box (no fuller groove), crossguard symmetric box, pommel sphere. Reads as silhouette but no detail.
- **Severity:** important.
- **Upgrade to A:** Carve fuller; sculpt crossguard with engraved detail.

### 59. `generate_curved_sword_mesh` (line 3885) — Grade: **B-**
- **Claims:** Curved single-edge sword.
- **Produces:** Curved blade + handle + guard.
- **AAA reference:** Katana / scimitar AAA asset.
- **Bug/Gap:** Curve approximated with stepped boxes/profile — visible facets along curve. No edge bevel.
- **Severity:** important.
- **Upgrade to A:** Sweep blade profile along smooth bezier.

### 60. `generate_hand_axe_mesh` (line 3942) — Grade: **B-**
- **Claims:** Small hand axe.
- **Produces:** Handle cylinder + head box/wedge.
- **AAA reference:** Standard hand axe (~2K tris).
- **Bug/Gap:** Head is generic wedge with no bit curve, no eye for handle insertion (handle just floats inside head box).
- **Severity:** important.
- **Upgrade to A:** Carve axe head profile; add eye boolean.

### 61. `generate_battle_axe_mesh` (line 3981) — Grade: **B-**
- **Claims:** Battle axe with medium haft.
- **Produces:** Haft + head with bit profile.
- **AAA reference:** AAA battle axe (~6K tris).
- **Bug/Gap:** Same as hand axe — head approximated with primitives, no eye, no edge bevel.
- **Severity:** important.
- **Upgrade to A:** Profile-extrude axe head.

### 62. `generate_greataxe_mesh` (line 4045) — Grade: **B-**
- **Claims:** Massive head + long haft.
- **Produces:** Long haft + scaled-up axe head primitives.
- **AAA reference:** WoW-style greataxe.
- **Bug/Gap:** Head is just larger primitives — no double-bit detail, no engraving.
- **Severity:** important.
- **Upgrade to A:** Sculpt double-bit head; add knot-work engraving normal map.

### 63. `generate_club_mesh` (line 4102) — Grade: **B**
- **Claims:** Rough club with nail/spike extrusions.
- **Produces:** Tapered club body + N cone spikes around top.
- **AAA reference:** Orc club (~3K tris).
- **Bug/Gap:** Spikes are straight cones with apex pinching.
- **Severity:** polish.
- **Upgrade to A:** Use small tapered cylinders welded into surface.

### 64. `generate_mace_mesh` (line 4147) — Grade: **B**
- **Claims:** Mace with flanged or studded head.
- **Produces:** Handle + head sphere/disc + flanges or studs.
- **AAA reference:** Standard mace (~5K tris).
- **Bug/Gap:** Flanges as flat boxes — no proper flange geometry (real flanges have triangular cross-section).
- **Severity:** important.
- **Upgrade to A:** Profile-extrude flange shape radially.

### 65. `generate_warhammer_mesh` (line 4206) — Grade: **B**
- **Claims:** Flat striking face + pick.
- **Produces:** Handle + head box + pick cone.
- **AAA reference:** WoW warhammer (~6K tris).
- **Bug/Gap:** Pick cone again pinched; head box has no engraving.
- **Severity:** polish.
- **Upgrade to A:** Weld pick cone apex; add detail box subdivision.

### 66. `generate_halberd_mesh` (line 4252) — Grade: **B-**
- **Claims:** Axe head + spike + hook on pole.
- **Produces:** Pole + axe head + top spike + back hook.
- **AAA reference:** AAA halberd (~10K tris).
- **Bug/Gap:** Hook is a bent primitive (likely cone or box) — no proper curve. Multiple sub-pieces likely use the broken axis-swap pattern.
- **Severity:** important.
- **Upgrade to A:** Bezier-sweep hook; profile-extrude axe head.

### 67. `generate_glaive_mesh` (line 4313) — Grade: **B**
- **Claims:** Curved blade on pole.
- **Produces:** Pole + curved blade.
- **AAA reference:** Glaive AAA asset.
- **Bug/Gap:** Curve approximated with primitives.
- **Severity:** important.
- **Upgrade to A:** Sweep blade profile along curve.

### 68. `_make_bow_limb` (line 4402) — Grade: **B**
- **Claims:** Curved bow limb along Y.
- **Produces:** Tapered cylinder bent via vertex displacement.
- **AAA reference:** SpeedTree bow limb / standard primitive.
- **Bug/Gap:** Bend is a single sin curve — no compound curvature.
- **Severity:** polish.
- **Upgrade to A:** Add second-order curve.

### 69. `generate_shortbow_mesh` (line 4423) — Grade: **B**
- **Claims:** Shortbow with curved limbs + string.
- **Produces:** Two limbs + grip + string.
- **AAA reference:** Standard fantasy shortbow.
- **Bug/Gap:** String is a thin straight cylinder — should curve under tension.
- **Severity:** polish.
- **Upgrade to A:** Curve string between limbs.

### 70. `generate_longbow_mesh` (line 4461) — Grade: **B**
- **Claims:** Longbow — taller than shortbow.
- **Produces:** Same approach as shortbow scaled up.
- **AAA reference:** English longbow AAA.
- **Bug/Gap:** Same as shortbow.
- **Severity:** polish.
- **Upgrade to A:** Add nock detail; arrow rest.

### 71. `generate_staff_magic_mesh` (line 4506) — Grade: **B**
- **Claims:** Gnarled wood + crystal/orb head.
- **Produces:** Tapered shaft (with grain noise) + sphere/crystal head + base ferrule.
- **AAA reference:** AAA mage staff (~8K tris).
- **Bug/Gap:** "Gnarled" is a sinusoidal radius — produces ribbed look, not actual gnarls.
- **Severity:** important.
- **Upgrade to A:** Add radial bumps with multi-octave noise; add bound runes.

### 72. `generate_wand_mesh` (line 4579) — Grade: **B**
- **Claims:** Short shaft with ornate tip.
- **Produces:** Tapered shaft + spherical/cone tip + grip wraps.
- **AAA reference:** Harry Potter-style wand asset.
- **Bug/Gap:** Tip ornament is generic; no carved runes.
- **Severity:** polish.
- **Upgrade to A:** Sculpt grip texture; add embedded crystal.

### 73. `generate_throwing_knife_weapon_mesh` (line 4639) — Grade: **B**
- **Claims:** Balanced throwing knife.
- **Produces:** Blade + grip + pommel.
- **AAA reference:** Standard throwing knife.
- **Bug/Gap:** Blade likely flat box, no edge bevel.
- **Severity:** polish.
- **Upgrade to A:** Add edge bevel; grip wrap.

### 74. `generate_paired_daggers_mesh` (line 4698) — Grade: **B-**
- **Claims:** Mirrored daggers for dual-wield.
- **Produces:** Two dagger meshes side by side.
- **AAA reference:** AAA dual-wield daggers.
- **Bug/Gap:** Mirror is just `(-x)` flip; both daggers identical, no L/R-handed asymmetry typical of curved daggers.
- **Severity:** polish.
- **Upgrade to A:** Build true left/right variants with handed grip curves.

### 75. `generate_twin_swords_mesh` (line 4757) — Grade: **B**
- **Claims:** Matched pair of swords.
- **Produces:** Two sword meshes.
- **AAA reference:** Twin sword AAA asset.
- **Bug/Gap:** Mirroring inherits any bugs from the base sword generator.
- **Severity:** polish.
- **Upgrade to A:** Same as paired daggers.

### 76. `generate_dual_axes_mesh` (line 4828) — Grade: **B-**
- **Claims:** Paired throwing/hand axes.
- **Produces:** Two hand axes mirrored.
- **AAA reference:** Dual-wield axes asset.
- **Bug/Gap:** Inherits hand-axe issues (no eye for haft).
- **Severity:** important.
- **Upgrade to A:** Sculpt heads.

### 77. `generate_dual_claws_mesh` (line 4880) — Grade: **B-**
- **Claims:** Paired claw weapons.
- **Produces:** Two claw meshes.
- **AAA reference:** Diablo demon claws.
- **Bug/Gap:** Inherits straight-cone issues from base claw.
- **Severity:** important.
- **Upgrade to A:** Bezier finger curves.

### 78. `generate_brass_knuckles_mesh` (line 4978) — Grade: **B**
- **Claims:** Knuckle-duster.
- **Produces:** Curved finger holes + knuckle spikes.
- **AAA reference:** Standard brass knuckles (~3K tris).
- **Bug/Gap:** Finger holes likely 4 separate torus rings — not joined into a single solid.
- **Severity:** important.
- **Upgrade to A:** Boolean union finger holes into solid bar.

### 79. `generate_cestus_mesh` (line 5019) — Grade: **B-**
- **Claims:** Wrapped fighting glove.
- **Produces:** Hand wrap + studs.
- **AAA reference:** Greek cestus AAA.
- **Bug/Gap:** Wrap likely beveled box, no actual wrapping pattern.
- **Severity:** important.
- **Upgrade to A:** Add helical wrap geometry.

### 80. `generate_bladed_gauntlet_mesh` (line 5068) — Grade: **B-**
- **Claims:** Gauntlet with blades.
- **Produces:** Gauntlet base + N blades.
- **AAA reference:** Wolverine claws / Assassin's Creed hidden blade.
- **Bug/Gap:** Blades are flat boxes; no extension mechanism geometry.
- **Severity:** important.
- **Upgrade to A:** Profile-extrude blade silhouettes; add segmented mechanism.

### 81. `generate_iron_fist_mesh` (line 5174) — Grade: **B-**
- **Claims:** Heavy metal fist weapon.
- **Produces:** Hand-shaped block + studs.
- **AAA reference:** Power gauntlet AAA.
- **Bug/Gap:** Hand block is a simple beveled box, no finger articulation.
- **Severity:** important.
- **Upgrade to A:** Sculpt finger ridges.

### 82. `generate_rapier_mesh` (line 5242) — Grade: **B**
- **Claims:** Rapier with thin blade + swept hilt.
- **Produces:** Thin blade + swept basket guard + grip + pommel.
- **AAA reference:** AAA rapier (~10K tris with intricate guard).
- **Bug/Gap:** Swept hilt approximated with bent cylinders/boxes — no continuous basket weave.
- **Severity:** important.
- **Upgrade to A:** Sweep guard along multi-curve bezier.

### 83. `generate_estoc_mesh` (line 5369) — Grade: **B**
- **Claims:** Stiff thrusting sword with triangular cross-section.
- **Produces:** Triangular-cross-section blade + hilt.
- **AAA reference:** Historical estoc reference (~6K tris).
- **Bug/Gap:** Triangular cross-section likely approximated with rotated box — facet angles may not be correct 60°.
- **Severity:** polish.
- **Upgrade to A:** Profile-extrude proper triangular profile.

### 84. `generate_javelin_mesh` (line 5448) — Grade: **B**
- **Claims:** Heavy thrown spear.
- **Produces:** Shaft + head + grip wrap.
- **AAA reference:** Standard javelin (~3K tris).
- **Bug/Gap:** Generic primitive composition.
- **Severity:** polish.
- **Upgrade to A:** Add fletching/balance bands.

### 85. `generate_throwing_axe_mesh` (line 5532) — Grade: **B**
- **Claims:** Balanced throwing axe.
- **Produces:** Short handle + axe head.
- **AAA reference:** Throwing axe AAA.
- **Bug/Gap:** Same axe-head issues as hand_axe.
- **Severity:** important.
- **Upgrade to A:** Sculpt head.

### 86. `generate_shuriken_mesh` (line 5596) — Grade: **B**
- **Claims:** Throwing star.
- **Produces:** Star-shaped flat plate.
- **AAA reference:** Standard shuriken (~1K tris).
- **Bug/Gap:** Star points likely flat triangles, no edge bevel.
- **Severity:** polish.
- **Upgrade to A:** Bevel edges; add center hole.

### 87. `generate_bola_mesh` (line 5660) — Grade: **C**
- **Claims:** Weighted rope/chain weapon.
- **Produces:** 3 spheres connected by 3 stretched boxes.
- **AAA reference:** Bola weapon AAA.
- **Bug/Gap:** "Rope" boxes have no rope texture, no tension curve. Looks like 3 balls floating with sticks between them.
- **Severity:** blocker — does not read as bola.
- **Upgrade to A:** Replace rope-boxes with thin tubes following catenary curve.

### 88. `generate_orb_focus_mesh` (line 5718) — Grade: **B**
- **Claims:** Mage off-hand orb.
- **Produces:** Orb sphere + cradle/holder.
- **AAA reference:** Wizard orb prop.
- **Bug/Gap:** Cradle is generic primitives, no claw-grip detail.
- **Severity:** polish.
- **Upgrade to A:** Sculpt claw cradle.

### 89. `generate_skull_fetish_mesh` (line 5794) — Grade: **B-**
- **Claims:** Necromancer off-hand focus.
- **Produces:** Skull (inherits skull-pile issues) + bone/feather attachments.
- **AAA reference:** Necromancer fetish AAA.
- **Bug/Gap:** Skull subcomponent has same protruding-eyes problem.
- **Severity:** important.
- **Upgrade to A:** Replace skull primitive with proper sculpt.

### 90. `generate_holy_symbol_mesh` (line 5889) — Grade: **B**
- **Claims:** Paladin off-hand focus.
- **Produces:** Symbol disc + chain/handle.
- **AAA reference:** Standard holy symbol.
- **Bug/Gap:** Symbol is flat geometry — no carved relief.
- **Severity:** polish.
- **Upgrade to A:** Carve cross/sun via boolean.

### 91. `generate_totem_mesh` (line 5970) — Grade: **B**
- **Claims:** Druid/shaman totem.
- **Produces:** Stacked carved figures on a pole.
- **AAA reference:** Native totem AAA (~15K tris).
- **Bug/Gap:** "Carved figures" are stacked spheres/boxes — no animal heads.
- **Severity:** important.
- **Upgrade to A:** Sculpt distinct creature heads per tier.

---

### CATEGORY: ARCHITECTURE & ENVIRONMENT

### 92. `generate_gargoyle_mesh` (line 6059) — Grade: **B-**
- **Claims:** Wall-mounted gargoyle.
- **Produces:** Body + head + wings + base.
- **AAA reference:** Notre Dame gargoyle AAA (~30K tris).
- **Bug/Gap:** Composed of generic primitives — body is sphere/box, wings are flat planes. No claws, no carved face.
- **Severity:** important.
- **Upgrade to A:** Sculpt face; add claw curves; pose wings.

### 93. `generate_fountain_mesh` (line 6153) — Grade: **B**
- **Claims:** Stone fountain.
- **Produces:** Basin + central column + tiered bowls + spout.
- **AAA reference:** Park fountain AAA (~25K tris).
- **Bug/Gap:** Water surface is missing or implied; spout is generic.
- **Severity:** important.
- **Upgrade to A:** Add water surface plane with shader hint; sculpt spout figure.

### 94. `generate_statue_mesh` (line 6227) — Grade: **B-**
- **Claims:** Generic humanoid statue.
- **Produces:** Pedestal + head sphere + torso box + arms/legs cylinders.
- **AAA reference:** AAA statue (~30K+ tris with sculpting).
- **Bug/Gap:** It's a snowman with cylinders for arms/legs. No facial features, no robes, no pose.
- **Severity:** blocker — would not read as a statue at distance.
- **Upgrade to A:** Replace primitive composition with sculpted reference mesh.

### 95. `generate_bridge_mesh` (line 6320) — Grade: **B**
- **Claims:** Bridge (style varies).
- **Produces:** Deck + supports + railings.
- **AAA reference:** UE5 bridge BP.
- **Bug/Gap:** Generic plank composition; no arch geometry for arched style.
- **Severity:** important.
- **Upgrade to A:** Add proper arch curve for span.

### 96. `generate_gate_mesh` (line 6457) — Grade: **B**
- **Claims:** Gate.
- **Produces:** Frame + bars + cross supports.
- **AAA reference:** Castle gate AAA.
- **Bug/Gap:** Bars likely use the same broken horizontal-rotation pattern as prison_door.
- **Severity:** important.
- **Upgrade to A:** Build horizontal bars with proper axis.

### 97. `generate_staircase_mesh` (line 6590) — Grade: **B**
- **Claims:** Staircase.
- **Produces:** N stacked step boxes + optional rails.
- **AAA reference:** Standard procedural stairs.
- **Bug/Gap:** Steps are individual boxes — no merged stringer; rails generic.
- **Severity:** polish.
- **Upgrade to A:** Add stringer geometry.

---

### CATEGORY: FENCES & BARRIERS

### 98. `generate_fence_mesh` (line 6703) — Grade: **B**
- **Claims:** Fence section.
- **Produces:** Posts + rails / planks per style.
- **AAA reference:** UE5 fence BP.
- **Bug/Gap:** Generic post+rail; no weathering geometry.
- **Severity:** polish.
- **Upgrade to A:** Add irregular tilts; broken planks.

### 99. `generate_barricade_mesh` (line 6880) — Grade: **B**
- **Claims:** Defensive barricade.
- **Produces:** Crossed beam barricade.
- **AAA reference:** Saw-horse barricade.
- **Bug/Gap:** Generic X-frame.
- **Severity:** polish.
- **Upgrade to A:** Add wire/spikes.

### 100. `generate_railing_mesh` (line 6998) — Grade: **B**
- **Claims:** Railing.
- **Produces:** Posts + horizontal rails + balusters.
- **AAA reference:** Architectural railing BP.
- **Bug/Gap:** Horizontal rails likely use the same axis-swap rotation pattern (broken).
- **Severity:** important.
- **Upgrade to A:** Build horizontal cylinders with proper axis.

---

### CATEGORY: TRAPS

### 101. `generate_spike_trap_mesh` (line 7127) — Grade: **B**
- **Claims:** Floor spike trap with pit + spikes.
- **Produces:** Pit box + N upward cones.
- **AAA reference:** Indiana Jones spike trap.
- **Bug/Gap:** Spikes have apex-pinching artifact.
- **Severity:** polish.
- **Upgrade to A:** Weld apex; add splayed bases.

### 102. `generate_bear_trap_mesh` (line 7193) — Grade: **B-**
- **Claims:** Iron jaw trap.
- **Produces:** Base plate + 2 jaw arcs + spring + chain.
- **AAA reference:** AAA bear trap (~5K tris).
- **Bug/Gap:** Jaws likely use stacked boxes/cones — no continuous arc; teeth are individual cones.
- **Severity:** important.
- **Upgrade to A:** Profile-extrude jaw arc with integrated teeth.

### 103. `generate_pressure_plate_mesh` (line 7257) — Grade: **B**
- **Claims:** Stone pressure plate.
- **Produces:** Recessed plate in floor frame.
- **AAA reference:** Standard pressure plate.
- **Bug/Gap:** Carved sigil missing.
- **Severity:** polish.
- **Upgrade to A:** Carve sigil via boolean.

### 104. `generate_dart_launcher_mesh` (line 7316) — Grade: **B**
- **Claims:** Wall dart launcher.
- **Produces:** Wall plate + barrel holes.
- **AAA reference:** Tomb Raider dart launcher.
- **Bug/Gap:** Holes likely flat circles, no depth.
- **Severity:** polish.
- **Upgrade to A:** Recess holes with cylinder cutout.

### 105. `generate_swinging_blade_mesh` (line 7384) — Grade: **B-**
- **Claims:** Pendulum blade.
- **Produces:** Pivot rod + blade + connecting arm.
- **AAA reference:** Indiana Jones blade trap.
- **Bug/Gap:** Blade is flat box, no edge bevel.
- **Severity:** important.
- **Upgrade to A:** Curve blade; add edge bevel.

### 106. `generate_falling_cage_mesh` (line 7456) — Grade: **B**
- **Claims:** Ceiling-mounted falling cage.
- **Produces:** Cage frame + ceiling mount + chain.
- **AAA reference:** Standard cage trap.
- **Bug/Gap:** Inherits chain interlock issue.
- **Severity:** important.
- **Upgrade to A:** Fix chain primitive.

---

### CATEGORY: VEHICLES

### 107. `generate_cart_mesh` (line 7546) — Grade: **C+**
- **Claims:** Cart with wheels + style.
- **Produces:** Platform + axles + wheels + style-specific body.
- **AAA reference:** Witcher 3 cart (~15K tris).
- **Bug/Gap:** Axle "rotation" at line 7590 collapses Y onto Z — produces ZERO-LENGTH axles. Wheels are toruses + hub cylinders with no spokes connecting hub to rim. Hoops for canvas cover at line 7644 use clamping `max(v[1], cover_y)` to fake half-torus — produces flat-bottomed lumps.
- **Severity:** blocker — axles broken, wheels lack spokes.
- **Upgrade to A:** Build axles with proper Z-axis cylinder; add spokes; replace hoop clamp with true half-torus.

### 108. `generate_boat_mesh` (line 7711) — Grade: **B**
- **Claims:** Boat (rowboat/longship/gondola).
- **Produces:** Hull via per-section semicircular cross-sections + decorations.
- **AAA reference:** AC4 boat asset (~30K tris).
- **Bug/Gap:** Hull is one half-tube — has FLAT TOP (no deck or gunwale closure). Bow/stern caps at j=0 and j=segs collapse to single point on each side, creating non-manifold edges. Oars at line 7787 use the same broken axis-swap.
- **Severity:** blocker — hulls have open tops and non-manifold tips.
- **Upgrade to A:** Add deck closure; weld bow/stern points; bezier-sweep oars.

### 109. `generate_wagon_wheel_mesh` (line 7933) — Grade: **B+**
- **Claims:** Wagon wheel with spokes.
- **Produces:** Torus rim + hub + N spoke boxes (with proper Y-axis rotation matrix).
- **AAA reference:** Standard wagon wheel (~3-5K tris).
- **Bug/Gap:** Spoke at line 7980 builds duplicate cylinder via `_make_cylinder` then immediately discards it for the box (dead code at lines 7978-7981). Final spoke uses correct rotation math (lines 7988-7994). Best rotation in the file.
- **Severity:** polish — dead duplicate primitive.
- **Upgrade to A:** Remove dead `_make_cylinder` call.

---

### CATEGORY: STRUCTURAL

### 110. `generate_column_row_mesh` (line 8014) — Grade: **B+**
- **Claims:** Colonnade with style.
- **Produces:** N columns + entablature.
- **AAA reference:** UE5 architectural columns.
- **Bug/Gap:** Doric/Corinthian are reasonable; "gothic" pointed capital uses an inverted cone via vertex flipping (line 8112) which only works because of the specific sphere-mirror trick — fragile. No fluting on Corinthian.
- **Severity:** important.
- **Upgrade to A:** Add fluting; build Gothic capital from primitives properly.

### 111. `generate_buttress_mesh` (line 8130) — Grade: **B**
- **Claims:** Flying or standard buttress.
- **Produces:** Pier + pinnacle + arch (flying), or stepped tiers (standard).
- **AAA reference:** Gothic buttress AAA.
- **Bug/Gap:** Flying arch built as 6 stacked tilted box segments — visible joints; not a smooth arch.
- **Severity:** important.
- **Upgrade to A:** Sweep arch profile along smooth curve.

### 112. `generate_rampart_mesh` (line 8212) — Grade: **B**
- **Claims:** Castle wall with walkway + crenellations.
- **Produces:** Wall + walkway top + N merlons.
- **AAA reference:** UE5 castle wall.
- **Bug/Gap:** Merlons are uniform boxes; no arrow slits.
- **Severity:** polish.
- **Upgrade to A:** Add arrow slits via boolean cut.

### 113. `generate_drawbridge_mesh` (line 8272) — Grade: **B**
- **Claims:** Drawbridge with chains.
- **Produces:** Plank deck + side chains + winch.
- **AAA reference:** Castle drawbridge.
- **Bug/Gap:** Chains use the broken interlock pattern.
- **Severity:** important.
- **Upgrade to A:** Fix chain primitive.

### 114. `generate_well_mesh` (line 8355) — Grade: **B**
- **Claims:** Stone well with optional roof.
- **Produces:** Cylindrical wall + roof (4 posts + slanted roof) + bucket + rope.
- **AAA reference:** Fantasy well (~10K tris).
- **Bug/Gap:** Rope is straight cylinder, doesn't drape. Bucket generic.
- **Severity:** polish.
- **Upgrade to A:** Catenary rope; staved bucket.

### 115. `generate_ladder_mesh` (line 8459) — Grade: **B**
- **Claims:** Ladder.
- **Produces:** 2 rails + N rungs.
- **AAA reference:** Standard ladder.
- **Bug/Gap:** Rungs likely vertical cylinders rotated horizontally via the broken axis swap.
- **Severity:** important.
- **Upgrade to A:** Build horizontal rungs natively.

### 116. `generate_scaffolding_mesh` (line 8505) — Grade: **B**
- **Claims:** Construction scaffolding.
- **Produces:** Lattice of vertical posts + horizontal beams + planks.
- **AAA reference:** Scaffolding asset.
- **Bug/Gap:** Same horizontal-beam axis-swap risk.
- **Severity:** important.
- **Upgrade to A:** Native horizontal beams.

---

### CATEGORY: DARK FANTASY

### 117. `generate_sacrificial_circle_mesh` (line 8589) — Grade: **B**
- **Claims:** Ritual circle with rune stones.
- **Produces:** Floor disc + N raised rune stones around perimeter.
- **AAA reference:** Diablo ritual circle.
- **Bug/Gap:** Runes are flat — should be carved into floor with depth.
- **Severity:** polish.
- **Upgrade to A:** Carve runes via boolean; add chalk lines.

### 118. `generate_corruption_crystal_mesh` (line 8683) — Grade: **B**
- **Claims:** Corrupted energy crystal.
- **Produces:** Crystal cluster + base.
- **AAA reference:** Diablo demon crystal.
- **Bug/Gap:** Crystals are tapered hexagons with flat tops (not pointed).
- **Severity:** important.
- **Upgrade to A:** Collapse crystal tops to points.

### 119. `generate_veil_tear_mesh` (line 8753) — Grade: **B-**
- **Claims:** Reality tear / portal frame.
- **Produces:** Oval frame + jagged edge geometry.
- **AAA reference:** Doom Eternal portal.
- **Bug/Gap:** "Tear" is just an oval ring; no actual rip geometry.
- **Severity:** important.
- **Upgrade to A:** Add jagged border verts; volumetric distortion target.

### 120. `generate_soul_cage_mesh` (line 8824) — Grade: **B-**
- **Claims:** Ethereal soul cage/prison.
- **Produces:** Cage frame + suspended sphere.
- **AAA reference:** AAA soul cage.
- **Bug/Gap:** Cage frame likely uses broken horizontal-bar rotation.
- **Severity:** important.
- **Upgrade to A:** Native bar primitives.

### 121. `generate_blood_fountain_mesh` (line 8919) — Grade: **B**
- **Claims:** Dark fantasy blood fountain.
- **Produces:** Basin + central spike + drip cones.
- **AAA reference:** Bloodborne fountain.
- **Bug/Gap:** No fluid surface; "drips" are static cones.
- **Severity:** important.
- **Upgrade to A:** Add fluid plane with shader hint.

### 122. `generate_bone_throne_mesh` (line 9006) — Grade: **B**
- **Claims:** Throne of bones and skulls.
- **Produces:** Throne base + bone struts + skull decorations.
- **AAA reference:** Game of Thrones / Diablo bone throne.
- **Bug/Gap:** Bones are generic cylinders; skulls inherit skull-pile issues.
- **Severity:** important.
- **Upgrade to A:** Sculpt distinct bone shapes.

### 123. `generate_dark_obelisk_mesh` (line 9101) — Grade: **B**
- **Claims:** Monolith with rune engravings.
- **Produces:** Tall tapered prism + base + rune detail.
- **AAA reference:** 2001 monolith / Diablo obelisk.
- **Bug/Gap:** Runes are flat geometric strips, not carved.
- **Severity:** polish.
- **Upgrade to A:** Carve runes.

### 124. `generate_spider_web_mesh` (line 9201) — Grade: **D**
- **Claims:** Geometric spider web.
- **Produces:** Concentric rings + radial spokes + connection lines.
- **AAA reference:** L4D2 web cards (alpha-tested).
- **Bug/Gap:** No SHEET geometry — all strands are 3D cylinders/boxes; rings are perfect circles (real webs have catenary sag); no irregular spans.
- **Severity:** blocker — reads as a metal grate.
- **Upgrade to A:** Use alpha-tested quad with web texture; add catenary sag.

### 125. `generate_coffin_mesh` (line 9285) — Grade: **B**
- **Claims:** Coffin.
- **Produces:** Tapered coffin body + lid.
- **AAA reference:** Standard coffin (~5K tris).
- **Bug/Gap:** Body uses mirror-extrude approach (z-fighting risk at midline).
- **Severity:** important.
- **Upgrade to A:** Build full coffin without mirror.

### 126. `generate_gibbet_mesh` (line 9376) — Grade: **B-**
- **Claims:** Hanging cage on pole.
- **Produces:** Pole + cage frame + chain.
- **AAA reference:** Witcher 3 gibbet.
- **Bug/Gap:** Cage bars + chain inherit broken patterns.
- **Severity:** important.
- **Upgrade to A:** Fix bars + chain.

---

### CATEGORY: CONTAINERS & LOOT

### 127. `generate_urn_mesh` (line 9481) — Grade: **B+**
- **Claims:** Urn/vase.
- **Produces:** Lathed body + neck + handles.
- **AAA reference:** Greek urn AAA.
- **Bug/Gap:** Handles are toruses inserted at fixed XZ — flat circles, not curved handle shapes.
- **Severity:** important.
- **Upgrade to A:** Sweep handle along bezier.

### 128. `generate_crate_mesh` (line 9587) — Grade: **B**
- **Claims:** Wooden crate.
- **Produces:** Beveled box + plank lines + nail dots.
- **AAA reference:** Half-Life crate (~2K tris).
- **Bug/Gap:** Plank seams are tiny boxes overlaid on faces (z-fighting risk); nails are spheres.
- **Severity:** polish.
- **Upgrade to A:** Subdivide faces with proper seam UV; flat nail geometry.

### 129. `generate_sack_mesh` (line 9659) — Grade: **B**
- **Claims:** Grain sack.
- **Produces:** Lathed lumpy form + tied neck.
- **AAA reference:** AAA grain sack (~3K tris).
- **Bug/Gap:** Lumpy form is a smooth lathe — no grain bulge variation.
- **Severity:** polish.
- **Upgrade to A:** Add per-vertex displacement.

### 130. `generate_basket_mesh` (line 9707) — Grade: **B**
- **Claims:** Woven basket.
- **Produces:** Lathed body + handle + weave detail.
- **AAA reference:** AAA basket (~5K tris).
- **Bug/Gap:** Weave is implied via material, not geometry.
- **Severity:** important.
- **Upgrade to A:** Add per-strand weave geometry.

### 131. `generate_treasure_pile_mesh` (line 9768) — Grade: **B**
- **Claims:** Pile of coins and gems.
- **Produces:** Mound + N coin discs + N gem prisms.
- **AAA reference:** Smaug treasure hoard.
- **Bug/Gap:** Coins are uniform; gems are uniform; no overlap variation.
- **Severity:** polish.
- **Upgrade to A:** Vary scales/rotations; merge into displaced mound.

### 132. `generate_potion_bottle_mesh` (line 9830) — Grade: **B+**
- **Claims:** Potion bottle.
- **Produces:** Lathed bottle + cork + label.
- **AAA reference:** AAA potion bottle.
- **Bug/Gap:** Label is flat box; no liquid inside.
- **Severity:** polish.
- **Upgrade to A:** Add liquid plane with refraction shader hint.

### 133. `generate_scroll_mesh` (line 9942) — Grade: **B**
- **Claims:** Scroll/parchment.
- **Produces:** Cylinder roll + extended parchment plane.
- **AAA reference:** AAA scroll (~3K tris).
- **Bug/Gap:** Parchment is flat plane, no curl, no texture seam.
- **Severity:** polish.
- **Upgrade to A:** Curve parchment.

---

### CATEGORY: LIGHT SOURCES

### 134. `generate_lantern_mesh` (line 10024) — Grade: **B**
- **Claims:** Lantern with frame + glass + handle.
- **Produces:** Top cap + bottom cap + 4 corner posts + glass panels + handle ring + candle.
- **AAA reference:** AAA lantern (~6K tris).
- **Bug/Gap:** Glass panels are flat boxes (no transparency hint); handle ring may use rotation issue.
- **Severity:** polish.
- **Upgrade to A:** Mark glass material slot; bezier handle.

### 135. `generate_brazier_mesh` (line 10142) — Grade: **B**
- **Claims:** Brazier (fire bowl).
- **Produces:** Bowl + tripod legs + coals/flames.
- **AAA reference:** AAA brazier (~8K tris).
- **Bug/Gap:** Flames are stacked cones — no flame card.
- **Severity:** important.
- **Upgrade to A:** Replace flames with billboard quad + emissive.

### 136. `generate_campfire_mesh` (line 10253) — Grade: **B**
- **Claims:** Campfire with logs + stone ring.
- **Produces:** Stone ring + 4 logs + ash + flames.
- **AAA reference:** AAA campfire (~5K tris).
- **Bug/Gap:** Logs are straight cylinders, no bark detail.
- **Severity:** polish.
- **Upgrade to A:** Bark normal map; flame billboard.

### 137. `generate_crystal_light_mesh` (line 10315) — Grade: **B**
- **Claims:** Glowing crystal cluster.
- **Produces:** N hex prism crystals + base.
- **AAA reference:** Hearthstone crystal.
- **Bug/Gap:** Flat-top crystals (not pointed).
- **Severity:** polish.
- **Upgrade to A:** Point crystals; emissive material slot.

### 138. `generate_magic_orb_light_mesh` (line 10360) — Grade: **B**
- **Claims:** Floating magic orb with optional cage.
- **Produces:** Sphere + cage frame.
- **AAA reference:** Wisp orb AAA.
- **Bug/Gap:** Cage is generic.
- **Severity:** polish.
- **Upgrade to A:** Sculpt cage.

---

### CATEGORY: DOORS & WINDOWS

### 139. `generate_door_mesh` (line 10420) — Grade: **B**
- **Claims:** Door with style.
- **Produces:** Frame + door slab + handle + hinges.
- **AAA reference:** UE5 door BP.
- **Bug/Gap:** Hinges are simple cylinders, no axle. Handle is generic.
- **Severity:** polish.
- **Upgrade to A:** Carve panel detail.

### 140. `generate_window_mesh` (line 10595) — Grade: **B**
- **Claims:** Window frame.
- **Produces:** Frame + crossbars + glass.
- **AAA reference:** UE5 window BP.
- **Bug/Gap:** Crossbars likely use horizontal-rotation issue.
- **Severity:** important.
- **Upgrade to A:** Native horizontal mullions.

### 141. `generate_trapdoor_mesh` (line 10725) — Grade: **B**
- **Claims:** Floor trapdoor.
- **Produces:** Door slab + frame + handle ring.
- **AAA reference:** Standard trapdoor.
- **Bug/Gap:** Generic.
- **Severity:** polish.
- **Upgrade to A:** Add hinge axis.

---

### CATEGORY: WALL & FLOOR DECORATIONS

### 142. `generate_banner_mesh` (line 10821) — Grade: **B**
- **Claims:** Hanging banner with drape.
- **Produces:** Subdivided plane with sin-wave drape.
- **AAA reference:** UE5 banner with cloth sim.
- **Bug/Gap:** Drape is uniform sine — no wind variation, no edge tassel.
- **Severity:** polish.
- **Upgrade to A:** Multi-octave noise drape; add tassel chain.

### 143. `generate_wall_shield_mesh` (line 10881) — Grade: **B**
- **Claims:** Wall-mounted decorative shield.
- **Produces:** Shield silhouette + boss + crossed weapons.
- **AAA reference:** Tavern wall shield.
- **Bug/Gap:** Crossed weapons are flat geometry.
- **Severity:** polish.
- **Upgrade to A:** Add depth.

### 144. `generate_mounted_head_mesh` (line 10984) — Grade: **B-**
- **Claims:** Mounted trophy head.
- **Produces:** Wooden plaque + animal head.
- **AAA reference:** AAA trophy head (~15K tris).
- **Bug/Gap:** Head is generic sphere + cones; doesn't read as a specific animal.
- **Severity:** important.
- **Upgrade to A:** Sculpt species-specific heads.

### 145. `generate_painting_frame_mesh` (line 11089) — Grade: **B**
- **Claims:** Ornate picture frame.
- **Produces:** Outer frame + canvas plane + inner molding.
- **AAA reference:** Standard frame.
- **Bug/Gap:** Molding is flat boxes.
- **Severity:** polish.
- **Upgrade to A:** Profile-extrude molding.

### 146. `generate_rug_mesh` (line 11163) — Grade: **B**
- **Claims:** Floor rug.
- **Produces:** Subdivided plane with edge fringe.
- **AAA reference:** AAA rug (~3K tris).
- **Bug/Gap:** Fringe is flat geometry.
- **Severity:** polish.
- **Upgrade to A:** 3D fringe strands.

### 147. `generate_chandelier_mesh` (line 11253) — Grade: **B-**
- **Claims:** Hanging chandelier.
- **Produces:** Center boss + radial arms + candles.
- **AAA reference:** AAA chandelier (~12K tris).
- **Bug/Gap:** Arms inherit candelabra rotation issues.
- **Severity:** important.
- **Upgrade to A:** Bezier-sweep arms.

### 148. `generate_hanging_cage_mesh` (line 11326) — Grade: **B-**
- **Claims:** Suspended prison cage.
- **Produces:** Cage + chain to ceiling.
- **AAA reference:** Witcher gibbet cage.
- **Bug/Gap:** Bars + chain broken.
- **Severity:** important.
- **Upgrade to A:** Fix bars + chain.

---

### CATEGORY: CRAFTING & TRADE

### 149. `generate_anvil_mesh` (line 11396) — Grade: **B+**
- **Claims:** Blacksmith anvil.
- **Produces:** Base + body + horn + hardy hole.
- **AAA reference:** AAA anvil (~5K tris).
- **Bug/Gap:** Horn is straight cone, not curved.
- **Severity:** polish.
- **Upgrade to A:** Curve horn taper.

### 150. `generate_forge_mesh` (line 11459) — Grade: **B**
- **Claims:** Forge with chimney + bellows.
- **Produces:** Hearth + chimney + bellows shape.
- **AAA reference:** AAA forge (~15K tris).
- **Bug/Gap:** Bellows is generic blob.
- **Severity:** important.
- **Upgrade to A:** Sculpt accordion bellows.

### 151. `generate_workbench_mesh` (line 11524) — Grade: **B**
- **Claims:** Workbench.
- **Produces:** Top + legs + vise + tool rack.
- **AAA reference:** Carpenter bench.
- **Bug/Gap:** Tools generic.
- **Severity:** polish.
- **Upgrade to A:** Detail individual tools.

### 152. `generate_cauldron_mesh` (line 11601) — Grade: **B+**
- **Claims:** Cauldron with tripod.
- **Produces:** Lathed pot + tripod legs + handle.
- **AAA reference:** Witch cauldron (~8K tris).
- **Bug/Gap:** Handle is generic torus, no curve.
- **Severity:** polish.
- **Upgrade to A:** Bezier handle.

### 153. `generate_grinding_wheel_mesh` (line 11664) — Grade: **B**
- **Claims:** Sharpening wheel.
- **Produces:** Stone wheel + frame + crank.
- **AAA reference:** AAA grindstone.
- **Bug/Gap:** Crank arm uses rotation pattern.
- **Severity:** important.
- **Upgrade to A:** Native crank geometry.

### 154. `generate_loom_mesh` (line 11726) — Grade: **B**
- **Claims:** Weaving loom.
- **Produces:** Frame + warp threads + heddle.
- **AAA reference:** AAA loom (~10K tris).
- **Bug/Gap:** Threads are likely flat strips.
- **Severity:** polish.
- **Upgrade to A:** Add tension curve.

### 155. `generate_market_stall_mesh` (line 11786) — Grade: **B**
- **Claims:** Vendor market stall.
- **Produces:** Counter + canopy posts + canopy roof.
- **AAA reference:** UE5 market stall.
- **Bug/Gap:** Canopy is flat plane (no drape).
- **Severity:** polish.
- **Upgrade to A:** Add drape/sag.

---

### CATEGORY: SIGNS & MARKERS

### 156. `generate_signpost_mesh` (line 11879) — Grade: **B**
- **Claims:** Directional signpost.
- **Produces:** Post + arrow signs.
- **AAA reference:** Standard signpost.
- **Bug/Gap:** Arrows are flat boxes.
- **Severity:** polish.
- **Upgrade to A:** Profile-extrude arrow shape.

### 157. `generate_gravestone_mesh` (line 11938) — Grade: **B+**
- **Claims:** Gravestone.
- **Produces:** Stone slab with rounded top.
- **AAA reference:** Cemetery asset (~3K tris).
- **Bug/Gap:** Surface is smooth — no inscription depth.
- **Severity:** polish.
- **Upgrade to A:** Carve inscription via boolean.

### 158. `generate_waystone_mesh` (line 12028) — Grade: **B**
- **Claims:** Runic waypoint marker.
- **Produces:** Stone + glowing rune detail.
- **AAA reference:** Standard waystone.
- **Bug/Gap:** Runes flat.
- **Severity:** polish.
- **Upgrade to A:** Carve runes.

### 159. `generate_milestone_mesh` (line 12075) — Grade: **B**
- **Claims:** Road distance marker.
- **Produces:** Squat stone + carved face.
- **AAA reference:** Roman milestone.
- **Bug/Gap:** Face flat.
- **Severity:** polish.
- **Upgrade to A:** Carve numerals.

---

### CATEGORY: NATURAL FORMATIONS

### 160. `generate_stalactite_mesh` (line 12119) — Grade: **B**
- **Claims:** Ceiling stalactite.
- **Produces:** Tapered cylinder hanging from ceiling.
- **AAA reference:** AAA cave stalactite.
- **Bug/Gap:** Smooth taper, no drip rings or surface variation.
- **Severity:** polish.
- **Upgrade to A:** Add concentric drip ridges.

### 161. `generate_stalagmite_mesh` (line 12175) — Grade: **B**
- **Claims:** Floor stalagmite.
- **Produces:** Tapered cone from floor.
- **AAA reference:** AAA cave stalagmite.
- **Bug/Gap:** Apex pinch.
- **Severity:** polish.
- **Upgrade to A:** Weld apex.

### 162. `generate_bone_pile_mesh` (line 12229) — Grade: **B**
- **Claims:** Scattered bone pile.
- **Produces:** N tapered cylinders + ribcage approximation.
- **AAA reference:** AAA bone pile (~10K tris).
- **Bug/Gap:** Bones are uniform straight cylinders, no joint detail.
- **Severity:** important.
- **Upgrade to A:** Sculpt distinct bones.

### 163. `generate_nest_mesh` (line 12282) — Grade: **B**
- **Claims:** Nest.
- **Produces:** Lathed bowl + woven twigs + eggs.
- **AAA reference:** Bird nest AAA.
- **Bug/Gap:** Twigs are uniform cylinders.
- **Severity:** polish.
- **Upgrade to A:** Vary twig tapers.

### 164. `generate_geyser_vent_mesh` (line 12388) — Grade: **B**
- **Claims:** Geyser vent.
- **Produces:** Cone crater + steam billboard hint.
- **AAA reference:** Standard geyser.
- **Bug/Gap:** No steam geometry; vent is symmetric cone.
- **Severity:** polish.
- **Upgrade to A:** Mineral deposit displacement.

### 165. `generate_fallen_log_mesh` (line 12441) — Grade: **B+**
- **Claims:** Fallen rotting log.
- **Produces:** Cylinder body + bark detail + moss spheres + broken end caps.
- **AAA reference:** Quixel rotting log.
- **Bug/Gap:** Broken ends are flat caps; should be irregular.
- **Severity:** polish.
- **Upgrade to A:** Irregular fracture caps.

---

### CATEGORY: MONSTER PARTS

### 166. `generate_horn_mesh` (line 12546) — Grade: **B**
- **Claims:** Horn (various fantasy styles).
- **Produces:** Curved tapered tube.
- **AAA reference:** Monster horn AAA.
- **Bug/Gap:** Curve approximated via stacked cylinders.
- **Severity:** important.
- **Upgrade to A:** Sweep along bezier.

### 167. `generate_claw_set_mesh` (line 12645) — Grade: **B-**
- **Claims:** Set of monster claws.
- **Produces:** N curved cones in fan arrangement.
- **AAA reference:** Monster claw set.
- **Bug/Gap:** Claws are straight cones, no curve, apex pinching.
- **Severity:** important.
- **Upgrade to A:** Bezier curve each claw.

### 168. `generate_tail_mesh` (line 12687) — Grade: **B**
- **Claims:** Creature tail with tip styles.
- **Produces:** Series of tapered segments.
- **AAA reference:** Dragon tail AAA.
- **Bug/Gap:** Segments are straight cylinders, no curl.
- **Severity:** important.
- **Upgrade to A:** Bezier sweep.

### 169. `generate_wing_mesh` (line 12762) — Grade: **B-**
- **Claims:** Creature wing.
- **Produces:** Wing membrane + bone struts.
- **AAA reference:** Dragon wing AAA (~20K tris).
- **Bug/Gap:** Membrane likely flat triangle fan, no curve, no skin texture hint.
- **Severity:** important.
- **Upgrade to A:** Curve membrane via bezier patches.

### 170. `generate_tentacle_mesh` (line 12834) — Grade: **B**
- **Claims:** Tentacle with optional suckers.
- **Produces:** Tapered curve + N sucker spheres.
- **AAA reference:** Octopus tentacle AAA.
- **Bug/Gap:** Body is straight; suckers are uniform spheres.
- **Severity:** important.
- **Upgrade to A:** Bezier sweep; recess suckers.

### 171. `generate_mandible_mesh` (line 12883) — Grade: **B**
- **Claims:** Insect/spider mandible.
- **Produces:** Curved jaw piece.
- **AAA reference:** AAA insect mandible.
- **Bug/Gap:** Generic curve.
- **Severity:** polish.
- **Upgrade to A:** Add serration.

### 172. `generate_carapace_mesh` (line 12936) — Grade: **B**
- **Claims:** Armored carapace plate.
- **Produces:** Curved shell segment.
- **AAA reference:** Insect armor AAA.
- **Bug/Gap:** Smooth shell, no segmentation.
- **Severity:** polish.
- **Upgrade to A:** Add armor plate seams.

### 173. `generate_spine_ridge_mesh` (line 12984) — Grade: **B**
- **Claims:** Dorsal spines.
- **Produces:** Row of cones along ridge.
- **AAA reference:** Dragon spine.
- **Bug/Gap:** Cones with apex pinch.
- **Severity:** polish.
- **Upgrade to A:** Weld apex.

### 174. `generate_fang_mesh` (line 13019) — Grade: **B**
- **Claims:** Teeth/fangs arrangement.
- **Produces:** N curved cones.
- **AAA reference:** Vampire fangs AAA.
- **Bug/Gap:** Straight cones with pinch.
- **Severity:** polish.
- **Upgrade to A:** Slight curve; weld apex.

---

### CATEGORY: MONSTER BODIES

### 175. `generate_humanoid_beast_body` (line 13074) — Grade: **B-**
- **Claims:** Hunched beast-man torso + limbs.
- **Produces:** Torso sphere + arm/leg cylinders.
- **AAA reference:** WoW orc body (~30K tris).
- **Bug/Gap:** Snowman composition — no muscle definition.
- **Severity:** important.
- **Upgrade to A:** Sculpted base mesh.

### 176. `generate_quadruped_body` (line 13122) — Grade: **B-**
- **Claims:** Four-legged beast base.
- **Produces:** Torso barrel + 4 legs + neck/head stub.
- **AAA reference:** UE5 quadruped base.
- **Bug/Gap:** Same primitive snowman approach.
- **Severity:** important.
- **Upgrade to A:** Sculpt base.

### 177. `generate_serpent_body` (line 13155) — Grade: **B**
- **Claims:** Snake/wyrm body with taper.
- **Produces:** Tapered curve.
- **AAA reference:** AAA snake (~10K tris).
- **Bug/Gap:** Body curve approximated with stacked cylinders.
- **Severity:** important.
- **Upgrade to A:** Bezier sweep.

### 178. `generate_insectoid_body` (line 13197) — Grade: **B**
- **Claims:** Segmented insect body.
- **Produces:** N segment spheres + 6 leg cones.
- **AAA reference:** AAA insect.
- **Bug/Gap:** Legs are straight cones.
- **Severity:** important.
- **Upgrade to A:** Bend legs at joints.

### 179. `generate_skeletal_frame` (line 13247) — Grade: **B-**
- **Claims:** Undead skeleton base.
- **Produces:** Spine + ribs + skull + limb bones.
- **AAA reference:** Diablo skeleton (~25K tris).
- **Bug/Gap:** Inherits skull issues; ribs are arc primitives.
- **Severity:** important.
- **Upgrade to A:** Sculpt anatomical bones.

### 180. `generate_golem_body` (line 13305) — Grade: **B**
- **Claims:** Golem body.
- **Produces:** Boxy torso + chunky limbs.
- **AAA reference:** Stone golem AAA.
- **Bug/Gap:** Generic block composition.
- **Severity:** important.
- **Upgrade to A:** Carve runes; add stone fracture lines.

---

### CATEGORY: PROJECTILES

### 181. `generate_arrow_mesh` (line 13396) — Grade: **B**
- **Claims:** Arrow.
- **Produces:** Shaft + head cone + fletching planes.
- **AAA reference:** Standard arrow.
- **Bug/Gap:** Fletching is flat triangles, no double-sided render hint.
- **Severity:** polish.
- **Upgrade to A:** Add 4-vane fletching.

### 182. `generate_magic_orb_mesh` (line 13443) — Grade: **B**
- **Claims:** Magic projectile orb.
- **Produces:** Glowing sphere + trailing particle hints.
- **AAA reference:** AAA spell projectile.
- **Bug/Gap:** Generic sphere.
- **Severity:** polish.
- **Upgrade to A:** Mark emissive material.

### 183. `generate_throwing_knife_mesh` (line 13490) — Grade: **B-**
- **Claims:** Balanced throwing blade.
- **Produces:** Flat knife.
- **AAA reference:** Standard projectile knife.
- **Bug/Gap:** Flat box, no edge bevel.
- **Severity:** polish.
- **Upgrade to A:** Bevel.

### 184. `generate_bomb_mesh` (line 13511) — Grade: **B**
- **Claims:** Throwable bomb.
- **Produces:** Sphere body + fuse + cap.
- **AAA reference:** AAA bomb (~3K tris).
- **Bug/Gap:** Fuse is straight cylinder.
- **Severity:** polish.
- **Upgrade to A:** Curve fuse.

---

### CATEGORY: ARMOR

### 185. `generate_helmet_mesh` (line 13561) — Grade: **B-**
- **Claims:** Helmet.
- **Produces:** Sphere shell + visor + crest.
- **AAA reference:** AAA helmet (~12K tris).
- **Bug/Gap:** Sphere shell with no facial cavity, visor is flat box.
- **Severity:** important.
- **Upgrade to A:** Sculpt face cutout; add cheek guards.

### 186. `generate_pauldron_mesh` (line 13640) — Grade: **B**
- **Claims:** Shoulder armor.
- **Produces:** Curved plate.
- **AAA reference:** AAA pauldron.
- **Bug/Gap:** Smooth curve, no engraving.
- **Severity:** polish.
- **Upgrade to A:** Add detail.

### 187. `generate_gauntlet_mesh` (line 13674) — Grade: **B-**
- **Claims:** Gauntlet armor.
- **Produces:** Hand cover + finger plates.
- **AAA reference:** AAA gauntlet (~10K tris).
- **Bug/Gap:** Fingers are uniform plates, no articulation.
- **Severity:** important.
- **Upgrade to A:** Segment fingers at knuckles.

### 188. `generate_greave_mesh` (line 13722) — Grade: **B**
- **Claims:** Leg armor.
- **Produces:** Curved shin plate.
- **AAA reference:** AAA greave.
- **Bug/Gap:** Smooth, no detail.
- **Severity:** polish.
- **Upgrade to A:** Add knee cup.

### 189. `generate_breastplate_mesh` (line 13762) — Grade: **B**
- **Claims:** Chest armor.
- **Produces:** Curved torso plate.
- **AAA reference:** AAA breastplate.
- **Bug/Gap:** Single curved plate, no muscle definition.
- **Severity:** important.
- **Upgrade to A:** Sculpt pectoral / abdomen relief.

### 190. `generate_shield_mesh` (line 13817) — Grade: **B**
- **Claims:** Generic shield.
- **Produces:** Round/kite shield.
- **AAA reference:** Standard shield.
- **Bug/Gap:** Flat with rim, no boss detail.
- **Severity:** polish.
- **Upgrade to A:** Add boss + rivets.

### 191. `generate_heater_shield_mesh` (line 13881) — Grade: **B+**
- **Claims:** Medieval heater shield (inverted triangle top).
- **Produces:** Profile-extruded triangular shield.
- **AAA reference:** AAA heater shield.
- **Bug/Gap:** Flat back; no curvature.
- **Severity:** polish.
- **Upgrade to A:** Curve shield slightly.

### 192. `generate_pavise_mesh` (line 13912) — Grade: **B**
- **Claims:** Full-body pavise with prop stand.
- **Produces:** Tall rectangular shield + prop.
- **AAA reference:** Crusader pavise.
- **Bug/Gap:** Generic.
- **Severity:** polish.
- **Upgrade to A:** Profile detail.

### 193. `generate_targe_mesh` (line 13946) — Grade: **B**
- **Claims:** Highland targe with spike.
- **Produces:** Round shield + center spike.
- **AAA reference:** AAA targe.
- **Bug/Gap:** Spike has apex pinch.
- **Severity:** polish.
- **Upgrade to A:** Weld apex.

### 194. `generate_magical_barrier_mesh` (line 13972) — Grade: **B**
- **Claims:** Translucent energy barrier.
- **Produces:** Curved pane.
- **AAA reference:** AAA energy shield.
- **Bug/Gap:** Generic plane.
- **Severity:** polish.
- **Upgrade to A:** Mark transparent material.

### 195. `generate_bone_shield_mesh` (line 14005) — Grade: **B-**
- **Claims:** Shield from monster bones.
- **Produces:** Bone struts + skin membrane.
- **AAA reference:** Diablo bone shield.
- **Bug/Gap:** Bones are uniform cylinders.
- **Severity:** important.
- **Upgrade to A:** Sculpt distinct bones.

### 196. `generate_crystal_shield_mesh` (line 14049) — Grade: **B**
- **Claims:** Crystalline shield with facets.
- **Produces:** Faceted disc.
- **AAA reference:** AAA crystal shield.
- **Bug/Gap:** Generic facets, no internal refraction hint.
- **Severity:** polish.
- **Upgrade to A:** Mark glass material.

### 197. `generate_living_wood_shield_mesh` (line 14081) — Grade: **D**
- **Claims:** Organic living wood shield with growing branches.
- **Produces:** Disc + N straight cylinder branches.
- **AAA reference:** Druid wood shield.
- **Bug/Gap:** Branches are perfectly straight, no growth pattern, no leaves.
- **Severity:** blocker — does not read as living wood.
- **Upgrade to A:** Recursive branching with bezier; add leaf cards.

### 198. `generate_aegis_mesh` (line 14135) — Grade: **B-**
- **Claims:** Ornate ceremonial aegis with face relief.
- **Produces:** Shield + sphere face + features.
- **AAA reference:** Greek aegis with Medusa head.
- **Bug/Gap:** Face is just a sphere, no relief.
- **Severity:** important.
- **Upgrade to A:** Sculpt face relief.

---

### CATEGORY: SCROLL/RUNE PROJECTILES

### 199. `generate_spell_scroll_mesh` (line 14194) — Grade: **B+**
- **Claims:** Spell scroll with element-distinct visuals.
- **Produces:** Per-element profile variations + symbol.
- **AAA reference:** AAA elemental scroll set.
- **Bug/Gap:** Variations are radius/color hints, not real geometry diff.
- **Severity:** important.
- **Upgrade to A:** Distinct accessory geometry per element.

### 200. `generate_rune_stone_mesh` (line 14279) — Grade: **B+**
- **Claims:** Per-brand rune stone with distinct geometry.
- **Produces:** 6 different brand silhouettes (the most ambitious per-style generator).
- **AAA reference:** Diablo rune set.
- **Bug/Gap:** Carved runes are thin raised strips, not boolean-cut grooves.
- **Severity:** polish.
- **Upgrade to A:** Boolean-carve runes.

### 201. `generate_fire_arrow_mesh` (line 14411) — Grade: **B**
- **Claims:** Fire arrow.
- **Produces:** Arrow + flame wrap.
- **AAA reference:** Standard fire arrow.
- **Bug/Gap:** Flame is solid cone — should be alpha card.
- **Severity:** polish.
- **Upgrade to A:** Replace with billboard.

### 202. `generate_ice_arrow_mesh` (line 14440) — Grade: **B**
- **Claims:** Ice arrow.
- **Produces:** Arrow + crystalline frost head.
- **AAA reference:** Standard ice arrow.
- **Bug/Gap:** Crystals are flat-top hex prisms.
- **Severity:** polish.
- **Upgrade to A:** Pointed crystals.

### 203. `generate_poison_arrow_mesh` (line 14468) — Grade: **B**
- **Claims:** Poison arrow with venom drip.
- **Produces:** Arrow + drip cone.
- **AAA reference:** Standard poison arrow.
- **Bug/Gap:** Drip is solid cone, no liquid hint.
- **Severity:** polish.
- **Upgrade to A:** Multi-drip with material slot.

### 204. `generate_explosive_bolt_mesh` (line 14506) — Grade: **B**
- **Claims:** Crossbow bolt with explosive head.
- **Produces:** Bolt + spherical charge.
- **AAA reference:** Witcher 3 bolt.
- **Bug/Gap:** Generic.
- **Severity:** polish.
- **Upgrade to A:** Add fuse curl.

### 205. `generate_silver_arrow_mesh` (line 14535) — Grade: **B**
- **Claims:** Silver arrow.
- **Produces:** Arrow with silver-tinted head.
- **AAA reference:** Standard silver arrow.
- **Bug/Gap:** Identical geometry to base arrow; only material differs.
- **Severity:** polish.
- **Upgrade to A:** Add silver inlay detail.

### 206. `generate_barbed_arrow_mesh` (line 14566) — Grade: **B**
- **Claims:** Barbed arrow.
- **Produces:** Arrow + back-pointing barbs.
- **AAA reference:** AAA barbed arrow.
- **Bug/Gap:** Barbs are simple cones.
- **Severity:** polish.
- **Upgrade to A:** Profile-extrude barb.

---

### CATEGORY: FURNITURE EXTENDED

### 207. `generate_bed_mesh` (line 14604) — Grade: **B**
- **Claims:** Bed.
- **Produces:** Frame + mattress + pillow + headboard.
- **AAA reference:** UE5 bed BP (~15K tris).
- **Bug/Gap:** Mattress is flat box, no quilt detail.
- **Severity:** polish.
- **Upgrade to A:** Add quilted pattern.

### 208. `generate_wardrobe_mesh` (line 14740) — Grade: **B**
- **Claims:** Wardrobe / armoire.
- **Produces:** Cabinet + doors + handles.
- **AAA reference:** AAA wardrobe.
- **Bug/Gap:** Generic.
- **Severity:** polish.
- **Upgrade to A:** Carve panel detail.

### 209. `generate_cabinet_mesh` (line 14851) — Grade: **B**
- **Claims:** Cabinet.
- **Produces:** Body + drawers + handles.
- **AAA reference:** AAA cabinet.
- **Bug/Gap:** Generic.
- **Severity:** polish.
- **Upgrade to A:** Carve panel.

### 210. `generate_curtain_mesh` (line 14965) — Grade: **B**
- **Claims:** Curtain (subdivided plane with wave).
- **Produces:** Wavy plane.
- **AAA reference:** UE5 curtain with cloth.
- **Bug/Gap:** Same as banner; no wind variation.
- **Severity:** polish.
- **Upgrade to A:** Multi-octave noise.

### 211. `generate_mirror_mesh` (line 15048) — Grade: **B**
- **Claims:** Mirror with frame + surface.
- **Produces:** Frame + reflective plane.
- **AAA reference:** AAA mirror.
- **Bug/Gap:** Generic frame.
- **Severity:** polish.
- **Upgrade to A:** Carve frame; mark reflective material.

### 212. `generate_hay_bale_mesh` (line 15189) — Grade: **B**
- **Claims:** Hay bale.
- **Produces:** Cylinder + binding rings + straw bristles.
- **AAA reference:** Standard hay bale.
- **Bug/Gap:** Bristles are flat strips.
- **Severity:** polish.
- **Upgrade to A:** 3D straw cards.

### 213. `generate_wine_rack_mesh` (line 15267) — Grade: **B**
- **Claims:** Wine rack with bottle slots.
- **Produces:** Frame + N slot dividers + bottle placeholders.
- **AAA reference:** AAA wine rack.
- **Bug/Gap:** Generic frame.
- **Severity:** polish.
- **Upgrade to A:** Detail bottles.

### 214. `generate_bathtub_mesh` (line 15361) — Grade: **B**
- **Claims:** Bathtub.
- **Produces:** Lathed/extruded tub + claw feet.
- **AAA reference:** AAA bathtub.
- **Bug/Gap:** Feet generic.
- **Severity:** polish.
- **Upgrade to A:** Sculpt claw feet.

### 215. `generate_fireplace_mesh` (line 15500) — Grade: **B**
- **Claims:** Fireplace.
- **Produces:** Surround + mantel + hearth + firebox.
- **AAA reference:** AAA fireplace (~20K tris).
- **Bug/Gap:** Generic boxes.
- **Severity:** polish.
- **Upgrade to A:** Carve mantel relief; add log set inside.

---

### CATEGORY: CONSUMABLES

### 216. `generate_health_potion_mesh` (line 15657) — Grade: **B+**
- **Claims:** Health potion bottle.
- **Produces:** Lathed bottle (style-distinct profile) + cork.
- **AAA reference:** AAA potion (~5K tris).
- **Bug/Gap:** Cork is plain cylinder; no liquid inside.
- **Severity:** polish.
- **Upgrade to A:** Add liquid plane; vary cork.

### 217. `generate_mana_potion_mesh` (line 15702) — Grade: **B+**
- **Claims:** Mana potion (angular/ornate).
- **Produces:** Lathed bottle + cone cork + neck ring.
- **AAA reference:** AAA mana potion.
- **Bug/Gap:** Same as health potion.
- **Severity:** polish.
- **Upgrade to A:** Add liquid.

### 218. `generate_antidote_mesh` (line 15751) — Grade: **B+**
- **Claims:** Antidote vial.
- **Produces:** Lathed vial (style-distinct) + wax seal.
- **AAA reference:** AAA antidote.
- **Bug/Gap:** Same as potions.
- **Severity:** polish.
- **Upgrade to A:** Add liquid.

### 219. `generate_bread_mesh` (line 15794) — Grade: **B**
- **Claims:** Bread (loaf/roll/flatbread).
- **Produces:** Sphere-clamped lump + scoring lines.
- **AAA reference:** AAA bread (~2K tris).
- **Bug/Gap:** "loaf" is a sphere clamped above y=0 then scaled per-axis — produces a flat-bottomed sphere. Score lines are flat boxes overlaid (z-fight risk).
- **Severity:** polish.
- **Upgrade to A:** Carve scores via boolean.

### 220. `generate_cheese_mesh` (line 15835) — Grade: **B**
- **Claims:** Cheese (wheel/wedge/block).
- **Produces:** Cylinder/triangle/box.
- **AAA reference:** Standard cheese.
- **Bug/Gap:** Wedge is triangulated by hand (line 15856) using an unusual face list — risk of incorrect winding on quad face `(0,1,4,3)`.
- **Severity:** polish.
- **Upgrade to A:** Use standard triangulation.

### 221. `generate_meat_mesh` (line 15870) — Grade: **B**
- **Claims:** Cooked meat.
- **Produces:** Drumstick/steak/ham via lathe + bone cylinder.
- **AAA reference:** AAA meat asset.
- **Bug/Gap:** Generic lathe + cylinder.
- **Severity:** polish.
- **Upgrade to A:** Add muscle striation.

### 222. `generate_apple_mesh` (line 15915) — Grade: **B+**
- **Claims:** Apple (whole/bitten/rotten).
- **Produces:** Lathed apple shape + stem + leaf + style modifier (bite sphere or RNG displacement).
- **AAA reference:** AAA fruit asset.
- **Bug/Gap:** Bite is an overlapping sphere not booleaned out — it's still solid; just a bump on the side.
- **Severity:** important — bite doesn't actually remove flesh.
- **Upgrade to A:** Boolean-subtract bite.

### 223. `generate_mushroom_food_mesh` (line 15971) — Grade: **B**
- **Claims:** Edible mushroom (smaller).
- **Produces:** Calls inner `_single_mush` to emit stem + cap.
- **AAA reference:** AAA edible mushroom.
- **Bug/Gap:** Cap profile starts at y=0 but is shifted by `mh*0.55` in line 15991 — coordinates work but profile is fragile if scale changes.
- **Severity:** polish.
- **Upgrade to A:** Parameterize properly.

### 224. `_single_mush` (line 15979, nested in `generate_mushroom_food_mesh`) — Grade: **B**
- **Claims:** Build single mushroom (stem + cap).
- **Produces:** Two parts (cylinder stem + lathed cap).
- **AAA reference:** Mushroom subroutine.
- **Bug/Gap:** Cap profile shifts hardcoded `mh*0.55` regardless of `cap_r`.
- **Severity:** polish.
- **Upgrade to A:** Decouple cap height from stem.

### 225. `generate_fish_mesh` (line 16010) — Grade: **B-**
- **Claims:** Fish (whole or fillet).
- **Produces:** Lathed body + tail quad + dorsal triangle + eye sphere.
- **AAA reference:** AAA fish (~5K tris).
- **Bug/Gap:** Body uses two consecutive vertex transforms (lines 16025-16026): first squashes Z, then SWAPS Y/Z — net result is a lying-down fish but the transformations are confusing and fragile. Tail is single quad.
- **Severity:** important.
- **Upgrade to A:** Build body in correct orientation natively; add fin geometry.

---

### CATEGORY: CRAFTING MATERIALS

### 226. `generate_ore_mesh` (line 16058) — Grade: **B**
- **Claims:** Raw ore chunk (iron/copper/gold/dark_crystal).
- **Produces:** RNG-jittered sphere + small fragment + crystal version uses tapered cylinders.
- **AAA reference:** Quixel ore chunks (~10K tris).
- **Bug/Gap:** Crystal cylinders flat-top.
- **Severity:** polish.
- **Upgrade to A:** Point crystal tops.

### 227. `generate_leather_mesh` (line 16103) — Grade: **B**
- **Claims:** Leather material (folded/strip/hide).
- **Produces:** Stacked beveled boxes / sin-curve strip / lathed hide.
- **AAA reference:** AAA leather drop.
- **Bug/Gap:** Generic.
- **Severity:** polish.
- **Upgrade to A:** Add edge irregularity for hide.

### 228. `generate_herb_mesh` (line 16145) — Grade: **B**
- **Claims:** Medicinal herb.
- **Produces:** Stem + leaf quads / bundle / flower petals.
- **AAA reference:** SpeedTree herb.
- **Bug/Gap:** Leaves are flat quads with no alpha hint.
- **Severity:** important.
- **Upgrade to A:** Mark alpha-tested material.

### 229. `generate_gem_mesh` (line 16200) — Grade: **B+**
- **Claims:** Brilliant-cut faceted gem.
- **Produces:** Table + crown + pavilion + culet — proper brilliant cut topology.
- **AAA reference:** Gem cutter brilliant-cut model.
- **Bug/Gap:** Single octahedron-like form per gem; no facet variation per stone type beyond size.
- **Severity:** polish.
- **Upgrade to A:** Different cuts per gem (emerald cut, princess cut, etc.).

### 230. `generate_bone_shard_mesh` (line 16240) — Grade: **B**
- **Claims:** Bone drop (fragment/fang/horn).
- **Produces:** RNG sphere + fragment / lathed fang / stacked horn.
- **AAA reference:** AAA bone drop.
- **Bug/Gap:** Horn at line 16273-16280 is a STACK of cylinders along Y at fixed `x_off = t*t*0.04` — produces a slightly bent post, not a curved horn.
- **Severity:** polish.
- **Upgrade to A:** Sweep along curve.

---

### CATEGORY: CURRENCY

### 231. `generate_coin_mesh` (line 16292) — Grade: **B**
- **Claims:** Currency coin.
- **Produces:** Cylinder + rim torus + face emboss.
- **AAA reference:** AAA coin.
- **Bug/Gap:** Emboss is just two thin discs stacked, no actual face relief.
- **Severity:** polish.
- **Upgrade to A:** Carve face via normal map.

### 232. `generate_coin_pouch_mesh` (line 16318) — Grade: **B**
- **Claims:** Coin pouch.
- **Produces:** Lathed pouch + tie ring + small overflow coins (large variant).
- **AAA reference:** AAA coin pouch.
- **Bug/Gap:** Pouch is a smooth lathe — no fabric folds.
- **Severity:** polish.
- **Upgrade to A:** Add per-vertex displacement for folds.

---

### CATEGORY: KEY ITEMS

### 233. `generate_key_mesh` (line 16368) — Grade: **B**
- **Claims:** Key.
- **Produces:** Bow ring + shaft + ward teeth.
- **AAA reference:** AAA key (~2K tris).
- **Bug/Gap:** Ward teeth are uniform boxes.
- **Severity:** polish.
- **Upgrade to A:** Vary ward shape.

### 234. `generate_map_scroll_mesh` (line 16423) — Grade: **B**
- **Claims:** Map document scroll.
- **Produces:** Roll cylinder + parchment plane + ribbon.
- **AAA reference:** AAA map scroll.
- **Bug/Gap:** Same as scroll_mesh.
- **Severity:** polish.
- **Upgrade to A:** Curve parchment.

### 235. `generate_lockpick_mesh` (line 16484) — Grade: **B**
- **Claims:** Lockpick set.
- **Produces:** Pick + tension wrench + handle.
- **AAA reference:** AAA lockpick.
- **Bug/Gap:** Picks are bent boxes.
- **Severity:** polish.
- **Upgrade to A:** Profile-extrude proper pick shapes.

---

### CATEGORY: FORTIFICATIONS

### 236. `generate_palisade_mesh` (line 16543) — Grade: **B**
- **Claims:** Palisade wall section.
- **Produces:** N pointed-top vertical posts.
- **AAA reference:** UE5 palisade.
- **Bug/Gap:** Posts are uniform; no variation.
- **Severity:** polish.
- **Upgrade to A:** Vary heights/lean.

### 237. `generate_watchtower_mesh` (line 16624) — Grade: **B**
- **Claims:** Multi-level watchtower.
- **Produces:** Base + N levels + roof + ladder.
- **AAA reference:** AAA watchtower (~30K tris).
- **Bug/Gap:** Levels are stacked boxes; ladder uses broken rotation.
- **Severity:** important.
- **Upgrade to A:** Add proper ladder; carve windows.

### 238. `generate_battlement_mesh` (line 16763) — Grade: **B+**
- **Claims:** Crenellated wall top.
- **Produces:** Wall + walkway + N merlons + arrow slits.
- **AAA reference:** Castle battlement.
- **Bug/Gap:** Slits are flat geometry, not cut into wall.
- **Severity:** polish.
- **Upgrade to A:** Boolean-cut slits.

### 239. `generate_moat_edge_mesh` (line 16856) — Grade: **B**
- **Claims:** Moat edge with sloped bank.
- **Produces:** Bank slope + retaining wall + water plane.
- **AAA reference:** AAA moat edge.
- **Bug/Gap:** Generic; no water shader hint.
- **Severity:** polish.
- **Upgrade to A:** Mark water material.

### 240. `generate_windmill_mesh` (line 16956) — Grade: **B**
- **Claims:** Windmill.
- **Produces:** Tower + cap + 4 sails + door.
- **AAA reference:** AAA windmill (~30K tris).
- **Bug/Gap:** Sails are flat planes, no ribbing; tower is smooth tapered cylinder.
- **Severity:** important.
- **Upgrade to A:** Add stone-block detail; sail ribs.

### 241. `generate_dock_mesh` (line 17074) — Grade: **B**
- **Claims:** Waterfront dock.
- **Produces:** Pier + piles + bollards.
- **AAA reference:** AAA dock.
- **Bug/Gap:** Generic; no plank seams.
- **Severity:** polish.
- **Upgrade to A:** Detail planks.

### 242. `generate_bridge_stone_mesh` (line 17165) — Grade: **B**
- **Claims:** Stone bridge.
- **Produces:** Arch + roadway + parapets.
- **AAA reference:** AAA stone bridge (~25K tris).
- **Bug/Gap:** Arch likely linearized.
- **Severity:** important.
- **Upgrade to A:** Real circular arch.

### 243. `generate_rope_bridge_mesh` (line 17326) — Grade: **B+**
- **Claims:** Rope/plank bridge with catenary sag.
- **Produces:** Two catenary ropes + N planks + side ropes.
- **AAA reference:** AAA rope bridge.
- **Bug/Gap:** Catenary math present but plank-rope connection is geometric only (no rigging hint).
- **Severity:** polish.
- **Upgrade to A:** Add bone rig hint for cloth sim.

### 244. `generate_tent_mesh` (line 17436) — Grade: **B**
- **Claims:** Camping tent.
- **Produces:** Pole + canvas plane + ground stakes.
- **AAA reference:** AAA tent.
- **Bug/Gap:** Canvas is flat plane, no drape.
- **Severity:** polish.
- **Upgrade to A:** Drape canvas.

### 245. `generate_hitching_post_mesh` (line 17605) — Grade: **B**
- **Claims:** Hitching post.
- **Produces:** Post + crossbar + ring.
- **AAA reference:** Standard hitching post.
- **Bug/Gap:** Crossbar uses rotation pattern.
- **Severity:** important.
- **Upgrade to A:** Native horizontal bar.

### 246. `generate_feeding_trough_mesh` (line 17661) — Grade: **B**
- **Claims:** Feeding trough.
- **Produces:** Hollowed box.
- **AAA reference:** AAA trough.
- **Bug/Gap:** Hollow is implied (wall geometry), no actual interior.
- **Severity:** polish.
- **Upgrade to A:** Boolean-subtract interior.

### 247. `generate_barricade_outdoor_mesh` (line 17719) — Grade: **B**
- **Claims:** Outdoor defensive barricade.
- **Produces:** Beams + spikes.
- **AAA reference:** AAA barricade.
- **Bug/Gap:** Generic.
- **Severity:** polish.
- **Upgrade to A:** Add wire.

### 248. `generate_lookout_post_mesh` (line 17802) — Grade: **B**
- **Claims:** Elevated lookout.
- **Produces:** 4 legs + platform + ladder.
- **AAA reference:** AAA lookout.
- **Bug/Gap:** Ladder + platform connection issues.
- **Severity:** important.
- **Upgrade to A:** Fix ladder.

### 249. `generate_spike_fence_mesh` (line 17908) — Grade: **B**
- **Claims:** Spiked fence.
- **Produces:** Posts + horizontal rails + N spikes.
- **AAA reference:** AAA spike fence.
- **Bug/Gap:** Spikes have apex pinch.
- **Severity:** polish.
- **Upgrade to A:** Weld apexes.

---

### CATEGORY: GATES & DOORS EXTENDED

### 250. `generate_portcullis_mesh` (line 17990) — Grade: **B-**
- **Claims:** Iron portcullis.
- **Produces:** Frame + N vertical bars + N horizontal bars.
- **AAA reference:** AAA portcullis.
- **Bug/Gap:** Horizontal bars use broken rotation.
- **Severity:** important.
- **Upgrade to A:** Native horizontal cylinders.

### 251. `generate_iron_gate_mesh` (line 18045) — Grade: **B**
- **Claims:** Iron gate/door.
- **Produces:** Frame + ornate scrolls.
- **AAA reference:** AAA iron gate.
- **Bug/Gap:** Scrolls likely flat curves.
- **Severity:** important.
- **Upgrade to A:** Sweep scrolls along bezier.

### 252. `generate_bridge_plank_mesh` (line 18134) — Grade: **B**
- **Claims:** Bridge plank/walkway.
- **Produces:** N planks + cross supports.
- **AAA reference:** Standard plank bridge.
- **Bug/Gap:** Generic.
- **Severity:** polish.
- **Upgrade to A:** Add nail detail.

---

### CATEGORY: PRISON

### 253. `generate_shackle_mesh` (line 18227) — Grade: **B**
- **Claims:** Iron shackle.
- **Produces:** Wrist ring + chain link + lock.
- **AAA reference:** AAA shackle.
- **Bug/Gap:** Chain inherits broken interlock.
- **Severity:** important.
- **Upgrade to A:** Fix chain.

### 254. `generate_cage_mesh` (line 18311) — Grade: **B-**
- **Claims:** Prison cage.
- **Produces:** Frame + bars + door.
- **AAA reference:** AAA cage.
- **Bug/Gap:** Bars use broken horizontal rotation.
- **Severity:** important.
- **Upgrade to A:** Native bars.

### 255. `generate_stocks_mesh` (line 18409) — Grade: **B**
- **Claims:** Wooden stocks (pillory).
- **Produces:** Posts + crossbeam with circular cutouts.
- **AAA reference:** AAA stocks.
- **Bug/Gap:** Cutouts are visual only (geometry not actually subtracted).
- **Severity:** important.
- **Upgrade to A:** Boolean-cut openings.

### 256. `generate_iron_maiden_mesh` (line 18460) — Grade: **D**
- **Claims:** Iron maiden.
- **Produces:** Coffin-shaped box.
- **AAA reference:** AAA torture device (~20K tris).
- **Bug/Gap:** Sealed box with no door panels, no internal spike volume, no hinges. Just a coffin.
- **Severity:** blocker — doesn't open, no spikes inside.
- **Upgrade to A:** Split into front/back halves with hinged door; add interior spike rows.

### 257. `generate_prisoner_skeleton_mesh` (line 18543) — Grade: **B-**
- **Claims:** Chained skeleton prop.
- **Produces:** Skeleton frame + chains.
- **AAA reference:** AAA prisoner remains.
- **Bug/Gap:** Inherits skull and chain issues.
- **Severity:** important.
- **Upgrade to A:** Fix sub-meshes.

---

### CATEGORY: OCCULT

### 258. `generate_summoning_circle_mesh` (line 18620) — Grade: **B**
- **Claims:** Summoning circle floor marking.
- **Produces:** Concentric rings + radial lines + symbols.
- **AAA reference:** Diablo summoning circle.
- **Bug/Gap:** Lines are flat boxes; symbols are simple shapes.
- **Severity:** polish.
- **Upgrade to A:** Use decal projection material.

### 259. `generate_ritual_candles_mesh` (line 18684) — Grade: **B**
- **Claims:** Cluster of ritual candles.
- **Produces:** N tapered cylinders + flame cones.
- **AAA reference:** AAA candle set.
- **Bug/Gap:** Flames are solid cones.
- **Severity:** polish.
- **Upgrade to A:** Replace flames with billboard.

### 260. `generate_occult_symbols_mesh` (line 18741) — Grade: **B**
- **Claims:** Floor occult symbols.
- **Produces:** Geometric pentagram and runes.
- **AAA reference:** AAA occult markings.
- **Bug/Gap:** Flat geometry overlaid (z-fight).
- **Severity:** polish.
- **Upgrade to A:** Decal projection.

### 261. `generate_cobweb_mesh` (line 18810) — Grade: **D**
- **Claims:** Cobweb.
- **Produces:** Stretched cylinders forming a net.
- **AAA reference:** L4D2 cobweb cards.
- **Bug/Gap:** No sheet polygon — strands are 3D cylinders forming a wireframe pattern; nothing to alpha-test against. Renders as a metal mesh, not a web.
- **Severity:** blocker.
- **Upgrade to A:** Replace with alpha quad.

### 262. `generate_spider_egg_sac_mesh` (line 18929) — Grade: **B**
- **Claims:** Egg sac cluster.
- **Produces:** N egg spheres in cluster.
- **AAA reference:** AAA egg sac.
- **Bug/Gap:** Generic spheres.
- **Severity:** polish.
- **Upgrade to A:** Add silk strand mesh.

### 263. `generate_rubble_pile_mesh` (line 18986) — Grade: **B**
- **Claims:** Rubble/debris pile.
- **Produces:** N scattered beveled boxes.
- **AAA reference:** Quixel rubble.
- **Bug/Gap:** Boxes are uniform sized; no large chunks.
- **Severity:** polish.
- **Upgrade to A:** Vary size dramatically.

### 264. `generate_hanging_skeleton_mesh` (line 19046) — Grade: **B-**
- **Claims:** Skeleton hanging from chains.
- **Produces:** Skeleton + chains.
- **AAA reference:** AAA hanging skeleton.
- **Bug/Gap:** Inherits skeleton + chain issues.
- **Severity:** important.
- **Upgrade to A:** Fix sub-meshes.

### 265. `generate_dripping_water_mesh` (line 19106) — Grade: **D**
- **Claims:** Dripping water with stalactite formation.
- **Produces:** Stalactite cone + tiny spheres labeled "drops".
- **AAA reference:** AAA water drip with shader.
- **Bug/Gap:** Function name suggests dripping water; it's just a stalactite + dots. No fluid simulation hint.
- **Severity:** blocker — name lies; misclassified asset.
- **Upgrade to A:** Add water plane + stretch deformation.

### 266. `generate_rat_nest_mesh` (line 19154) — Grade: **B**
- **Claims:** Small rat nest.
- **Produces:** Bowl + twigs + small debris.
- **AAA reference:** Standard rat nest.
- **Bug/Gap:** Generic.
- **Severity:** polish.
- **Upgrade to A:** Add fur strands.

### 267. `generate_rotting_barrel_mesh` (line 19197) — Grade: **B**
- **Claims:** Damaged/rotting barrel.
- **Produces:** Barrel with broken staves.
- **AAA reference:** Standard rotting barrel.
- **Bug/Gap:** "Broken" is just gaps in the lathe ring — no plank fragmentation.
- **Severity:** polish.
- **Upgrade to A:** Sculpt broken plank chunks.

### 268. `generate_treasure_chest_mesh` (line 19249) — Grade: **B**
- **Claims:** Dungeon treasure chest.
- **Produces:** Chest + gold/gem overflow.
- **AAA reference:** AAA treasure chest.
- **Bug/Gap:** Inherits chest issues.
- **Severity:** polish.
- **Upgrade to A:** Add jewel spillover detail.

### 269. `generate_gem_pile_mesh` (line 19360) — Grade: **B**
- **Claims:** Scattered gems.
- **Produces:** N gem prisms.
- **AAA reference:** AAA gem pile.
- **Bug/Gap:** All gems identical size/cut.
- **Severity:** polish.
- **Upgrade to A:** Vary cut + color hint.

### 270. `generate_gold_pile_mesh` (line 19397) — Grade: **B**
- **Claims:** Gold coin pile.
- **Produces:** N coin discs.
- **AAA reference:** AAA gold pile.
- **Bug/Gap:** Coins are uniform discs.
- **Severity:** polish.
- **Upgrade to A:** Vary thickness; add small gem accents.

### 271. `generate_lore_tablet_mesh` (line 19441) — Grade: **B**
- **Claims:** Stone tablet with carved surface.
- **Produces:** Slab + raised text strips.
- **AAA reference:** AAA lore tablet.
- **Bug/Gap:** Text is flat geometry.
- **Severity:** polish.
- **Upgrade to A:** Carve text via boolean.

---

### CATEGORY: FOREST ANIMALS

### 272. `generate_deer_mesh` (line 19514) — Grade: **B**
- **Claims:** Stylized deer with antlers.
- **Produces:** Body + neck + head + 4 legs + antlers (adult).
- **AAA reference:** RDR2 deer (~30K tris with proper rigging).
- **Bug/Gap:** Body uses tapered cylinder "rotated" via line 19536 vertex transform `(v[0], 0.55*sc + v[2]*0.15, v[1] - 0.55*sc + body_len*0.1)` which is a non-orthogonal shear masquerading as a rotation. Result: body is sheared, not rotated. Antlers built via similar shear (line 19623). Snout has placeholder rotation `[(v[0], v[1], v[2]) for v in sv]` (no-op identity loop — dead code).
- **Severity:** important — body is geometrically distorted.
- **Upgrade to A:** Build body in correct orientation via direct vertex math; remove identity loop.

### 273. `generate_wolf_mesh` (line 19643) — Grade: **B**
- **Claims:** Stylized wolf.
- **Produces:** Body sphere + torso + chest + neck + head + snout + ears + 4 legs + bushy tail.
- **AAA reference:** RDR2 wolf.
- **Bug/Gap:** Same shear pattern as deer for torso (line 19669); tail is stacked spheres = visible bumps.
- **Severity:** important.
- **Upgrade to A:** Sweep tail along curve.

### 274. `generate_fox_mesh` (line 19743) — Grade: **B-**
- **Claims:** Stylized fox.
- **Produces:** Same approach as wolf, scaled smaller, with bushy tail.
- **AAA reference:** AAA fox.
- **Bug/Gap:** Snout cone "rotated" via line 19790-19791 vertex transform that is a Y/Z swap with offset; result is sheared cone, not rotated.
- **Severity:** important.
- **Upgrade to A:** Build snout with correct axis natively.

### 275. `generate_rabbit_mesh` (line 19832) — Grade: **C**
- **Claims:** Sitting rabbit.
- **Produces:** Body sphere + haunch sphere + head + ears + paws + hind legs + cotton tail.
- **AAA reference:** AAA rabbit (~5K tris).
- **Bug/Gap:** "Hind legs" are SPHERES (line 19886) and "hind feet" are tiny tapered cylinders — does not read as rabbit anatomy. Whole rabbit is a snowman of spheres.
- **Severity:** blocker — silhouette fails.
- **Upgrade to A:** Replace primitive composition with sculpt.

### 276. `generate_owl_mesh` (line 19905) — Grade: **B**
- **Claims:** Perched owl with face disc.
- **Produces:** Body sphere + face disc + eyes + beak + wings + talons.
- **AAA reference:** AAA owl.
- **Bug/Gap:** Wings are flat planes; no feathers.
- **Severity:** polish.
- **Upgrade to A:** Layer feather cards.

### 277. `generate_crow_mesh` (line 19997) — Grade: **B**
- **Claims:** Crow/raven.
- **Produces:** Body + head + beak + wings + tail + legs.
- **AAA reference:** AAA crow.
- **Bug/Gap:** Wings flat.
- **Severity:** polish.
- **Upgrade to A:** Feather layers.

---

### CATEGORY: MOUNTAIN ANIMALS

### 278. `generate_mountain_goat_mesh` (line 20088) — Grade: **B**
- **Claims:** Mountain goat with horns.
- **Produces:** Body + head + horns + 4 legs.
- **AAA reference:** AAA goat.
- **Bug/Gap:** Horns are stacked cylinders, no curl.
- **Severity:** important.
- **Upgrade to A:** Sweep horn along spiral.

### 279. `generate_eagle_mesh` (line 20195) — Grade: **B**
- **Claims:** Large bird of prey.
- **Produces:** Body + head + beak + spread wings + talons.
- **AAA reference:** AAA eagle.
- **Bug/Gap:** Wings are flat planes.
- **Severity:** important.
- **Upgrade to A:** Feather layers.

### 280. `generate_bear_mesh` (line 20293) — Grade: **B**
- **Claims:** Large quadruped bear.
- **Produces:** Body + chest + head + snout + 4 legs + tail.
- **AAA reference:** RDR2 bear.
- **Bug/Gap:** Same shear-as-rotation bugs.
- **Severity:** important.
- **Upgrade to A:** Sculpt.

---

### CATEGORY: DOMESTIC ANIMALS

### 281. `generate_horse_mesh` (line 20427) — Grade: **B**
- **Claims:** Horse.
- **Produces:** Body + neck + head + 4 legs + mane + tail.
- **AAA reference:** AAA horse (RDR2 ~80K tris).
- **Bug/Gap:** Mane is flat strip; tail is stacked spheres.
- **Severity:** important.
- **Upgrade to A:** Hair cards for mane/tail.

### 282. `generate_chicken_mesh` (line 20555) — Grade: **B**
- **Claims:** Chicken.
- **Produces:** Body + head + comb + beak + wings + legs + tail feathers.
- **AAA reference:** AAA chicken.
- **Bug/Gap:** Generic.
- **Severity:** polish.
- **Upgrade to A:** Feather cards.

### 283. `generate_dog_mesh` (line 20647) — Grade: **B**
- **Claims:** Medium dog.
- **Produces:** Same template as wolf with proportions adjusted.
- **AAA reference:** RDR2 dog.
- **Bug/Gap:** Inherits wolf issues.
- **Severity:** important.
- **Upgrade to A:** Sculpt.

### 284. `generate_cat_mesh` (line 20766) — Grade: **B**
- **Claims:** Cat.
- **Produces:** Body + head + ears + 4 legs + tail.
- **AAA reference:** RDR2 cat.
- **Bug/Gap:** Tail is stacked spheres.
- **Severity:** polish.
- **Upgrade to A:** Sweep tail.

---

### CATEGORY: VERMIN

### 285. `generate_rat_mesh` (line 20871) — Grade: **B**
- **Claims:** Tiny quadruped rat.
- **Produces:** Body + head + ears + tail + 4 legs.
- **AAA reference:** Standard rat.
- **Bug/Gap:** Tail is straight cylinder.
- **Severity:** polish.
- **Upgrade to A:** Curve tail.

### 286. `generate_bat_mesh` (line 20945) — Grade: **B**
- **Claims:** Bat with wings spread.
- **Produces:** Body + wings.
- **AAA reference:** AAA bat.
- **Bug/Gap:** Wings flat planes.
- **Severity:** polish.
- **Upgrade to A:** Add wing struts.

### 287. `generate_small_spider_mesh` (line 21027) — Grade: **B**
- **Claims:** Small 8-legged spider.
- **Produces:** Body + head + 8 legs.
- **AAA reference:** AAA spider.
- **Bug/Gap:** Legs are straight cylinders, no joint articulation.
- **Severity:** important.
- **Upgrade to A:** Bend legs at joints.

### 288. `generate_beetle_mesh` (line 21105) — Grade: **B**
- **Claims:** Beetle.
- **Produces:** Body + carapace + head + 6 legs + antennae.
- **AAA reference:** AAA beetle.
- **Bug/Gap:** Same straight-leg issue.
- **Severity:** important.
- **Upgrade to A:** Bent legs.

---

### CATEGORY: SWAMP ANIMALS

### 289. `generate_frog_mesh` (line 21179) — Grade: **B**
- **Claims:** Sitting frog.
- **Produces:** Body + head + eyes + 4 legs.
- **AAA reference:** AAA frog.
- **Bug/Gap:** Generic primitive composition.
- **Severity:** polish.
- **Upgrade to A:** Sculpt.

### 290. `generate_snake_ambient_mesh` (line 21265) — Grade: **B**
- **Claims:** Non-monster snake (ambient wildlife).
- **Produces:** Coiled body via stacked cylinders.
- **AAA reference:** AAA snake.
- **Bug/Gap:** Stacked cylinders without smooth weld; coil is faceted.
- **Severity:** important.
- **Upgrade to A:** Sweep along bezier coil.

### 291. `generate_turtle_mesh` (line 21360) — Grade: **B**
- **Claims:** Turtle with shell.
- **Produces:** Shell hemisphere + body + head + 4 flippers.
- **AAA reference:** AAA turtle.
- **Bug/Gap:** Flippers are flat boxes.
- **Severity:** polish.
- **Upgrade to A:** Curve flippers.

---

### CATEGORY: MEGA-COMPOSITES (BUILDINGS)

### 292. `generate_mine_entrance_mesh` (line 21452) — Grade: **B+**
- **Claims:** Mine shaft entrance with supports + track + cart.
- **Produces:** Frame archway + interior support beams + tracks + ties + mine cart with wheels.
- **AAA reference:** AAA mine entrance (~50K tris).
- **Bug/Gap:** "Tilted post" for `abandoned` style at line 21574-21581 is a hand-built box that is supposed to be tilted but is actually axis-aligned (the "tilt" is just an X offset between bottom and top quads — produces a slight parallelogram, not a true lean angle). Cart wheels are tiny cylinders, not the wagon-wheel mesh. Tracks are infinite thin boxes.
- **Severity:** important.
- **Upgrade to A:** Use proper rotation matrix for tilted post; reuse wagon_wheel for cart wheels.

### 293. `generate_sewer_tunnel_mesh` (line 21610) — Grade: **B+**
- **Claims:** Brick-lined sewer tunnel with water + walkway.
- **Produces:** Walls + ceiling + floor + water channel + walkways + drains + pipe outlets.
- **AAA reference:** AAA sewer (Half-Life Alyx ~80K tris per section).
- **Bug/Gap:** Ceiling is FLAT slab not arched (acknowledged in comment line 21637 "arched approximation -- flat slab"). Stalactites use NEGATIVE height parameter `_make_tapered_cylinder(...,-0.3,...)` (line 21711) — `_make_tapered_cylinder` doesn't formally support negative height; result is undefined behavior depending on segment math.
- **Severity:** important — negative height is a latent bug.
- **Upgrade to A:** Real arch ceiling; flip stalactite construction with positive height + Y inversion.

### 294. `generate_catacomb_mesh` (line 21754) — Grade: **B**
- **Claims:** Corridor with burial niches.
- **Produces:** Walls + ceiling + floor + style-specific niches/sarcophagi/skulls.
- **AAA reference:** AAA catacomb.
- **Bug/Gap:** Niche "recess" boxes are placed at `sx * (hw + wall_thick * 0.3)` which puts them OUTSIDE the wall (they protrude from the wall surface, not recess into it). Skulls inherit issues.
- **Severity:** important — niches protrude.
- **Upgrade to A:** Boolean-cut niches.

### 295. `generate_temple_mesh` (line 21860) — Grade: **B+**
- **Claims:** Large temple with nave, columns, altar.
- **Produces:** Floor + walls + columns + roof + altar (gothic); stylobate + columns + entablature + pediment + altar (ancient); broken walls + columns + rubble (ruined).
- **AAA reference:** AAA temple level (~100K+ tris per chunk).
- **Bug/Gap:** Roof at line 21927 has a 4-vertex face `(0, 3, 5, 2)` and `(1, 2, 5, 4)` that may be non-planar; pediment triangle at line 21992 has only 1 face — open from behind. Ancient pediment is a single triangle floating on the front of the entablature.
- **Severity:** important — pediment is one-sided / non-manifold.
- **Upgrade to A:** Extrude pediment into 3D triangular prism.

### 296. `generate_harbor_dock_mesh` (line 22054) — Grade: **B+**
- **Claims:** Extended dock complex with crane + warehouse.
- **Produces:** Pier + piles + finger berths + bollards + crane (A-frame) + warehouse (wooden); quay + bollards + crane base + warehouse (stone); reinforced quay + battlements + towers + chain anchors + military warehouse (fortified).
- **AAA reference:** AC4 harbor (~150K tris per dock).
- **Bug/Gap:** Crane "boom arm" is a single straight box (no truss structure). Pulley block is a 0.5m vertical box, not a pulley. A-frame legs are hand-built 8-vert boxes (line 22119-22128) with no diagonal cross-bracing.
- **Severity:** important.
- **Upgrade to A:** Add truss geometry; sculpt pulley.

---

## Cross-Generator Findings

1. **Universal: No PBR material binding.** Every `_make_result` call passes `category="..."` but never `material_slots=[...]`. Every mesh ships as a single grey lambert by default. Megascans assets ship with 4-channel PBR (BC, MR, N, AO). **Severity: blocker for AAA shipping.**

2. **Universal: No LOD chain.** Each generator returns ONE LOD0 mesh. No automatic decimation pass to LOD1/LOD2/LOD3. UE5 PCG default builds 4-LOD chain automatically. **Severity: blocker for streaming.**

3. **Universal: No collision proxy.** No simplified collision hull is generated. UE5 expects UCX_/UBX_/USP_ collision sub-meshes. **Severity: blocker for physics.**

4. **Universal: No tangent/normal export.** `_make_result` doesn't compute tangents — engines that need them for normal mapping (UE5, Unity) must recompute. **Severity: important.**

5. **Universal: Box-projection UVs only.** `_auto_generate_box_projection_uvs` uses ONE projection plane for the entire mesh — textures will smear on side faces. Real tri-planar requires per-face normal selection. **Severity: blocker for texturing.**

6. **Pervasive: Broken "axis-swap rotation" pattern.** The pattern `[(v[1], y_pos, v[2]) for v in xv]` and similar tuple permutations appear ~30 times throughout the file. Most are NOT proper rotations — they collapse one axis onto another. Generators using them: `generate_table_mesh`, `generate_prison_door_mesh`, `generate_chain_mesh`, `generate_candelabra_mesh`, `generate_torch_sconce_mesh`, `generate_hammer_mesh`, `generate_cart_mesh`, `generate_boat_mesh`, `generate_deer_mesh`, `generate_wolf_mesh`, `generate_fox_mesh`, `generate_bear_mesh`, `generate_horse_mesh`, `generate_dog_mesh`, `generate_iron_gate_mesh`, `generate_window_mesh`, `generate_railing_mesh`, `generate_ladder_mesh`, `generate_grinding_wheel_mesh`, `generate_hitching_post_mesh`, `generate_portcullis_mesh`, `generate_cage_mesh`, `generate_chandelier_mesh`, `generate_hanging_cage_mesh`, `generate_scaffolding_mesh`, `generate_drawbridge_mesh`, `generate_chain_mesh` (multiple chain consumers). **Severity: blocker — affects 30+ generators.**

7. **Pervasive: Cone apex pinching.** `_make_cone` creates a single shared apex vertex — every spike, fang, horn, claw, arrow head, candle flame, finial, crystal point, etc. inherits the smooth-shading pinch artifact. **Severity: important.**

8. **Pervasive: Sphere-collage anatomy.** Every animal/creature/skull is a snowman of spheres with cylinder limbs. None have continuous body topology. **Severity: blocker — does not pass even mid-tier mobile game standards.**

9. **Pervasive: Hand-built half-shells with degenerate caps.** `generate_mushroom_mesh` (shelf_fungus), `generate_chest_mesh` (lid end caps), `generate_boat_mesh` (hull bow/stern) all have manual face lists with off-by-one or non-planar issues. **Severity: important.**

10. **Pervasive: Hardcoded RNG seeds.** Many `import random as _rng; rng = _rng.Random(SOME_INT)` calls use fixed seeds (33, 42, 55, 66, 77, 99, 211, 313, 666, 1701, 9127). Two callers requesting the same generator get identical "random" geometry — no per-instance variation. **Severity: blocker for vegetation/scatter quality.** Examples: `generate_bookshelf_mesh` (42), `generate_tree_mesh` (none — but spheres are deterministic), `generate_pillar_mesh` (77), `generate_archway_mesh` (99), `generate_skull_pile_mesh` (666), `generate_grass_clump_mesh` (211), `generate_shrub_mesh` (313), `generate_ivy_mesh` (71), `generate_apple_mesh` (42), `generate_leather_mesh` (77), `generate_bone_shard_mesh` (55), `generate_ore_mesh` (seed map by style only).

11. **Pervasive: `_enhance_mesh_detail` is largely a no-op.** Default `min_vertex_count=500` (or 100 in the helper signature) is met by most generators before the function fires — so the "supporting edge loop" promise is rarely delivered. **Severity: important — function exists but doesn't help.**

12. **Pervasive: `_merge_meshes` doesn't weld duplicate verts.** Multi-part meshes carry 30-50% redundant vertices. **Severity: important — bloats GPU memory.**

13. **Pervasive: Hardcoded scales.** Many functions accept no size parameter and bake dimensions like `radius * 0.06`, `0.02 * sc`, `0.04 * size` into geometry. This works for one player scale but breaks composition. **Severity: polish.**

14. **Pervasive: No second UV channel for lightmaps.** Static meshes need a non-overlapping lightmap UV. None is emitted. **Severity: blocker for baked lighting.**

15. **Pervasive: No vertex color channel.** Many engines use vertex color for AO/wear masks. None emitted. **Severity: important.**

---

## NEW BUGS FOUND (BUG-60 onward to avoid clashing with A1/A2/A3/G2)

- **BUG-60 — `_make_beveled_box` non-manifold corners** (line 588). 8 corner triangle fans are missing where 3 bevel quads meet; produces small triangular holes at every cube corner. Affects every prop using beveled boxes (most of the file). Severity: blocker.

- **BUG-61 — `generate_chain_mesh` links don't interlock** (line 3105). Both branches generate identical XZ-plane torus; the "axis swap" `(v[2], v[1], v[0])` is a reflection, not a 90° rotation around Y. Severity: blocker for chains/flails/gibbets/shackles/drawbridges/hanging cages.

- **BUG-62 — `generate_prison_door_mesh` horizontal cross bars are zero-length** (line 2578). The vertex transform `(v[1] - y_pos + (-inner_w / 2), y_pos, v[2])` clamps Y to constant and collapses the cylinder. Severity: blocker.

- **BUG-63 — `_make_torus_ring` dead variables** (line 518-519). `_tcx`/`_tcz` computed but never used. Severity: polish.

- **BUG-64 — `_make_cone` apex pinching** (line 488). Single shared apex vertex creates a smooth-shading singularity. Affects every cone-using generator (~50 functions). Severity: important.

- **BUG-65 — `generate_skull_pile_mesh` eye sockets protrude outward** (line 3188). Eye spheres positioned at `fz + skull_r * 0.15` extend OUTSIDE the cranium. Severity: blocker.

- **BUG-66 — `generate_cart_mesh` axles are zero-length** (line 7590). Same Y/Z collapse pattern. Severity: blocker.

- **BUG-67 — `generate_boat_mesh` hulls have open tops + non-manifold tips** (line 7754). j=0 and j=segs at every cross-section collapse to the same point, creating non-manifold cones at bow and stern. Severity: blocker.

- **BUG-68 — `generate_table_mesh` dead rotation code** (lines 1184-1190). `_rotated_v_unused` and `_rotated_v` computed and discarded. Severity: polish.

- **BUG-69 — `generate_mushroom_mesh` shelf_fungus degenerate face** (line 2221). Rim face indexes `j+2` which on the last iteration equals `n_pts+1` (the bottom-fan center), producing a face that crosses the mesh. Severity: important.

- **BUG-70 — `generate_chest_mesh` lid end caps are concave N-gons** (line 1428). Triangulation produces visible artifacts. Severity: important.

- **BUG-71 — `generate_pillar_mesh` "broken" variant has no seed variation** (line 2867). `Random(77)` is fixed regardless of caller params. Severity: important.

- **BUG-72 — `generate_temple_mesh` ancient pediment is one-sided** (line 21992). Single triangle face, no back face. Severity: important.

- **BUG-73 — `generate_temple_mesh` gothic roof has potentially non-planar quads** (line 21927-21932). 4-vertex faces with 6-vertex topology may not be coplanar. Severity: important.

- **BUG-74 — `generate_iron_maiden_mesh` is just a sealed coffin box** (line 18460). No door split, no internal spike volume. Severity: blocker.

- **BUG-75 — `generate_living_wood_shield_mesh` branches are perfectly straight** (line 14081). Function name promises living organic wood; output is a disc with straight cylinder spokes. Severity: blocker.

- **BUG-76 — `generate_dripping_water_mesh` is a stalactite, not water** (line 19106). Severity: blocker (false advertising).

- **BUG-77 — `generate_cobweb_mesh` has no sheet polygon** (line 18810). Severity: blocker (renders as wireframe grate).

- **BUG-78 — `generate_bola_mesh` rope segments are stretched boxes** (line 5660). Severity: blocker.

- **BUG-79 — `generate_torch_sconce_mesh` torch shaft floats** (line 2502). Positioned at `cz=0.12` independent of arm/cup geometry. Severity: important.

- **BUG-80 — `generate_candelabra_mesh` arms are vertical cylinders ringed around shaft** (line 1606). They don't reach outward like real candelabra arms. Severity: blocker.

- **BUG-81 — `generate_root_mesh` cylinders are all Y-axis aligned** (line 2263). Result: ring of vertical posts, not splayed roots. Severity: important.

- **BUG-82 — `generate_sarcophagus_mesh` mirror seam at x=0** (line 2622). Co-planar overlapping faces cause z-fighting. Severity: important.

- **BUG-83 — `generate_altar_mesh` "blood channel" is RAISED, not recessed** (line 2684). Inverted geometry. Severity: important.

- **BUG-84 — `generate_archway_mesh` pointed arch uses linear interpolation, not arcs** (line 2954-2968). Visible incorrect curve. Severity: important.

- **BUG-85 — `generate_catacomb_mesh` niches PROTRUDE from walls** (line 21800). Positioned outside the wall plane. Severity: important.

- **BUG-86 — `generate_sewer_tunnel_mesh` stalactites use negative height** (line 21711). `_make_tapered_cylinder(..., -0.3, ...)` is undefined behavior. Severity: important.

- **BUG-87 — `generate_apple_mesh` "bitten" bite is an additive sphere** (line 15946). It bumps OUT instead of subtracting from the apple. Severity: important.

- **BUG-88 — `generate_deer_mesh` body uses non-orthogonal shear instead of rotation** (line 19536). Affects also wolf, fox, bear, horse, dog, cat, rabbit (all use the same template). Severity: important — bodies are geometrically distorted.

- **BUG-89 — `generate_fox_mesh` snout is sheared cone** (line 19790). Severity: important.

- **BUG-90 — `generate_fish_mesh` body uses double vertex transform** (line 16025-16026). Fragile; sequence of squash + axis swap produces brittle orientation. Severity: important.

- **BUG-91 — `generate_wagon_wheel_mesh` has dead `_make_cylinder` call** (line 7980-7981). Spoke cylinder created and discarded. Severity: polish.

- **BUG-92 — `generate_mine_entrance_mesh` "tilted post" isn't actually tilted** (line 21574-21581). Hand-built box with bottom/top X offset is a parallelogram, not a tilted post. Severity: important.

- **BUG-93 — `_make_lathe` produces degenerate triangles when r=0 in profile** (line 1029). Many potion/bottle profiles start with `(0.001, 0)` or `(0, 0)`, creating thin triangles at the pole. Severity: polish.

- **BUG-94 — `_get_trig_table` cache too small** (line 118). LRU=32 evicts when many distinct segment counts are used. Severity: polish.

- **BUG-95 — `_auto_detect_sharp_edges` over-sharps boundary edges** (line 186). Open shells (shields, banners) get faceted boundaries. Severity: important.

- **BUG-96 — `_auto_generate_box_projection_uvs` uses single projection plane** (line 220). Smears textures on side faces. Severity: blocker for texturing.

- **BUG-97 — `_merge_meshes` doesn't weld coincident verts** (line 853). 30-50% redundant vertices on multi-part meshes. Severity: important.

- **BUG-98 — `_enhance_mesh_detail` defaults skip most generators** (line 695). `min_vertex_count=100` is met by most base meshes; the function rarely fires. Severity: important.

- **BUG-99 — `_make_beveled_box` returns no UVs** (line 588). Caller relies on auto-UV which uses single-plane projection. Severity: important.

- **BUG-100 — `generate_cheese_mesh` wedge uses non-standard quad face winding** (line 15858). Face `(0, 1, 4, 3)` may flip-normal in some engines. Severity: polish.

---

## Verdict
The procedural mesh library is a coherent **blockout asset generator** in the spirit of UE5 PCG defaults BEFORE artists pass over them. It is internally consistent, parameter-respecting at the silhouette level, and produces dozens of categories of recognizable shapes from a small set of primitive operations.

It is **NOT a Megascans/SpeedTree-class library**. Compared to AAA targets:
- No PBR materials → grey lambert only.
- No LOD chains → cannot stream.
- No collision proxies → cannot physics.
- No proper UVs → cannot texture without smearing.
- No tangents/normals → cannot normal-map.
- No vertex colors → no AO/wear masks.
- No second UV → no baked lighting.
- No hair/feather/leaf cards → all "vegetation" is opaque sphere/cone.
- 30+ generators have geometrically broken rotation operations.
- Animals/creatures are sphere-collages, not anatomically continuous.
- "Variety" relies on hardcoded RNG seeds → identical outputs.

Net composite grade: **B-**. Suitable for greybox prototyping; would be rejected at any AAA studio's pre-alpha asset review.

To reach **A** (UE5 PCG default ship quality) would require:
1. Replace primitive composition with proper sculpt-and-bake pipeline OR (more realistic for procedural) integrate Houdini Engine / OpenSubdiv.
2. Add PBR material slot system to MeshSpec.
3. Generate 4-LOD chain via decimation.
4. Generate UCX collision proxies.
5. Implement true tri-planar UV projection.
6. Fix all 30+ axis-swap rotation bugs.
7. Replace hardcoded RNG seeds with caller-passed `seed` parameter.
8. Replace cone-apex pinching with split-apex topology.
9. Replace sphere-collage anatomy with proper sculpted base meshes per creature.
10. Add hair-card / leaf-card / feather-card systems for vegetation and animals.

Reaching **A+** (Megascans/SpeedTree) is out of scope for a pure-Python procedural library — it requires real asset-pipeline tooling (Houdini, ZBrush, Substance, Marvelous Designer).
