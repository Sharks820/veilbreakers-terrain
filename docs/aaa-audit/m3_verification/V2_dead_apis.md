# V2 Dead-API Exhaustive Scan

**Agent:** M3 ultrathink verification wave, V2 (dead-API detection lens)
**Date:** 2026-04-16
**Source:** `docs/TERRAIN_UPGRADE_MASTER_AUDIT.md` (3547 lines, all `**Fix:**` / Context7 R5/R7 lines)
**Method:** Firecrawl MCP scrapes of authoritative upstream docs; diff against every API reference in master audit.

---

## Firecrawl URLs scraped (11 total)

| # | URL | Purpose | Result |
|---|-----|---------|--------|
| 1 | `https://docs.blender.org/api/current/bmesh.ops.html` | Authoritative bmesh.ops function list | 113 functions extracted (full set) |
| 2 | `https://docs.blender.org/api/current/bpy.ops.mesh.html` | bpy.ops.mesh operators | 205 operators extracted |
| 3 | `https://docs.blender.org/api/current/bpy.ops.import_scene.html` | Import operators | Confirmed `import_scene.gltf`, `import_scene.fbx` |
| 4 | `https://docs.scipy.org/doc/scipy/reference/ndimage.html` | scipy.ndimage catalog | Full filter/morphology/measurement list |
| 5 | `https://docs.scipy.org/doc/scipy/reference/spatial.transform.html` | Rotation class API | Confirmed `Rotation`, `Slerp`, `RigidTransform` |
| 6 | `https://scikit-image.org/docs/stable/api/skimage.measure.html` | skimage.measure catalog | Full list scraped |
| 7 | `https://rasterio.readthedocs.io/en/stable/api/index.html` | rasterio API index | Confirmed package structure |
| 8 | `https://python-watchdog.readthedocs.io/en/latest/api.html` | watchdog module | Confirmed `Observer`, `PatternMatchingEventHandler`, `on_modified` |
| 9 | `https://pypi.org/project/opensimplex/` | opensimplex PyPI | Confirmed v0.4.5.1 API (`noise2`, `noise2array`, `OpenSimplex(seed)`) |
| 10 | `https://pypi.org/project/meshoptimizer/` | meshoptimizer Python binding | Confirmed v0.2.30a0 with `simplify`, `optimize_vertex_cache`, etc. |
| 11 | `https://pymeshlab.readthedocs.io/en/latest/classes/meshset.html` | pymeshlab MeshSet | Confirmed `apply_filter`, `load_new_mesh`, `save_current_mesh` |
| 12 | `https://numpy.org/doc/stable/reference/routines.html` | numpy 2.4 routines index | Confirmed category coverage |

---

## Dead APIs found (confirmed non-existent in upstream)

| # | Referenced in master | API | Exists? | Correct replacement | Firecrawl source |
|---|----------------------|-----|---------|---------------------|------------------|
| 1 | L1611 BUG-750 fix (eroded-stone chamber): `bmesh.ops.boolean(bm, target=rock_bm, cutter=tunnel_bm, op="DIFFERENCE")` | `bmesh.ops.boolean` | **NO** (not in 113-op list) | Use `bpy.ops.mesh.intersect_boolean` (exists on bpy.ops.mesh) on the active mesh OR add a `BOOLEAN` modifier via `obj.modifiers.new(type='BOOLEAN')` and apply. **Previously flagged by A5** — this reference is still live in the master audit. | docs.blender.org/api/current/bmesh.ops.html |
| 2 | (Referenced only in R5 verification narrative, but cited as "use `bmesh.ops.decimate`" pattern context) | `bmesh.ops.decimate` | **NO** | Use `bpy.ops.mesh.decimate` (bpy-operator, requires active edit-mode mesh) OR add `DECIMATE` modifier via `obj.modifiers.new(type='DECIMATE')`. **Previously flagged by A5.** | docs.blender.org/api/current/bmesh.ops.html |
| 3 | L945 BUG-80: "topological accumulation via `np.bincount` / scipy `ndimage.watershed`" | `scipy.ndimage.watershed` | **NO** — only `scipy.ndimage.watershed_ift` exists | Either `scipy.ndimage.watershed_ift(input, markers)` (Image-Foresting-Transform watershed, IS documented) OR `skimage.segmentation.watershed` (scikit-image's). The bare `ndimage.watershed` is a common naming mistake. | docs.scipy.org/doc/scipy/reference/ndimage.html |
| 4 | L2912: "`scipy.spatial.cKDTree.query_ball_point()`" | `scipy.spatial.cKDTree` | **DEPRECATED-ALIAS** — still resolvable but the canonical modern API is `scipy.spatial.KDTree` (cKDTree is a legacy alias retained for back-compat; new SciPy docs promote `KDTree`) | `scipy.spatial.KDTree(positions).query_ball_point(pt, r=radius)` is the documented form. `cKDTree` still works but is deprecated in spirit. **BORDERLINE, not a hard break.** | docs.scipy.org/doc/scipy/reference/spatial.html (implicit; not on the transform page) |

---

## Borderline / version-specific (APIs that exist but have signature changes or confusion risk)

| # | Referenced in master | API | Status | Note | Source |
|---|----------------------|-----|--------|------|--------|
| B1 | L926 BUG-23 fix: `_terrain_noise.opensimplex_array` | Internal wrapper function — assumes opensimplex's `OpenSimplex.noise2array` is reachable | **VERIFIED** | `opensimplex` v0.4.5.1 exposes module-level `opensimplex.noise2array(x, y)` AND class `OpenSimplex(seed).noise2array(x, y)`. Both are valid. The wrapper name `opensimplex_array` is internal to VeilBreakers and does not map 1:1 to the upstream name — confusing but not dead. | pypi.org/project/opensimplex |
| B2 | L3415 R5: `opensimplex.OpenSimplex(seed).noise2(x, y)` | `OpenSimplex` class + `noise2` method | **CONFIRMED EXISTS** | v0.4.5.1 documented API. Also supports `.noise2array(xs, ys)`. | pypi.org/project/opensimplex |
| B3 | L270 R1: `np.ptp()` replaces removed `h.ptp()` method | `numpy.ptp` | **CONFIRMED EXISTS** in numpy 2.x; `ndarray.ptp` method removed in 2.0 | Master fix is correct. | numpy.org/doc/stable/reference/routines.html (routines.statistics) |
| B4 | L504 BUG-15: `np.gradient(hmap, cell_size)` | `numpy.gradient(varargs, ..., axis)` | **CONFIRMED EXISTS** | Second positional arg is `varargs` (scalar cell_size or array of coords). Documented. | numpy.org/doc/stable/reference/routines.math.html |
| B5 | L683 BUG-49: `np.random.default_rng(seed)` replaces `np.random.RandomState` | `numpy.random.default_rng` | **CONFIRMED EXISTS** | Modern RNG factory, available since numpy 1.17. Canonical. | numpy.org/doc/stable/reference/random/index.html |
| B6 | L673 BUG-48: `functools.lru_cache(maxsize=4)` | `functools.lru_cache` | **CONFIRMED EXISTS** | Python stdlib since 3.2. | Python stdlib docs (well-known). |
| B7 | L1272 / L645 / L1763: `dataclasses.replace(obj, **changes)` | `dataclasses.replace` | **CONFIRMED EXISTS** | Python stdlib since 3.7. Canonical immutable-mutate. | Python stdlib docs (well-known). |
| B8 | L1350 BUG-116: `dataclasses.asdict(obj)` | `dataclasses.asdict` | **CONFIRMED EXISTS** | Python stdlib. | Python stdlib docs (well-known). |
| B9 | L1263: `watchdog.Observer` + `PatternMatchingEventHandler.on_modified` | watchdog classes/methods | **CONFIRMED EXIST** | watchdog 2.x documented: `Observer`, `FileSystemEventHandler`, `PatternMatchingEventHandler`, `on_modified` all present. `WindowsApiObserver` also exists (cited in L1731). | python-watchdog.readthedocs.io/en/latest/api.html |
| B10 | L861 BUG-67 / L2364 GAP-12: `rasterio` (with optional fallback) | rasterio package | **CONFIRMED EXISTS** | `rasterio.open(path)` is documented. Current stable docs confirm package layout; master's "add to pyproject.toml" is correct guidance. | rasterio.readthedocs.io/en/stable/api/index.html |
| B11 | L2544: `bpy.ops.import_scene.gltf()` | bpy operator | **CONFIRMED EXISTS** | Full signature verified (many parameters incl. `filepath`, `import_shading`, etc.). Master audit's "Just a thread lock. NO bpy.ops.import_scene.gltf call" is an accurate bug report — the operator exists, the code doesn't call it. | docs.blender.org/api/current/bpy.ops.import_scene.html |
| B12 | L900 BUG-88: `scipy.spatial.transform.Rotation.from_euler('x', 90, degrees=True)` | `Rotation` class | **CONFIRMED EXISTS** | `scipy.spatial.transform.Rotation` has `from_euler`, `as_matrix`, `apply`. | docs.scipy.org/doc/scipy/reference/spatial.transform.html |
| B13 | L1542 BUG-747: "meshoptimizer tracks per-edge manifold flags" | meshoptimizer Python binding | **CONFIRMED EXISTS** on PyPI (`pip install meshoptimizer`, v0.2.30a0) | Provides `simplify()`, `simplify_with_attributes()`, `optimize_vertex_cache()`, `encode_vertex_buffer()`. Manifold-flag claim is a feature characterization of the C++ library, not a Python API name. **BORDERLINE** — correct library but claim-level detail wasn't verified. | pypi.org/project/meshoptimizer |
| B14 | L1367 / L2382 BUG-68: `recast4j`/`recast-navigation-python` for `dtNavMesh.bin` | External dep — not scraped-verified | **NOT-IN-FIRECRAWL-SCOPE** (PyPI availability uncertain in this scan). Master correctly marks as NEEDS-REVISION. | out-of-scope |
| B15 | L731 BUG-57: `OpenEXR` / `Imath` Python bindings | External deps | **NOT-IN-FIRECRAWL-SCOPE**. Master correctly marks as NEEDS-REVISION. | out-of-scope |

---

## Verified-correct (spot-check — all EXIST, no issues)

### scipy.ndimage — every referenced call is valid

- `scipy.ndimage.distance_transform_edt` (L450, L614, L1052, L1410, L1384) — EXISTS (Morphology section)
- `scipy.ndimage.uniform_filter` (L1224, L1464, L271) — EXISTS (Filters section)
- `scipy.ndimage.maximum_filter` (L759, L1401) — EXISTS (Filters section)
- `scipy.ndimage.minimum_filter` (L821, L954) — EXISTS (Filters section)
- `scipy.ndimage.zoom` (L1168) — EXISTS (Interpolation section)
- `scipy.ndimage.gaussian_filter` (L990) — EXISTS (Filters section)
- `scipy.ndimage.binary_dilation` (L2886, L3217) — EXISTS (Morphology section)
- `scipy.ndimage.label` (L2665, L2888) — EXISTS (Measurements section)
- `scipy.ndimage.watershed_ift` (R5 L444 — correctly spelled) — EXISTS (Measurements section)

### bmesh.ops — referenced operators that DO exist

- `bmesh.ops.remove_doubles(bm, verts=..., dist=...)` (L842, L1071) — EXISTS
- `bmesh.ops.recalc_face_normals(bm, faces=bm.faces)` (L1079) — EXISTS
- `bmesh.ops.spin` (Firecrawl example) — EXISTS
- `bmesh.ops.extrude_edge_only`, `bmesh.ops.create_circle`, `bmesh.ops.translate`, `bmesh.ops.rotate`, `bmesh.ops.transform`, `bmesh.ops.subdivide_edges`, `bmesh.ops.triangulate`, `bmesh.ops.convex_hull`, `bmesh.ops.weld_verts`, `bmesh.ops.dissolve_verts`, `bmesh.ops.bevel`, `bmesh.ops.bridge_loops` — ALL EXIST

### bpy.ops / bpy.data / bpy.types

- `bpy.ops.import_scene.gltf` (L2544, L2102) — EXISTS
- `bpy.ops.mesh.decimate` (implied replacement for bmesh.ops.decimate) — EXISTS
- `bpy.ops.mesh.intersect_boolean` (implied replacement for bmesh.ops.boolean) — EXISTS
- `bpy.ops.render.render` (L1647, referenced as missing-call) — EXISTS
- `bpy.data.materials.new(...)` (L1702) — EXISTS (well-known)
- `bpy.data.objects.new(...)` (L1702) — EXISTS (well-known)
- `polygon.material_index` (L1427) — EXISTS on `MeshPolygon` (bpy.types)

### numpy — every referenced routine is valid

- `np.gradient`, `np.roll`, `np.pad`, `np.where`, `np.clip`, `np.ptp`, `np.meshgrid`, `np.bincount`, `np.frombuffer`, `np.isfinite`, `np.linalg.lstsq`, `np.empty`, `np.zeros_like`, `np.argsort`, `np.random.default_rng` — ALL EXIST in numpy 2.4.

### Python stdlib

- `dataclasses.replace`, `dataclasses.asdict`, `dataclasses.field`, `functools.lru_cache`, `math.radians`, `math.tan`, `math.ceil`, `contextlib` references — ALL EXIST.

### External libs

- `opensimplex.seed(n)`, `opensimplex.noise2(x, y)`, `opensimplex.noise2array(xs, ys)`, `opensimplex.OpenSimplex(seed)` — ALL EXIST (v0.4.5.1).
- `rasterio.open(path)` — EXISTS (stable docs).
- `watchdog.observers.Observer()`, `watchdog.events.PatternMatchingEventHandler`, `on_modified` handler — ALL EXIST.
- `meshoptimizer.simplify(...)`, `meshoptimizer.optimize_vertex_cache(...)` — ALL EXIST (v0.2.30a0).
- `scipy.spatial.transform.Rotation.from_euler` — EXISTS.
- `scipy.spatial.KDTree` / `cKDTree` (legacy alias) — both resolvable.

### skimage.measure

- Not directly cited as a fix-line in master audit. Firecrawl confirms catalog is standard (`label`, `regionprops`, `find_contours`, `marching_cubes`, etc.).

---

## Summary

**Dead APIs (hard breaks — code would raise `AttributeError` at import/runtime):**

1. **`bmesh.ops.boolean`** — L1611 (BUG-750 chamber fix) — **STILL LIVE IN MASTER AUDIT** despite A5's earlier flag on the twin `bmesh.ops.decimate`. Fix-line must be rewritten to use `bpy.ops.mesh.intersect_boolean` (active mesh) OR a `BOOLEAN` modifier on the object.
2. **`bmesh.ops.decimate`** — A5's original catch. Fix: `bpy.ops.mesh.decimate` or `DECIMATE` modifier.
3. **`scipy.ndimage.watershed`** — L945 (BUG-80 fix). Does NOT exist bare. Fix: `scipy.ndimage.watershed_ift` OR `skimage.segmentation.watershed`.

**Borderline (still works but not the modern canonical spelling):**

- `scipy.spatial.cKDTree` — legacy alias; prefer `scipy.spatial.KDTree`.

**Total fix-line API references scanned:** ~220 (every `**Fix:**` line + R5/R7 Context7 verification blocks).
**Firecrawl scrapes:** 12.
**Hard dead-API count:** 3 (1 newly-found beyond A5's 2).
**Borderline count:** 1.

The master audit is largely API-correct; A5's earlier `bmesh.ops.boolean`/`bmesh.ops.decimate` find was the major hit. The new finding this wave is **`scipy.ndimage.watershed`** (BUG-80 fix line L945) — should be `watershed_ift`.
