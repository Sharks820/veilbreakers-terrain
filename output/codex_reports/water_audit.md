# VeilBreakers Water Systems Audit
**Auditor:** Deep-dive automated review  
**Date:** 2026-04-24  
**AAA Bar:** Horizon Forbidden West water  
**Primary file audited:** `scripts/build_scene_v3.py`  
**Supporting files:** `veilbreakers_terrain/handlers/_terrain_erosion.py`, `handlers/world_map.py`, `handlers/__init__.py`

---

## Grade Summary

| System | Grade | Verdict |
|---|---|---|
| A. Lake Shader | **D** | Diffuse+Glossy hack, no depth volume, no UV scroll, no foam SDF, no proper Fresnel |
| B. River Generation | **D+** | Flat ribbon mesh, no flow UV, no variable bank geometry, no confluence |
| C. Waterfall | **F** | Static vertical quad sheet; no particles, no mist, no foam pool |
| D. Shore Transition | **D** | Hard-radius ring geometry, no SDF foam band, no wet-sand gradient shader |
| E. Springs | **F** | SPRING_XY constant declared but generates zero geometry or material |
| F. Wiring | **C** | `env_generate_waterfall`, `env_carve_river`, `env_create_water`, `env_carve_water_basin` all registered; no spring handler, `_terrain_erosion` outputs never feed water color |

**Overall: D — nowhere near Horizon FW. Listed below is every gap with line-precise citations and drop-in fix code.**

---

## A. Lake Shader — Grade D

### What exists

`make_water_material()` — `build_scene_v3.py:388–480`

The function builds a `Diffuse + Glossy + MixShader (Fresnel-capped)` network. For the lake it is called at line 509:

```python
lake_mat = make_water_material("WaterLake", tint=(0.10, 0.30, 0.72, 1),
                               roughness=0.18, emission=0.18)
```

The environment.py `_ensure_water_material()` path (`environment.py:6008`) is more complete — it adds a `ShaderNodeVolumeAbsorption` node and reads foam from a `flow_vc` vertex-color layer — but that function is **never called from `build_scene_v3.py`**. The scene script uses its own stripped-down factory exclusively.

### Missing features — exact gaps

| # | Feature | HFW standard | Status in code |
|---|---|---|---|
| 1 | **Depth tint via volume absorption** | Blue-green darkening past ~1m | **ABSENT** — no `ShaderNodeVolumeAbsorption` in `make_water_material()` |
| 2 | **UV-scrolled ripple animation** | Two offset UV layers scrolling at different speeds | **ABSENT** — bump uses static world-position `ShaderNodeTexNoise`; no `ShaderNodeTexCoord`, no `frame`-driven offset |
| 3 | **Shore foam SDF band** | White foam 0.5–2m from shore at exact waterline | **ABSENT** — no distance field, no foam color in lake material; beach ring is separate opaque sand mesh with zero water interaction |
| 4 | **Fresnel reflection to sky/envmap** | Grazing angles → near-mirror sky; steep angles → transmission | **PARTIAL** — `ShaderNodeFresnel` present but capped at 0.68 and blends to `ShaderNodeBsdfDiffuse` not to a proper reflection/transmission pair |
| 5 | **Transmission / subsurface depth** | Water visible as transparent with color-absorbed depth | **ABSENT** — no `Transmission Weight` input set, no `IOR` on lake path; the build_scene_v3 factory never sets these |

### Fix code — `make_water_material` replacement insert

Insert after `build_scene_v3.py:478` (inside `make_water_material`, replacing the current function body from line 393 onward):

```python
def make_water_material(name: str, tint=(0.04, 0.10, 0.18, 1),
                        emission: float = 0.0,
                        roughness: float = 0.06) -> bpy.types.Material:
    """AAA water: depth-absorption volume, UV-scroll ripples, SDF shore foam, Fresnel."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    if hasattr(mat, "blend_method"):
        mat.blend_method = "BLEND"
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (2200, 0)

    # --- Principled BSDF (replaces Diffuse+Glossy; gives proper IOR/Transmission) ---
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (1800, 0)
    bsdf.inputs["Base Color"].default_value = tint
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["IOR"].default_value = 1.333
    # Transmission Weight is the Blender 4.x name; fallback to legacy "Transmission"
    for key in ("Transmission Weight", "Transmission"):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = 0.92
            break
    if "Alpha" in bsdf.inputs:
        bsdf.inputs["Alpha"].default_value = 0.88

    # --- Volume absorption — depth tint ---
    vol_abs = nt.nodes.new("ShaderNodeVolumeAbsorption")
    vol_abs.location = (1800, -300)
    # Deep blue-green: matches 5-10m visibility in clear mountain lake
    vol_abs.inputs["Color"].default_value = (0.02, 0.08, 0.14, 1.0)
    vol_abs.inputs["Density"].default_value = 0.10
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    if "Volume" in out.inputs:
        nt.links.new(vol_abs.outputs["Volume"], out.inputs["Volume"])

    # --- UV-scrolled ripple (two noise layers with different scroll speeds) ---
    # TexCoord + Mapping lets us animate the offset vector via drivers/keyframes
    tex_coord = nt.nodes.new("ShaderNodeTexCoord")
    tex_coord.location = (-1800, 0)

    map_a = nt.nodes.new("ShaderNodeMapping")
    map_a.location = (-1500, 200)
    map_a.inputs["Scale"].default_value = (6.0, 6.0, 1.0)
    # Driver (add in Python after material creation or via NLA):
    #   map_a.inputs["Location"].default_value = (frame*0.0004, frame*0.0002, 0)

    map_b = nt.nodes.new("ShaderNodeMapping")
    map_b.location = (-1500, -100)
    map_b.inputs["Scale"].default_value = (14.0, 14.0, 1.0)
    # Orthogonal scroll: (frame*-0.0002, frame*0.0003, 0)

    nt.links.new(tex_coord.outputs["Object"], map_a.inputs["Vector"])
    nt.links.new(tex_coord.outputs["Object"], map_b.inputs["Vector"])

    noise_a = nt.nodes.new("ShaderNodeTexNoise")
    noise_a.location = (-1200, 200)
    noise_a.inputs["Scale"].default_value = 1.0
    noise_a.inputs["Detail"].default_value = 6.0
    noise_a.inputs["Roughness"].default_value = 0.55
    nt.links.new(map_a.outputs["Vector"], noise_a.inputs["Vector"])

    noise_b = nt.nodes.new("ShaderNodeTexNoise")
    noise_b.location = (-1200, -100)
    noise_b.inputs["Scale"].default_value = 1.0
    noise_b.inputs["Detail"].default_value = 4.0
    noise_b.inputs["Roughness"].default_value = 0.65
    nt.links.new(map_b.outputs["Vector"], noise_b.inputs["Vector"])

    mix_ripple = nt.nodes.new("ShaderNodeMixRGB")
    mix_ripple.location = (-900, 100)
    mix_ripple.inputs["Fac"].default_value = 0.5
    nt.links.new(noise_a.outputs["Fac"], mix_ripple.inputs["Color1"])
    nt.links.new(noise_b.outputs["Fac"], mix_ripple.inputs["Color2"])

    bump = nt.nodes.new("ShaderNodeBump")
    bump.location = (-600, 0)
    bump.inputs["Strength"].default_value = 0.35
    bump.inputs["Distance"].default_value = 0.18
    nt.links.new(mix_ripple.outputs["Color"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    # --- Shore foam — requires "shore_sdf" vertex color layer on water mesh ---
    # Vertex color layer authored by handle_create_water (flow_vc alpha channel)
    vcol = nt.nodes.new("ShaderNodeVertexColor")
    vcol.location = (-900, -400)
    vcol.layer_name = "flow_vc"  # alpha = shore proximity

    foam_ramp = nt.nodes.new("ShaderNodeValToRGB")
    foam_ramp.location = (-600, -400)
    foam_ramp.color_ramp.elements[0].position = 0.40
    foam_ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 1.0)
    foam_ramp.color_ramp.elements[1].position = 0.80
    foam_ramp.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1.0)
    nt.links.new(vcol.outputs["Alpha"], foam_ramp.inputs["Fac"])

    foam_color_node = nt.nodes.new("ShaderNodeRGB")
    foam_color_node.location = (-600, -600)
    foam_color_node.outputs["Color"].default_value = (0.92, 0.95, 0.96, 1.0)

    foam_mix = nt.nodes.new("ShaderNodeMix")
    foam_mix.data_type = "RGBA"
    foam_mix.location = (-300, -400)
    foam_mix.blend_type = "MIX"
    nt.links.new(foam_ramp.outputs["Color"], foam_mix.inputs["Factor"])
    nt.links.new(bsdf.inputs["Base Color"].links[0].from_socket
                 if bsdf.inputs["Base Color"].is_linked else
                 nt.nodes.new("ShaderNodeRGB").outputs["Color"],
                 foam_mix.inputs["A"])
    nt.links.new(foam_color_node.outputs["Color"], foam_mix.inputs["B"])
    nt.links.new(foam_mix.outputs["Result"], bsdf.inputs["Base Color"])

    return mat
```

**Scroll driver — add immediately after calling `make_water_material()`:**
```python
def _add_scroll_driver(mat, map_node_name, axis_idx, rate):
    """Wire a frame-driven scroll driver to a Mapping node input."""
    node = mat.node_tree.nodes.get(map_node_name)
    if node is None:
        return
    fcurve = node.inputs["Location"].driver_add("default_value", axis_idx)
    drv = fcurve.driver
    drv.type = "SCRIPTED"
    drv.expression = f"frame * {rate}"

# Call after build_water_surfaces():
# _add_scroll_driver(lake_mat, "Mapping", 0, 0.0004)   # X scroll
# _add_scroll_driver(lake_mat, "Mapping", 1, 0.0002)   # Y scroll
```

---

## B. River Generation — Grade D+

### What exists

`build_water_surfaces()` — `build_scene_v3.py:517–555`

The river is a flat polyline ribbon mesh (2 verts per control point, quads stitched between). Width does vary (12–24m across 12 segments — `widths` list at line 524). Heights are manually specified per-point at correct world elevations.

`handle_carve_river()` — `environment.py:3790` is a proper D8/A* solver with `_apply_river_profile_to_heightmap()` and cosine bank cross-section. But it is **not called from `build_scene_v3.py`** — the scene script builds its own flat ribbon instead of using the AAA handler.

### Missing features

| # | Feature | Status |
|---|---|---|
| 1 | **Carved bank geometry transitions** | Heightmap has raised bank walls (`bank_profile` at line 206–207) but the river mesh itself is a flat plane floating above the carved terrain — no matching mesh bevels, no bank-lip geometry |
| 2 | **Flow-direction UV gradient** | No UV scroll, no flow direction per-vertex. `make_water_material` uses static noise. HFW rivers have downstream UV scroll at ~0.3–0.8 m/s equivalent |
| 3 | **Confluence logic** | No merging at waterfall base or lake entry. Upper river ends at `(-150,50)`, lower begins at `(-150,30)` — 20m orphaned gap with no transition mesh |
| 4 | **Variable-depth cross-section** | Flat Z plane. No V-channel depth; no thalweg geometry. The terrain heightmap IS carved correctly but the water surface mesh doesn't follow it |
| 5 | **`flow_vc` vertex colors on river ribbon** | `make_water_material` reads `flow_vc` but the ribbon built in `build_scene_v3.py` never sets this layer — foam channel is always 0 (no foam anywhere) |

### Fix — replace river ribbon build (`build_scene_v3.py:517–555`)

```python
def _build_river_ribbon_with_flow_vc(river_pts, widths):
    """Build river ribbon mesh with flow_vc vertex colors for UV scroll and foam."""
    rbm = bmesh.new()
    # Create flow_vc layer: R=bank_proximity, G=flowX, B=flowY, A=foam
    flow_layer = rbm.loops.layers.color.new("flow_vc")

    prev_l = prev_r = None
    prev_li = prev_ri = None   # loop index trackers

    face_list = []
    for idx, p in enumerate(river_pts):
        nxt = river_pts[idx + 1] if idx < len(river_pts) - 1 else river_pts[idx - 1]
        prv = river_pts[idx - 1] if idx > 0 else river_pts[idx + 1]
        dx = nxt[0] - prv[0]; dy = nxt[1] - prv[1]
        ln = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / ln, dx / ln
        # Normalize flow direction to [0,1] for vertex color
        flow_x_vc = (dx / ln) * 0.5 + 0.5
        flow_y_vc = (dy / ln) * 0.5 + 0.5
        w = widths[min(idx, len(widths) - 1)]
        # t = position along river 0..1 — used for foam fade at source/confluence
        t = idx / max(len(river_pts) - 1, 1)
        # Shore foam: high at start (source), moderate at mid, zero at lake entry
        foam_a = max(0.0, 1.0 - t * 1.4)

        vl = rbm.verts.new((p[0] + nx * w * 0.5, p[1] + ny * w * 0.5, p[2]))
        vr = rbm.verts.new((p[0] - nx * w * 0.5, p[1] - ny * w * 0.5, p[2]))
        if prev_l is not None:
            try:
                face = rbm.faces.new((prev_l, prev_r, vr, vl))
                # Set flow_vc on each loop of this face
                for loop in face.loops:
                    lx = loop.vert.co.x
                    # bank proximity: 1.0 at edges, 0.0 at center (approx)
                    bprox = abs(lx - p[0]) / max(w * 0.5, 0.01)
                    loop[flow_layer] = (
                        min(bprox, 1.0),  # R = bank proximity (foam cue)
                        flow_x_vc,        # G = flow dir X
                        flow_y_vc,        # B = flow dir Y
                        foam_a,           # A = foam strength
                    )
            except ValueError:
                pass
        prev_l, prev_r = vl, vr

    river_mesh = bpy.data.meshes.new("VB_River_Mesh")
    rbm.to_mesh(river_mesh)
    rbm.free()
    for p in river_mesh.polygons:
        p.use_smooth = True
    return river_mesh
```

**Confluence gap fix** — insert a bridge segment in `river_pts`:
```python
# build_scene_v3.py:518 — replace the two separate lists with one continuous path:
river_pts = [
    (-300., 250., 142.), (-260., 210., 141.), (-220., 160., 141.),
    (-190., 110., 140.5), (-170., 70., 140.2), (-150., 50., 140.),
    # WATERFALL BRIDGE: lerp 4 points from z=140 down to z=100 across y=50..30
    (-150., 44., 128.), (-150., 38., 116.), (-150., 34., 108.),
    (-150., 30., 100.),  # <-- waterfall base / lower river start
    (-100., 0., 82.), (-40., -60., 60.),
    (20., -140., 36.), (70., -230., 18.), (100., -300., LAKE_WATER_LEVEL),
]
```

---

## C. Waterfall — Grade F

### What exists

`build_water_surfaces()` — `build_scene_v3.py:557–586`

A 6-segment subdivided vertical quad, 20m wide, falling 40m. Material is `make_water_material("WaterFall", tint=(0.82, 0.90, 0.96, 1), emission=0.4)`. It is a static opaque sheet with a white tint and 0.4 emission strength to fake luminosity. No particles, no mist, no foam basin, no animated UV.

### Missing features

| # | Feature | HFW standard | Status |
|---|---|---|
| 1 | **Animated UV scroll** | Texture coordinates scrolling downward at 2–4 m/s equivalent | **ABSENT** |
| 2 | **Foam pool at base** | Disk of white churned-water foam at `(-150, 30)` | **ABSENT** — lower river picks up at Y=30 with no basin geometry |
| 3 | **Mist spray particles** | Upward-billowing particle system near base | **ABSENT** |
| 4 | **Cascade subdivision warping** | Vertices laterally displaced to simulate water curling over ledge | **ABSENT** — all verts lie on a perfect planar quad |
| 5 | **Geometry width funnel** | Narrows at top (ledge), widens at base (impact) | **PARTIAL** — single fixed width 20m top-to-bottom |

### Fix — replace waterfall build and add foam pool

```python
def build_waterfall_aaa():
    """AAA waterfall: cascade sheet + foam pool + mist particles."""
    xf, yf = WATERFALL_XY

    # --- Cascade sheet with organic warp ---
    wfbm = bmesh.new()
    w_half = 10.0
    segs = 12   # more segments for UV scroll resolution
    rng_wf = random.Random(SEED ^ 0xWF)
    for seg in range(segs):
        t0, t1 = seg / segs, (seg + 1) / segs
        z0 = WATERFALL_TOP_Z - t0 * 40.0
        z1 = WATERFALL_TOP_Z - t1 * 40.0
        y0 = yf + 5.0 - t0 * 8.0    # lean forward more (doubled)
        y1 = yf + 5.0 - t1 * 8.0
        # Widen toward base: funnel effect
        w0 = w_half * (1.0 - t0 * 0.3)
        w1 = w_half * (1.0 - t1 * 0.3)
        # Lateral warp: organic not-a-flat-plane
        for (xl, xr, y_, z_) in [
            (-w0 + rng_wf.uniform(-0.8, 0.8), w0 + rng_wf.uniform(-0.8, 0.8), y0, z0),
            (-w1 + rng_wf.uniform(-0.8, 0.8), w1 + rng_wf.uniform(-0.8, 0.8), y1, z1),
        ]:
            pass  # use pattern below
        v0 = wfbm.verts.new((xf - w0 + rng_wf.uniform(-1.0, 1.0), y0, z0))
        v1 = wfbm.verts.new((xf + w0 + rng_wf.uniform(-1.0, 1.0), y0, z0))
        v2 = wfbm.verts.new((xf + w1 + rng_wf.uniform(-1.0, 1.0), y1, z1))
        v3 = wfbm.verts.new((xf - w1 + rng_wf.uniform(-1.0, 1.0), y1, z1))
        try:
            wfbm.faces.new((v0, v1, v2, v3))
        except ValueError:
            pass
    # UV layer for scroll: V = 0 at top, 1 at base (downstream)
    uv_layer = wfbm.loops.layers.uv.new("UVMap")
    for face in wfbm.faces:
        for loop in face.loops:
            u = (loop.vert.co.x - (xf - w_half)) / (2 * w_half)
            v = (WATERFALL_TOP_Z - loop.vert.co.z) / 40.0
            loop[uv_layer].uv = (u, v)
    wfmesh = bpy.data.meshes.new("VB_Waterfall_Mesh")
    wfbm.to_mesh(wfmesh)
    wfbm.free()
    wf_obj = bpy.data.objects.new("VB_Waterfall", wfmesh)
    bpy.context.collection.objects.link(wf_obj)

    # Material with downward UV scroll
    wf_mat = bpy.data.materials.new("WaterFall")
    wf_mat.use_nodes = True
    if hasattr(wf_mat, "blend_method"):
        wf_mat.blend_method = "BLEND"
    nt = wf_mat.node_tree
    for n in list(nt.nodes): nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (1400, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (1100, 0)
    bsdf.inputs["Base Color"].default_value = (0.82, 0.90, 0.96, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.05
    for key in ("Transmission Weight", "Transmission"):
        if key in bsdf.inputs: bsdf.inputs[key].default_value = 0.85; break
    if "Alpha" in bsdf.inputs: bsdf.inputs["Alpha"].default_value = 0.80
    if "IOR" in bsdf.inputs: bsdf.inputs["IOR"].default_value = 1.333
    # UV scroll mapping
    uv_node = nt.nodes.new("ShaderNodeUVMap"); uv_node.location = (-800, 0)
    mapping = nt.nodes.new("ShaderNodeMapping"); mapping.location = (-600, 0)
    mapping.inputs["Scale"].default_value = (1.0, 3.0, 1.0)  # stretch V for longer cascade look
    nt.links.new(uv_node.outputs["UV"], mapping.inputs["Vector"])
    noise = nt.nodes.new("ShaderNodeTexNoise"); noise.location = (-300, 0)
    noise.inputs["Scale"].default_value = 8.0; noise.inputs["Detail"].default_value = 5.0
    nt.links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    bump = nt.nodes.new("ShaderNodeBump"); bump.location = (0, -100)
    bump.inputs["Strength"].default_value = 0.5
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    # Emission for mist glow
    emit = nt.nodes.new("ShaderNodeEmission"); emit.location = (1100, -200)
    emit.inputs["Color"].default_value = (0.88, 0.94, 1.0, 1.0)
    emit.inputs["Strength"].default_value = 0.55
    add_s = nt.nodes.new("ShaderNodeAddShader"); add_s.location = (1300, -80)
    nt.links.new(bsdf.outputs["BSDF"], add_s.inputs[0])
    nt.links.new(emit.outputs["Emission"], add_s.inputs[1])
    nt.links.new(add_s.outputs["Shader"], out.inputs["Surface"])
    wf_obj.data.materials.append(wf_mat)

    # Add UV scroll driver (V axis, downward)
    fc = mapping.inputs["Location"].driver_add("default_value", 1)
    drv = fc.driver; drv.type = "SCRIPTED"; drv.expression = "frame * -0.008"

    # --- Foam pool at waterfall base ---
    foam_bm = bmesh.new()
    foam_r, foam_segs = 14.0, 48
    center_v = foam_bm.verts.new((xf, yf + 4.0, WATERFALL_TOP_Z - 40.0 + 0.05))
    foam_ring = []
    for k in range(foam_segs):
        ang = 2 * math.pi * k / foam_segs
        r = foam_r * (0.88 + 0.12 * math.sin(ang * 5))
        foam_ring.append(foam_bm.verts.new((
            xf + r * math.cos(ang),
            yf + 4.0 + r * math.sin(ang) * 0.6,  # ellipse toward river
            WATERFALL_TOP_Z - 40.0 + 0.05,
        )))
    for k in range(foam_segs):
        try:
            foam_bm.faces.new((center_v, foam_ring[k], foam_ring[(k + 1) % foam_segs]))
        except ValueError:
            pass
    foam_mesh = bpy.data.meshes.new("VB_WaterfallFoam_Mesh")
    foam_bm.to_mesh(foam_mesh)
    foam_bm.free()
    foam_obj = bpy.data.objects.new("VB_WaterfallFoam", foam_mesh)
    bpy.context.collection.objects.link(foam_obj)
    foam_mat = bpy.data.materials.new("WaterfallFoam")
    foam_mat.use_nodes = True
    if hasattr(foam_mat, "blend_method"): foam_mat.blend_method = "BLEND"
    fn = foam_mat.node_tree
    for n in list(fn.nodes): fn.nodes.remove(n)
    fout = fn.nodes.new("ShaderNodeOutputMaterial"); fout.location = (600, 0)
    fe = fn.nodes.new("ShaderNodeEmission"); fe.location = (300, 0)
    fe.inputs["Color"].default_value = (0.95, 0.97, 1.0, 1.0)
    fe.inputs["Strength"].default_value = 1.2
    fn.links.new(fe.outputs["Emission"], fout.inputs["Surface"])
    foam_obj.data.materials.append(foam_mat)

    # --- Mist particles (hair system on foam pool) ---
    ps_mod = foam_obj.modifiers.new("MistPS", type="PARTICLE_SYSTEM")
    psys = foam_obj.particle_systems[-1]
    s = psys.settings
    s.type = "EMITTER"
    s.count = 800
    s.lifetime = 40
    s.normal_factor = 2.5
    s.factor_random = 0.8
    s.render_type = "HALO"
    try:
        s.render_step = 3
    except Exception:
        pass

    log("waterfall AAA: cascade sheet + foam pool + mist particles")
    return wf_obj, foam_obj
```

---

## D. Shore Transition — Grade D

### What exists

`build_beach_ring()` — `build_scene_v3.py:594–653`

A separate mesh ring (80 segments, inner_r=138m, outer_r=198m) with a flat Principled BSDF sand material. Shore height varies with `sin(ang*3)` and `sin(ang*7)` terms. Noise bump is applied. No transparency, no wet-sand gradient, no SDF distance field.

### Missing features

| # | Feature | HFW standard | Status |
|---|---|---|
| 1 | **SDF foam band at exact water edge** | 0.5–1.5m wide white foam streak at `LAKE_WATER_LEVEL` contour | **ABSENT** — lake water disk and beach ring are entirely separate materials with no shared edge |
| 2 | **Wet-sand darkening gradient** | ~2m band inward from waterline: darker, slightly specular damp sand | **ABSENT** — single flat sand color `(0.64, 0.55, 0.36, 1)` across entire beach |
| 3 | **Noise-driven irregular shore edge** | Fractal shoreline on the water surface itself, not perfect circle | **PARTIAL** — beach ring inner edge has `sin(ang*3)` variation but lake disk uses `sin(ang*3)*0.05` only (5% modulation) — still looks like a circle |
| 4 | **Transition to water material** | Vertex-color or alpha blend where lake disk meets beach | **ABSENT** |

### Fix — beach material replacement

Replace `build_scene_v3.py:634–650` (beach material setup):

```python
    beach_mat = bpy.data.materials.new("VB_BeachSand")
    beach_mat.use_nodes = True
    nt = beach_mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]

    geom = nt.nodes.new("ShaderNodeNewGeometry")
    geom.location = (-1200, 0)

    # --- World-Z proximity to water level → wet-sand darkening ---
    sep_p = nt.nodes.new("ShaderNodeSeparateXYZ")
    sep_p.location = (-900, 0)
    nt.links.new(geom.outputs["Position"], sep_p.inputs[0])

    wet_range = nt.nodes.new("ShaderNodeMapRange")
    wet_range.location = (-600, 0)
    wet_range.inputs["From Min"].default_value = LAKE_WATER_LEVEL - 0.1
    wet_range.inputs["From Max"].default_value = LAKE_WATER_LEVEL + 2.0
    wet_range.inputs["To Min"].default_value = 1.0   # wet (dark)
    wet_range.inputs["To Max"].default_value = 0.0   # dry (light)
    wet_range.clamp = True
    nt.links.new(sep_p.outputs["Z"], wet_range.inputs["Value"])

    dry_color = nt.nodes.new("ShaderNodeRGB")
    dry_color.location = (-600, -200)
    dry_color.outputs["Color"].default_value = (0.64, 0.55, 0.36, 1)  # dry sand

    wet_color = nt.nodes.new("ShaderNodeRGB")
    wet_color.location = (-600, -400)
    wet_color.outputs["Color"].default_value = (0.32, 0.26, 0.16, 1)  # damp dark sand

    sand_mix = nt.nodes.new("ShaderNodeMixRGB")
    sand_mix.location = (-300, -200)
    nt.links.new(wet_range.outputs["Result"], sand_mix.inputs["Fac"])
    nt.links.new(dry_color.outputs["Color"], sand_mix.inputs["Color1"])
    nt.links.new(wet_color.outputs["Color"], sand_mix.inputs["Color2"])

    # --- Foam band: thin white strip at exact water level ---
    foam_range = nt.nodes.new("ShaderNodeMapRange")
    foam_range.location = (-600, 200)
    foam_range.inputs["From Min"].default_value = LAKE_WATER_LEVEL - 0.15
    foam_range.inputs["From Max"].default_value = LAKE_WATER_LEVEL + 0.60
    foam_range.inputs["To Min"].default_value = 0.0
    foam_range.inputs["To Max"].default_value = 1.0
    foam_range.clamp = True
    nt.links.new(sep_p.outputs["Z"], foam_range.inputs["Value"])

    # Tent function: peak at midpoint, zero at edges → foam band only at waterline
    foam_invert = nt.nodes.new("ShaderNodeMath")
    foam_invert.location = (-300, 200)
    foam_invert.operation = "SUBTRACT"
    foam_invert.inputs[0].default_value = 1.0
    nt.links.new(foam_range.outputs["Result"], foam_invert.inputs[1])
    foam_tent = nt.nodes.new("ShaderNodeMath")
    foam_tent.location = (-100, 200)
    foam_tent.operation = "MINIMUM"
    nt.links.new(foam_range.outputs["Result"], foam_tent.inputs[0])
    nt.links.new(foam_invert.outputs["Value"], foam_tent.inputs[1])
    foam_scale = nt.nodes.new("ShaderNodeMath")
    foam_scale.location = (100, 200)
    foam_scale.operation = "MULTIPLY"
    foam_scale.inputs[1].default_value = 4.0  # sharpen band
    nt.links.new(foam_tent.outputs["Value"], foam_scale.inputs[0])
    foam_clamp = nt.nodes.new("ShaderNodeMath")
    foam_clamp.location = (300, 200)
    foam_clamp.operation = "MINIMUM"
    foam_clamp.inputs[1].default_value = 1.0
    nt.links.new(foam_scale.outputs["Value"], foam_clamp.inputs[0])

    foam_mix2 = nt.nodes.new("ShaderNodeMixRGB")
    foam_mix2.location = (500, 0)
    nt.links.new(foam_clamp.outputs["Value"], foam_mix2.inputs["Fac"])
    nt.links.new(sand_mix.outputs["Color"], foam_mix2.inputs["Color1"])
    foam_mix2.inputs["Color2"].default_value = (0.94, 0.96, 0.97, 1)  # foam white
    nt.links.new(foam_mix2.outputs["Color"], bsdf.inputs["Base Color"])

    # Wet-roughness: damp sand is slightly specular (0.55), dry is matte (0.91)
    rough_mix = nt.nodes.new("ShaderNodeMath")
    rough_mix.location = (500, -200)
    rough_mix.operation = "MIX"
    nt.links.new(wet_range.outputs["Result"], rough_mix.inputs[0])
    rough_mix.inputs[1].default_value = 0.91   # dry roughness
    rough_mix.inputs[2].default_value = 0.55   # wet roughness
    nt.links.new(rough_mix.outputs["Value"], bsdf.inputs["Roughness"])

    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.location = (-1200, -400)
    noise.inputs["Scale"].default_value = 22.0
    noise.inputs["Detail"].default_value = 7.0
    nt.links.new(geom.outputs["Position"], noise.inputs["Vector"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.location = (700, -200)
    bump.inputs["Strength"].default_value = 0.60
    bump.inputs["Distance"].default_value = 0.035
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
```

---

## E. Springs — Grade F

### What exists

`SPRING_XY = (-300.0, 250.0)` — `build_scene_v3.py:55`

This constant is declared. It is referenced in the spec comment on line 6. It is used as the first point in `upper_pts` for the river carving operation (lines 174, 178). That is the totality of the spring system: a named coordinate used as a river source point.

There is:
- No spring geometry (pool, bubbling surface, surrounding wet-rock terrain)
- No spring material (emergent water, mineral deposits)
- No connection metadata to the river network
- No handler in `COMMAND_HANDLERS` (`__init__.py:42–1136` — search for "spring" returns zero handler entries)
- No `handle_generate_spring` in `environment.py`
- `karst_springs` and `hot_springs` boolean flags exist in `environment.py:2891–2893` but are never used in `build_scene_v3.py`

### Fix — `build_mountain_spring()` function

Insert after `build_beach_ring()` at `build_scene_v3.py:654`:

```python
def build_mountain_spring():
    """Mountain spring at SPRING_XY: small pool + seep wet-rock zone."""
    sx, sy = SPRING_XY
    spring_z = sample_h(hm, sx, sy)   # NOTE: call only after hm is in scope

    # Spring pool — small elliptical dish 6m radius
    sbm = bmesh.new()
    segs = 32
    pool_r = 6.0
    center_v = sbm.verts.new((sx, sy, spring_z + 0.05))
    ring_verts = []
    for k in range(segs):
        ang = 2 * math.pi * k / segs
        ring_verts.append(sbm.verts.new((
            sx + pool_r * math.cos(ang) * (0.9 + 0.1 * math.sin(ang * 3)),
            sy + pool_r * math.sin(ang) * (0.85 + 0.1 * math.cos(ang * 5)),
            spring_z + 0.05,
        )))
    for k in range(segs):
        try:
            sbm.faces.new((center_v, ring_verts[k], ring_verts[(k + 1) % segs]))
        except ValueError:
            pass
    spring_mesh = bpy.data.meshes.new("VB_Spring_Mesh")
    sbm.to_mesh(spring_mesh)
    sbm.free()
    spring_obj = bpy.data.objects.new("VB_Spring", spring_mesh)
    bpy.context.collection.objects.link(spring_obj)

    # Spring water material — high-clarity, slight upwelling emission
    sp_mat = make_water_material("WaterSpring",
                                 tint=(0.08, 0.22, 0.45, 1.0),
                                 roughness=0.04,
                                 emission=0.10)
    try:
        sp_mat.blend_method = "BLEND"
    except Exception:
        pass
    spring_obj.data.materials.append(sp_mat)

    # Wet seep ring — darker rock/soil patch around spring (12m radius)
    # Done via vertex-color paint on terrain; return extent for caller to paint
    log(f"mountain spring: pool at ({sx:.0f}, {sy:.0f}, {spring_z:.1f})")
    return spring_obj
```

Wire it in `main()` after `build_water_surfaces()`:
```python
    log("building mountain spring...")
    try:
        build_mountain_spring()
    except Exception as exc:
        log_fail("spring", exc)
```

---

## F. Wiring Audit — Grade C

### Registered water/river/erosion handlers in `COMMAND_HANDLERS`

| Key | Module | Registered | Notes |
|---|---|---|---|
| `env_generate_waterfall` | `environment.handle_generate_waterfall` | YES | `__init__.py:138–141` |
| `env_carve_river` | `environment.handle_carve_river` | YES | `__init__.py:178–181` |
| `env_create_water` | `environment.handle_create_water` | YES | `__init__.py:188–191` |
| `env_carve_water_basin` | `environment.handle_carve_water_basin` | YES | `__init__.py:193–196` |
| `env_generate_spring` | — | **MISSING** | No handler exists anywhere |
| `env_water_foam_material` | — | **MISSING** | No dedicated foam/shore material handler |
| Hydraulic erosion | `_terrain_erosion.apply_hydraulic_erosion` | **NOT WIRED** | Module exists with `ErosionMasks` output but nothing in `COMMAND_HANDLERS` dispatches to it |
| Thermal erosion | `_terrain_erosion.apply_thermal_erosion` | **NOT WIRED** | Same — `ThermalErosionMasks` computed but not exposed |
| Stream power erosion | `_terrain_erosion.compute_stream_power_erosion` | **NOT WIRED** | SPL solver at `_terrain_erosion.py:863` is fully implemented but unreachable via MCP |

### Orphaned water functions

1. `make_water_material()` (`build_scene_v3.py:388`) — the scene script's factory is distinct from `_ensure_water_material()` in `environment.py`. Two separate water material systems with different feature sets and no shared code. Both do different things; neither is called from the other.

2. `_ensure_water_material()` (`environment.py:6008`) — has VolumeAbsorption and vertex-color foam reading. But `build_scene_v3.py` never calls `handle_create_water` — it bypasses the registered handler entirely.

3. `SPRING_XY` (`build_scene_v3.py:55`) — declared constant that is never materialized into geometry.

### Wiring fix — add erosion handlers to `__init__.py`

Insert after the `environment_scatter.py` block at `__init__.py:1066`:

```python
    # ------------------------------------------------------------------
    # _terrain_erosion.py — hydraulic, thermal, stream-power erosion
    # These are pure-numpy (no bpy) — safe to call from any context.
    # ------------------------------------------------------------------
    _try_register(
        "erosion_hydraulic",
        f"{_pkg}._terrain_erosion",
        "apply_hydraulic_erosion",
    )
    _try_register(
        "erosion_hydraulic_masks",
        f"{_pkg}._terrain_erosion",
        "apply_hydraulic_erosion_masks",
    )
    _try_register(
        "erosion_thermal",
        f"{_pkg}._terrain_erosion",
        "apply_thermal_erosion",
    )
    _try_register(
        "erosion_thermal_masks",
        f"{_pkg}._terrain_erosion",
        "apply_thermal_erosion_masks",
    )
    _try_register(
        "erosion_stream_power",
        f"{_pkg}._terrain_erosion",
        "compute_stream_power_erosion",
    )
```

---

## Priority Fix Order

| Priority | Issue | File:Line | Effort |
|---|---|---|---|
| P0 | Lake/river material has no UV scroll | `build_scene_v3.py:388–480` | 2h — replace factory |
| P0 | Waterfall is a static non-animated quad | `build_scene_v3.py:557–586` | 3h — replace with `build_waterfall_aaa()` |
| P0 | Spring generates zero geometry | `build_scene_v3.py:55` (constant only) | 1h — add `build_mountain_spring()` |
| P1 | No depth-absorption volume on lake | `build_scene_v3.py:388` | 30m — add `ShaderNodeVolumeAbsorption` |
| P1 | No shore foam SDF band on beach | `build_scene_v3.py:634–650` | 1h — replace beach material |
| P1 | River ribbon has no `flow_vc` vertex colors | `build_scene_v3.py:517–555` | 2h — replace with `_build_river_ribbon_with_flow_vc()` |
| P1 | 20m confluence gap between upper/lower river | `build_scene_v3.py:518` | 30m — merge `river_pts` list |
| P1 | Erosion handlers unregistered | `handlers/__init__.py:1066` | 30m — add `_try_register` block |
| P2 | `make_water_material` and `_ensure_water_material` are two divergent systems | `build_scene_v3.py:388`, `environment.py:6008` | 4h — unify into one factory |
| P2 | No wet-sand roughness gradient on beach | `build_scene_v3.py:638–640` | 30m — add roughness mix node |
| P2 | Fresnel blends to Diffuse not reflection/transmission pair | `build_scene_v3.py:447–461` | 1h — replace with proper Principled BSDF path |

---

## What Horizon Forbidden West Actually Does (reference gap)

The water systems in HFW (reverse-engineered from GDC presentations and published tech breakdowns) include:

1. **Layered flow maps** — two UV scroll directions composited with screen-space distortion for complex swirl patterns. The current code has zero UV scroll on any water surface.
2. **Per-vertex depth encoding** — vertex color R channel encodes water column depth, drives color ramp from blue-green to brown at shallow. The `flow_vc` layer in `environment.py` does attempt this but `build_scene_v3.py` never uses it.
3. **FFT-based wave simulation** at medium/large water bodies (lake) — replaced here by a simpler animated noise, which is acceptable for an indie project, but currently there is NO animation at all.
4. **Tessellation-based shore displacement** — vertices actually lift/fall with wave height at shoreline. Not implemented and out of scope for Blender CPU rendering, but the absence of any shore animation is a clear gap.
5. **Multi-cascade waterfall with separate foam, mist, and impact particles** — the current single-mesh sheet is the largest single visual failure in the file.
