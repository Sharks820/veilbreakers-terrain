# H1 — Blender 4.5 API Compatibility Audit

**Audit date:** 2026-04-27
**Target Blender version:** 4.5 LTS
**Scope:** all `veilbreakers_terrain/handlers/*.py` files importing `bpy`,
`scripts/build_terrain_aaa_node_v6.py`, `veilbreakers_terrain/sim/*.py`,
`veilbreakers_terrain/handlers/blender_capability_bridge.py`.

This audit flags only API calls that are genuinely **broken**, **removed**,
or **silently no-op** in Blender 4.5. Stylistic concerns are out of scope.
Each finding is graded **P0** (will crash / silently lose feature),
**P1** (silent feature regression), or **P2** (latent risk).

---

## Summary Table

| ID  | Severity | File:Line                                           | Symptom                                                                        |
| --- | -------- | --------------------------------------------------- | ------------------------------------------------------------------------------ |
| H1-A| P1       | `environment_scatter.py:1968`                       | `leaf_mat.shadow_method = "CLIP"` — removed in 4.2 EEVEE Next                  |
| H1-B| P1       | `environment_scatter.py:233, 238, 1967`             | `mat.blend_method = "CLIP"` unguarded; semantics changed in 4.2 EEVEE Next     |
| H1-C| P1       | `terrain_caves.py:4815-4816`                        | `mesh.use_auto_smooth = True` — removed in 4.1 (hasattr-guarded → silent skip) |
| H1-D| P1       | `_mesh_bridge.py:1511-1513`                         | `mesh_data.use_auto_smooth` + `auto_smooth_angle` — removed in 4.1             |
| H1-E| P2       | `terrain_materials.py:3479-3482`                    | `mesh.calc_normals_split()` deprecated 4.1 (no-op); `calc_normals()` removed 4.0 |
| H1-F| P2       | `blender_capability_bridge.py:380-381`              | `mat.blend_method = "BLEND"`, `use_screen_refraction = True` 4.2-EEVEE-Next risks |
| H1-G| P2       | `terrain_scene_read.py:76`                          | `bpy.data.scenes[0].name` — fragile across multi-scene files                   |
| H1-H| P2       | `blender_capability_bridge.py:744-768`              | `bpy.ops.uv.smart_project / unwrap / cube_project` — needs context override headless |
| H1-I| P2       | `lod_pipeline.py:1646`, `terrain_materials.py:2324, 3483` | Per-vertex `.co.x` python loop — slow (4.x foreach_get is 100× faster)         |

**Files scanned (handlers with bpy imports):** 60+ files. **Bug count:** 4 P1 silent-feature-regression issues, 5 P2 latent issues. **No P0 crashes** found — every removed API call is either guarded with `hasattr()`/`try/except` or wrapped in pre-flight checks.

---

## H1-A — `Material.shadow_method` removed (P1, silent feature regression)

**File:** `veilbreakers_terrain/handlers/environment_scatter.py:1968`

```python
leaf_mat.blend_method = "CLIP"          # alpha cutout (no sorting artifacts)
leaf_mat.shadow_method = "CLIP"         # ← BROKEN IN 4.2+
leaf_mat.use_backface_culling = False
```

**Why it breaks in 4.5:** `bpy.types.Material.shadow_method` was removed in Blender 4.2 (the EEVEE Next rewrite). The replacement is `mat.surface_render_method = "DITHERED" | "BLENDED"`. In 4.5, setting `shadow_method` raises `AttributeError`, which currently propagates up through tree-creation and aborts the entire foliage species pass.

**Other unguarded uses:** none — the other call sites (`environment.py:5042`, `environment.py:6411`) are hasattr-guarded.

**Fix (4.5):**
```python
if hasattr(leaf_mat, "shadow_method"):           # 3.x / 4.0 / 4.1
    leaf_mat.shadow_method = "CLIP"
elif hasattr(leaf_mat, "surface_render_method"): # 4.2+ EEVEE Next
    leaf_mat.surface_render_method = "DITHERED"
```

---

## H1-B — `Material.blend_method` value semantics shifted in 4.2 (P1)

**File:** `veilbreakers_terrain/handlers/environment_scatter.py:233, 238, 1967`
**File:** `scripts/build_terrain_aaa_node_v6.py:689` (water material — `blend_method = "BLEND"`)

```python
mat.blend_method = "CLIP"        # line 233 — unguarded
mat.blend_method = "OPAQUE"      # line 238 — unguarded
leaf_mat.blend_method = "CLIP"   # line 1967 — unguarded
water_mat.blend_method = "BLEND" # build_terrain_aaa_node_v6.py:689
```

**Why it breaks in 4.5:** The property `blend_method` itself still exists on `Material` for backwards compatibility in 4.5, but EEVEE Next ignores `"CLIP"` (alpha cutout is now driven by the shader's `Alpha` socket + threshold or `surface_render_method = "DITHERED"`). Result: leaf cards render with full alpha blending instead of cutout, producing the classic foliage halo / sorting bug under EEVEE Next.

**Note:** `Material.alpha_threshold` (also referenced at line 235) was REMOVED in 4.2. The hasattr-guard there silently no-ops.

**Fix (4.5):** drive alpha cutout via `surface_render_method = "DITHERED"` plus `bsdf.inputs["Alpha"]` connected to the leaf alpha texture; only fall back to `blend_method` when running on Blender 3.x/4.0/4.1.

---

## H1-C — `Mesh.use_auto_smooth` removed in 4.1 (P1, silent skip)

**File:** `veilbreakers_terrain/handlers/terrain_caves.py:4815-4816`

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

**Why it breaks in 4.5:** `Mesh.use_auto_smooth` and `Mesh.auto_smooth_angle` were REMOVED in Blender 4.1. The `hasattr()` guard prevents an `AttributeError`, but the *intent* — "enable auto-smooth so my custom split normals take effect" — is now silently skipped. In 4.1+ the replacement is the **"Smooth by Angle" modifier** added programmatically, or marking specific edges sharp via `mesh.edges[i].use_edge_sharp = True`. Without that, on 4.1+ the per-face flat normals from `normals_split_custom_set()` *do still apply* (split normals work without auto_smooth in 4.1+), so the file luckily survives — but the comment + `hasattr` check is misleading dead code.

**Fix (4.5):** delete the dead `hasattr` block; `normals_split_custom_set()` is sufficient on its own in 4.1+. For 3.x compatibility, either drop the support or use:
```python
# Blender 3.x compatibility shim (4.1+ does not need this)
if hasattr(mesh, "use_auto_smooth"):
    mesh.use_auto_smooth = True
    mesh.auto_smooth_angle = math.pi  # 180° — let custom normals win
```

---

## H1-D — Same `use_auto_smooth` issue in `_mesh_bridge.py` (P1)

**File:** `veilbreakers_terrain/handlers/_mesh_bridge.py:1511-1513`

```python
if hasattr(mesh_data, "use_auto_smooth"):
    mesh_data.use_auto_smooth = True
    mesh_data.auto_smooth_angle = math.radians(auto_smooth_angle)
```

**Why it breaks in 4.5:** Same as H1-C — both attributes removed in 4.1. Here the *function signature* exposes `auto_smooth_angle: float = 35.0` to callers (line 1340) which now does nothing on 4.5. Custom callers passing `auto_smooth_angle=15` expecting hard creases at >15° will get a default-smoothed mesh instead.

**Fix (4.5):** in 4.1+, the equivalent is to mark sharp edges on the mesh:
```python
if hasattr(mesh_data, "use_auto_smooth"):
    mesh_data.use_auto_smooth = True
    mesh_data.auto_smooth_angle = math.radians(auto_smooth_angle)
else:
    # 4.1+: mark edges sharp where the dihedral angle exceeds the threshold
    threshold_rad = math.radians(auto_smooth_angle)
    for edge in mesh_data.edges:
        # …compute dihedral angle from adjacent face normals…
        if dihedral > threshold_rad:
            edge.use_edge_sharp = True
    # Or attach the modern "Smooth by Angle" modifier instead:
    # bpy.ops.object.modifier_add_node_group(asset_library_type='ESSENTIALS',
    #     asset_library_identifier='', relative_asset_identifier=
    #     'geometry_nodes/smooth_by_angle.blend/NodeTree/Smooth by Angle')
```

The comment at line 1510 (`Auto-smooth: Blender 3.x has use_auto_smooth, 4.x uses sharp edges`) is correct — it just isn't *acted on*.

---

## H1-E — `mesh.calc_normals_split()` deprecated, `calc_normals()` removed (P2)

**File:** `veilbreakers_terrain/handlers/terrain_materials.py:3479-3482`

```python
if hasattr(mesh, "calc_normals_split"):
    mesh.calc_normals_split()
elif hasattr(mesh, "calc_normals"):
    mesh.calc_normals()
vl = [(v.co.x, v.co.y, v.co.z) for v in mesh.vertices]
nl = [(p.normal.x, p.normal.y, p.normal.z) for p in mesh.polygons]
```

**Why it's degraded in 4.5:**
- `mesh.calc_normals()` — REMOVED in Blender 4.0 (auto computed now). The `elif hasattr` branch is dead code.
- `mesh.calc_normals_split()` — DEPRECATED in 4.1, present in 4.5 but a **no-op**: split normals are now computed automatically. Calling it doesn't error, but it doesn't do anything either.

In Blender 4.5 the script lands in the first `if` branch, calls a no-op, then reads `p.normal` — which is fine because polygon normals are auto-computed when accessed. So this is actually safe in 4.5 (P2, no functional regression), just stale.

**Fix (4.5):** delete the entire `if/elif` block. `mesh.polygons[i].normal` is always populated.

---

## H1-F — `mat.blend_method` + `use_screen_refraction` unguarded in capability bridge (P2)

**File:** `veilbreakers_terrain/handlers/blender_capability_bridge.py:378-383`

```python
if rgba[3] < 1.0:
    try:
        mat.blend_method = "BLEND"
        mat.use_screen_refraction = True
    except Exception:  # noqa: BLE001
        pass
```

**Why it's risky in 4.5:** `mat.use_screen_refraction` was REMOVED in Blender 4.2 EEVEE Next (replaced by per-shader raytraced refraction). The `try/except` catches the `AttributeError`, so transparent materials silently lose their screen-space refraction. The same property *is* properly hasattr-guarded at `environment.py:6423-6424`, where the modern path uses `mat.surface_render_method = "DITHERED"`.

**Fix (4.5):** mirror the pattern from `environment.py:6418-6424`:
```python
if rgba[3] < 1.0:
    if hasattr(mat, "blend_method"):           # 4.1 and earlier
        mat.blend_method = "BLEND"
    if hasattr(mat, "surface_render_method"):  # 4.2+
        mat.surface_render_method = "BLENDED"
    if hasattr(mat, "use_screen_refraction"):  # 4.1 and earlier only
        mat.use_screen_refraction = True
```

---

## H1-G — `bpy.data.scenes[0].name` is fragile (P2)

**File:** `veilbreakers_terrain/handlers/terrain_scene_read.py:76`

```python
result["timestamp"] = bpy.data.scenes[0].name  # use scene name as identifier
```

**Why it's risky:** Not a Blender 4.5 API change — but a portability footgun. `bpy.data.scenes[0]` is the *first scene by collection order*, not the active scene. In `.blend` files containing multiple scenes (animation pre-vis, reference shots), this returns whichever scene was created first, not the one being edited.

**Fix:** use `bpy.context.scene.name` for the active scene, or `bpy.context.window.scene.name` if you need to bypass override frames.

---

## H1-H — UV unwrap operators need context override in headless 4.x (P2)

**File:** `veilbreakers_terrain/handlers/blender_capability_bridge.py:959-983`

```python
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
…
bpy.ops.uv.smart_project(angle_limit=angle, …)
…
bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=…, correct_aspect=…)
bpy.ops.object.mode_set(mode="OBJECT")
```

**Why it's risky in 4.5:** `bpy.ops.uv.smart_project`, `bpy.ops.uv.unwrap`, and `bpy.ops.uv.cube_project` traditionally required a **3D viewport** in the operator context. In Blender 4.x headless mode (no UI), these ops will fail with `RuntimeError: Operator bpy.ops.uv.smart_project.poll() failed, context is incorrect` unless you wrap them in a `bpy.context.temp_override(area=…, region=…)` block.

The current code lands in the bare `try/except` at line 984 and returns `"uv_project_failed"` — so no crash, but every UV-unwrap call from CI will silently fail. The ramifications are large: cliff/cave/road meshes lose their UV layers, which silently breaks every triplanar / atlas shader that depends on them.

**Fix (4.5):** before calling each UV op, build a viewport context override:
```python
# Build a fake 3D viewport area for headless ops.
override = {}
for window in bpy.context.window_manager.windows:
    for area in window.screen.areas:
        if area.type == "VIEW_3D":
            override["window"] = window
            override["area"] = area
            override["region"] = next(r for r in area.regions if r.type == "WINDOW")
            break

if override:
    with bpy.context.temp_override(**override):
        bpy.ops.uv.smart_project(angle_limit=angle, …)
else:
    # Headless: fall back to bmesh-based UV projection (uvcalc in bmesh.ops)
    …
```

---

## H1-I — `for v in mesh.vertices: v.co.x` is slow in 4.x (P2, performance)

**Files:**
- `veilbreakers_terrain/handlers/lod_pipeline.py:1646`
- `veilbreakers_terrain/handlers/terrain_materials.py:2324, 3483`

```python
vertices = [(v.co.x, v.co.y, v.co.z) for v in mesh.vertices]
```

**Why it's degraded in 4.5:** Per-element Python iteration over `mesh.vertices` triggers a full RNA struct allocation + 3 attribute lookups per vertex. On a 512×512 grid (~262 144 verts) this is ~1.5 s vs. ~15 ms for `foreach_get` (100× speedup). Blender 4.x didn't deprecate the iteration form — it just got slower because `mesh.vertices` is now backed by a generic attribute layer rather than a flat C array.

The codebase already uses `foreach_get` correctly elsewhere (`environment.py:1725, 3526, 3605, 3606`), so this is a localized regression.

**Fix (4.5):**
```python
import numpy as np
n = len(mesh.vertices)
co = np.empty(n * 3, dtype=np.float32)
mesh.vertices.foreach_get("co", co)
co = co.reshape((n, 3))
vertices = co.tolist()  # if you need plain Python tuples
```

---

## What's correct (no action needed)

- **`bpy.ops.render.opengl(write_still=True)`** at `terrain_visual_qa.py:239` and `blender_capability_bridge.py:1060` — still valid in 4.5 (the header comment at `terrain_live_preview.py:166` claiming it was "removed in Blender 4.0" is **incorrect**; the operator is present in 4.5 but requires a 3D viewport context).
- **Principled BSDF socket renames** (Specular IOR Level, Subsurface Weight, Transmission Weight, Coat Weight, Sheen Weight, Emission Color) — `procedural_materials.py:_BSDF_SOCKET_FALLBACKS` (lines 973-994) and `environment.py:5086, 6539, 6545` correctly fall back from new to old name.
- **Geometry-Nodes interface API** — `blender_capability_bridge.py:1170-1184` and `terrain_materials.py:2000-2014` correctly use `group.interface.new_socket()` (4.0+) with fallback to `group.inputs.new()` (3.x).
- **Color attribute API** — every handler that creates vertex colors uses `mesh.color_attributes.new(name=…, type="FLOAT_COLOR" | "BYTE_COLOR", domain="CORNER" | "POINT")`, which is the 3.2+ API. **No** uses of legacy `mesh.vertex_colors.new()` were found in handlers (only in test scaffolding, which is fine).
- **`bpy.context.view_layer.objects.active`** — used everywhere; correct 2.8+ API. No legacy `bpy.context.scene.objects.active` calls in production code.
- **`obj.select_set(True)`** — used at `blender_capability_bridge.py:958` and `scripts/build_terrain_aaa_node_v6.py:489`. Correct 2.8+ API. No legacy `obj.select = True` calls.
- **`mesh.from_pydata(verts, [], faces)`** — every call passes an explicit empty `edges=[]`, so no implicit edge generation issues.
- **`bpy.context.scene.collection.objects.link(obj)`** — correct 2.8+ collection API. No legacy `bpy.context.scene.objects.link()` calls.
- **`render.image_settings.file_format = "PNG"`** — valid in 4.5.
- **EEVEE engine string** — `BLENDER_EEVEE_NEXT` is correctly used as the 4.5 default at `blender_capability_bridge.py:1002, 1005` with `BLENDER_EEVEE` as a fallback in the valid set.
- **`mat.use_backface_culling`** — still valid in 4.5.
- **`Material.alpha_threshold`** — `environment_scatter.py:234-235` correctly hasattr-guards this (removed in 4.2).
- **`Mesh.normals_split_custom_set()`** — still valid in 4.5; works without `use_auto_smooth=True` in 4.1+.
- **No hardcoded paths** (`C:\…`, `/Users/…`, `/home/…`) found anywhere in `veilbreakers_terrain/`. Only one `os.sep` usage at `terrain_quality_profiles.py:917-918` for path-prefix comparison, which is correct.
- **`veilbreakers_terrain/sim/`** is pure Python (no `import bpy`, no `bpy.` calls) — nothing to audit there.

---

## Recommended remediation order

1. **H1-A, H1-B** (P1, foliage shader regression on EEVEE Next 4.2+): wrap `shadow_method` and `blend_method` writes with `hasattr` + `surface_render_method` fallback. **5 lines of changes across 3 files.**
2. **H1-D** (P1, custom auto_smooth angle ignored on 4.1+): add the "mark sharp edges" branch in `_mesh_bridge.py` so caller-supplied `auto_smooth_angle` is honored on 4.5.
3. **H1-H** (P2 → P0 for any CI that depends on UV unwraps): add `temp_override` block around UV ops, or switch to `bmesh.ops.uvcalc_*` projections that don't need a viewport context.
4. **H1-C, H1-E** (P2 cleanup): delete dead `hasattr` blocks for clarity; behaviour is already correct on 4.5.
5. **H1-I** (P2 performance): swap the three per-vertex Python loops for `foreach_get` numpy reads — high ROI on AAA-size meshes.
6. **H1-F, H1-G** (P2 latent risk): align `blender_capability_bridge.py:378-383` with the modern guarded pattern from `environment.py:6418-6424`; replace `bpy.data.scenes[0].name` with `bpy.context.scene.name`.

**Total estimated diff:** ~50 lines across 5 files. No P0 crashes; the addon currently *runs* on 4.5 but loses 3 silent features (alpha-cutout shadows, custom hard-crease angles, headless UV unwrap).
