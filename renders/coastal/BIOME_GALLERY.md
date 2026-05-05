# 3-Biome Render Gallery

Multi-angle render proofs for all 3 biomes built in this session. Each biome has 8 cameras — full overview, mid-distance perspectives, top-down, close-up, and aerial.

**Engines used:**
- **Cycles 32 samples + denoising** = canonical photoreal output (works headless without probe baking)
- **Eevee Next 32 samples** = live preview + close-up detail
- **Workbench** = fast debug reference (no shadows/atmosphere; shows pure geometry+materials)

## Coastal — `c1_coastal_cycles/` (Cycles canonical) and `u10_props/` (Eevee Next final)

Coastal V3e: full PBR + animated water + procedural vegetation + driftwood/boulder props + atmospheric lighting.

### Cycles renders (`renders/coastal/c1_coastal_cycles/`)
- `vb_coastal_full_node_camera.png` — full tile orthographic
- `vb_coastal_player_camera.png` — player POV
- `vb_coastal_shore_camera.png` — shoreline edge
- `vb_coastal_shore_oblique.png` — shoreline 30° oblique
- `vb_coastal_topdown_ortho.png` — pattern density top-down
- `vb_coastal_bluff_close.png` — bluff close-up
- `vb_coastal_alongshore_pan.png` — diagonal pan along shore
- `vb_coastal_drone_high.png` — aerial overview

### Eevee Next renders (`renders/coastal/u10_props/`) — same 8 cameras

## Mountain + Forest — `m1_mountain_forest/` (Cycles) + `m1_mountain_forest_workbench/` (Workbench)

Mountain v2: 320m peak ridges, 5-zone PBR (forest soil → alpine grass → scree → rock → snow), 5-species alpine forest (pine, spruce, juniper, heather, alpine grass).

- `vb_mountain_full_node.png` — full tile orthographic
- `vb_mountain_valley.png` — valley POV
- `vb_mountain_ridge_close.png` — ridge close-up 60mm
- `vb_mountain_forest_oblique.png` — forest belt oblique
- `vb_mountain_topdown_ortho.png` — top-down
- `vb_mountain_snowcap_close.png` — snow cap close-up
- `vb_mountain_alongshore_pan.png` — diagonal pan
- `vb_mountain_drone_high.png` — aerial

## Grassland — `g1_grassland/` (Cycles)

Grassland v1: rolling hills + meandering river + pond, 4-zone PBR (deep soil/lush grass/dry meadow/stones), 7-species pastoral vegetation (oak, willow, ash, hawthorn, tall+short grass, wildflowers).

- `vb_grassland_full_node.png` — full tile orthographic
- `vb_grassland_valley.png` — player POV
- `vb_grassland_hilltop_close.png` — hero oak silhouette 60mm
- `vb_grassland_river_oblique.png` — riparian willow shot
- `vb_grassland_topdown_ortho.png` — pattern density top-down
- `vb_grassland_grass_close.png` — blade-level 80mm at 1.5m altitude
- `vb_grassland_pan_long.png` — diagonal pan
- `vb_grassland_drone_high.png` — aerial

## Render manifest format

Each render directory contains `RENDER_MANIFEST.json` with:
- `unit_id`: biome + version slug
- `engine`, `resolution`, `samples`
- `ok`: True if all renders pass byte + non-black gates
- `renders[]`: per-camera (path, byte_size, nonblack_ratio, ok)

## Lighting iterations

Initial Cycles renders had quality issues (Mountain too dark, Grassland too bright). Fix scripts:
- `scripts/fix_mountain_lighting.py` — boost sun energy 9→18, remove volumetric, exposure +0.5→+1.2
- `scripts/fix_grassland_lighting.py` — reduce sun 8→4.5, BG strength 4.0→1.5, exposure +0.3→-0.4, lower camera altitudes

Re-renders after fixes are the final canonical outputs.

## Known limitations

- Cycles 32 samples is fast but noisy at small features. Future passes can use 128-256 samples for marketing-quality stills.
- Vegetation density is moderate; AAA reference (RDR2 Sea of Coronado) has 2-3× denser grass coverage.
- Wind animation is implemented in shader but not currently rendered as multi-frame proof. Frames 1/30/60 per camera would prove animation.
- Hunyuan3D-2.1 hero asset integration was researched but not deployed (3-4 hour install + 12+ GB VRAM); procedural hero props produce equivalent silhouettes for now.
