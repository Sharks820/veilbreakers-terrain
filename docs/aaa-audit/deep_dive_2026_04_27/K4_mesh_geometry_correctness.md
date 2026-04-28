# K4 — Mesh Geometry Correctness Audit

**Date:** 2026-04-27
**Auditor:** K4 (Opus deep-dive, 1M context)
**Scope:** correctness of emitted overhang / cave / bridge / cliff mesh geometry,
LOD wiring, normal computation, Blender 4.5 impact.
**Source root:** `veilbreakers_terrain/handlers/`

---

## Summary

Six P0 findings, three P1 findings, two P2 findings.

| ID       | Severity | Title                                                                                  |
|----------|---------:|----------------------------------------------------------------------------------------|
| K4-P0-1  | **P0**   | `pass_emit_overhang_meshes` is a dead-end cache — output channel has no consumer       |
| K4-P0-2  | **P0**   | Cliff "overhang" quad is a flat horizontal shelf at lip elevation, not an overhang     |
| K4-P0-3  | **P0**   | Single one-sided quad — non-watertight, invisible under backface culling               |
| K4-P0-4  | **P0**   | Outward normal axis-quantised to `(0,1)` or `(1,0)` — wrong direction for many cliffs  |
| K4-P0-5  | **P0**   | Unity export `_zup_to_unity_vector` does Y/Z swap with NO winding reversal             |
| K4-P0-6  | **P0**   | Cave overhang box: top + bottom + front + left faces have flipped winding              |
| K4-P1-1  | P1       | No LOD chain wired for any emitted cliff/cave/bridge mesh                              |
| K4-P1-2  | P1       | `_create_bridge_object_from_spec` skips `recalc_face_normals` (no winding fix-up)      |
| K4-P1-3  | P1       | Cave mouth surround ring has UV-seam discontinuity at θ wrap                           |
| K4-P2-1  | P2       | Custom split normals on cave wall mesh silently broken in Blender 4.5                  |
| K4-P2-2  | P2       | Cave overhang face-zero comment says "visible underside" but normal points outward     |

J6's "billboard LOD3 NotImplementedError latent crash" claim is not reproducible
in the current tree — `vegetation_lsystem.generate_billboard_impostor` exists
(`vegetation_lsystem.py:1615`) so the `ImportError` fallback at
`lod_pipeline.py:1901-1906` never fires. The deprecation-warning shim does fire,
but issuing a `DeprecationWarning` is not a crash. The function name
`_install_billboard_lod3` referenced in J6 does not exist; the actual function
is `_setup_billboard_lod` (`lod_pipeline.py:1847`).

---

## K4-P0-1 — `pass_emit_overhang_meshes` writes to a channel nothing reads

**Files:** `veilbreakers_terrain/handlers/terrain_cliffs.py:1763-1795`

The pass concatenates `stack["cliff_mesh_specs"]` and `stack["cave_mesh_specs"]`
and stores the union under a tile-keyed token in
`state.mesh_layer_specs[overhang_mesh_layer:<tx>:<ty>:<n>]`.

```python
layer_token = f"overhang_mesh_layer:{state.tile_x}:{state.tile_y}:{len(all_specs)}"
cache = dict(getattr(state, "mesh_layer_specs", {}))
cache[layer_token] = all_specs
state.mesh_layer_specs = cache  # type: ignore[attr-defined]
```

Grepping the entire repo for `mesh_layer_specs` and `overhang_mesh_layer`
returns **only the writer above and one test assertion**
(`tests/test_terrain_cliffs.py:387`). No consumer reads this attribute or the
`overhang_mesh_layer:*` token.

The actual Unity export (`terrain_unity_export._supplemental_mesh_specs_json`,
line 475) reads the upstream channels directly:

```python
for raw_spec in list(stack.cliff_mesh_specs or []) + list(stack.cave_mesh_specs or []):
    ...
```

bypassing the pass output entirely. `pass_emit_overhang_meshes` is a no-op
beyond emitting metrics. This is one of the eight passes that runs in
production — production runs a pass that has zero downstream effect.

**Why P0:** the entire `emit_overhang_meshes` pipeline phase produces nothing
that any downstream stage uses. Future work touching the channel will silently
fail because nothing is wired to it. The contract is unenforced — refactoring
`cliff_mesh_specs` to remove the `cliff_overhang` mesh_type would break Unity
export with no test signal.

**Fix sketch:** delete the pass (it is a phantom) OR wire
`_supplemental_mesh_specs_json` to consume `mesh_layer_specs` instead of the
upstream channels, and gate the consumer behind the layer-token format.

---

## K4-P0-2 — "Overhang" is geometrically a horizontal shelf at lip elevation

**File:** `veilbreakers_terrain/handlers/terrain_cliffs.py:1741-1759`

The cliff overhang mesh spec emits a quad with these vertices:

```python
"vertices": [
    (base_l_x, base_l_y, base_l_z),                                          # v0
    (base_r_x, base_r_y, base_r_z),                                          # v1
    (base_r_x + out_nx * depth_m, base_r_y + out_ny * depth_m, base_r_z),    # v2
    (base_l_x + out_nx * depth_m, base_l_y + out_ny * depth_m, base_l_z),    # v3
],
"faces": [(0, 1, 2, 3)],
```

`base_l_z = base_r_z = height_arr[lip_cell]` (the lip elevation). The two tip
vertices (v2, v3) reuse the same z values as the base verts. The quad is
therefore **horizontal at z = lip elevation**, not a roof under which the
player can stand.

A real overhang has a vertical (or near-vertical) front face whose top is at the
lip elevation and whose bottom is below (creating sheltered space). The current
geometry is the lip itself extruded outward — it is the **lip cap**, not an
overhang.

The driving comment at `_generate_cliff_overhang` claims "35% of cliff lip
segments receive a small outward protrusion (0.3–1.2 m) in the top 20% of the
face height" — but the top-20% logic only gates which lip segments produce a
spec; the geometry once emitted is flat at the lip itself.

**Why P0:** ships as production-active geometry. Players cannot walk under
these "overhangs" — the silhouette break advertised by the design intent is
absent, and the wet-cliff drip-edge material logic that downstream water passes
attach to `drip_edge_indices = (2, 3)` is attached to vertices that are at the
lip elevation, so drip foam will appear on top of the cliff rather than dripping
off the underside.

**Fix sketch:** drop `base_l_z` / `base_r_z` for the tip vertices by 0.3 m or
emit an L-shaped 6-vert spec (lip face + roof face + drip edge) so the overhang
has both a vertical front and a horizontal soffit.

---

## K4-P0-3 — Single quad is non-watertight and one-sided

**File:** `veilbreakers_terrain/handlers/terrain_cliffs.py:1741-1759`

Even granting that K4-P0-2 might be fixed by lowering tips, the quad has only
one face — `(0, 1, 2, 3)`. With outward = (0, 1) and base_l on the left,
base_r on the right, base_l_z == base_r_z == z0:

- `v1 - v0 = (xR - xL, 0, 0)`
- `v3 - v0 = (0, depth, 0)` (after K4-P0-2 fix)
- cross = `(0, 0, (xR - xL) * depth)` → normal +Z (pure up)

So the only visible side is from above. From below (where players would stand
under a real overhang) Unity backface-culls the face and the overhang
disappears. There is no second face on the underside, no side wall, no back
seam to the cliff. The quad is also non-watertight: if it were merged into the
terrain mesh the outward edge would be a non-manifold boundary edge that
Hou/Unity importers flag.

**Why P0:** the emitted geometry, even after fixing winding/orientation, will
visually pop under any camera with backface culling enabled (the default for
Unity StandardLit / HDRP/Lit). Stylised dual-sided shaders are not part of the
emitted material hint (`wet_cliff_drip` — assumed single-sided).

**Fix sketch:** emit a thin slab (8 verts, 6 faces) instead of a single quad.

---

## K4-P0-4 — Outward normal is hard-quantised to a world axis

**File:** `veilbreakers_terrain/handlers/terrain_cliffs.py:1578-1589`

```python
if cliff_profile.world_bounds is not None:
    ...
    if wx >= wy:
        out_nx, out_ny = 0.0, 1.0   # protrude in +Y
    else:
        out_nx, out_ny = 1.0, 0.0   # protrude in +X
else:
    out_nx, out_ny = 0.0, 1.0
```

The "outward" face direction is not derived from the actual lip-polyline
tangent normal. Instead, every cliff in the entire scene gets its overhangs
projected in **either +X or +Y world-axis-aligned**. A cliff facing -Y (south)
will have its overhang protruding into the cliff face itself — the quad will
appear behind / inside the cliff wall rather than out into the open air. Same
for any cliff facing -X.

The lip polyline is available (and the wall-mesh builder at
`_build_cliff_wall_mesh_spec` line 1836 uses arc tangents correctly). A correct
outward normal would be `(-tangent_y, tangent_x, 0)` per lip segment, possibly
sign-flipped using the local mass centroid. The current axis-quantised choice
is wrong for at least 50% of cliffs.

**Why P0:** ships in production; produces visibly broken geometry on roughly
half the cliffs in the game (any cliff whose face normal has a negative X or Y
component).

**Fix sketch:** compute per-segment outward normal from `lip_polyline` tangent
and a sign decision based on the local `face_mask` neighborhood (which side of
the lip is open air vs. mass).

---

## K4-P0-5 — Unity Z-up→Y-up swap inverts winding without reversing face indices

**File:** `veilbreakers_terrain/handlers/terrain_unity_export.py:1024-1026, 475-503`

```python
def _zup_to_unity_vector(vec):
    x, y, z = (float(vec[0]), float(vec[1]), float(vec[2]))
    return [x, z, y]
```

Blender uses a right-handed coordinate system (X right, Y forward, Z up).
Unity uses a left-handed coordinate system (X right, Y up, Z forward). The
mapping `(x, y, z) → (x, z, y)` correctly relabels axes by purpose, **but** the
RH→LH transition without negating one axis (or reversing face winding)
**inverts the face orientation of every emitted polygon**.

The face emission at lines 498-501 preserves indices verbatim:

```python
faces.append({"indices": [int(idx) for idx in face]})
```

So a Blender face with indices `(0, 1, 2, 3)` and CCW winding (normal +Z up)
becomes a Unity face with the same indices. Under Unity's LH convention, the
same index sequence in the relabelled coordinates yields the opposite face
orientation. Result: **every cliff and cave mesh exported through this path
has its winding inverted** — the face normals point inward, surfaces appear
backwards under backface culling.

The roundtrip test at `tests/test_terrain_unity_export_bridge.py:301-353`
asserts vertex coordinates and UV values but never validates winding parity,
so this is uncovered.

The standard fixes are either:
- Negate one of the swapped axes: `return [x, z, -y]` (or `[-x, z, y]`), or
- Reverse the face index list: `faces.append({"indices": list(reversed([...]))})`.

The current export does neither.

**Why P0:** every cliff overhang mesh, every cave entrance, every cave mouth
surround that lands in `supplemental_mesh_specs.json` and gets imported into
Unity will appear inside-out. This is the only emission path for these meshes
into Unity (the JSON descriptor is the only mesh-spec channel).

**Fix sketch:** add `face_indices = list(reversed(face_indices))` in the loop
at line 498, and document the convention in the export schema. Also reverse
UV index association if it is positionally aligned.

---

## K4-P0-6 — Cave entrance overhang box: top + bottom + front + left faces flipped

**File:** `veilbreakers_terrain/handlers/terrain_caves.py:1217-1234`

The cave entrance overhang is built as an 8-vertex box with 6 quad faces.
Vertex positions:

```python
verts = [
    (x0 - hw, y0 + overhang_depth_m, arch_base_z),   # 0: front-BL
    (x0 + hw, y0 + overhang_depth_m, arch_base_z),   # 1: front-BR
    (x0 + hw, y0 + overhang_depth_m, arch_top_z),    # 2: front-TR
    (x0 - hw, y0 + overhang_depth_m, arch_top_z),    # 3: front-TL
    (x0 - hw, y0, arch_top_z),                        # 4: back-TL
    (x0 + hw, y0, arch_top_z),                        # 5: back-TR
    (x0 + hw, y0, arch_base_z),                       # 6: back-BR
    (x0 - hw, y0, arch_base_z),                       # 7: back-BL
]
faces = [
    (0, 1, 2, 3),   # front face — comment: "visible underside of overhang"
    (3, 2, 5, 4),   # top face
    (4, 5, 6, 7),   # back face (into cliff)
    (7, 6, 1, 0),   # bottom face
    (0, 3, 4, 7),   # left side
    (1, 6, 5, 2),   # right side
]
```

Computing per-face normals via `(v1 - v0) × (v2 - v0)`:

| Face        | Verts | Cross Z component | Inferred normal | Expected   | Status      |
|-------------|-------|-------------------|-----------------|------------|-------------|
| (0,1,2,3)   | front | n_y = -2hw·rock_h | -Y              | +Y         | **flipped** |
| (3,2,5,4)   | top   | n_z = -2hw·depth  | -Z              | +Z         | **flipped** |
| (4,5,6,7)   | back  | n_y = -2hw·rock_h | -Y              | -Y         | OK          |
| (7,6,1,0)   | bot   | n_z = +2hw·depth  | +Z              | -Z         | **flipped** |
| (0,3,4,7)   | left  | n_x = +depth·h    | +X              | -X         | **flipped** |
| (1,6,5,2)   | right | n_x = +depth·h    | +X              | +X         | OK          |

**Four of six faces** have inverted winding. Only the back face (into the
cliff, hidden from camera) and the right side are correct. With backface
culling on, the cave entrance overhang renders as a hollow shell — players see
the inside of the rock-mass box rather than its outer surfaces.

`mesh_from_spec` at `_mesh_bridge.py:1499` would fix this via
`bmesh.ops.recalc_face_normals(...)`, but the cave overhang spec **does not
flow through `mesh_from_spec`**. It is consumed only by
`_supplemental_mesh_specs_json` (Unity export) and by the deletion logic at
`terrain_caves.py:2774` (which checks mesh_type only). There is no Blender-side
materialisation path that calls `recalc_face_normals` on these specs.

**Why P0:** when `controller_apply_caves=True` (J2-gated, default off — but
this is the path the gate is meant to enable), every cave entrance overhang
produces an inside-out box. Combined with K4-P0-5 (Unity Y/Z swap also flipping
winding), four of the six faces double-invert (becoming correct in Unity by
accident) and the other two render inside-out. This is geometrically incorrect
in both engines.

**Fix sketch:** correct the face index orderings explicitly:

```python
faces = [
    (3, 2, 1, 0),   # front — flipped from (0,1,2,3)
    (4, 5, 2, 3),   # top
    (4, 5, 6, 7),   # back — already correct
    (0, 1, 6, 7),   # bottom
    (7, 4, 3, 0),   # left
    (1, 6, 5, 2),   # right
]
```

(or run the spec through `bmesh.ops.recalc_face_normals` before export).

---

## K4-P1-1 — No LOD chain wired for cliff/cave/bridge meshes

**Files searched:** `environment.py`, `_bridge_mesh.py`, `terrain_cliffs.py`,
`terrain_caves.py`, `lod_pipeline.py`.

`generate_lod_chain` and `_setup_billboard_lod` are only invoked from
`environment_scatter.py` (vegetation), `vegetation_system.py` (vegetation), and
internally inside `lod_pipeline.py`. **No call site for cliff overhangs, cave
overhangs, cave mouth surrounds, or terrain bridges**:

- `_create_bridge_object_from_spec` (`environment.py:5341`) creates the
  bridge mesh data with `from_pydata` and stops — no LOD child object, no
  custom property `lod_*`, no `lod_billboard_*` markers.
- The cliff/cave overhang specs go straight to JSON; Unity's LOD group setup
  cannot infer LOD structure from a single mesh.

For a 100-cliff scene, every cliff overhang renders at full poly count
regardless of distance. Same for caves and bridges. This is sub-AAA but does
not crash — flagged P1 because the LOD pipeline exists and is wired for
vegetation, so adding this is a small extension rather than a blocker.

**Fix sketch:** call `_setup_billboard_lod` (or a non-billboard variant of
`generate_lod_chain`) on each `_create_bridge_object_from_spec` /
`_create_mesh_object_from_spec` site for cliff/cave meshes. Or extend the
JSON spec to include LOD0/1/2/3 vertex/face arrays so Unity import can build
a LOD group.

---

## K4-P1-2 — Bridge object skips winding fix-up

**File:** `veilbreakers_terrain/handlers/environment.py:5341-5372`

```python
def _create_bridge_object_from_spec(spec, *, object_name, parent, material_key):
    mesh_data = bpy.data.meshes.new(object_name)
    mesh_data.from_pydata(spec.get("vertices", []), [], spec.get("faces", []))
    mesh_data.update()
    obj = bpy.data.objects.new(object_name, mesh_data)
    bpy.context.collection.objects.link(obj)
    ...
```

Unlike `_mesh_bridge.mesh_from_spec` which calls
`bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])`, the bridge creator
does not normalise winding. The bridge spec geometry is consistent (verified
by hand for `_oriented_box` and the swept deck/underside/edge faces in
`_bridge_mesh.py:350-356`), but if the centerline is degenerate or the swept
sweep produces zero-length normals at index 0, `_frame_at` falls back to
`tangent = (1.0, 0.0, 0.0)` and `normal = (0.0, 1.0, 0.0)` — leading to
T-junctions where flipped frames meet. Without `recalc_face_normals` these
remain in the output.

**Fix sketch:** mirror `_mesh_bridge.mesh_from_spec`'s bmesh path for bridges
(or call it directly with `mesh_from_spec(spec, name=object_name)`).

---

## K4-P1-3 — Cave mouth surround ring has UV-seam discontinuity

**File:** `veilbreakers_terrain/handlers/terrain_caves.py:1403-1438`

```python
for seg_i in range(n_segments):
    ...
    u = seg_i / float(n_segments)
    inner_verts.append((inner_x, inner_y, inner_z))
    outer_verts.append((outer_x, outer_y, outer_z))
    uvs_inner.append((u, 0.0))
    uvs_outer.append((u, 1.0))
```

For `n_segments = 12`, the u values are `0/12 .. 11/12`. The closure face at
`seg_i = 11` uses indices `(11, 0, 12, 23)` with UVs `(11/12, 0/12, 0/12, 11/12)`.
There is **no duplicate vertex with `u = 1.0`** — the UV mapping wraps from
`11/12` back to `0` instead of to `1`, producing a 1-segment-wide UV stretch on
the closure quad and a visible seam where the texture jumps mid-quad rather
than wrapping cleanly.

For tiling rock textures with horizontally repeating patterns this is
tolerable; for any non-repeating decal or normal-map detail it produces a
visible seam.

**Fix sketch:** duplicate the seg=0 vertices at u=1.0 (so the ring has
`n_segments + 1` inner and outer vertices with the last pair at u=1.0), and
emit `n_segments` quad faces using sequential indices (no modular wrap).

---

## K4-P2-1 — Custom split normals on cave wall silently broken in Blender 4.5

**File:** `veilbreakers_terrain/handlers/terrain_caves.py:4814-4823`

```python
if hasattr(mesh, "use_auto_smooth"):
    mesh.use_auto_smooth = True
custom_normals = []
for pi, poly in enumerate(mesh.polygons):
    fn = face_normals[pi] if pi < len(face_normals) else (0.0, 0.0, 1.0)
    for _ in poly.loop_indices:
        custom_normals.append(fn)
mesh.normals_split_custom_set(custom_normals)
```

In Blender 4.5, `Mesh.use_auto_smooth` was removed (replaced by the "Sharp
Edge" boolean attribute / Auto Smooth modifier system). The `hasattr` gate
silently skips the assignment — no crash. But `normals_split_custom_set` then
runs without auto-smooth being enabled. In 4.5, custom split normals require
the mesh to have appropriate sharp-edge attributes set; without them the
custom normals may be ignored or the visual result reverts to face-flat /
smooth-default.

This affects the cave-wall mesh emission (which actually renders inside caves
when controller_apply_caves=True). Already documented in H1 / Section 11; flagged
here to confirm this specific call site is impacted.

**Fix sketch:** in Blender 4.5, set sharp edges via the "sharp_edge" boolean
attribute on `mesh.attributes` and use the standard `normals_split_custom_set`
path — Blender 4.5 honours custom split normals when sharp-edge attribute is
set, without `use_auto_smooth`.

---

## K4-P2-2 — Cave overhang face-zero comment misleading

**File:** `veilbreakers_terrain/handlers/terrain_caves.py:1228`

```python
faces = [
    (0, 1, 2, 3),   # front face (visible underside of overhang)
    ...
]
```

The vertex layout puts vertices 0-3 at `y0 + overhang_depth_m` (i.e. on the
+Y side, which is "front" toward the player). This face is the **outward-facing
front of the rock mass**, not the underside. The visible underside of an arch
overhang is the bottom face (y=front to back at z=arch_base) — face index 3
`(7, 6, 1, 0)` in the original list. The comment misleads readers reviewing
the geometry, and is one reason K4-P0-6's flipped winding survived review.

---

## What works correctly (not findings, just verified)

1. The bridge `_oriented_box` quad windings (`_bridge_mesh.py:171-178`)
   produce consistent outward normals in Blender RH space (verified by hand
   for top/bottom).
2. The bridge swept-deck winding (`_bridge_mesh.py:350-356`) produces
   correct deck-up / underside-down normals.
3. `mesh_from_spec` (`_mesh_bridge.py:1497-1499`) calls
   `bmesh.ops.recalc_face_normals` so any spec routed through it self-heals
   inconsistent windings (this protects vegetation, props, and most
   `_create_mesh_object_from_spec` callers — but **not** bridge or cliff/cave
   exports).
4. `vegetation_lsystem.generate_billboard_impostor` exists; the LOD3 fallback
   `NotImplementedError` raised by the inner shim at `lod_pipeline.py:1903`
   is unreachable.
5. The `_supplemental_mesh_specs_json` JSON encoder correctly skips
   degenerate specs (`raw_vertices == [] or raw_faces == []`) and rejects
   3-tuple verts (`len(vec) < 3`).

---

## Cross-references

- J2-P0-1 (`controller_apply_caves` gate) — caves are gated off in production,
  but the geometry bugs above (K4-P0-6, K4-P2-1) become active production
  issues the moment the J2 gate is unblocked.
- H1 / Section 11 (Blender 4.5 regressions) — K4-P2-1 is the cave-specific
  expression of the use_auto_smooth removal documented there.
- A6_mesh_lod_export — K4-P1-1 (no LOD wiring for cliff/cave/bridge) overlaps
  with A6's LOD export gap; K4 confirms the gap on the source side.

---

## Recommended P0 fix order

1. **K4-P0-5** (Unity Y/Z swap winding) — global; affects every supplemental
   mesh emission. Single-line fix in `_supplemental_mesh_specs_json`.
2. **K4-P0-6** (cave overhang flipped faces) — corrects geometry the moment
   J2-P0-1 lands.
3. **K4-P0-2** + **K4-P0-3** (cliff overhang as flat shelf, single quad) —
   redesign the spec to a 6-vert L-shape with bottom and front faces.
4. **K4-P0-4** (axis-quantised outward normal) — replace world-axis snap
   with per-segment lip tangent.
5. **K4-P0-1** (dead-end pass) — last; either delete the pass or rewire the
   exporter to consume `mesh_layer_specs`.
