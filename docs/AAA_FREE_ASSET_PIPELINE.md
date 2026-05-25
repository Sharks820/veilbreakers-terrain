# AAA Free Asset Pipeline — CC0 foliage + terrain PBR (2026-05-25)

How the hero render gets real AAA foliage and terrain texturing **for free**,
and how it's wired into the production builder. Read this before touching
foliage, terrain materials, or the showcase render.

## Governing rule (unchanged)

**Python owns placement; third-party tools only author meshes/textures.** We do
not depend on any Blender addon at render time (they break under
`blender --background`). Instead we download **static asset files** (glTF +
PBR texture sets) once, then our own Bridson scatter places them headlessly.
This is why Geo-Scatter/Botaniq were dead-ends but Poly Haven CC0 works.

## Pieces

| File | Role |
|------|------|
| `scripts/_fetch_cc0_foliage.py` | Downloads CC0 models + texture sets from the **Poly Haven public API** (all CC0). `--list`, `--list-tex`, `--get <id> <cat>`, `--curated`, `--curated-tex <ids>`. |
| `scripts/aaa_render_visuals.py` | Terrain material (procedural **and** triplanar-PBR), dim sky, flat-plane water. The single source of truth imported by the builder. |
| `scripts/aaa_asset_foliage.py` | Imports the glTF assets and scatters them in ecological strata (`scatter_asset_biome`). |
| `scripts/build_terrain_aaa_node_v8.py` | Production builder — calls the above after generating the terrain. |
| `scripts/_hero_polish2.py` | Fast iteration on the saved `.blend` (~2–3 min/loop vs ~14 min full pipeline): applies the shared modules + a data-driven shoreline camera, renders to `output/hero_iter/`. |

## Asset layout (git-ignored — do not commit; large)

```text
assets/foliage_cc0/<category>/<asset_id>/<id>_1k.gltf + .bin + textures/
assets/terrain_pbr/<texture_id>/<id>_{diff,nor_gl,rough}_1k.jpg
```

Acquire with: `python scripts/_fetch_cc0_foliage.py --curated` (foliage kit) and
`--curated-tex forest_ground_04 aerial_rocks_02 dry_ground_rocks coast_sand_01`.

### What works / gotchas
- **glTF 1k** is the right format (importable headless via `bpy.ops.import_scene.gltf`; textures resolve via the relative `textures/` path). Materials come through; orientation is Z-up.
- **Skip geometry-nodes hero assets for scatter** — e.g. `fir_tree_01` baked to **457 MB / millions of verts**. Photoscan assets are light (fern ~1 MB, grass ~3 MB, boulder ~5 MB, `island_tree` ~64 MB / 1.3M verts → decimate).
- **Decimate** heavy trees (`island_tree` → ratio ~0.12) before instancing thousands.
- **Recenter origin to bbox bottom** on import so instances sit ON the ground (see `_import_templates`).
- Poly Haven plant catalog is finite and biome-limited; for more variety/quality add **Graswald free (145 species FBX)**, or pay for **SpeedTree Indie ($199/yr)** (also exports `.ST` for Unity).

## Terrain material (kills the "architecture render" look)

`make_terrain_material_pbr()` — real scanned PBR via **triplanar** (Blender
`ShaderNodeTexImage.projection = "BOX"` = triplanar in one node, no UVs needed):
- 4 CC0 sets → biomes: `forest_ground_04`→vegetation, `aerial_rocks_02`→rock,
  `dry_ground_rocks`→scree, `coast_sand_01`→shore; snow procedural.
- Blended by **slope+height masks broken with two-scale noise** so cliffs show
  no constant-elevation contour "layers".
- Falls back to the fully-procedural `make_terrain_material_aaa()` if the
  texture sets are missing (pipeline never hard-fails on missing assets).

## Foliage (ecological strata)

`scatter_asset_biome(terrain, water_z)` — `LIBRARY_SPEC` maps assets to 6 layers
(canopy / understory / grass / ground / deadfall / rock); `LAYER_PARAMS` sets per-layer
spacing, slope/height limits, instance caps, and ground-sink. Each layer is a
Bridson (cluster-density) scatter, raycast onto the displaced terrain, with
water/slope/treeline rejection. Add assets by editing `LIBRARY_SPEC`.

## Sky / water
- `setup_aaa_sky()` — dim cool gradient. **Do not use a bright Nishita dome**: under the scene's AgX view transform it washes the whole render to milky haze.
- `build_aaa_water()` — flat plane at the water level → shoreline = terrain∩plane (organic, no blocky footprint edge); reflective + ripple normal.

## Pipeline integration
`build_terrain_aaa_node_v8.py` calls (after terrain gen): the terrain material,
`setup_aaa_sky`, `build_aaa_water`, and the foliage scatter — each in a guarded
`try/_fail` block so a missing-asset case degrades gracefully rather than
crashing the build.

## Best-practices audit (AAA terrain) — applied & deferred

Audited against Horizon ZD GPU placement (GDC 2017), Golus/selfshadow normal-blend, Heitz/Deliot stochastic tiling, Crest water.

**Applied:**
- **Procedural Bump (scalar height → normal) is the PRIMARY terrain detail** — geometrically correct and projection-independent. Scanned tangent-normal kept at LOW strength (0.18) for character only.
- **Vegetation tilts to the terrain normal** (`LAYER_ALIGN`): grass 0.65, ground 0.6, understory 0.4; trees/rocks upright (0.0). Horizon ZD convention.
- **Bases buried into terrain** (`z_sink`; rocks/logs ~32 % of height) — fixes floating; recenter origin to a low Z percentile (not abs-min) so trunks don't hover.
- Macro/meso/micro relief stack; pointiness cavity; **noise-broken biome thresholds** (no contour bands).
- **Shoreline**: wet darkening + foam line + wet sheen at the waterline.
- Scatter: Poisson + cluster-density + slope/water/height **exclusion masks**; raycast onto the **DISPLACE-evaluated** surface (force `view_layer.update()` first).

**Deferred (known correct-but-not-yet):**
- Triplanar tangent-normal is RGB-lerp blended (Golus: incorrect); **mitigated** by low strength + procedural-bump-primary. Proper fix = UDN blend + per-axis swizzle node group.
- Water **depth-colour** (shallow→deep) needs a depth pass; currently approximated by the terrain shore band. Crest (vendored) is the runtime answer.
- Vegetation **base alpha-fade ramp** (vertex-colour) to remove the hard intersection seam — sinking only for now.
- **Height/depth-blend** for biome transitions (currently noise-broken linear mix).
- Stochastic/hex anti-tiling on scanned maps (not needed yet — albedo is procedural, normals are low-strength).

## Verified
- glTF headless import + materials + decimate + recenter: ✅ (2026-05-25).
- Full pipeline reproduces the iter14 look end-to-end: ✅ — `build_terrain_aaa_node_v8.py`
  rendered all 5 cameras at 1025-res with the CC0 terrain/sky/water/foliage
  (`output/aaa_node_v8/render_Cam_*.png`, 2026-05-25 04:14). The generator's
  `validation_full` pass reports a pre-existing PARTIAL that is unrelated to the
  post-generation visual layer (tracked separately).
- Asset biome scatter (~30K instances), grounding, grass layer, PBR-hybrid terrain: ✅ (iter13/iter14).
