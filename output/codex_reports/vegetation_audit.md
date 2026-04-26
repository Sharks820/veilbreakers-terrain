# VeilBreakers Vegetation & Foliage Deep-Dive Audit
**Date:** 2026-04-24  
**Auditor:** Claude (Sonnet 4.6)  
**AAA Benchmark:** Ghost of Tsushima grass system, Horizon Forbidden West foliage density + wind  
**Scope:** build_scene_v3.py + all handler-layer vegetation systems  

---

## Executive Summary

The project has **two completely separate vegetation codebases** that do not talk to each other:

1. **Scene layer** (`scripts/build_scene_v3.py`): A hand-rolled Blender script that actually runs, produces the 180 trees + 18 000 grass-blade hair-particle scene described in BUILD_SUMMARY.json. This is what the player sees in renders today.

2. **Handler/system layer** (`vegetation_system.py`, `terrain_foliage_catalog.py`, `environment_scatter.py`, `vegetation_lsystem.py`, `terrain_vegetation_depth.py`): A sophisticated, catalog-driven, biome-aware scatter pipeline registered in `COMMAND_HANDLERS`. It is **never called by build_scene_v3.py** and has no path to the rendered scene.

The scene layer is the auditable ground truth for what was actually rendered. The handler layer is a large body of unreachable code from the perspective of the live scene. Both are audited below.

---

## A. GRASS SYSTEM

### What runs in the scene (build_scene_v3.py lines 965–1039)

**Species count: 1**  
One mesh, one material. Three crossed-quad blade groups share identical geometry (3 quads crossing at 0°/60°/-60°). All 18 000 hair-particle instances use the same `VB_GrassBlade` object. This produces a mathematically uniform grass carpet. At GoT level, there are 4–6 distinct blade species with different silhouettes, curl, and colour variation.

**Placement: hair particle system, vertex-group gated**  
- Vertex group `GrassDensity` restricts emission to verts with `LAKE_WATER_LEVEL + 1.5 < z < 52.0` and outside the lake radius. This is correct altitude gating.  
- Hair particle system emission is **uniform random across the weighted vertex group**, not blue-noise Poisson. The `_scatter_engine.poisson_disk_sample` is never called for grass in the scene build.  
- No grid jitter parameter exists in the particle system code — Blender hair particles are inherently random per-face, not structured grid, so this item is acceptable.

**Scale variation:**  
`settings.size_random = 0.35` at a base `settings.particle_size = 0.65`. This means blades vary from approximately 0.42× to 0.88× of the base — a 0.42–0.88 range. The target is 0.75–1.4×. The range is too narrow at the low end (blades can disappear to 42% size) and the maximum is below the target floor of 1.0×. The blades are all uniformly short; no lush tall clumps exist.

**Rotation:**  
`settings.rotation_mode = "NOR"` with `settings.phase_factor_random = 1.0` provides full random yaw. `settings.rotation_factor_random = 0.06` provides only ±3.4° lean — far below the target ±8–15° for natural grass. Blades stand nearly perfectly upright.

**Wind deformation: ABSENT**  
No wind modifier, no shader-driven UV animation, no shape key animation, no vertex color wind channel on the grass mesh. The 18 000 blades are completely static. GoT has per-blade real-time wind deformation driven by a dynamic Perlin-noise velocity field. This is the single biggest visual gap in the grass system.

**Alpine/lowland differentiation: NONE in scene**  
The vertex group gates on `z < 52.0` — one elevation band, one species. No alpine sparse tuft species at high altitude, no lush meadow differentiation near the lake. Both areas use the same blade.

**Grass material:**  
Single Principled BSDF at `(0.08, 0.15, 0.05)` with roughness 0.80. No subsurface scattering (GoT and HFW use SSS weight ~0.1 on grass for backlit translucency). No alpha clip — the blades use opaque faces, so at oblique view angles they look like solid rectangles, not thin blades.

### Handler-layer grass (terrain_foliage_catalog.py)

The catalog defines 4 grass species: `grass_tall`, `grass_short`, `grass_dry`, `grass_lush`. These exist only as `SpeciesSpec` metadata records. No Blender mesh is generated for any of them — `requires_retired_model_provider_asset` is False (implying a procedural mesh exists), but `VEGETATION_GENERATOR_MAP` does not contain any grass entry referencing these species. They fall through to `_fallback_grass` which is a trivially small stub. None are called by the scene build at all.

### Grade: **D**

**Ghost of Tsushima comparison:** GoT has minimum 4 grass species with distinct silhouettes, density fields per biome, real-time animated wind using a GPU velocity-field texture, subsurface transmission material, and blade-lean variation of ±12°. This scene has 1 static, opaque, uniform species with 3.4° lean and no wind. It looks like a flat carpet at any distance above 2m.

### Missing feature code

**1. Wind modifier (most critical — immediate visual impact)**

Add after particle system setup in `add_grass()` (build_scene_v3.py line 1039):

```python
# Wind deformation via Force Field — animates hair particles in render
wind_obj = bpy.data.objects.new("VB_WindField", bpy.data.lattices.new("_tmp"))
bpy.context.collection.objects.link(wind_obj)
bpy.ops.object.select_all(action='DESELECT')
wind_obj.select_set(True)
bpy.context.view_layer.objects.active = wind_obj
bpy.ops.object.effector_add(type='WIND', location=(0, 0, 50))
wind = bpy.context.active_object
wind.name = "VB_WindEffect"
wind.field.strength = 0.4
wind.field.noise = 0.8
wind.field.seed = SEED & 0xFFFF
# Animate wind direction over 120 frames for render
wind.rotation_euler[2] = 0.0
wind.keyframe_insert(data_path="rotation_euler", frame=1)
wind.rotation_euler[2] = math.radians(15)
wind.keyframe_insert(data_path="rotation_euler", frame=120)
```

**2. Second grass species — lush lowland near water**

Insert before existing `add_grass()` calls in `main()` (build_scene_v3.py line 1309):

```python
def make_lush_blade_mesh():
    """Wide, curling lush blade for lake/river margins."""
    gbm = bmesh.new()
    blade_h = 0.65
    blade_w = 0.10
    # Wider, taller, with midpoint lean to simulate curl
    for ang in (0.0, math.pi / 4.0, -math.pi / 4.0, math.pi / 2.0):
        s, c = math.sin(ang), math.cos(ang)
        lean = 0.18  # midpoint offset for natural droop
        v0 = gbm.verts.new((-s * blade_w, -c * blade_w, 0.0))
        v1 = gbm.verts.new((s * blade_w, c * blade_w, 0.0))
        v2 = gbm.verts.new((s * blade_w * 0.55 + lean * s, c * blade_w * 0.55 + lean * c, blade_h * 0.55))
        v3 = gbm.verts.new((-s * blade_w * 0.55 + lean * s, -c * blade_w * 0.55 + lean * c, blade_h * 0.55))
        v4 = gbm.verts.new((s * blade_w * 0.15 + lean * 2 * s, c * blade_w * 0.15 + lean * 2 * c, blade_h))
        v5 = gbm.verts.new((-s * blade_w * 0.15 + lean * 2 * s, -c * blade_w * 0.15 + lean * 2 * c, blade_h))
        gbm.faces.new((v0, v1, v2, v3))
        gbm.faces.new((v3, v2, v4, v5))
    gmesh = bpy.data.meshes.new("VB_LushBlade")
    gbm.to_mesh(gmesh)
    gbm.free()
    lmat = bpy.data.materials.new("VB_LushGrassMat")
    lmat.use_nodes = True
    nt = lmat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.06, 0.18, 0.06, 1)
    bsdf.inputs["Roughness"].default_value = 0.72
    try:
        bsdf.inputs["Subsurface Weight"].default_value = 0.10  # backlit translucency
    except KeyError:
        pass
    lmat.blend_method = "CLIP"
    lmat.alpha_threshold = 0.5
    gmesh.materials.append(lmat)
    return gmesh
```

Then add a second particle system restricted to a `LushGrassDensity` vertex group targeting `z < 20.0` within `LAKE_RADIUS * 1.6` of the lake. Use `count = 8000`, `particle_size = 0.90`, `size_random = 0.45`.

**3. Fix scale and lean parameters**

Replace lines 1015–1021 of build_scene_v3.py:

```python
settings.particle_size = 0.75       # base height matches AAA floor
settings.size_random = 0.55         # results in 0.75×(1 ± 0.55) ≈ 0.34–1.16 range
settings.use_rotations = True
settings.rotation_mode = "NOR"
settings.phase_factor_random = 1.0
settings.rotation_factor_random = 0.18   # ±10° lean — within 8-15° target
```

**4. Alpha-clip material for blades**

Add after `gmesh.materials.append(gmat)` at build_scene_v3.py line 988:

```python
gmat.blend_method = "CLIP"
gmat.alpha_threshold = 0.5
gmat.shadow_method = "CLIP"
try:
    gmat.node_tree.nodes["Principled BSDF"].inputs["Subsurface Weight"].default_value = 0.10
except KeyError:
    pass
```

---

## B. TREE SYSTEM

### What runs in the scene (build_scene_v3.py lines 733–905)

**Species count: 2 — INSUFFICIENT**  
`make_pine_mesh()` (line 755) and `make_broad_tree_mesh()` (line 800). Both are stacked-cone silhouettes built from `bmesh.ops.create_cone` calls. No snag/dead tree, no alpine sparse pine, no blighted or corrupted variant. The minimum for dark fantasy AAA is 4–6 distinct tree species. Two is grassland-filler territory.

**Species selection (scatter_trees, line 845):**  
```python
use_pine = (wz > 55.0) or (norm.z < 0.78) or (RNG.random() < 0.35)
```
Pines appear at altitude > 55 m, on slopes, or randomly 35% of the time. Broad-leaf trees appear at low flat areas. This is a rough biome split but produces a heavily pine-dominated scene (the OR logic means pines appear far more than 65% of the time).

**Scale variation:**  
`scale = RNG.uniform(1.5, 2.8)` applied uniformly to both species. Range is 1.87× (2.8/1.5). This is a scale variation, but it varies the whole tree uniformly, not independently per-axis. A 2.8m-scale pine and a 1.5m-scale pine use the same proportions — no tall-and-thin vs short-and-fat variation. The target of 0.75–1.4× is meant as instance variation relative to a canonical design scale. Using absolute units 1.5–2.8 loses all bark/foliage detail contrast.

**Rotation:**  
`RNG.uniform(-0.04, 0.04)` for X and Y tilt — that is ±2.3°. The target is ±8°. Trees stand near-perfectly upright, which is fine for healthy trees but wrong for alpine pines stressed by wind and slope load.

**LOD proxy at 200m: ABSENT**  
No LOD modifier, no billboard setup, no `settings.lod_group` assignment. All 180 trees render at full polygon count regardless of distance. For a 1024m tile this means trees 800m away render at the same mesh density as trees 5m away. This is a major performance failure — at full render it will become a bottleneck.

Note: `scatter_biome_vegetation` in vegetation_system.py calls `_setup_billboard_lod` from `lod_pipeline.py`. That pipeline exists and is wired. But `scatter_trees` in the scene build **does not call it at all**.

**Wind on branches: ABSENT from scene build**  
`compute_wind_vertex_colors` in `vegetation_system.py` bakes R=sway_strength, G=sway_frequency, B=phase_offset into vertex colors for Unity consumption. This is only called when `bake_wind_colors=True` is passed to `scatter_biome_vegetation`. In the Blender scene, no wind modifier is applied to tree instances. Trees are completely static.

**Foliage cards at far distance: ABSENT**  
The billboard impostor system exists in `vegetation_lsystem.generate_billboard_impostor()` and is referenced from `lod_pipeline._setup_billboard_lod()`. Neither is ever called in build_scene_v3.py.

### Grade: **D+**

**Ghost of Tsushima comparison:** GoT has ~8 tree species per biome, independently x/y/z scaled instances, physically-based branch wind with GPU vertex shader animation, billboard sprites beyond 150m, and per-cluster LOD density that reduces polygon count 40:1 at max view distance. This codebase has 2 static, non-LOD, non-wind cone-stack trees with sub-3° lean.

### Missing feature code

**1. Dead snag tree species (needed immediately)**

Add after `make_broad_tree_mesh()` in build_scene_v3.py (after line 842):

```python
def make_dead_snag_mesh() -> bpy.types.Mesh:
    """Dead tree: bare trunk + sparse broken branch stubs, no foliage."""
    bm = bmesh.new()
    trunk_h = 11.0
    # Slightly twisted trunk — more cross-sections at different angles
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=7,
                          radius1=0.55, radius2=0.08, depth=trunk_h)
    for v in bm.verts:
        v.co.z += trunk_h / 2.0
        # Slight twist
        angle = v.co.z / trunk_h * math.radians(25)
        x, y = v.co.x, v.co.y
        v.co.x = x * math.cos(angle) - y * math.sin(angle)
        v.co.y = x * math.sin(angle) + y * math.cos(angle)
    # 4 stub branches at varying heights, downward-angled
    for i in range(4):
        ht = trunk_h * (0.45 + i * 0.14)
        ang = i * math.pi / 2.0 + RNG.uniform(0, 0.6)
        bx = math.cos(ang) * 0.45
        by = math.sin(ang) * 0.45
        stub_bm = bmesh.new()
        bmesh.ops.create_cone(stub_bm, cap_ends=True, cap_tris=False, segments=6,
                              radius1=0.14, radius2=0.02, depth=1.8)
        for sv in stub_bm.verts:
            # Rotate stub to point outward and slightly downward
            sv.co.z += 0.9
            ox, oz = sv.co.x, sv.co.z
            sv.co.x = ox * math.cos(math.radians(-30)) - oz * math.sin(math.radians(-30))
            sv.co.z = ox * math.sin(math.radians(-30)) + oz * math.cos(math.radians(-30))
            sv.co.x += bx; sv.co.y += by; sv.co.z += ht
        tmp = bpy.data.meshes.new("_snag_stub")
        stub_bm.to_mesh(tmp)
        stub_bm.free()
        bm.from_mesh(tmp)
        bpy.data.meshes.remove(tmp)
    bm.normal_update()
    mesh = bpy.data.meshes.new("DeadSnagMesh")
    bm.to_mesh(mesh)
    bm.free()
    for p in mesh.polygons:
        p.use_smooth = True
    bark_dead = bpy.data.materials.new("DeadBark")
    bark_dead.use_nodes = True
    bark_dead.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.22, 0.18, 0.14, 1)
    bark_dead.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.96
    mesh.materials.append(bark_dead)
    return mesh
```

Then update `scatter_trees` to include the snag as a third species, placed at 8–12% of tree positions where `wz > 80.0` and `norm.z > 0.70` (dead trees prefer old-growth altitude, not cliffs):

```python
# In scatter_trees, inside the while loop, replace use_pine assignment:
dead_chance = 0.10 if wz > 80.0 else 0.04
use_dead = (RNG.random() < dead_chance) and dead_mesh is not None
use_pine = not use_dead and ((wz > 55.0) or (norm.z < 0.78) or (RNG.random() < 0.35))
mesh_to_use = dead_mesh if use_dead else (pine_mesh if use_pine else broad_mesh)
obj = bpy.data.objects.new(f"VB_Tree_{placed:03d}", mesh_to_use)
```

**2. LOD billboard setup — wire existing pipeline to scatter_trees**

Add at the end of `scatter_trees` (build_scene_v3.py around line 904), before the return:

```python
# Attach LOD distances as custom props — Unity importer reads these
# Full LOD mesh chain requires lod_pipeline.generate_lod_chain which needs
# bpy.ops context; use custom property tagging as a lightweight substitute
for obj in trees_col.objects:
    obj["lod0_distance"] = 0.0
    obj["lod1_distance"] = 60.0    # reduced mesh at 60m
    obj["lod2_distance"] = 150.0   # billboard at 150m
    obj["lod3_distance"] = 300.0   # cull at 300m
    obj["lod_enabled"] = True
```

For actual Blender LOD (viewport performance), add after object creation in the scatter loop:

```python
# Decimate modifier for LOD2 proxy — 40% poly reduction
if placed % 3 == 0:  # every 3rd tree gets a decimate for render variety
    dec = obj.modifiers.new("Decimate_LOD", type="DECIMATE")
    dec.ratio = 0.4
    dec.use_collapse_triangulate = True
```

**3. Per-axis scale variation (independent x/y/z)**

Replace `obj.scale = (scale, scale, scale)` in `scatter_trees` (line 896):

```python
scale_base = RNG.uniform(1.5, 2.8)
scale_x = scale_base * RNG.uniform(0.88, 1.12)  # ±12% width variation
scale_y = scale_base * RNG.uniform(0.88, 1.12)
scale_z = scale_base * RNG.uniform(0.92, 1.18)  # slightly taller range
obj.scale = (scale_x, scale_y, scale_z)
```

**4. Increase trunk lean to ±8°**

Replace rotation_euler assignment in `scatter_trees` (line 898):

```python
lean_max = 0.14  # ~8 degrees
# Alpine trees lean more into slope
altitude_lean = min(0.08, (wz - 55.0) / 1200.0) if wz > 55.0 else 0.0
obj.rotation_euler = (
    RNG.uniform(-lean_max - altitude_lean, lean_max + altitude_lean),
    RNG.uniform(-lean_max - altitude_lean, lean_max + altitude_lean),
    RNG.uniform(0, math.tau),
)
```

---

## C. SPECIES INVENTORY

### Target for dark fantasy AAA

| Species | Exists in scene? | Exists in handler catalog? | Wired to scene? |
|---|---|---|---|
| Dark conifer / spruce | YES (pine_mesh, stacked cones) | YES (tree_pine in FOLIAGE_SPECIES_CATALOG) | NO (catalog never reaches scene) |
| Alpine pine (sparse, wind-bent) | NO — same mesh used at all altitudes | YES (implied by tree_pine alt 200–2200m) | NO |
| Dead snag | NO | YES (tree_dead) | NO |
| Broadleaf / oak | YES (broad_tree_mesh, wide cones) | YES (tree_oak, tree_birch) | NO |
| Tall grass | YES (1 species in particle system) | YES (grass_tall, grass_short, grass_dry, grass_lush — 4 variants) | NO |
| Shrubs | NO | YES (bush_berry, bush_thorn, bush_ornamental) | NO |
| Undergrowth / ferns | NO | YES (ferns in accent_foliage) | NO |
| Mushrooms | NO | YES (mushrooms in accent_foliage) | NO |
| Moss | NO | YES (moss_rock, moss_log, moss_tree_base) | NO |
| Fallen logs | NO | YES (log_fallen, log_rotted) | NO |
| Stumps | NO | YES (stump_old, stump_fresh_cut) | NO |
| Vines | NO | YES (vine_hanging, vine_climbing) | NO |
| Water foliage (reeds, lily pads) | NO | YES (reeds, lily_pad, algae, submerged_grass) | NO |

**Summary:** The handler catalog (`terrain_foliage_catalog.py`) has complete, well-designed coverage of 14 categories. The scene build uses **2 of ~35 species** from that catalog. The disconnect is a structural gap, not missing knowledge. The catalog quality is B+ on its own merits. The scene quality is D because nothing from the catalog reaches it.

---

## D. BIOME-AWARE DENSITY

### Scene build (build_scene_v3.py)

**Slope masking — PARTIAL:**  
Trees: `norm.z < 0.52` rejects cliff faces (>58° slope). This correctly blocks tree placement on cliff walls.  
Grass: vertex group uses pure altitude (`z < 52.0`) without any slope check. Grass **will appear on steep cliff faces** as long as they are below 52m elevation. On the 80–120m cliff band (y≈0–30), there are faces at low z values that will be grass-covered. This is visually wrong — no real grass grows on vertical rock.

**Snowline / high-altitude filtering:**  
Trees: `wz > 230.0` blocks trees above 230m. With a 320m peak this provides a treeline, but 230m is relatively low — alpine sparse pines would typically survive to ~270m. More critically, there is no material change at the snowline (no snow-dusted rocks, no bare stone treatment). The filter is correct-ish but unsophisticated.  
Grass: maximum z for grass is `52.0m` — substantially below the treeline. No grass appears at high altitude, which is correct.

**Water proximity / denser near water:**  
Trees: `math.hypot(wx - LAKE_XY[0], wy - LAKE_XY[1]) < LAKE_RADIUS + 15.0` exclusion zone around lake. Trees cannot grow within 15m of the lake. This is correct.  
Grass: `math.hypot(wx - LAKE_XY[0], wy - LAKE_XY[1]) > LAKE_RADIUS + 48.0` means grass is excluded within 48m of the lake. This is **backwards** — lakeside areas in dark fantasy should have the densest, lushest grass. The 48m exclusion gap creates a visible bald ring around the lake.

**No grass on rock faces:**  
As noted above, the grass vertex group does not check slope. The fix:

```python
# In add_grass(), replace the grass_vi append block (lines 996-1004):
for vi in all_vi:
    v = mesh.vertices[vi]
    wz_v = v.co.z
    wx_v, wy_v = v.co.x, v.co.y
    vn = v.normal
    slope_ok = vn.z > 0.64  # blocks faces steeper than ~50 degrees
    if (LAKE_WATER_LEVEL + 1.5) < wz_v < 52.0 and slope_ok:
        if math.hypot(wx_v - LAKE_XY[0], wy_v - LAKE_XY[1]) > LAKE_RADIUS + 5.0:
            grass_vi.append(vi)
```

**Handler layer (vegetation_system.py):**  
`compute_vegetation_placement` correctly applies slope limits by category: trees < 45°, ground_cover < 55°, rocks < 75°. Water level is gated via `norm_h < water_level`. Altitude gating uses per-entry `min_altitude`/`max_altitude` fields. The handler layer does this correctly. It just never runs in the scene.

---

## E. WIRING GAPS

### Critical wiring failures

**1. Scene build never calls the handler layer.**  
`build_scene_v3.py` uses hand-rolled `make_pine_mesh()`, `scatter_trees()`, and `add_grass()`. `COMMAND_HANDLERS["scatter_biome_vegetation"]` is wired to `vegetation_system.scatter_biome_vegetation`, but no code in `build_scene_v3.py` or `main()` calls it. The 1 000+ lines of vegetation pipeline in `vegetation_system.py` produce zero output in the actual scene.

**2. Grass particle system misses slope mask (D.)**  
Already documented in Section D.

**3. Lush grass vertex group is too conservative.**  
The 48m lake exclusion in `add_grass()` (line 1001) should be 5m to place lush grass up to the waterline. The scene calls this function but the wrong radius means visible bald rings around all water bodies.

**4. Billboard impostor never attached.**  
`vegetation_lsystem.generate_billboard_impostor` is defined and exported. `lod_pipeline._setup_billboard_lod` is called from `scatter_biome_vegetation`. But `scatter_trees` in build_scene_v3.py has no LOD setup code. 180 trees get no billboard proxy.

**5. Wind vertex colors baked to zero.**  
`compute_wind_vertex_colors` is a pure function that returns correct sway data. In the handler path it is gated on `bake_wind_colors=True`. In the scene path it is never called. Unity will receive all-zero wind vertex colors on every tree instance, meaning tree wind shaders will be completely non-functional regardless of shader setup.

**6. Foliage catalog species constraints not consumed by scene scatter.**  
`SPECIES_CONSTRAINTS_FROM_CATALOG` in `terrain_foliage_catalog.py` is pre-computed and exported. `environment_scatter._scatter_pass` imports and uses it. `scatter_trees` in the scene does not import or use it — the catalog-defined altitude ranges for `tree_pine` (200–2200m), `tree_oak` (0–900m), and `tree_dead` (0–2000m) are ignored.

### Recommended wiring fix for build_scene_v3.py

The fastest path to correct wiring is to refactor `scatter_trees` to accept a species configuration list and drive mesh selection from it, matching the catalog's altitude bands:

```python
TREE_SPECIES_CONFIG = [
    # (mesh_factory, min_z, max_z, base_probability)
    ("pine",    55.0, 230.0, 0.55),
    ("broad",    2.0,  90.0, 0.35),
    ("snag",    80.0, 230.0, 0.10),
]

def scatter_trees_v2(terrain_obj, hm, species_meshes: dict, count=180):
    """species_meshes: {'pine': mesh, 'broad': mesh, 'snag': mesh}"""
    # ... same placement loop, replace use_pine logic with:
    eligible = [(k, p) for k, lo, hi, p in TREE_SPECIES_CONFIG
                if lo <= wz <= hi]
    if not eligible:
        continue
    total_p = sum(p for _, p in eligible)
    roll = RNG.random() * total_p
    cumulative = 0.0
    chosen_key = eligible[0][0]
    for k, p in eligible:
        cumulative += p
        if roll <= cumulative:
            chosen_key = k
            break
    obj = bpy.data.objects.new(f"VB_Tree_{placed:03d}", species_meshes[chosen_key])
```

---

## Summary Grades

| Section | Area | Grade | Primary Reason |
|---|---|---|---|
| A | Grass system (scene) | D | 1 species, no wind, wrong lean, wrong lake proximity, no slope mask |
| A | Grass catalog (handler) | B | 4 species defined, correct metadata, never called |
| B | Tree system (scene) | D+ | 2 species, no LOD, no wind, sub-3° lean, no snag |
| B | Tree catalog (handler) | B+ | oak/birch/pine/dead defined, LOD pipeline exists, never called by scene |
| C | Species inventory | D | 2/35 species reach the scene; catalog is comprehensive but disconnected |
| D | Biome density (scene) | D+ | Slope mask missing for grass; lake exclusion backwards; treeline correct |
| D | Biome density (handler) | B | vegetation_system correctly gates slope/altitude/moisture |
| E | Wiring | F | Scene build and handler layer are 100% disconnected; 6 confirmed wiring gaps |

**Overall vegetation grade: D+**

The codebase demonstrates significant planning and handler-layer investment. The gap between the handler layer (B quality) and the scene layer (D quality) is caused entirely by the scene build never calling the handler pipeline. Bridging this gap — specifically wiring `scatter_biome_vegetation` into `main()` and replacing the hand-rolled `scatter_trees`/`add_grass` with handler-layer calls — would move the scene from D to B without writing new logic.

The three immediate P0 fixes are:
1. Add slope mask to grass vertex group (build_scene_v3.py line 996–1004) — 10 lines
2. Fix lake exclusion radius from 48m to 5m (build_scene_v3.py line 1001) — 1 line  
3. Add wind force field to grass particle system (build_scene_v3.py after line 1039) — 12 lines

The P1 work is adding the dead snag species and wiring `bake_wind_colors=True` into the scatter path. Full AAA parity requires routing the scene through the handler layer's biome-aware pipeline.

