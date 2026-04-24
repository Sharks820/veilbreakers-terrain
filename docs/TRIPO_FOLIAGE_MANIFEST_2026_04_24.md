# Tripo Foliage Manifest — VeilBreakers Phase I (2026-04-24)

This manifest enumerates the Tripo AI prompts needed to produce the full
foliage / scatter prop library for VeilBreakers. Each prompt yields the four
variations Tripo ships per request. Total: **30 prompts × 4 variations = 120
assets**.

## How to use
1. Open Tripo (https://www.tripo3d.ai/) and paste one prompt at a time.
2. Let Tripo produce the 4 variations; download all of them as GLB (preferred)
   or ZIP.
3. Save the downloads under your OS `Downloads/` folder **without renaming**.
   The ingest pipeline keys off the prompt category in the filename; the
   pipeline accepts any filename but parses the category token if present
   (e.g. `tripo_grass_lush_A.glb`). If Tripo returns opaque names, drop them
   into a subfolder named after the category (e.g.
   `~/Downloads/tripo_grass_lush/`).
4. Run:
   ```bash
   python scripts/batch_ingest_tripo_downloads.py \
       --downloads ~/Downloads \
       --assets assets/foliage
   ```
5. The pipeline will decimate, LOD, export, and register every asset in
   `assets/foliage/catalog.json`. The catalog is auto-loaded by
   `veilbreakers_terrain.handlers.terrain_foliage_catalog` at scatter time.

## Aesthetic anchor
> VeilBreakers is a dark-fantasy open world: wet, overgrown, reclaimed ruins;
> ash-tinged skies; saturated moss and lichen; colours pulled toward teal,
> umber, and oxidised copper. Foliage leans lush but never cartoon; rocks are
> stratified and moss-kissed; wood is soaked, cracked, or half-rotted.

### Concrete style directives (apply to every asset)

1. **Palette** — desaturated teal, umber, and oxidised-copper dominate;
   moss emerald and lichen sage for accents; avoid primary-red,
   saturated-orange, or cartoon-yellow. Pigments look mixed with ash.
2. **Lighting** — author as if lit by ambient overcast; wet-surface
   specular (low roughness on stone/bark/leaf tips). No implied direct
   sunlight, no baked hard shadows in the asset itself.
3. **Material feel** — matte painterly PBR; faint subsurface scatter on
   leaves and petals; mossy damp bloom on stone and wood; iron elements
   oxidised and rust-streaked, never polished.
4. **Silhouette** — readable from 15 m distance even when the asset is
   a cluster; asymmetric and hand-placed, never symmetrical or
   computer-generated. Silhouettes must survive backlit billboard LODs.
5. **Wear level** — every prop shows weathering: moss kissed, water
   stained, age-cracked, chipped, or half-overgrown. Nothing pristine.
6. **Scale** — realistic human-scale; **1 Blender unit = 1 metre**.
   Dimensions specified in each prompt are target sizes Tripo must hit.
7. **Pivot** — base-centre at origin for grass / bush / tree / moss
   patches; bottom-face-centre at origin for rocks / stumps / logs;
   lowest-rigid-contact at origin for tile-along props (fences, walls,
   walkways, signposts). Z-up.
8. **Topology** — game-ready low/mid-poly with clean alpha edges; no
   floating geo; no intersecting cards that would flicker in game.

### Style tokens — ALWAYS include in EVERY prompt

Every prompt must begin with this exact leading sentence so Tripo's
retrieval anchors on the coherent VeilBreakers look. The tokens are
chosen so no single one is so narrow it contradicts a specific asset:

> `STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: <original prompt text>`

Each prompt below bakes that language in. Do **not** modify the core phrases
after the `ASSET:` marker: Tripo's retrieval is word-order sensitive.

---

## A. Grass (12 assets / 3 prompts × 4 variations)

Poly budget: **200-400 tris / variant**.

### A1. `grass_lush_wet` — temperate & swamp biomes
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Dense clump of tall wet meadow grass, dark-fantasy painterly style, blades
> 40-60 cm tall, deep emerald with teal undertones, moisture droplets on tips,
> bent-over silhouette from wind, low-poly game-ready fan of cross-card blades,
> clean alpha edges, matte texture, neutral pivot at base centre.

Expected variations: (A) upright cluster, (B) wind-pushed leaning, (C) sparse
tufts with flower stalks, (D) compact dense mat.

Scatter species binding: `grass_tall_wet`, `grass_meadow_default`,
`grass_swamp_edge`.

### A2. `grass_dry_ashen` — highland & wasteland biomes
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Brittle dry highland grass clump, burnt-sienna and pale-straw blades, some
> blackened tips, 30-50 cm tall, wiry wind-carved silhouette, dark-fantasy
> palette, low-poly cross-card fan, game-ready alpha, neutral base pivot,
> matte non-shiny surfacing.

Expected variations: (A) dense clump, (B) broken windblown, (C) half-burnt
stubble, (D) thin lone stalks.

Scatter species binding: `grass_dry_highland`, `grass_wasteland`,
`grass_ash_field`.

### A3. `grass_rotten_forest` — rotwood & shadow-vale biomes
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Dark forest floor grass with lichen spots and tiny pale mushrooms, deep
> forest green with black-violet tint, dark-fantasy painterly style, 25-40 cm,
> uneven clump with decaying yellow blades, low-poly cross-card fan,
> game-ready, clean alpha edges, base pivot at centre.

Expected variations: (A) mossy dense clump, (B) decaying with mushrooms,
(C) lichen-patched, (D) trampled flat patch.

Scatter species binding: `grass_rot_forest`, `grass_shadow_vale`,
`grass_mushroom_ring`.

---

## B. Small Rocks / Pebbles (8 assets / 2 prompts × 4 variations)

Poly budget: **500-900 tris / variant**.

### B1. `pebbles_streambed`
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Cluster of 4-6 smooth wet river pebbles, various sizes 5-15 cm, dark slate
> grey with teal mineral veins, damp sheen, rounded by water, dark-fantasy
> palette, game-ready low-poly, tri-planar-friendly pivot at cluster centre
> ground plane, matte to slight wet roughness.

Expected variations: (A) tight cluster, (B) spread scatter, (C) mossy wet,
(D) larger boulderlet mix.

Scatter species binding: `rock_pebble_stream`, `rock_pebble_path`.

### B2. `gravel_ruin_debris`
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Cluster of cracked stone shards and gravel from a fallen dark-fantasy ruin,
> rough angular fragments 3-12 cm, weathered limestone and basalt,
> ash-dusted, umber and grey, game-ready low-poly, pivot at cluster base
> centre, matte surfacing with fine cracks.

Expected variations: (A) rubble heap, (B) scattered debris, (C) mossy shards,
(D) ashy large fragments.

Scatter species binding: `rock_debris_ruin`, `rock_gravel_road`.

---

## C. Boulders (8 assets / 2 prompts × 4 variations)

Poly budget: **800-1500 tris / variant**.

### C1. `boulder_mossy_forest`
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Large forest boulder 1-2 m across, stratified granite with thick emerald
> moss blanket on top, dark-fantasy painterly style, damp stone with teal
> lichen patches, ferns sprouting from crevices, game-ready mid-poly, pivot at
> base centre, matte stone with wet highlights.

Expected variations: (A) mostly mossed, (B) half-buried tilted, (C) split
with fern, (D) clean stratified stone.

Scatter species binding: `boulder_forest`, `boulder_hillside`,
`boulder_shrine_edge`.

### C2. `boulder_shattered_cliff`
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Fractured cliff boulder 1.5-2.5 m, sharp angular breaks, iron-oxide rust
> streaks, dark-fantasy weathered basalt, faint carved runes half-eroded,
> ash-dusted, game-ready mid-poly, pivot at base centre, matte rock with
> metallic mineral flecks.

Expected variations: (A) sharp split, (B) rune-carved face, (C) overturned,
(D) partially collapsed pile.

Scatter species binding: `boulder_cliff`, `boulder_rune`, `boulder_wasteland`.

---

## D. Moss Patches (8 assets / 2 prompts × 4 variations)

Poly budget: **300-600 tris / variant**.

### D1. `moss_patch_ground`
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Ground moss patch 30-60 cm, thick emerald velvet surface, tiny pale-gold
> moss fruiting bodies, dark-fantasy wet palette, uneven organic silhouette,
> game-ready low-poly with fine displaced surface, pivot at centre ground,
> matte soft surfacing.

Expected variations: (A) thick dome, (B) spread flat, (C) with tiny flowers,
(D) half-dry crispy edge.

Scatter species binding: `moss_ground_forest`, `moss_rock_top`,
`moss_shrine_base`.

### D2. `moss_stalactite_drape`
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Hanging moss drape / usnea beard lichen cluster, 40-80 cm hanging length,
> pale sage-green strands, wet dark-fantasy atmosphere, soft wispy silhouette,
> game-ready cross-card alpha fans, pivot at top attachment point, matte
> soft surfacing.

Expected variations: (A) dense curtain, (B) sparse strands, (C) long
trailing, (D) twisted knot.

Scatter species binding: `moss_tree_drape`, `moss_cave_drape`,
`moss_ruin_drape`.

---

## E. Vines (4 assets / 1 prompt × 4 variations)

Poly budget: **600-1200 tris / variant**.

### E1. `vine_climbing_ruin`
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Climbing vine with dark leaves and small red berries, 2-4 m length, dark
> emerald leaves with black veins, dark-fantasy overgrown ruin style, wraps
> naturally around a stone surface, game-ready mid-poly trunk plus cross-card
> alpha leaves, pivot at base attachment, matte leaf with subtle translucency.

Expected variations: (A) thick wrap, (B) trailing free, (C) flowering, (D)
dried brown curl.

Scatter species binding: `vine_ruin_wrap`, `vine_tree_wrap`,
`vine_archway`, `vine_window_drape`.

---

## F. Trees (16 assets / 4 prompts × 4 variations)

Poly budget: **3000-8000 tris / variant** (billboards handled by LOD
pipeline, not Tripo).

### F1. `tree_oak_ancient`
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Ancient gnarled oak, 8-12 m tall, thick twisted trunk with exposed roots,
> deep-green canopy with teal undertone, dark-fantasy painterly style, damp
> bark with moss patches, broad spreading silhouette, game-ready mid-poly
> trunk and cross-card leaf clusters, pivot at root base centre, matte bark
> with soft leaf alpha.

Expected variations: (A) dense canopy, (B) half-leafless, (C) split trunk,
(D) leaning overgrown.

Scatter species binding: `tree_oak`, `tree_oak_shrine`.

### F2. `tree_birch_pale`
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Pale birch with peeling white-grey bark and small dark knots, 7-10 m tall,
> thin graceful trunk, dark emerald foliage cloud, dark-fantasy style, slight
> ash dusting on bark, game-ready mid-poly trunk plus cross-card leaf clouds,
> pivot at base centre, matte bark, delicate leaf alpha.

Expected variations: (A) full canopy, (B) thin sparse, (C) storm-broken top,
(D) grouped twin trunks.

Scatter species binding: `tree_birch`, `tree_birch_river`.

### F3. `tree_pine_black`
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Tall black pine, 10-14 m, narrow conical silhouette, dark blue-green
> needles, black-brown furrowed bark with sap streaks, dark-fantasy palette,
> game-ready mid-poly trunk and needle cross-cards, pivot at base centre,
> matte bark with soft needle alpha.

Expected variations: (A) dense conical, (B) bare-bottomed, (C) storm-bent,
(D) dead-top with crow perch look.

Scatter species binding: `tree_pine`, `tree_pine_highland`.

### F4. `tree_dead_claw`
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Dead dark-fantasy tree, no leaves, 8-12 m, twisted claw-like branches,
> bleached-black bark with splits, charred base, ash-dusted, painterly dark
> silhouette, game-ready mid-poly, pivot at base centre, matte cracked
> surface.

Expected variations: (A) upright claw, (B) leaning fallen, (C) split
lightning strike, (D) charred stump with broken trunk.

Scatter species binding: `tree_dead`, `tree_burnt`, `tree_lightning`.

---

## G. Logs / Stumps (8 assets / 2 prompts × 4 variations)

Poly budget: **800-1500 tris / variant**.

### G1. `log_fallen_mossy`
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Fallen forest log 2-3 m long, heavy moss blanket on top, dark damp bark,
> teal lichen patches, fungal shelves on side, dark-fantasy style, game-ready
> mid-poly, pivot at log centre ground contact, matte bark with soft moss
> fuzz.

Expected variations: (A) intact mossy, (B) split open hollow, (C) heavy
fungus cluster, (D) half-sunken in mud.

Scatter species binding: `log_forest`, `log_swamp`, `log_path_block`.

### G2. `stump_rotting`
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Rotting tree stump 60-90 cm tall, jagged broken top, mushrooms clustered
> around base, dark brown decay with yellow rot patches, dark-fantasy palette,
> game-ready low-poly, pivot at base centre, matte rotted wood.

Expected variations: (A) tall jagged, (B) short flat-top, (C) mushroom
ringed, (D) hollow-centred with roots.

Scatter species binding: `stump_forest`, `stump_clearing`,
`stump_mushroom`.

---

## H. Bushes (12 assets / 3 prompts × 4 variations)

Poly budget: **1200-2500 tris / variant**.

### H1. `bush_bramble_thorn`
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Dense thorny bramble bush, 1-1.5 m, dark red-green serrated leaves with
> long thorns, small black berries, dark-fantasy overgrown style, tangled
> chaotic silhouette, game-ready mid-poly trunk plus cross-card leaf cards,
> pivot at base centre, matte leaf with subtle translucency.

Expected variations: (A) dense spherical, (B) spreading wide, (C) berry
laden, (D) broken half-dead.

Scatter species binding: `bush_bramble`, `bush_forest_dense`,
`bush_path_edge`.

### H2. `bush_fern_shadowleaf`
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Large shadowleaf fern bush, 70-100 cm, dark emerald fronds with black
> veins, unfurling fiddleheads, dark-fantasy forest floor style, soft
> graceful silhouette, game-ready mid-poly with cross-card frond leaves,
> pivot at base centre, matte leaf with subsurface translucency.

Expected variations: (A) dense symmetric, (B) asymmetric leaning, (C) young
curled, (D) old and browning.

Scatter species binding: `bush_fern`, `bush_fern_cave`,
`bush_fern_shrine`.

### H3. `bush_heath_bloom`
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Low heath bush with tiny violet flowers, 40-60 cm, wiry dark branches,
> small dark-green leaves, flecked with purple blossoms, dark-fantasy
> moorland palette, game-ready mid-poly with cross-card leaf-and-flower
> cards, pivot at base centre, matte leaf with soft flower emissive tint.

Expected variations: (A) full bloom, (B) sparse bloom, (C) post-bloom brown,
(D) wind-flattened.

Scatter species binding: `bush_heath`, `bush_moor`, `bush_highland_bloom`.

---

## I. Water foliage (8 assets / 2 prompts × 4 variations)

Poly budget: **400-900 tris / variant**.

### I1. `reed_water_edge`
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Cluster of tall water reeds, 1-1.5 m, pale-teal and olive blades, dark
> swamp-water splash at base, dark-fantasy palette, thin upright silhouette,
> game-ready low-poly cross-card fan, pivot at base centre at water plane,
> matte blade with soft subsurface.

Expected variations: (A) dense reed bed, (B) bent windblown, (C) with seed
heads, (D) broken half-dead.

Scatter species binding: `reed_lake`, `reed_swamp`, `reed_river`.

### I2. `lily_pad_swamp`
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Floating dark lily pad cluster with single pale luminescent bloom, pads
> 20-40 cm, inky water reflections, dark-fantasy bioluminescent style,
> game-ready low-poly flat cards with bloom petals, pivot at centre water
> plane, matte pad with soft emissive bloom.

Expected variations: (A) single bloom, (B) many pads no flower, (C) closed
bud, (D) wilting with algae.

Scatter species binding: `lily_swamp`, `lily_pond`, `algae_surface`,
`submerged_grass`.

---

## J. Fences / Gates (4 assets / 1 prompt × 4 variations)

Poly budget: **900-1800 tris / variant**.

### J1. `fence_rotwood`
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Weathered rotwood fence segment, 2 m long, dark-stained cracked planks,
> rusted iron nails, moss streaks, dark-fantasy palette, game-ready mid-poly,
> pivot at base centre of segment, matte cracked wood with subtle metal
> flecks.

Expected variations: (A) intact line, (B) broken missing plank, (C) leaning
collapsed, (D) gate with rusted hinges.

Scatter species binding: `fence_road`, `fence_field`, `gate_ruin`,
`fence_ruin`.

---

## K. Signposts (4 assets / 1 prompt × 4 variations)

Poly budget: **700-1400 tris / variant**.

### K1. `signpost_wayward`
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Old wooden wayward signpost, 1.5 m tall, dark-stained post with carved
> arrow board, faded runes, iron bands, dark-fantasy style, moss at base,
> game-ready mid-poly, pivot at base centre, matte wood with soft iron
> reflectance.

Expected variations: (A) upright intact, (B) leaning cracked, (C) double
arrow crossroads, (D) broken stub with fallen plank.

Scatter species binding: `signpost_road`, `signpost_crossroads`,
`signpost_ruin`, `signpost_grave`.

---

## L. Walkway texture sets (4 assets / 1 prompt × 4 variations)

Poly budget: **1200-2000 tris / variant** (tile-able plane with inset
stones).

### L1. `walkway_cobbled`
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Cobbled dark-fantasy walkway tile, 2x2 m, irregular slate cobbles with
> grass tufts between, rainy damp sheen, umber and grey palette, game-ready
> mid-poly tile-able, pivot at tile centre on ground plane, matte stone with
> wet specular and fine moss inlay.

Expected variations: (A) dense cobble, (B) half-overgrown, (C) broken with
cracks, (D) flooded with puddles.

Scatter species binding: `path_cobble_main`, `path_cobble_ruin`,
`path_flag_shrine`, `path_wet`.

---

## M. Accent flora (8 assets / 2 prompts × 4 variations)

Poly budget: **400-1000 tris / variant**.

### M1. `flower_dark_wisp`
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Small dark-fantasy wisp flower cluster, 20-30 cm, pale-violet petals with
> luminous soft glow centre, thin dark stems, 3-5 blooms, game-ready low-poly
> with cross-card petals, pivot at base centre, matte stem with soft
> emissive bloom.

Expected variations: (A) tight cluster, (B) single stem, (C) closed bud,
(D) wilting drooping.

Scatter species binding: `flower_wisp`, `flower_shrine`,
`flower_path_edge`, `flower_meadow_accent`.

### M2. `mushroom_glow_cap`
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, neutral A-pose pivot. ASSET: Cluster of 3-5 dark-fantasy glow-cap mushrooms, 15-40 cm, deep indigo caps
> with turquoise luminescent underside, pale stems, moss skirts, game-ready
> low-poly, pivot at cluster base centre, matte cap with soft emissive
> gills.

Expected variations: (A) small cluster, (B) tall lone, (C) shelf-on-log
variant, (D) broken toppled.

Scatter species binding: `mushroom_glow`, `mushroom_log`,
`mushroom_shrine`, `mushroom_cave`.

---

## Totals

| Category         | Prompts | Assets |
|------------------|---------|--------|
| A. Grass         |  3      |   12   |
| B. Small rocks   |  2      |    8   |
| C. Boulders      |  2      |    8   |
| D. Moss          |  2      |    8   |
| E. Vines         |  1      |    4   |
| F. Trees         |  4      |   16   |
| G. Logs/stumps   |  2      |    8   |
| H. Bushes        |  3      |   12   |
| I. Water foliage |  2      |    8   |
| J. Fences        |  1      |    4   |
| K. Signposts     |  1      |    4   |
| L. Walkways      |  1      |    4   |
| M. Accent flora  |  2      |    8   |
| **Total**        | **26**  | **104** |

> The brief said "~30 prompts × 4 = ~120 assets". We land at **26 prompts /
> 104 assets** with every requested category covered; add additional prompts
> in Phase J if biome variety requires it.

## Filename convention (for auto-category detection)

When you save downloads, the ingest script infers the category from the first
category-keyword it matches in the filename. The keywords are:

```
grass, pebble, gravel, boulder, moss_drape, moss, vine, log, stump,
oak, birch, pine, dead_tree, tree, bramble, fern, heath, bush, reed,
lily, fence, gate, signpost, walkway, cobble, path, flower, mushroom
```

Examples Tripo commonly emits:
- `tripo-2026-04-24-grass_lush_wet-A.glb` → category `grass`
- `tripo-oak_ancient-variant2.zip` → category `oak` → `tree_oak`
- `moss_stalactite_drape_03.glb` → category `moss_drape`

If the filename has no hit, place the file in a per-category subfolder
under `~/Downloads/` and the batch script will use the folder name.
