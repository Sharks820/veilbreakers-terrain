# VeilBreakers Camera and Render Pipeline Audit
**Audit date:** 2026-04-24
**Files audited:**
- `scripts/build_scene_v3.py`
- `scripts/render_closeups_v3.py`
- `veilbreakers_terrain/handlers/terrain_unity_export.py`
- `veilbreakers_terrain/src/veilbreakers_mcp/blender_server.py`

Tile bounds: X/Y = [-512, +512], Z valid range ≈ [-21, +388] (actual heightmap: min -20.8m, max 387.7m per BUILD_SUMMARY.json).

---

## A. CAMERA BOUNDARY AUDIT

### Reference Points (from script constants)
| Feature | World Position |
|---|---|
| Spring | X=-300, Y=250 |
| Waterfall XY | X=-150, Y=50, top Z=140 |
| Lake center | X=100, Y=-300, water level Z=8 |
| Cave entry | X=0, Y=100, Z=180 |
| Cave exit | X=400, Y=100, Z=180 |
| Mountain peak (nominal) | Z=320 (actual heightmap peak ~388) |

### build_scene_v3.py — Cameras

**CAM_Hero** (`setup_hero_camera`, line 1150–1164)
- Location: `(-60, -700, 180)`
- Target: `(80, -80, 50)`
- Lens: 32mm | Clip end: 4000m
- Bounds check: X=-60 OK. **Y=-700 is OUT OF TILE by 188m** (tile south edge is -512). Camera sits 188m south of the tile boundary in empty space.
- Clipping: Z=180 with terrain near Y=-700 is near-zero height (flatland ~3-8m), so camera is 172m above ground — no geometry intersection.
- Severity: HIGH. The camera is completely outside the tile. At 188m south of bounds, viewing the scene at a shallow angle, the lower half of the frustum will show void/sky below the terrain edge. Depends on tile edge treatment.

**CAM_CavePOV** (`setup_cave_pov_camera`, line 1167–1180)
- Location: `(-30, 70, 175)`
- Target: `(8, 115, 180)` (CAVE_ENTRY + offset)
- Lens: 24mm | Clip end: 800m
- Bounds check: X=-30 OK, Y=70 OK, Z=175.
- Z check: Terrain at X=-30, Y=70 is in the Y=0..100 mountain transition band. The cliff step puts terrain at this XY at roughly 60-100m. Camera Z=175 is above terrain — no clipping.
- Status: IN BOUNDS. No clipping issue.

**CAM_Orbit** (`render_orbit`, line 1220–1239) — dynamically positioned
- Radius: 480m, Height: 420m
- All 8 frame positions: radius=480, center=(0,0,80), angle offset=22°
  - Frame 0: ang = 0.384 rad → X = 480·cos(0.384) = +444, Y = 480·sin(0.384) = +179, Z=420
  - Frame 1: ang = 1.169 rad → X = +225, Y = +424, Z=420
  - Frame 2: ang = 1.954 rad → X = -152, Y = +457, Z=420
  - Frame 3: ang = 2.739 rad → X = -432, Y = +223, Z=420
  - Frame 4: ang = 3.524 rad → X = -444, Y = -179, Z=420
  - Frame 5: ang = 4.309 rad → X = -225, Y = -424, Z=420
  - Frame 6: ang = 5.094 rad → X = +152, Y = -457, Z=420
  - Frame 7: ang = 5.879 rad → X = +432, Y = -223, Z=420
- Bounds check: All X values: max +444, min -444 → **max |X| = 444 < 512. IN BOUNDS.**
- All Y values: max +457, min -457 → **max |Y| = 457 < 512. IN BOUNDS.**
- Z=420. Terrain max is ~388. Camera is 32m above the highest peak. No geometry clipping.
- Orbit target: `(0, 0, 80)`. Tile center + 80m elevation. Reasonable framing.
- Status: All 8 orbit positions IN BOUNDS. No clipping.

---

### render_closeups_v3.py — Cameras (12 total)

| # | Name | Location (X, Y, Z) | Target (X, Y, Z) | X in [-512,512] | Y in [-512,512] | Z clipping risk |
|---|---|---|---|---|---|---|
| 1 | CAM_TileOverview | (0, -80, 1100) | (0, 0, 0) | OK | OK | Z=1100 well above terrain. OK |
| 2 | CAM_Hero2 | (-60, **-480**, 180) | (80, -80, 50) | OK | OK (edge: -480 < -512 gap=32) | Z=180 above ~3m terrain. OK |
| 3 | CAM_CavePortal | (-18, 80, 178) | (8, 130, 182) | OK | OK | Z=178, terrain at cave entry ~180. **RISK: camera at Z=178 may be inside mountain at Y=80, X=-18. Mountain terrain at this XY with cliff step could be 100-180m+. Needs verification.** |
| 4 | CAM_CaveInterior | (120, 105, 178) | (400, 100, 180) | OK | OK | Cave tunnel interior — Z=178 is on the cave centerline (Z=180). Z is 2m below centerline but within the cave radius (6m). OK inside tunnel. |
| 5 | CAM_Waterfall | (-190, 32, 152) | (-150, 50, 120) | OK | OK | Waterfall top Z=140, camera Z=152. Terrain at X=-190, Y=32 is cliff-band region (~60-100m). Camera above. OK |
| 6 | CAM_RiverBankEntry | (-50, -20, 48) | (-25, -55, 40) | OK | OK | River bank area, terrain ~42-48m. Camera at Z=48 grazes bank. Low clipping risk but could intersect raised bank geometry (+4.8m profile puts terrain to ~47m here). |
| 7 | CAM_LakeBankExit | (-42.5, -280, 9.8) | (-187.5, -265, 11) | OK | OK | Z=9.8 is 1.8m above water level. Beach ring area. Low clipping risk. |
| 8 | CAM_LakePanorama | (20, -420, 50) | (100, -200, 160) | OK | OK | Southern lake approach. Z=50, terrain at Y=-420 flatland ~3-8m. Well above. OK |
| 9 | CAM_LakeShoreline | (272.5, -300, 12) | (70, -300, 9) | OK | OK | East shore of lake. Beach ring outer radius ~202.5m from lake center. Camera at shore level Z=12. OK |
| 10 | CAM_CliffFace | (80, -120, 130) | (80, 20, 140) | OK | OK | South face of mountain, above cliff band. Z=130, terrain at X=80, Y=-120 is ~40-60m. Camera elevated. OK |
| 11 | CAM_MountainPeak | (-50, 350, 340) | (80, -180, 30) | OK | OK | Y=350 is in-bounds (< 512). Z=340, mountain peak actual ~388 at ridge. Camera Z=340 is **below the actual peak by 48m** — may be embedded in mountain geometry near ridge. **RISK.** |
| 12 | CAM_ForestCanopy | (-180, 150, 110) | (-120, 50, 60) | OK | OK | Forested slope. Mountain ramp at Y=150 (t≈0.29) puts base at ~70m + noise + cliff. Camera Z=110 may be close to or inside terrain. **MODERATE RISK.** |

**Derived positions for row 7 (CAM_LakeBankExit):**
- `LAKE_XY[0] - LAKE_RADIUS * 0.95 = 100 - 142.5 = -42.5`
- `LAKE_XY[1] + 20 = -280`
- `Z = LAKE_WATER_LEVEL + 1.8 = 9.8`

**Derived positions for row 8 (CAM_LakePanorama):**
- `LAKE_XY[0] - 80 = 20`, `LAKE_XY[1] - 120 = -420`

**Derived positions for row 9 (CAM_LakeShoreline):**
- `LAKE_XY[0] + LAKE_RADIUS * 1.15 = 100 + 172.5 = 272.5`
- `LAKE_XY[1] = -300`
- `Z = LAKE_WATER_LEVEL + 4 = 12`

---

### BOUNDARY VIOLATIONS SUMMARY

| Camera | Script | Violation | Magnitude |
|---|---|---|---|
| CAM_Hero | build_scene_v3.py | Y=-700, tile south = -512 | **OUT BY 188m** |
| CAM_Hero2 | render_closeups_v3.py | Y=-480, within bounds but 32m from edge | Marginal (in-bounds) |

**CAM_Hero in build_scene_v3.py is the only hard out-of-bounds camera.** Y=-700 vs tile edge -512 = 188m outside. This camera renders `render_hero.png` at 96 spp as the hero establishing shot.

---

### CLIPPING RISK SUMMARY

| Camera | Risk | Reason |
|---|---|---|
| CAM_CavePortal | HIGH | Location Z=178, terrain at X=-18, Y=80 with cliff band could be 150-175m. Camera may be embedded in hillside. |
| CAM_MountainPeak | MEDIUM-HIGH | Z=340, actual heightmap max is ~388 at ridgeline. At Y=350, X=-50 this is deep in the ridge zone. Camera likely inside mountain. |
| CAM_ForestCanopy | MEDIUM | Z=110, slope at Y=150 with cliff adds up to ~100-130m. Close to terrain surface. May self-intersect near-clip plane. |
| CAM_RiverBankEntry | LOW | Z=48, raised bank geometry peaks at ~47m. Very close to bank top. |

---

## B. SAMPLE COUNT AUDIT

### build_scene_v3.py

| Render | Call site (line) | Samples | Resolution | Grade |
|---|---|---|---|---|
| Hero establishing (`render_hero.png`) | line 1328: `configure_render(samples=96, ...)` | **96 spp** | 1920x1080 | **FAIL — below 128 AAA minimum for hero** |
| Orbit (8 frames, `render_orbit`) | line 1224: `configure_render(samples=96, ...)` | **96 spp** | 1280x720 | **PASS** (requirement 96) |

Note: `configure_render` default parameter is `samples=64` (line 1186), but the hero render overrides this at line 1328 with `samples=96`. The 64 default is never used in main().

### render_closeups_v3.py

| Render | Call site | Samples | Resolution | Grade |
|---|---|---|---|---|
| All 12 closeup shots | line 92: `configure_render(samples=48, ...)` | **48 spp** | 1920x1080 | **FAIL — below 96 AAA minimum for closeups** |

### GRADE TABLE

| Shot type | AAA Minimum | Actual | Grade |
|---|---|---|---|
| Hero establishing | 128 spp | 96 spp | **F (−32 spp)** |
| Orbit turntable | 96 spp | 96 spp | **PASS** |
| Closeups (12 shots) | 96 spp | 48 spp | **F (−48 spp, half AAA minimum)** |

**Two of three render classes are below AAA minimum. The orbit fix (24→96) is confirmed in place. The closeup fix to 96 spp was NOT applied — still at 48. The hero shot was also not raised to 128.**

---

## C. GPU CONFIGURATION

### Required 2-step pattern:
```python
cp.preferences.compute_device_type = 'OPTIX'
cp.preferences.get_devices()
for d in cp.preferences.devices:
    d.use = True
scn.cycles.device = "GPU"
```

### build_scene_v3.py — `configure_render` (lines 1200–1211)
```python
cp.preferences.compute_device_type = 'OPTIX'
cp.preferences.get_devices()
for d in cp.preferences.devices:
    d.use = True
scn.cycles.device = "GPU"
```
Status: **PRESENT AND CORRECT.** Full 4-step pattern verified. All steps in correct order.

### render_closeups_v3.py — `configure_render` (lines 71–80)
```python
cp.preferences.compute_device_type = 'OPTIX'
cp.preferences.get_devices()
for d in cp.preferences.devices:
    d.use = True
scn.cycles.device = "GPU"
```
Status: **PRESENT AND CORRECT.** Full 4-step pattern verified. Commit bcc7bac fix is confirmed applied.

**GPU configuration: PASS in both scripts.**

---

## D. COLOR MANAGEMENT

### build_scene_v3.py — `configure_render` (lines 1195–1199)
```python
scn.view_settings.view_transform = "AgX"
scn.view_settings.exposure = 0.0
scn.view_settings.look = "AgX - Medium High Contrast"
```
Status: **PASS.** AgX with "Medium High Contrast" look. No Filmic.

### render_closeups_v3.py — `configure_render` (lines 65–69)
```python
scn.view_settings.view_transform = "AgX"
scn.view_settings.look = "AgX - Medium High Contrast"
```
Status: **PASS.** AgX with "Medium High Contrast" look. No Filmic. Exposure not set (no `exposure = 0.0` line), but defaults to 0 — minor omission, not a bug.

**One minor gap: render_closeups_v3.py does not explicitly set `scn.view_settings.exposure = 0.0`. This is not a bug (Blender default is 0) but is an inconsistency with build_scene_v3.py's defensive approach.**

---

## E. ORBIT SYSTEM

### Radius fix verification
`render_orbit` in build_scene_v3.py (line 1221): `radius: float = 480.0`

**CONFIRMED fixed from 640 → 480m.** At radius 480m the camera sits 32m inside tile bounds on all 8 axes — safe margin.

### Frame count and height variation
- Frames: 8
- Height: fixed at `height: float = 420.0` (constant, no variation)
- Target: `(0, 0, 80)` — tile center, 80m elevation
- Angle offset: +22° to avoid pure-north shadow position

**Height variation: NONE.** All 8 frames are at the same Z=420. This means all orbit frames show the same elevation angle (looking down at identical pitch). A proper AAA orbit would vary height between frames (e.g., 3 low/mid/high passes) to show different sides of the mountain. A fixed Z=420 shooting at target Z=80 gives a depression angle of `atan((420-80)/480) ≈ 35°` on every frame — the orbit only rotates azimuth, not elevation. **8 frames all at 35° depression is weak for showcasing terrain relief.**

### Below-terrain check
At Z=420 with the mountain peak at ~388m actual (heightmap max), the orbit camera at Z=420 is 32m above the highest terrain point. The orbit never goes below terrain. **No below-terrain issue.**

### Orbit coverage gaps
- No low-angle (horizon) frame to show cliff faces from the south
- No high oblique (60°+ elevation) frame to show overhead tile layout
- The 8-frame 1280×720 orbit at 96 spp is functional but artistically flat (single elevation band)

---

## F. AGENT VIEW FUNCTIONS — Gameplay-Driven Camera Placement

### Are cameras driven by gameplay data?

**No.** All cameras in both scripts use hard-coded world coordinates. There is no code that reads player spawn points, combat zone bounds, or portal landmark tables from a data file or the terrain pipeline. Positions are authored constants.

### Scene Feature vs Camera Target Analysis

| Feature | Scene position (script constant) | Closest camera targeting it | Alignment assessment |
|---|---|---|---|
| Cave entry portal | (0, 100, 180) | CAM_CavePortal: location=(-18, 80, 178), target=(8, 130, 182) | Good — 15m outside entrance, looking in at correct angle |
| Cave exit | (400, 100, 180) | CAM_CaveInterior: target=(400, 100, 180) | Exact target match |
| Waterfall top | (-150, 50, 140) | CAM_Waterfall: target=(-150, 50, 120) | Correct XY, target Z=120 is 20m below top — misses spray/crest. Camera is to SW. Reasonable. |
| Lake center | (100, -300) | CAM_LakePanorama, CAM_LakeShoreline | Panorama doesn't target lake center; targets (100, -200, 160). CAM_LakeShoreline targets (70, -300, 9) — close to lake center. |
| Mountain peak | nominal Z=320, actual ~388 at Y~320 | CAM_MountainPeak: location=(-50, 350, 340) | Camera placed near peak but Z=340 is below actual maximum — may be embedded in ridge. Target looks down to flatland correctly. |
| Player spawn | Not defined in scripts | None | No player spawn concept exists in either render script. |
| Combat zones | Not defined | None | No combat zone-driven cameras. |

### Key gap: No gameplay-data-driven placement
The render pipeline has no connection to any gameplay systems. All 14 cameras are pure art-direction positions. For a dark fantasy open-world game, the hero shot and closeup cameras should be informed by: player spawn position, major landmark sight-lines, combat arena bounds. This wiring does not exist in either script.

---

## G. RENDER OUTPUT

### Where renders go
- Hero render: `output/scene_v3/render_hero.png`
- Orbit: `output/scene_v3/orbit/orbit_00.png` ... `orbit_07.png` (8 frames)
- Closeups: `output/scene_v3/closeups/01_tile_overview.png` ... `12_forest_canopy.png` (12 frames)
- Build summary: `output/scene_v3/BUILD_SUMMARY.json`
- Blend file: `output/scene_v3/VeilBreakers_Scene_v3.blend`

### Are renders committed to git?
**YES — all render outputs are tracked in git.** `git ls-files` shows all 21 PNGs (1 hero + 8 orbit + 12 closeups) and BUILD_SUMMARY.json are committed. The `.gitignore` does NOT exclude `output/scene_v3/`. Committing binary PNGs and .blend files to git is problematic for repo size (binary bloat, no delta compression). The `.blend1` backup file is also present on disk but not tracked.

### Unity export path
`terrain_unity_export.py` writes to a caller-supplied `output_dir: Path`. The MCP dispatch key `"unity_export"` resolves to `"env_export_unity_bundle"` in blender_server.py. The Unity export pipeline produces: `heightmap.raw`, `terrain_normals.bin`, `splatmap_*.raw`, `detail_density__*.raw`, `manifest.json`, `unity_import_descriptor.json`, `water_shader_manifest.json`, and a suite of JSON zone files. **No direct connection exists between the Blender render pipeline (`build_scene_v3.py`) and the terrain Unity export pipeline (`terrain_unity_export.py`).** Rendered PNGs are not included in the Unity export bundle — this is correct and expected.

### Render pipeline wiring gaps in blender_server.py

1. **No render-camera MCP entry.** `blender_server.py` has `"render_still": "blender_render_still"` and `"render_engine": "blender_set_render_engine"` but has no `"render_hero"`, `"render_orbit"`, `"render_closeups"` entries. The full scene render passes in `build_scene_v3.py` are not triggerable via MCP dispatch. An MCP client cannot request a hero render or closeup pass by name.

2. **`visual_setup_camera` → `visual_qa_setup_camera` exists** (line 54) but it resolves to a visual QA handler, not the scene-level camera setup. No `"camera_hero"`, `"camera_orbit"`, or `"camera_closeup"` keys exist in `_LOC_HANDLERS`.

3. **No render output path control via MCP.** There is no handler entry for setting or querying the output directory, so MCP clients cannot redirect renders to alternate paths (e.g., per-session output folders).

4. **The `unity_export` key (line 91)** is present and wired. Unity export IS triggerable via MCP. This is the one correctly wired pipeline.

---

## FIXES REQUIRED (priority order)

### P0 — Must fix before any asset review

**FIX 1: CAM_Hero Y coordinate out of bounds (build_scene_v3.py line 1158)**
```python
# CURRENT (wrong):
cam.location = (-60.0, -700.0, 180.0)
# FIX: Move to Y=-440 (72m inside south tile edge = -512)
# At Y=-440 with target (80,-80,50) the distance is ~365m, appropriate for 32mm establishing shot.
cam.location = (-60.0, -440.0, 180.0)
```
Rationale: Y=-700 is 188m outside the tile. The hero shot is the primary portfolio image. Camera must be inside or at most 1-2m outside for billboard/atmosphere framing.

**FIX 2: Closeup sample count (render_closeups_v3.py line 92)**
```python
# CURRENT:
configure_render(samples=48, res_x=1920, res_y=1080)
# FIX:
configure_render(samples=96, res_x=1920, res_y=1080)
```
48 spp is half the AAA minimum. All 12 closeup shots will have visible noise in shadows, foliage, and water.

**FIX 3: Hero render sample count (build_scene_v3.py line 1328)**
```python
# CURRENT:
configure_render(samples=96, res_x=1920, res_y=1080)
# FIX:
configure_render(samples=128, res_x=1920, res_y=1080)
```
Hero establishing shot is the single most important render for showcase and review. 96 spp leaves visible noise in sky and mountain gradients. 128 minimum is the AAA bar for hero shots.

### P1 — Fix before next wave of renders

**FIX 4: CAM_MountainPeak Z clipping (render_closeups_v3.py line 190)**
```python
# CURRENT:
location=(-50.0, 350.0, 340.0),
# FIX: Raise to Z=420 — 32m above actual heightmap max (387.7m)
location=(-50.0, 320.0, 420.0),
# Also pull Y back from 350 to 320 to be on the near-ridge approach, not inside it
```
At the ridgeline Y≈320-380, X=-50, terrain reaches 350-388m. Camera Z=340 is embedded in the mountain.

**FIX 5: CAM_CavePortal clipping check (render_closeups_v3.py line 116)**
```python
# CURRENT:
location=(CAVE_ENTRY[0] - 18.0, CAVE_ENTRY[1] - 20.0, CAVE_ENTRY[2] - 2.0),
# = (-18, 80, 178)
# FIX: Add a 4m safety lift and pull slightly further south
location=(CAVE_ENTRY[0] - 20.0, CAVE_ENTRY[1] - 28.0, CAVE_ENTRY[2] + 4.0),
# = (-20, 72, 184)
```
At Y=80, X=-18 the terrain is in the mountain transition zone with cliff banding. Z=178 is within 2m of the cave centerline at Z=180 and likely inside the hillside.

**FIX 6: CAM_ForestCanopy Z lift (render_closeups_v3.py line 199)**
```python
# CURRENT:
location=(-180.0, 150.0, 110.0),
# FIX:
location=(-180.0, 150.0, 135.0),
```
At Y=150 the mountain ramp plus cliff banding can reach 100-125m. A 25m lift puts the camera safely above the canopy zone.

### P2 — Quality improvements

**FIX 7: Orbit height variation**
Change `render_orbit` to step through 3 height bands across the 8 frames. Suggested: frames 0-2 at Z=280 (low, shows cliff faces), frames 3-5 at Z=420 (mid), frames 6-7 at Z=580 (high, shows tile overview). All radii at 480m.

**FIX 8: MCP render dispatch entries**
Add to `blender_server.py _LOC_HANDLERS`:
```python
"render_hero": "blender_render_hero_shot",
"render_orbit": "blender_render_orbit",
"render_closeups": "blender_render_closeups",
```
And register corresponding handlers so the render pipeline is fully MCP-addressable.

**FIX 9: Remove render PNGs from git**
Add to `.gitignore`:
```
output/scene_v3/*.png
output/scene_v3/orbit/
output/scene_v3/closeups/
output/scene_v3/*.blend
output/scene_v3/*.blend1
```
Keep BUILD_SUMMARY.json tracked. Use a render artifact host or LFS for binary outputs. Current tracked binary: 21 PNGs + 1 blend = significant repo weight.

**FIX 10: render_closeups_v3.py — add explicit exposure = 0.0**
```python
scn.view_settings.exposure = 0.0
```
Add after `view_transform = "AgX"` for parity with build_scene_v3.py.

---

## SUMMARY TABLE

| Section | Status | Severity |
|---|---|---|
| CAM_Hero out of bounds (Y=-700) | FAIL — 188m outside tile | P0 |
| All other cameras in bounds | PASS | — |
| Hero spp (96 vs 128 minimum) | FAIL | P0 |
| Closeup spp (48 vs 96 minimum) | FAIL | P0 |
| Orbit spp (96) | PASS | — |
| GPU OPTIX pattern — build_scene_v3 | PASS | — |
| GPU OPTIX pattern — render_closeups_v3 | PASS | — |
| AgX Medium High Contrast — build_scene_v3 | PASS | — |
| AgX Medium High Contrast — render_closeups_v3 | PASS | — |
| Orbit radius (480m, was 640) | PASS | — |
| Orbit height variation | FAIL — single height band | P2 |
| CAM_MountainPeak likely inside terrain | FAIL | P1 |
| CAM_CavePortal possible Z clipping | WARN | P1 |
| CAM_ForestCanopy close to terrain | WARN | P1 |
| Gameplay-driven camera placement | NOT IMPLEMENTED | P2 |
| Render outputs in git (binary bloat) | WARN | P2 |
| MCP render dispatch wiring | PARTIAL | P2 |
| Unity export → render coupling | N/A (correct separation) | — |
