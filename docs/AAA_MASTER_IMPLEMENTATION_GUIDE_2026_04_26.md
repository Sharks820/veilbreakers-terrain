# AAA Master Implementation Guide — VeilBreakers Terrain
**Document date:** 2026-04-26
**Audience:** Engineer executing the work, not a reader filing a report.
**Source:** Synthesis of 6 parallel deep-dive audit agents (Bug/Wiring, Water, Bridge/Path, Heightmap/Cliff, Foliage Research, AAA Benchmark).

---

## 1. Executive Summary

**The pattern of failure is not algorithmic — it is integration.** Across every domain audited (water, bridges, paths, cliffs, foliage), the underlying physics, geometry, and data are already computed by code that exists in this repository. What is missing is the wiring pass that connects computed signals to shader bindings, mesh vertices, and export atlases. Water has six fully-implemented physics subsystems (foam, mist, caustics, wet rock, velocity, wave energy) that produce numpy arrays nobody reads. Cliffs run an 8-stage analysis pipeline that generates displacement fields then never builds a mesh. Bridges have correct routing logic locked behind underscore-prefixed wrappers no caller can reach. The gap to KCD2/TW3/RDR2 is not exotic technique — it is 10 to 20 year old standard techniques (Beer-Lambert, Schlick Fresnel, flow maps, triplanar, stratigraphy banding) that every shipped AAA game uses and we already have data for but have not bound.

**The strategy is therefore wiring-first, authoring-second, replacement-third.** Wave 1 deletes dead code and fixes the Z-fighting that produces "glass water." Waves 2-3 wire the orphaned water and cliff outputs into shaders, atlases, and mesh geometry — this single pass is what closes the perceptual gap to AAA on terrain and water. Wave 4 unlocks the bridge and path primitives behind underscore wrappers and adds the missing geometric details (rail Catmull-Rom, pier plinths, layered road materials, A* slope heuristic). Wave 5 retires the Python L-system foliage path entirely and adopts the The Grove + Geo-Scatter (Blender) or UE5 PCG + Megaplants (engine) toolchain — Python cannot reach SpeedTree-class output and trying is wasted effort. Every wave ends with a regression test added to the suite so the gains do not erode.

---

## 2. Codebase Health Summary

| Domain | Current Grade | Target Grade | Primary Gap |
|---|---|---|---|
| Heightmap (fBm/erosion math) | A- | A | Already AAA. Only np.roll edge bugs left. |
| Cliffs (analysis pipeline) | B+ | A | 8-stage analysis solid. **Mesh emission pass missing.** |
| Cliffs (rendered output) | D | A- | No mesh = no visible cliffs. Triplanar/stratigraphy unbound. |
| Water (algorithms) | A- | A | All physics implemented. |
| Water (rendered output) | F | A- | Glass-flat. Z-fights terrain. Foam/caustics/depth unwired. |
| Bridges (routing/structural) | B | A- | Catmull-Rom, pier detail, layered road missing. |
| Paths/Roads | C+ | A- | Slope heuristic naive, turn radius unenforced, water cost missing. |
| Scatter/Foliage (current Python) | D+ | — (retire) | Architecturally cannot reach AAA. |
| Scatter/Foliage (target stack) | — | A | Adopt Grove+Geo-Scatter or UE5 PCG. |
| Bug/Wiring hygiene | C | A | 8 duplicate generators, 1 channel mismatch, 4 np.roll bugs, 8 underscore-locked APIs. |

---

## 3. Immediate Bug Fixes (P0) — Do These First

Execute these before touching any visual work. They are mechanical and unblock later waves.

### 3.1 Delete duplicate feature generators in `_scatter_engine.py`

These are dead legacy scatter specs — never imported, shadowed by `terrain_features.py` versions actually called by the pipeline.

| File | Line | Function to DELETE |
|---|---|---|
| `_scatter_engine.py` | 1134 | `generate_canyon` |
| `_scatter_engine.py` | 1234 | `generate_waterfall` |
| `_scatter_engine.py` | 1328 | `generate_cliff_face` |
| `_scatter_engine.py` | 1416 | `generate_swamp_terrain` |
| `_scatter_engine.py` | 1516 | `generate_sinkhole` |
| `_scatter_engine.py` | 1621 | `generate_floating_rocks` |
| `_scatter_engine.py` | 1727 | `generate_ice_formation` |
| `_scatter_engine.py` | 1819 | `generate_lava_flow` |

Verify after delete: `grep -rn "from _scatter_engine import" .` returns nothing referencing these names. Run full test suite. The `terrain_features.py` versions remain as the single source of truth.

### 3.2 Fix channel declaration mismatch in `terrain_cliffs.py`

`talus_boulder_placements` is written via `stack.set()` at line 2612 but not declared in `produces_channels` at line 2701. The stack contract validator should be flagging this. Patch:

```python
# terrain_cliffs.py:2701  (produces_channels tuple)
produces_channels = (
    # ...existing entries...
    "talus_boulder_placements",   # ADD THIS — written at line 2612
)
```

### 3.3 Z-fighting fix that eliminates "glass water" — single highest-impact one-liner in the repo

```python
# environment.py:6949-6951  REPLACE
MIN_WATER_ELEVATION = 0.02   # 2 cm — exceeds float32 depth precision at 200 m
surface_z = max(water_level, terrain_z + MIN_WATER_ELEVATION)
```

This alone removes the speckled black-pixel z-fighting that makes every water surface look broken in renders.

---

## 4. Water System Fix Guide (Critical Path)

Water is the single largest visual gap. Every algorithm is already implemented; nothing is bound. Execute the 12 steps in order — each unlocks the next.

### Phase 1 — Eliminate glass water (P0, ~1 day)

**Step 1. Z-fight fix** — see §3.3 above.
**Visual change:** speckle artifacts gone. Water no longer looks "broken."

**Step 2. Wire foam atlas**
```python
# terrain_waterfalls.py:2317  (foam currently stored as 2D array, dropped on the floor)
foam = compute_foam_mask(...)   # already returns 3-layer mask
rasterize_channel_to_atlas(foam, stack, channel_name="foam",
                           atlas_path="export/atlases/water_foam.png",
                           bit_depth=8)
stack.set("foam_atlas_path", "export/atlases/water_foam.png")
```
**Visual change:** white spume at obstacle wakes, waterfall bases, and high-velocity zones.

**Step 3. Call caustics** — the function `compute_riverbed_caustics()` at `_water_network_ext.py:1048` has zero callers in the repo.
```python
# _water_network_ext.py — add new pass at module bottom:
def pass_caustic_maps(stack, water_mask, depth, sun_dir):
    caustics = compute_riverbed_caustics(water_mask, depth, sun_dir)   # already implemented
    rasterize_channel_to_atlas(caustics, stack, "caustics",
                               "export/atlases/water_caustics.png", bit_depth=8)
    stack.set("caustic_atlas_path", "export/atlases/water_caustics.png")

# Register in pipeline orchestrator (wherever waterfall passes are sequenced):
pass_caustic_maps(stack, water_mask, bathymetry, sun_dir)
```
**Visual change:** dappled animated light patterns on submerged rocks/bed. Single biggest "this looks AAA" win.

**Step 4. Bind atlases in shader manifest**
```python
# terrain_unity_export.py:519-527  add to shader_textures dict
"foam_texture":     stack.get("foam_atlas_path"),
"caustic_texture":  stack.get("caustic_atlas_path"),
```
**Visual change:** Phase 1 visible improvements actually reach the engine.

### Phase 2 — Add depth perception (P1, ~1 day)

**Step 5. Export bathymetry as depth texture**
```python
# Anywhere the bathymetry channel is finalized (search "water_depth" in environment.py:6942):
depth_norm = np.clip(bathymetry / MAX_DEPTH_M, 0, 1).astype(np.float32)
rasterize_channel_to_atlas(depth_norm, stack, "water_depth",
                           "export/atlases/water_depth.png", bit_depth=16)
stack.set("water_depth_atlas_path", "export/atlases/water_depth.png")

# terrain_unity_export.py — bind:
"_WaterDepthTex": stack.get("water_depth_atlas_path"),
```

**Step 6. Beer-Lambert depth absorption (shader-side)**
```hlsl
// Water shader fragment
float depth = SAMPLE_TEXTURE2D(_WaterDepthTex, sampler_linear, uv).r * MAX_DEPTH_M;
float3 extinction = float3(0.45, 0.15, 0.10);   // tune per biome (R absorbs first)
float3 transmittance = exp(-extinction * depth);
float3 underwaterColor = lerp(_DeepColor, _ShallowColor, transmittance);
```
**Visual change:** shallow water transparent (you see the bed), deep water opaque blue-green. This is THE difference between "shallow puddle vs. deep lake" reading.

**Step 7. Wire mist mask to volumetric fog**
The mask at `_water_network_ext.py:847` is 2D — convert to fog volume descriptor:
```python
# After compute_mist_mask call:
mist_2d = compute_mist_mask(...)
mist_fog_volume = {
    "mask_2d":     mist_2d,
    "height_m":    3.0,           # extrude vertically
    "density_max": 0.6,
    "color":       (0.7, 0.75, 0.8),
}
stack.set("mist_fog_volume", mist_fog_volume)
# Engine-side: convert to VolumetricFogVolume actor on import.
```

**Step 8. Schlick Fresnel reflection**
```hlsl
float3 V = normalize(_WorldSpaceCameraPos - worldPos);
float NdotV = saturate(dot(worldNormal, V));
float F = 0.04 + 0.96 * pow(1.0 - NdotV, 5.0);
float3 col = lerp(underwaterColor, reflectionColor, F);
```
**Visual change:** mirror-like grazing reflections, less plastic-y from above.

### Phase 3 — Surface motion (P2, ~2 days)

**Step 9. Generate surface normal map atlases**
Sobel derivative on bathymetry + flow direction gives a usable surface normal:
```python
# new pass in _water_network_ext.py
import numpy as np
def generate_water_normal_atlas(bathymetry, flow_uv):
    dzdx = np.gradient(bathymetry, axis=1)
    dzdy = np.gradient(bathymetry, axis=0)
    n = np.stack([-dzdx, -dzdy, np.ones_like(bathymetry)], axis=-1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    n_rgb = (n * 0.5 + 0.5)   # 0-1 encode
    return n_rgb
# rasterize, bind as _WaterNormalTex_A; produce a 2nd at half scale, scrolled along flow_uv.
```

**Step 10. Wire flow velocity to wave amplitude**
```python
# terrain_waterfalls.py — when emitting per-vertex water mesh data:
wave_amp = np.linalg.norm(velocity_field, axis=-1) * 0.05   # 5 cm per m/s
stack.set("wave_amplitude_per_vertex", wave_amp)
# Bind to vertex color G channel (R=flow_x, B=flow_y, G=amp, A=foam).
```

**Step 11. Gerstner waves OR tessellation displacement**
Choose one — Gerstner if Unity URP target, tessellation if HDRP/UE5:
```hlsl
// Gerstner wave summed in vertex shader
float3 gerstner(float3 p, float2 dir, float lambda, float steepness, float speed, float t) {
    float k = 2.0 * 3.14159 / lambda;
    float f = k * (dot(dir, p.xz) - speed * t);
    float a = steepness / k;
    return float3(dir.x * a * cos(f), a * sin(f), dir.y * a * cos(f));
}
// Sum 6 waves with varied dir/lambda. Manifest already declares gerstner_wave_count=6 at terrain_unity_export.py:541.
```

**Step 12. Wire particle specs**
```python
# terrain_waterfalls.py:2327  particle_specs currently dropped
stack.set("vfx_particle_specs", particle_specs)
# Engine importer reads this list and instantiates Niagara/VFX Graph systems at the listed transforms.
```
**Visual change:** mist puffs at falls, splash bursts at rocks, ripple emitters at obstacles.

### Orphaned function wiring summary

| Function | File:Line | Wired in step |
|---|---|---|
| `compute_foam_mask` | `_water_network_ext.py:711` | Step 2 |
| `compute_mist_mask` | `_water_network_ext.py:847` | Step 7 |
| `compute_riverbed_caustics` | `_water_network_ext.py:1048` | Step 3 |
| `compute_wet_rock_mask` | `_water_network_ext.py:547` | Step 9 (extend to wet-rock blend factor) |
| `generate_velocity_field` | `terrain_waterfalls.py:1848` | Steps 10-11 |
| Coastal JONSWAP foam | `coastline.py:925` | Step 2 (extend foam atlas to coastlines) |

---

## 5. Bridge/Path Fix Guide

Current bridge quality 6/10 vs KCD2's 9/10. All fixes are localized geometry and routing changes.

### 5.1 Catmull-Rom rail tangents (eliminates module-boundary shearing)

```python
# _mesh_bridge.py  ~line 380  REPLACE finite-difference with Catmull-Rom:
# OLD:
# tangent = (p_next - p_prev).normalized()
# NEW:
def catmull_rom_tangent(p_prev, p0, p1, p_next):
    return (0.5 * ((p1 - p_prev) + (p_next - p0))).normalized()
tangent = catmull_rom_tangent(p_prev, p0, p1, p_next)
```
**Visual change:** rails are C1 continuous, no faceted breaks at joints.

### 5.2 Pier detail (plinth + astragal + cutwater)

```python
# _bridge_profile()  add to returned dict:
pier_detail = {
    "plinth": {"shape": "truncated_cone", "h": 0.3, "r_top": 1.0, "r_base": 1.4},
    "astragal": {"shape": "ring", "h": 0.15, "r_offset": 0.05},
    "cutwater": {"shape": "wedge", "side": "upstream", "depth": 0.6, "angle_deg": 35},
}
# In pier mesh emission, add 3 components per pier: plinth at base, astragal at cap, cutwater on upstream face.
```
**Visual change:** piers read as masonry, not extruded cylinders.

### 5.3 Layered road material

```python
# road_network.py:977-1055  _road_segment_mesh_spec()
layers = [
    {"name": "bedrock", "thickness": 0.40, "material": "rock_base"},
    {"name": "stone",   "thickness": 0.25, "material": "cobble"},
    {"name": "gravel",  "thickness": 0.15, "material": "gravel_road"},
    {"name": "dirt",    "thickness": 0.10, "material": "packed_dirt"},
]
spec["layers"] = layers
# Each layer inherits crown and shoulder geometry; cross-section beveled at edges.
```

### 5.4 A* slope-aware heuristic

```python
# road_network.py  ~line 180  A* heuristic
# OLD: h = euclidean_distance
# NEW:
def heuristic(a, b, slope_map, max_grade=0.08):
    eucl = np.linalg.norm(np.array(a) - np.array(b))
    est_slope = abs(slope_map[a] - slope_map[b]) / max(eucl, 1e-6)
    slope_penalty = 0.5 * max(0.0, est_slope - max_grade) ** 2
    return eucl + slope_penalty
```

### 5.5 Turn radius post-processing

```python
# After A* returns raw path, before mesh emission:
from rdp import rdp   # or local equivalent
simplified = rdp(raw_path, epsilon=2.0)
final_path = enforce_turn_radius(simplified, min_radius=15.0)
```
`enforce_turn_radius` inserts arc fillets at any vertex whose incoming/outgoing angle exceeds the curvature limit.

### 5.6 Pre-routing water cost penalty

```python
# Before A* call:
cost_map[water_mask] = 1e6   # roads route around water unless bridge cost added explicitly
cost_map[bridge_candidate_mask] = bridge_cost_per_meter   # 50-200x road cost
```

### 5.7 Switchback model replacement

```python
# road_network.py  _generate_switchback_points()
# OLD: 15m parabolic hairpin
# NEW: 20m approach ramp + 12m radius arc turn + 20m exit ramp = 52m switchback module
def generate_switchback_module(entry, exit, slope_dir):
    ramp_in  = generate_ramp(entry, length=20.0)
    arc      = generate_arc_turn(ramp_in.end, radius=12.0, sweep_deg=180)
    ramp_out = generate_ramp(arc.end, length=20.0, target=exit)
    return ramp_in.points + arc.points + ramp_out.points
```

### 5.8 Unlock 8 underscore-prefixed APIs

Rename and re-export so MCP/external callers can reach them:

| Internal name | Export as |
|---|---|
| `_astar_24dir` | `route_path_astar` |
| `_detect_bridges` | `detect_bridge_valleys` |
| `_generate_switchback_points` | `insert_switchbacks_on_steep_grades` |
| `_compute_worn_path_spec` | `compute_path_erosion_spec` |
| `_road_segment_mesh_spec` | `generate_road_mesh_cross_section` |
| `_generate_swept_centerline_bridge_mesh` | `generate_swept_centerline_bridge` |
| `_generate_straight_bridge_mesh` | `generate_straight_bridge` |
| `distance_point_to_polyline` | `project_point_to_polyline` |

Pattern: keep internal under existing name, add public alias at module bottom:
```python
route_path_astar = _astar_24dir
__all__ = [..., "route_path_astar", ...]
```

---

## 6. Heightmap / Cliff Fix Guide

**Heightmap math is already AAA.** No changes to fBm parameters, octaves, gain, or domain warping. The two fix areas are toroidal-wrap bugs and the missing cliff mesh emission.

### 6.1 Replace 4 `np.roll` toroidal-wrap bugs with edge-repeat

A reusable template already exists at `terrain_wind_erosion.py:41-89` (`_shift_with_edge_repeat`). Copy/import it and replace each call site:

| File | Line | Site |
|---|---|---|
| `terrain_geology_validator.py` | 60-63 | 4 np.roll calls in `validate_strata_consistency` |
| `terrain_stratigraphy.py` | 311 | exposure neighborhood averaging |
| `terrain_stratigraphy.py` | 336 | hardness_above lookup (causes spurious bottom-edge undercuts) |
| `terrain_advanced.py` | 1700 | wind deposition seam (lines 1701-1708 zero out, but contamination may have propagated) |

Replacement pattern:
```python
# OLD:
shifted = np.roll(arr, shift=1, axis=0)
# NEW:
padded  = np.pad(arr, 1, mode="edge")
shifted = padded[:-2, 1:-1]   # equivalent of roll(+1,axis=0) without wrap
# (or call the existing helper)
shifted = _shift_with_edge_repeat(arr, dy=1, dx=0)
```

### 6.2 Cliff mesh geometry pass — the missing implementation

The 8-stage analysis at `terrain_cliffs.py` produces displacement fields (strata banding, vertical cracks, fBm perturbation) stored in the stack. The comment at line 2252 references `generate_cliff_face_mesh` but **that function does not exist.** Implement it:

```python
# terrain_cliffs.py — new function near line 2252
def generate_cliff_face_mesh(stack, cliff_mask, lip_polylines, base_polylines):
    """Emit 3D mesh geometry from cliff displacement fields."""
    strata_band   = stack.get("strata_displacement")        # vertical banding offset
    vertical_crack = stack.get("vertical_crack_field")      # narrow grooves
    fbm_perturb   = stack.get("cliff_fbm_displacement")     # micro-roughness
    overhang_mask = stack.get("overhang_mask")
    talus_field   = stack.get("talus_boulder_placements")   # see §3.2

    verts, faces, uvs, normals = [], [], [], []
    for lip, base in zip(lip_polylines, base_polylines):
        # Build vertical strip between lip and base, sampled every 0.25m vertically
        strip = build_cliff_strip(lip, base, vertical_resolution=0.25)
        # Apply layered displacements along surface normal
        for v in strip.vertices:
            d = (strata_band.sample(v.uv)
               + vertical_crack.sample(v.uv) * 0.5
               + fbm_perturb.sample(v.uv) * 0.3)
            v.position += v.normal * d
            if overhang_mask.sample(v.uv) > 0.5:
                v.position += v.normal * OVERHANG_BIAS_M
        verts.extend(strip.vertices)
        faces.extend(strip.faces)
        uvs.extend(strip.triplanar_uvs)   # store triplanar-ready UV
        normals.extend(strip.normals)
    stack.set("cliff_face_mesh", {"verts": verts, "faces": faces,
                                  "uvs": uvs, "normals": normals})
    # Emit talus boulders as scatter instances at base
    emit_talus_instances(stack, talus_field, base_polylines)
```

Wire into the pipeline at the existing call site (line 2252) — replace the comment with the real call.

**Shader-side requirements** (minimum to ship cliffs that don't look like 2010):
- Triplanar projection: `blendWeights = abs(worldNormal); blendWeights = pow(blendWeights, 4.0); blendWeights /= dot(blendWeights, 1.0);`
- Stochastic UV offset (hash worldPos into 4 UV variants, blend) — kills tiling
- Height-banded layer blend for stratigraphy (use `strata_band` as sample input)
- Slope threshold drives talus/scree scatter at base

---

## 7. Foliage System Replacement Guide

**Critical truth: the current Python L-system foliage cannot reach AAA. This is architectural, not parametric.** AAA studios author trees in dedicated tools (SpeedTree, The Grove) and scatter via engine-native GPU instancing. Continuing to invest in the Python generator is wasted effort.

### 7.1 What to retire

- All Python L-system tree generators in the foliage path.
- Any custom scatter density-field generator that competes with Geo-Scatter / PCG.
- Per-tree mesh emission code in `vegetation_system.py` — replace with proxy import.

### 7.2 What to keep

- Biome classification (slope/moisture/altitude/sunlight → species probability) — this is the **input** to the new scatter tools.
- Density/exclusion mask generation (e.g., water-edge, road-edge proximity).
- Wind direction/strength field (becomes input to engine wind systems).

### 7.3 Path A — Blender-first: The Grove 3D + Geo-Scatter (~$325 one-time)

Adopt this if final renders happen in Blender or you need scriptable Python control.

1. Install The Grove 3D (€199 Indie). Author 3-5 grown presets per biome (dead oak, hollow ash, twisted pine, gnarled willow, fallen sentinel). Save as Blender assets.
2. Install Geo-Scatter 5.6 ($99). Confirm Blender 4.5 compatibility on first import.
3. Build .scatpacks per biome by combining Grove presets + custom debris (stumps, logs, roots).
4. Export biome density masks from existing classifier as 8-bit PNGs.
5. Call Geo-Scatter from `vegetation_system.py`:
   ```python
   import bpy
   bpy.ops.scatter5.add_psy_preset(preset_name="dark_fantasy_forest")
   bpy.ops.scatter5.set_density_mask(image_path=biome_density_path)
   ```
6. Hand-model 3-5 reed variants, 2 lily pad variants, 2 water plant variants for aquatic foliage. Geo-Scatter has a water-edge proximity distribution mode — feed it the `water_edge_mask` from existing pipeline.

### 7.4 Path B — Engine-first: UE5 PCG + Megaplants + Fab Dead Forest (~$0-50)

Adopt this if shipping target is UE5 (recommended for VeilBreakers).

1. Enable UE 5.7 PCG Biome Core plugin (free).
2. Import Megaplants from Fab Launcher (free tier covers 80% of needs).
3. Acquire Fab "Foliage VOL.32 - Dead Forest (Nanite)" — 88 meshes, dead trees/stumps/logs, 4K textures, perfect for dark fantasy.
4. Define biome data assets in PCG with Megaplants + Dead Forest as source meshes.
5. Pipe existing Python biome density masks into PCG sample points (export as .uasset or runtime-imported PNGs).
6. Hand-model the same aquatic set as Path A. PCG has a water-edge biome layer.
7. Wind: PCG drives Pivot Painter 2.0 wind hierarchy automatically when meshes ship with Pivot Painter data (Megaplants/Dead Forest already include this).

### 7.5 What "AAA foliage" requires (reference)

- 3-4 canopy + 3-4 midstory + 3-4 ground species per biome (minimum).
- GPU instancing (HISM, Nanite). Never spawn individual actors.
- Per-blade GPU grass via compute shader (Ghost of Tsushima approach).
- Wind hierarchy: global vector → trunk sway → branch flutter → leaf noise → gust pulses (5 layers, separate passes).
- Pivot Painter 2.0 vertex-encoded hierarchy.
- LOD: full mesh → reduced poly → card impostors → billboard. Nanite eliminates this.
- SSS leaf transmission shader.
- Ground-cover grounding at tree bases (duff, root flare, bark moss).

---

## 8. Dead Code Cleanup Checklist

Concrete files to delete / sections to remove. Verify each with a grep before deletion.

```
_scatter_engine.py:1134  delete generate_canyon
_scatter_engine.py:1234  delete generate_waterfall
_scatter_engine.py:1328  delete generate_cliff_face
_scatter_engine.py:1416  delete generate_swamp_terrain
_scatter_engine.py:1516  delete generate_sinkhole
_scatter_engine.py:1621  delete generate_floating_rocks
_scatter_engine.py:1727  delete generate_ice_formation
_scatter_engine.py:1819  delete generate_lava_flow
```

Also flagged elsewhere: `procedural_meshes.py` (22,607 lines) is scope contamination in this terrain repo per existing memory `project_procedural_meshes_scope.md`. Out of scope for this guide but should be relocated/removed.

Foliage Python L-system: full retirement after Wave 5 of the new toolchain is producing scenes.

---

## 9. AAA Guardrails — Tests to Add

One regression test per visual domain. Add to test suite before each wave's commit.

| Domain | Test | Pass condition |
|---|---|---|
| Water Z-fight | Render top-down water scene at 200 m, count black speckles in 1024x1024 crop | < 5 pixels |
| Water foam atlas | Verify `stack.get("foam_atlas_path")` exists and PNG decodes after pipeline | non-empty file |
| Water caustics | Verify `pass_caustic_maps` ran (check stack key) | key present |
| Water depth | Beer-Lambert shallow vs deep luminance ratio in test scene | shallow > 1.4x deep |
| Cliff mesh | `stack.get("cliff_face_mesh")` returns dict with verts > 1000 on test cliff | passes |
| Cliff seam | Tile two adjacent chunks; sample strata_band along seam | max delta < 1e-3 |
| Bridge rail C1 | Sample tangent at 100 points along test bridge rail | no angle delta > 5° between adjacent samples |
| Road slope cap | Generate route across 30° slope | no segment exceeds max_grade |
| Foliage density | Run scatter on test biome, count instances vs density-mask integral | within ±5% |
| np.roll seam | Run terrain at 1024x1024, check edge values vs interior in stratigraphy | no anomalous bottom-edge undercuts |
| Channel contract | Schema validator runs on every `stack.set` call | every set channel is in `produces_channels` |

---

## 10. Foliage Tool Comparison Table

| Tool | Cost | Pipeline fit | Pros | Cons |
|---|---|---|---|---|
| **UE5 PCG + Megaplants + Fab Dead Forest** | $0-$50 | Engine-first (UE5) | Free; production AAA assets; Nanite eliminates LOD; wind already authored; PCG handles all scatter logic | Locks pipeline to UE5; rendering quality outside UE5 not guaranteed |
| **The Grove 3D + Geo-Scatter** | ~$325 one-time | Blender-first | Native Blender; Python API on Grove; scriptable from existing code; one-time cost | Manual scatpack authoring; not as polished as Megaplants out of box |
| **SpeedTree Indie** | $19/month | Either (best UE5) | Industry gold standard; KCD2/TW3/Ghost of Tsushima all use it; photogrammetry conversion; auto-LOD | Subscription lock — lapse loses project access; FBX→Blender loses wind/materials |
| **Quixel Megascans (alone)** | $0 (with UE) | UE5 only | Free in UE; photogrammetry quality | No procedural generation — fixed assets only |
| **Current Python L-system** | $0 | Blender | In-repo, scripted | Architecturally cannot reach AAA — RETIRE |

**Recommendation for VeilBreakers (UE5 target):** Path B (UE5 PCG + Megaplants + Dead Forest VOL.32). Lowest cost, highest ceiling, smallest integration effort.

---

## 11. Implementation Sequencing — Wave Plan

Each wave ships a commit with regression tests. No wave starts before previous wave's tests pass.

### Wave 1 — Bug fixes + glass-water elimination (1-2 days)
- §3.1 Delete 8 dead generators in `_scatter_engine.py`
- §3.2 Fix `talus_boulder_placements` channel declaration
- §3.3 Z-fight fix at `environment.py:6949-6951`
- §6.1 Replace 4 np.roll toroidal-wrap bugs
- Add tests: water Z-fight, channel contract, np.roll seam

### Wave 2 — Water wiring (3-4 days)
- §4 Steps 2-4: foam atlas, caustics call, atlas binding
- §4 Steps 5-6: depth atlas, Beer-Lambert shader
- §4 Steps 7-8: mist volumetric fog descriptor, Schlick Fresnel
- Add tests: foam atlas exists, caustic atlas exists, Beer-Lambert ratio

### Wave 3 — Cliff mesh emission + cliff shader (3-5 days)
- §6.2 Implement `generate_cliff_face_mesh`
- Triplanar + stochastic UV + height-banded blend in cliff shader
- Talus instance emission from `talus_boulder_placements`
- Add tests: cliff mesh vert count, cliff seam continuity

### Wave 4 — Bridge + road geometry and routing (3-4 days)
- §5.1 Catmull-Rom rail tangents
- §5.2 Pier plinth/astragal/cutwater
- §5.3 Layered road material
- §5.4-5.6 A* slope heuristic, turn radius post-process, water cost penalty
- §5.7 Switchback ramp+arc+ramp module
- §5.8 Unlock 8 underscore-prefixed APIs
- Add tests: rail C1, road slope cap

### Wave 5 — Water surface motion (2-3 days)
- §4 Step 9: surface normal atlas
- §4 Step 10: flow→wave amplitude
- §4 Step 11: Gerstner waves OR tessellation displacement
- §4 Step 12: VFX particle spec wiring
- Add test: surface normal atlas valid; particle spec list non-empty

### Wave 6 — Foliage toolchain adoption (5-7 days)
- §7.1 Retire Python L-system foliage path
- §7.4 Adopt UE5 PCG + Megaplants + Dead Forest VOL.32 (recommended)
   - Or §7.3 The Grove + Geo-Scatter if Blender-first
- Hand-model aquatic set (3-5 reeds, 2 lily pads, 2 water plants)
- Pipe existing biome masks into PCG / Geo-Scatter
- Add test: foliage density vs mask integral within 5%

### Wave 7 — AAA tooling adoption (optional, 2-4 weeks)
- Evaluate QuadSpinner Gaea 2.2 or World Machine 4 for macro heightmap erosion (Python heightmap is already A-, low priority).
- Evaluate Houdini Indie for procedural scatter/road/biome (only if PCG insufficient).

**Total realistic timeline to AAA-grade visuals:** 4-6 weeks of focused engineering. Waves 1-4 alone (≈2 weeks) close the largest perceptual gap.

---

## Appendix A — File:Line Quick Reference

| Concern | Location |
|---|---|
| Z-fight | `environment.py:6949-6951` |
| Foam orphan | `_water_network_ext.py:711` |
| Mist orphan | `_water_network_ext.py:847` |
| Caustics orphan | `_water_network_ext.py:1048` |
| Wet rock orphan | `_water_network_ext.py:547` |
| Velocity orphan | `terrain_waterfalls.py:1848` |
| Coastal foam orphan | `coastline.py:925` |
| Foam drop site | `terrain_waterfalls.py:2317` |
| Particle drop site | `terrain_waterfalls.py:2327` |
| Gerstner manifest | `terrain_unity_export.py:541` |
| Caustic manifest | `terrain_unity_export.py:519` |
| Cliff mesh stub | `terrain_cliffs.py:2252` |
| Talus channel bug | `terrain_cliffs.py:2612 / 2701` |
| Bridge rail tangent | `_mesh_bridge.py:~380` |
| A* heuristic | `road_network.py:~180` |
| Road mesh spec | `road_network.py:977-1055` |
| np.roll bugs | `terrain_geology_validator.py:60-63`, `terrain_stratigraphy.py:311,336`, `terrain_advanced.py:1700` |
| Edge-repeat template | `terrain_wind_erosion.py:41-89` |
| Dead generators | `_scatter_engine.py:1134, 1234, 1328, 1416, 1516, 1621, 1727, 1819` |

---

**End of guide.** Execute Wave 1 today. Do not skip ahead.
