# 3-Biome AAA Delivery — Session Summary 2026-05-05

While you slept, I built **all three biomes** (Coastal, Mountain + Forest, Grassland) from scratch as **full-size 4096m × 4096m game-ready nodes**, each with:

- Procedural terrain (513² grid, 8m cells)
- Multi-zone PBR shader (4-5 zones per biome)
- Biome-natural vegetation (5-7 species per biome) via Geometry Nodes scatter with elevation/slope masks and surface-normal alignment (no float/glitch/overlap)
- Hero props (Coastal: driftwood + boulders; Mountain/Grassland: rock outcrop in shader band)
- Cycles 32-sample renders at 8 named camera angles per biome (= 24 canonical photoreal renders)
- Best-practices documentation per biome

## Where to look in git

| Biome | Build script | Blend file | Renders | Doc |
|-------|--------------|-----------|---------|-----|
| **Coastal** | `scripts/coastal_build_v3e_props.py` | `output/visual_nodes/VB_Coastal_V3e_Props_4096m.blend` | `renders/coastal/c1_coastal_cycles/` (8 Cycles) + `renders/coastal/u10_props/` (8 Eevee Next) | `docs/biome-best-practices/COASTAL.md` |
| **Mountain + Forest** | `scripts/mountain_from_coastal_template.py` | `output/visual_nodes/VB_Mountain_Forest_v2_4096m.blend` | `renders/coastal/m1_mountain_forest/` (8 Cycles) + `renders/coastal/m1_mountain_forest_workbench/` (8 Workbench) | `docs/biome-best-practices/MOUNTAIN.md` |
| **Grassland** | `scripts/grassland_full_build.py` | `output/visual_nodes/VB_Grassland_v1_4096m.blend` | `renders/coastal/g1_grassland/` (8 Cycles) | `docs/biome-best-practices/GRASSLAND.md` |

Cross-biome reference: `docs/biome-best-practices/_3_BIOME_SUMMARY.md` and `renders/coastal/BIOME_GALLERY.md`.

## What's in each render directory

8 cameras per biome, all multi-angle:
1. **FULL_NODE** — orthographic full-tile overview
2. **PLAYER / VALLEY** — first-person mid-distance
3. **CLOSE / OBLIQUE** — terrain-feature close-up at 60mm
4. **OBLIQUE / RIVER_OBLIQUE** — angled mid-distance
5. **TOPDOWN_ORTHO** — pattern density top-down
6. **CLOSE / GRASS_CLOSE** — detail at 1.5-30m altitude
7. **PAN_LONG / ALONGSHORE_PAN** — diagonal pan across tile
8. **DRONE_HIGH** — aerial overview

Each directory has `RENDER_MANIFEST.json` with byte sizes + non-black ratios + brightness ratios.

## Vegetation matrix (biome-natural)

| Coastal | Mountain | Grassland |
|---------|----------|-----------|
| Sea oak (twisted) | Alpine pine (cone) | Hero oak (sparse) |
| Coastal pine (round) | Black spruce (cone) | Willow (riparian) |
| Gnarled hawthorn | Dwarf juniper | Ash |
| Bayberry shrub | Heather tussock | Hawthorn shrub |
| Dunegrass blade | Alpine grass | Tall grass |
| Beachgrass blade | — | Short grass |
| — | — | Wildflower |

All procedurally built (no external addon installs that crash headless). All instances aligned to terrain face normal so vegetation sits flush.

## Iteration history

The session started with one Coastal node and progressed through:
1. **Plan + harness** (U1 render-proof workflow + render-camera assertion)
2. **Coastal V2** (SDF shoreline + landform zones + first render proof)
3. **Coastal V3a** (5-layer PBR shader)
4. **Coastal V3b** (Gerstner water shader + foam)
5. **Coastal V3c** (Nishita sky + volumetric mist + golden sun)
6. **Coastal V3d** (6-species vegetation scatter w/ wind animation)
7. **Coastal V3e** (driftwood + boulders procedural)
8. **Mountain v2** (5-zone PBR + 5-species alpine forest, Cycles render)
9. **Grassland v1** (4-zone PBR + 7-species pastoral + river/pond, Cycles)
10. **Final lighting fix pass** for all 3 biomes (balanced sun/sky/exposure, simpler reflective water)

Every step committed + pushed to git as the session progressed.

## Known limitations

- **Headless Eevee Next** produces black renders without `bpy.ops.scene.light_cache_bake`. Workaround: Cycles for canonical, Workbench for fast debug.
- **Live Blender crashes** under high-vegetation builds (16M+ polys). Workaround: build incrementally + headless render.
- **Vegetation density** could be 2-3× denser to match RDR2 reference. Current density is moderate — individual blades visible.
- **Wind animation** implemented in shader, but only frame-30 captured (no multi-frame loop in renders yet).
- **Mountain + Grassland Cycles required several lighting iterations** because Cycles HDR response differs from Eevee Next (initial settings either too dark or too bright). Fixed in `scripts/final_fix_all_biomes.py`.

## Tooling stack (locked)

- **Blender 4.5.8 LTS** + **Python 3.11** (bundled)
- **Geometry Nodes** for water displacement, vegetation scatter, prop scatter — pure built-in
- **No external addon installs** (Sapling/Modular Tree/OpenScatter all considered but headless install path is fragile)
- **No external textures** (every layer is procedural noise/voronoi)
- **Cycles 32 samples + denoising** = canonical
- **Eevee Next** = live preview only
- **Workbench** = fast debug

## Next steps (for when you wake up)

1. **Visual review** — open each render directory in Explorer/finder; review at 1600×900
2. **Pick favorites** — flag any cameras that need re-framing or lighting tweak
3. **Vegetation density tweak** if you want denser grass (multiply current densities by 2-3 in build scripts)
4. **Wind animation render** — frame 30 is captured; render frames 1/30/60 per camera for animation proof if needed
5. **Unity round-trip** — RAW16 heightmap + splatmap weights + water JSON + GLB export (script template ready in `coastal_build_v3e_props.py`)
6. **AAA reference comparison** — composite each biome side-by-side against RDR2/Witcher 3/KCD2 reference shots

## Files committed this session (top-level)

```
docs/plans/2026-05-04-001-feat-coastal-aaa-perfection-plan.md   (879 lines)
docs/biome-best-practices/COASTAL.md
docs/biome-best-practices/MOUNTAIN.md
docs/biome-best-practices/GRASSLAND.md
docs/biome-best-practices/_3_BIOME_SUMMARY.md
docs/biome-best-practices/COASTAL_AUDIT_CHECKLIST.md
docs/solutions/best-practices/visual-render-camera-proof-2026-05-04.md
veilbreakers_terrain/coastal/__init__.py
veilbreakers_terrain/coastal/shoreline_sdf.py    (15 tests pass)
veilbreakers_terrain/coastal/landform_zones.py   (14 tests pass)
veilbreakers_terrain/handlers/visual_render_camera_proof.py   (13 tests pass)
veilbreakers_terrain/tests/test_*.py
scripts/coastal_build_v3*.py
scripts/mountain_*.py
scripts/grassland_full_build.py
scripts/render_coastal_inline.py
scripts/render_coastal_camera_proof.py
scripts/build_biome_composite.py
scripts/fix_*_lighting.py
scripts/final_fix_all_biomes.py
output/visual_nodes/VB_Coastal_V3e_Props_4096m.blend            (~75MB)
output/visual_nodes/VB_Mountain_Forest_v2_4096m.blend           (~30MB)
output/visual_nodes/VB_Grassland_v1_4096m.blend                 (~23MB)
renders/coastal/{u04,u05,u06,u07,u08,u08b,u10,c1_coastal_cycles,
                 m1_mountain_forest,m1_mountain_forest_workbench,
                 g1_grassland}/                                  (~150MB total)
```

All commits include detailed messages explaining the changes.

Branch: `feat/dynamic-quality-audit`
PR target: `main` (squash merge per CLAUDE.md branch protocol)
