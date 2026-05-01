# AAA Visual Pipeline v2 — Design Spec
*2026-05-01 | Branch: codex/aaa-terrain-golden-semantics*

## Problem Statement

1. **CPU crash**: Blender runs 9 × Cycles CPU renders (96 spp, 1920×1080) plus 18 000-particle grass.
   GPU fallback silently fails → full CPU lockup.
2. **Tree quality**: Stacked-cone geometry (8-seg) with flat-color Principled BSDF reads as mobile-game
   assets. Alpha-card fresh-node trees are plasticky and uniform.
3. **Water/shoreline glitch**: Beach ring inner edge is 0.05 m *below* water level → Z-fighting.
   Beach colour `(0.075, 0.095, 0.070)` is dark grey-green, indistinguishable from terrain.
4. **Waterfall invisible**: Hero camera looks SSW→NNE; waterfall sits off-frame in NW quadrant.
5. **River invisible at aerial scale**: `water_lift=0.25–0.30 m` on a 1024 m tile is sub-pixel.
6. **Path/bridge crash**: `route_out` grade 55.8 % > 33.5 % budget → RuntimeError.
7. **No GitHub artifact delivery**: Renders never reach the remote branch.

## Root Cause Summary

| Layer | Issue | Severity |
|---|---|---|
| Renderer | Cycles CPU fallback, 9 sequential renders, 18 k particles | **CRASH** |
| Water | Beach Z-fight + wrong colour | **VISUAL** |
| Trees | Low-poly cone + flat BSDF | **VISUAL** |
| Camera | Waterfall outside hero frame | **VISUAL** |
| River | Ribbon too thin for aerial view | **VISUAL** |
| Path | Grade contract too strict for mountain terrain | **LOGIC** |
| CI | Renders not committed to branch | **DELIVERY** |

## Design

### 1. Render Safety System
- Add `_gpu_cycles_available()` probe: tries OPTIX → CUDA → HIP → METAL in order.
- `configure_render()` defaults to **EEVEE NEXT** when no GPU found; Cycles GPU when found.
- `render_orbit()`: always EEVEE NEXT (16 TAA samples), reduced from 8 → 4 frames.
- `add_grass()`: particle count 18 000 → 3 500 (renders identically at scene scale).
- `build_aaa_mountain_pass_node_v1.py`: hero render 96 spp → 48 spp; orbit always EEVEE.

### 2. Water / Shoreline Fix
- Beach inner edge: `LAKE_WATER_LEVEL - 0.05` → `+ 0.04` (eliminates Z-fight).
- Beach colour: `(0.075, 0.095, 0.070)` → `(0.165, 0.142, 0.092)` (warm sandy gravel, readable).
- River ribbon `water_lift`: 0.25/0.30 m → 0.55/0.65 m (visible at aerial camera).

### 3. Tree Quality
- `make_pine_mesh()`: Replace flat BSDF bark with Musgrave-textured Principled BSDF.
  Foliage: SSS 0.10 → 0.22, deeper conifer green `(0.022, 0.085, 0.030)`.
- `make_alpha_card_conifer_mesh()`: Add procedural Musgrave bark + warm SSS foliage.

### 4. Waterfall Visibility
- Add `setup_waterfall_camera()`: positions camera NE of waterfall, looking SW.
- `_run_fresh_scene_build()`: render waterfall hero + include in orbit set.
- Waterfall sheet material: raise base alpha 0.38 → 0.58 for daylight visibility.

### 5. Path Grade Fix
- Increase `route_out` grade budget from 18.5° to 32° (mountain pass traversal).
- Fresh node: restore `build_bridge_and_approach_paths` with relaxed constraint.

### 6. GitHub Artifact Delivery
- `_push_renders_to_github(rc)`: `git add` render PNGs → `git commit` → `git push`.
- Called at end of `main()` regardless of RC (so even partial renders reach GitHub).

## Files Modified
- `scripts/build_scene_v3.py` — renderer, water, trees
- `scripts/build_aaa_mountain_pass_node_v1.py` — render config, cameras, GitHub push

## Success Criteria
- Blender completes without CPU lockup on CPU-only machine.
- Hero + waterfall + 4 orbit renders committed to remote branch.
- Shoreline shows warm sandy beach transition (no Z-fight).
- Trees have visible bark texture variation.
- Waterfall is in-frame for at least one render.
