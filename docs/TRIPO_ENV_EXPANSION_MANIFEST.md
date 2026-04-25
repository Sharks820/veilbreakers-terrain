# Tripo Environment Expansion Manifest — VeilBreakers Phase II (2026-04-24)

This manifest covers all missing environment zones not in Phase I: cave, alpine/snow,
ground micro-detail, extended grass biomes, extended tree species, ruin structures,
dark-fantasy identity props, and waterfall/mountain terrain dressing.

**48 prompts × 4 variations = 192 assets.**

All assets use the updated STYLE token with `seamless base-fade for terrain blending` —
every prop base fades to transparent so it melds into the terrain texture naturally
without a hard geo cut.

## How to run

```bash
python scripts/tripo_batch_generate.py \
    --manifest docs/TRIPO_ENV_EXPANSION_MANIFEST.md \
    --backend studio \
    --hard-task-cap 200 \
    --run-ingest
```

## Aesthetic anchor

VeilBreakers environment expansion keeps the same dark-fantasy anchor as Phase I:
wet, overgrown, reclaimed ruins; ash-tinged skies; teal-umber-copper palette.
Extended zones each have a biome modifier layered over the base style — never
replacing it, only shading it (cave = dark + bioluminescent; alpine = frost-pale;
corruption = black-violet emissive).

### Style tokens — ALWAYS include in EVERY prompt

> `STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: <original prompt text>`

The key addition over Phase I: **`seamless base-fade for terrain blending`** tells Tripo
to taper the mesh base into a soft transparent gradient so painted terrain shows through
rather than leaving a hard geo island. **`Z-up pivot ground-plane`** anchors all pivots
at the lowest contact with the ground plane (Z=0), ready for direct terrain placement.

---

## S. Extended Grass (32 assets / 8 prompts × 4 variations)

Poly budget: **200-400 tris / variant**.

### S1. `grass_alpine_frost` — alpine highland biome
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Sparse alpine frost-grass tuft, 15-25 cm, pale silver-white blades with frost crystals on tips, dark-fantasy highland palette, wiry low silhouette, low-poly cross-card fan, clean alpha edges, base pivot at ground-plane, matte frosty surfacing.

Expected variations: (A) frost-heavy dense, (B) wind-stripped sparse, (C) ice-rimmed tips with glint, (D) half-snow-buried.

Scatter species binding: `grass_alpine_frost`, `grass_highland_pale`.

### S2. `grass_cave_pale` — cave / underground biome
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Cave pale grass cluster, 20-35 cm, bleached white-grey blades with faint bioluminescent teal stripe, damp dark-fantasy cave atmosphere, thin sparse silhouette, low-poly cross-card fan, clean alpha, base pivot at ground-plane, matte damp surfacing.

Expected variations: (A) tall pale cluster, (B) low mat near drip channel, (C) glowing teal stripe tips, (D) sparse isolated blades.

Scatter species binding: `grass_cave_pale`, `grass_underground`.

### S3. `grass_swamp_marsh` — swamp biome
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Swamp marsh sedge clump, 40-70 cm, brown-olive tipped blades with water-logged base, dark-fantasy wet palette, wide spreading silhouette, low-poly cross-card fan, clean alpha, base at water-plane pivot, matte wet surfacing.

Expected variations: (A) dense marsh clump, (B) flood-flat spread, (C) dying brown-edged, (D) with small cattail spike.

Scatter species binding: `grass_swamp_marsh`, `grass_sedge_water`.

### S4. `grass_riverbank_lush` — river / stream biome
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Lush riverbank grass tuft, 35-55 cm, vivid teal-green blades with water-spray droplets, dark-fantasy forest palette, upright dense silhouette, low-poly cross-card fan, clean alpha, base at bank pivot, matte wet leafy surfacing.

Expected variations: (A) upright dense, (B) cascade lean over bank edge, (C) with tiny blue flowers, (D) partially submerged base.

Scatter species binding: `grass_riverbank`, `grass_stream_edge`.

### S5. `grass_highland_moor` — moor / moorland biome
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Highland moorland grass clump, 30-50 cm, deep umber-brown blades with seed heads, dark-fantasy moorland palette, windswept asymmetric silhouette, low-poly cross-card fan, clean alpha, base pivot at centre, matte dry surfacing.

Expected variations: (A) seed-head-heavy full, (B) windswept lying low, (C) mixed with heather sprigs, (D) dry crackling edge.

Scatter species binding: `grass_moor`, `grass_highland_brown`.

### S6. `grass_shadow_dark` — deep shadow / dark-vale biome
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Shadow-vale dark grass patch, 25-40 cm, near-black indigo blades with faint violet iridescence, dark-fantasy deep-shadow palette, low flat silhouette, low-poly cross-card fan, clean alpha, base pivot at centre, matte with faint emissive shimmer on tips.

Expected variations: (A) dense dark mat, (B) scattered sparse blades, (C) glowing violet tip fringe, (D) trampled dead blackened.

Scatter species binding: `grass_shadow`, `grass_dark_vale`.

### S7. `grass_beach_shore` — coastal / shoreline biome
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Shoreline sea-grass tuft, 30-50 cm, grey-green blades with salt-bleached tips, dark-fantasy coastal palette, wind-bent silhouette, low-poly cross-card fan, clean alpha, base pivot at ground plane, matte wind-dried surfacing.

Expected variations: (A) wind-bent cluster, (B) upright neat, (C) salt-bleached pale tips, (D) partially sand-buried.

Scatter species binding: `grass_shore`, `grass_coastal`.

### S8. `grass_tall_overland` — open overland / plains biome
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Tall overland grass, 60-90 cm, deep-green and umber mixed blades, dark-fantasy open plains style, broad spreading silhouette, low-poly cross-card fan, clean alpha, base pivot at centre, matte surfacing.

Expected variations: (A) dense tall wave, (B) seed-head plumes, (C) parted by wind gap, (D) crushed path strip.

Scatter species binding: `grass_tall`, `grass_overland_plains`.

---

## T. Extended Trees (24 assets / 6 prompts × 4 variations)

Poly budget: **3000-8000 tris / variant** (billboards handled by LOD pipeline).

### T1. `tree_willow_weeping` — river / lake biome
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Weeping dark-fantasy willow tree, 10-15 m, long hanging curtains of pale-green-silver fronds, thick damp bark, dark-fantasy river palette, sweeping drooping silhouette, game-ready mid-poly trunk and cross-card hanging frond cards, pivot at base centre, matte bark with soft frond alpha.

Expected variations: (A) full heavy drape, (B) sparse thin curtains, (C) riverside leaning over water, (D) half-dead with rot patches.

Scatter species binding: `tree_willow`, `tree_willow_river`.

### T2. `tree_swamp_gnarled` — swamp / bog biome
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Swamp gnarled tree, 8-12 m, twisted low branches with thick moss and lichen, wide knee-root base flared at waterline, dark-fantasy swamp palette, low spreading silhouette, mid-poly trunk with cross-card sparse leaf cards, pivot at root-base centre, matte damp bark.

Expected variations: (A) full canopy with water lean, (B) bare branches over water, (C) moss-heavy draping, (D) hollow-trunk form.

Scatter species binding: `tree_swamp`, `tree_bog_gnarled`.

### T3. `tree_alpine_fir` — alpine / mountain biome
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Alpine dark fir tree, 12-18 m, tight narrow spire, snow-dusted dark-blue-green needles, dark-fantasy mountain palette, game-ready mid-poly trunk with cross-card needle clusters, pivot at base centre, matte bark with soft needle alpha.

Expected variations: (A) snow-laden heavy boughs, (B) clear dark spire no snow, (C) broken top from snow load, (D) grouped cluster of 3 young firs.

Scatter species binding: `tree_fir`, `tree_alpine_fir`.

### T4. `tree_canopy_giant` — deep forest biome
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Massive ancient canopy tree, 20-30 m, enormous spreading crown, deeply-furrowed ancient bark, dark-fantasy forest palette, vast silhouette, game-ready mid-poly trunk with cross-card leaf cloud clusters, pivot at root-base centre, matte dark bark.

Expected variations: (A) full summer canopy, (B) autumn-tinted teal-amber canopy, (C) storm-bent with broken limb, (D) prominent buttress roots exposed.

Scatter species binding: `tree_giant_canopy`, `tree_ancient`.

### T5. `tree_sapling_cluster` — general forest regeneration
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Cluster of 3-5 dark-fantasy saplings, 2-4 m each, thin flexible stems, small dark emerald leaf clusters, dark-fantasy forest style, loose organic grouping, game-ready low-poly multiple stems with cross-card leaf cards, pivot at cluster ground centre, matte bark.

Expected variations: (A) dense tight group, (B) spread loose open group, (C) mixed sizes graduated, (D) one dead stem among living.

Scatter species binding: `tree_sapling`, `tree_young_forest`.

### T6. `tree_corrupted_shadow` — corrupted / dark-fantasy biome
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Corrupted shadow tree, 8-14 m, sickly black-purple bark, vestigial shrivelled dark leaves, twisted angular branching, dark-fantasy corruption palette, jagged ominous silhouette, game-ready mid-poly with cross-card dead leaf wisps, pivot at base centre, matte corrupt bark.

Expected variations: (A) full corrupted intact form, (B) shedding diseased leaves, (C) split trunk oozing, (D) partially crystallised limbs.

Scatter species binding: `tree_corrupted`, `tree_shadow_rot`.

---

## U. Cave Zone (24 assets / 6 prompts × 4 variations)

Poly budget: **800-2000 tris / variant**.

### U1. `cave_stalactite_cluster` — cave ceiling decor
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Dark-fantasy cave stalactite cluster hanging 60-120 cm, calcite grey-blue spike formations, water-drip gloss tips, dark cave palette, varied spike lengths asymmetric, game-ready mid-poly, pivot at top attachment plane (inverted), matte stone with water-sheen tips.

Expected variations: (A) tight dense cluster, (B) 3 large isolated spikes, (C) small drip-tip fine cluster, (D) broken stub remnants.

Scatter species binding: `cave_stalactite`, `cave_ceiling_spike`.

### U2. `cave_stalagmite_cluster` — cave floor decor
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Dark-fantasy cave stalagmite cluster, 30-80 cm tall, calcite grey-brown lumps growing upward from cave floor, moisture-dampened surface, dark cave palette, blunt rounded tops, game-ready mid-poly, pivot at base ground-plane, matte wet stone.

Expected variations: (A) tall sharp-tip group, (B) short dome cluster, (C) single large boss column, (D) broken snapped tops with rubble.

Scatter species binding: `cave_stalagmite`, `cave_floor_spike`.

### U3. `cave_crystal_formation` — cave feature
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Dark-fantasy cave crystal cluster, 30-60 cm, translucent teal-violet faceted crystals, faint internal bioluminescent glow, damp cave palette, geometric asymmetric growth, game-ready mid-poly, pivot at base ground-plane, matte crystal with soft emissive glow.

Expected variations: (A) tall spike cluster, (B) low flat geode formation, (C) single large central prism, (D) shattered with crystal debris.

Scatter species binding: `cave_crystal`, `cave_geode`.

### U4. `cave_mushroom_giant` — cave floor accent
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Giant glowing cave mushroom, 60-100 cm, enormous pale dome cap with deep gills, teal bioluminescent rim glow, short stout stem, dark-fantasy cave palette, game-ready mid-poly, pivot at base centre, matte cap with emissive rim.

Expected variations: (A) single giant upright, (B) cluster of 3 varied sizes, (C) dome split open hollow, (D) partially collapsed cap.

Scatter species binding: `mushroom_cave_giant`, `mushroom_cave_glow`.

### U5. `cave_bone_debris` — cave floor scatter
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Scattered cave bone debris cluster, dark-fantasy dungeon palette, mix of 6-8 small bones and skull fragments, bleached grey-cream with cave grime stains, game-ready low-poly cluster, pivot at cluster base centre, matte weathered bone.

Expected variations: (A) dense compact pile, (B) spread scatter pattern, (C) with intact full skull, (D) half-buried in cave mud.

Scatter species binding: `cave_bones`, `cave_debris`.

### U6. `cave_wall_lichen` — cave wall / surface accent
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Cave wall lichen mat, 40-70 cm diameter, flat encrusting biological growth, pale teal-grey with dark patches, dark-fantasy cave palette, irregular organic silhouette, game-ready low-poly flat panel, pivot at wall attachment plane, matte biological damp surface.

Expected variations: (A) circular dense mat, (B) irregular spreading patch, (C) with tiny pale mushroom sprouts, (D) dry flaking cracked edges.

Scatter species binding: `cave_lichen`, `cave_wall_growth`.

---

## V. Alpine / Snow (20 assets / 5 prompts × 4 variations)

Poly budget: **500-1500 tris / variant**.

### V1. `rock_snowcap` — alpine / snow biome
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Alpine snowcap rock cluster, 50-120 cm, dark basalt rock with thick white snow mantle on top, dark-fantasy mountain palette, angular stratified rock forms, game-ready mid-poly, pivot at base ground, matte dark stone with clean snow cap.

Expected variations: (A) fresh heavy snow cap, (B) partial melt rock reveal, (C) icy glaze crust over rock, (D) wind-scoured bare rock.

Scatter species binding: `rock_snowcap`, `boulder_alpine`.

### V2. `icicle_cluster` — alpine / cave ceiling
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Ice icicle cluster hanging 30-80 cm, crystal clear ice formations, dark-fantasy cold palette, sharp translucent spikes, game-ready mid-poly, pivot at top attachment plane (inverted), translucent ice material with cold refraction hint.

Expected variations: (A) dense straight cluster, (B) drip-melting long tapers, (C) thick stubby compact, (D) broken shards fallen.

Scatter species binding: `icicle`, `ice_drip`.

### V3. `frost_shrub` — alpine / frost biome
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Frost-encased alpine shrub, 40-70 cm, small thorny branches with thick ice coating, dark-fantasy cold palette, crystalline white-blue form, game-ready mid-poly, pivot at base centre, matte ice-coated surface.

Expected variations: (A) fully iced solid white form, (B) partial thaw with leaf reveal, (C) dark berries trapped in ice, (D) broken ice-shattered branches.

Scatter species binding: `shrub_frost`, `bush_alpine_frost`.

### V4. `boulder_alpine_snow` — alpine boulder
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Alpine snow boulder, 1.5-2.5 m, dark rough volcanic rock with deep snow drifts around base and snow cap, dark-fantasy mountain palette, heavy weathered form, game-ready mid-poly, pivot at base centre, matte rock with clean snow.

Expected variations: (A) snow-heavy full cap, (B) partial melt pattern, (C) ice-veined deep cracks, (D) avalanche-scarred face.

Scatter species binding: `boulder_alpine`, `boulder_snowdrift`.

### V5. `snow_drift_mound` — alpine / open snow ground
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Soft snow drift mound, 30-60 cm tall, 1-2 m wide, dark-fantasy cold palette, pure white with blue-shadow undersides, subtle wind-ripple surface, game-ready low-poly, pivot at base ground, matte snow.

Expected variations: (A) smooth wave drift, (B) footprint-disturbed surface, (C) small drift with frost shrub, (D) melting edge reveal.

Scatter species binding: `snow_drift`, `snow_ground`.

---

## W. Ground Micro-detail (20 assets / 5 prompts × 4 variations)

Poly budget: **300-800 tris / variant**.

### W1. `root_gnarled_surface` — forest floor
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Gnarled exposed tree root network on forest floor, 50-80 cm spread, thick rope-like dark-brown roots with moss between, dark-fantasy forest palette, organic flat ground-hugging form, game-ready mid-poly, pivot at centre ground plane, matte damp root.

Expected variations: (A) tight knot cluster, (B) spreading fan roots, (C) root arch gap walkable, (D) half-buried moss-covered.

Scatter species binding: `root_surface`, `root_floor_forest`.

### W2. `leaf_mound_dead` — forest floor autumn
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Mound of dead leaves and forest debris, 20-40 cm high, 60-80 cm spread, dark-fantasy autumn palette, umber-copper-brown with black patches, organic irregular silhouette, game-ready low-poly, pivot at base centre, matte dry leaf.

Expected variations: (A) deep heap mound, (B) wind-spread flat mat, (C) wet-matted damp press, (D) with mushrooms sprouting from beneath.

Scatter species binding: `leaf_mound`, `debris_leaf`.

### W3. `bone_scatter_field` — dungeon / dark ground
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Small bone scatter cluster on dungeon floor, dark-fantasy palette, 4-7 individual bone pieces, bleached grey-white with soil and grime stains, game-ready low-poly, pivot at cluster base, matte weathered bone.

Expected variations: (A) compact group, (B) spread loose pattern, (C) rib cage arc formation, (D) lone small skull.

Scatter species binding: `bone_scatter`, `bone_field`.

### W4. `mud_puddle` — wet terrain / swamp edge
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Dark muddy ground puddle, 40-70 cm diameter, flat inky mudwater surface, dark-fantasy swamp palette, slightly raised muddy rim, game-ready low-poly flat plane with inset rim, pivot at centre ground, matte wet mud.

Expected variations: (A) dark still surface, (B) bubble-rippled active, (C) footprint-sunken edge, (D) half-dry cracked mud.

Scatter species binding: `mud_puddle`, `puddle_ground`.

### W5. `mushroom_ring_fairy` — forest floor ring accent
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Dark-fantasy fairy mushroom ring, 60-80 cm diameter circle of 8-12 small dark-cap mushrooms, indigo caps with pale spots, glowing teal gill edges, game-ready low-poly ring layout, pivot at ring centre ground, matte caps with soft emissive gills.

Expected variations: (A) full circle complete, (B) broken incomplete arc, (C) dense tight ring, (D) scattered breaking ring.

Scatter species binding: `mushroom_ring`, `fairy_ring`.

---

## X. Ruin Structures (24 assets / 6 prompts × 4 variations)

Poly budget: **1500-4000 tris / variant**.

### X1. `ruin_broken_pillar` — ruin / dungeon accent
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Dark-fantasy broken stone pillar, 1.5-2.5 m standing height, cracked and partially toppled, carved basalt with moss in cracks, dark-fantasy ruin palette, game-ready mid-poly, pivot at base centre, matte stone with carved detail.

Expected variations: (A) mid-height broken clean shear, (B) shattered top — only stump remains, (C) toppled on ground, (D) carved rune bands on surface.

Scatter species binding: `ruin_pillar`, `pillar_broken`.

### X2. `ruin_crumbled_wall` — ruin accent
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Dark-fantasy crumbled stone wall section, 1-1.5 m long, 60-100 cm tall, rough basalt blocks, mortar cracked, moss grown in seams, dark-fantasy ruin palette, game-ready mid-poly, pivot at base-left corner, matte stone.

Expected variations: (A) partial intact wall top, (B) half-collapsed rubble heap, (C) moss-heavy fully overgrown, (D) iron-grate remnant inset.

Scatter species binding: `ruin_wall`, `wall_crumbled`.

### X3. `ruin_collapsed_arch` — hero ruin prop
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Collapsed dark-fantasy stone arch segment, 2-3 m, keystone fallen with flanking supports cracked, heavy carved basalt, vine and moss growth, dark-fantasy ruin palette, game-ready mid-poly, pivot at base centre, matte stone with carved detail.

Expected variations: (A) keystone still wedged in place, (B) keystone dropped to centre, (C) one side fully collapsed, (D) half-buried in earth and root.

Scatter species binding: `ruin_arch`, `arch_collapsed`.

### X4. `ruin_altar_stone` — ruin ritual accent
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Dark-fantasy stone altar block, 80 cm x 60 cm x 40 cm, carved ritual symbols, rust-stained top surface, dark basalt, ominous dark palette, game-ready mid-poly, pivot at base centre, matte stone with carved groove detail.

Expected variations: (A) intact with rust stain, (B) cracked down centre split, (C) blood-rust drain channels carved, (D) toppled on its side.

Scatter species binding: `ruin_altar`, `altar_stone`.

### X5. `ruin_carved_block` — ruin debris
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Dark-fantasy carved stone block, 40-70 cm, single block with partial carved relief, crumbled edges, dark-fantasy ruin palette, game-ready low-poly, pivot at base centre, matte stone.

Expected variations: (A) decorative frieze carving, (B) symbol carved face, (C) uncarved worn blank, (D) fractured split face.

Scatter species binding: `ruin_carved_block`, `stone_block`.

### X6. `ruin_burial_cairn` — ruin / grave accent
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Dark-fantasy burial cairn, 60-90 cm, stacked rough stones with small carved marker at top, lichen and moss growth between stones, dark ruin palette, game-ready mid-poly, pivot at base centre, matte stone.

Expected variations: (A) neat intact stacked cairn, (B) partially toppled leaning, (C) moss-heavy overgrown, (D) iron stake driven through top.

Scatter species binding: `burial_cairn`, `cairn_grave`.

---

## Y. Dark Fantasy Identity (20 assets / 5 prompts × 4 variations)

Poly budget: **800-2500 tris / variant**.

### Y1. `dark_skull_stake` — dark accent prop
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Dark-fantasy skull on a stake, total height 1.5 m, rotted wooden stake, human skull wired to top, dark-fantasy ominous palette, bleached skull with rust wire binding, dark damp wood, game-ready low-poly, pivot at base centre, matte.

Expected variations: (A) fresh skull clean on stake, (B) weathered lichen-kissed, (C) with chain wrap, (D) broken stake skull fallen.

Scatter species binding: `dark_accent_skull`, `stake_skull`.

### Y2. `corrupt_crystal_shard` — dark corruption accent
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Dark corruption crystal shard cluster, 30-50 cm, black-violet translucent crystals with internal dark glow, corruption cracks in ground around base, dark-fantasy corruption palette, game-ready mid-poly, pivot at base ground, matte crystal with dark emissive glow.

Expected variations: (A) 3-spike cluster, (B) single tall shard, (C) shattered ring spread, (D) ground-cracking emergence.

Scatter species binding: `dark_accent_crystal`, `corrupt_crystal`.

### Y3. `rune_monolith` — dark identity hero prop
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Dark-fantasy standing rune stone, 2-3 m tall, narrow rough basalt column, deeply carved runic symbols with faint teal luminescent fill, ominous dark palette, game-ready mid-poly, pivot at base centre, matte stone with emissive rune lines.

Expected variations: (A) intact upright full runes, (B) tilted cracked, (C) runes glowing bright active, (D) toppled broken with split.

Scatter species binding: `rune_monolith`, `standing_stone`.

### Y4. `ritual_ground_circle` — dark ritual accent
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Dark-fantasy ritual ground marking, 1-2 m flat stone tile, carved dark stone disc with concentric rune rings and central symbol, dark palette, faint emissive rune glow, game-ready low-poly flat, pivot at centre, matte stone with emissive inlay.

Expected variations: (A) fresh carved clean, (B) worn and faded, (C) glowing fully activated, (D) cracked broken disc halves.

Scatter species binding: `ritual_ground`, `ritual_circle`.

### Y5. `blight_tendril_growth` — dark corruption ground accent
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Dark corruption blight tendril growth, 40-80 cm, writhing black-purple organic tendrils emerging from cracked ground, dark-fantasy corruption palette, alien twisted silhouette, game-ready mid-poly, pivot at ground-crack centre, matte organic with faint dark emissive.

Expected variations: (A) 5-tendril cluster emerging, (B) low wide spreading mat, (C) single thick corrupted trunk, (D) dried dead black.

Scatter species binding: `dark_accent_tendril`, `blight_growth`.

---

## Z. Water / Waterfall / Mountain (28 assets / 7 prompts × 4 variations)

Poly budget: **500-2000 tris / variant**.

### Z1. `waterfall_moss_rock` — waterfall biome
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Waterfall-polished moss-covered rock, 60-120 cm, smooth rounded form, thick emerald and teal moss blanket with water-carved channels, dark-fantasy wet palette, game-ready mid-poly, pivot at base, matte wet stone and moss.

Expected variations: (A) fully mossed rounded, (B) water-channel carved deep, (C) small water pool at base, (D) with fern in crack.

Scatter species binding: `waterfall_rock`, `water_moss_rock`.

### Z2. `waterfall_spray_fern` — waterfall edge biome
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Spray-zone fern cluster at waterfall edge, 50-80 cm, deep emerald fronds with moisture droplets, dark-fantasy waterfall palette, lush and dense, game-ready mid-poly with cross-card fronds, pivot at base centre on wet ground, matte with subsurface leaf translucency.

Expected variations: (A) dense upright spray fan, (B) cascade lean over rock, (C) with tiny blue spray flowers, (D) half-submerged roots.

Scatter species binding: `waterfall_fern`, `spray_fern`.

### Z3. `algae_mat_surface` — water / swamp surface
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Floating algae mat, 60-100 cm flat irregular form, deep teal-green surface film, dark-fantasy swamp palette, game-ready low-poly flat organic plane, pivot at water surface centre, matte algae.

Expected variations: (A) dense flat full mat, (B) broken segment gaps, (C) with tiny red algae dot accents, (D) edges curling up.

Scatter species binding: `algae_mat`, `algae_surface`.

### Z4. `lotus_dark_bloom` — water / swamp surface
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Dark-fantasy lotus bloom, 30-50 cm, dark indigo petals with pale luminescent tips, thick dark pad, dark-fantasy swamp palette, game-ready low-poly, pivot at water surface centre, matte pad with soft emissive petal tips.

Expected variations: (A) open full bloom, (B) closed tight bud, (C) wilting with bruised petals, (D) seed pod head form.

Scatter species binding: `lotus_dark`, `water_lotus`.

### Z5. `scree_talus_pile` — mountain / cliff biome
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Alpine scree talus debris pile, 60-120 cm spread, loose angular rock fragments 10-30 cm, dark-grey and rust basalt, dark-fantasy mountain palette, low irregular mound, game-ready mid-poly, pivot at base centre, matte rough stone.

Expected variations: (A) compact fresh pile, (B) spread flat scatter, (C) moss just starting, (D) lichen-patched old pile.

Scatter species binding: `scree_talus`, `rock_talus`.

### Z6. `cliff_spire_rock` — cliff / mountain hero prop
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Narrow dark rock spire, 2-4 m tall, weathered basalt column with wind-carved striations, dark-fantasy mountain palette, sharp narrow silhouette, game-ready mid-poly, pivot at base centre, matte wind-carved stone.

Expected variations: (A) straight vertical clean, (B) slight lean, (C) twin spires side by side, (D) broken top sheared.

Scatter species binding: `cliff_spire`, `rock_spire`.

### Z7. `cliff_overhang_boulder` — cliff / mountain
> STYLE: dark-fantasy painterly, damp weathered, desaturated teal-umber-copper palette, matte PBR, 1m scale, game-ready low-poly, clean alpha edges, seamless base-fade for terrain blending, Z-up pivot ground-plane. ASSET: Cliff-edge overhang boulder, 2-3 m, massive dark rock jutting over edge, underside damp with drip moss, dark-fantasy mountain palette, dramatic dramatic silhouette, game-ready mid-poly, pivot at rock base on cliff surface, matte stone with moss underside.

Expected variations: (A) clean overhang, (B) moss-heavy underside, (C) crack splitting through, (D) small cave pocket beneath.

Scatter species binding: `cliff_boulder`, `overhang_rock`.

---

## Totals

| Section                      | Prompts | Assets |
|------------------------------|---------|--------|
| S. Extended Grass            |   8     |   32   |
| T. Extended Trees            |   6     |   24   |
| U. Cave Zone                 |   6     |   24   |
| V. Alpine / Snow             |   5     |   20   |
| W. Ground Micro-detail       |   5     |   20   |
| X. Ruin Structures           |   6     |   24   |
| Y. Dark Fantasy Identity     |   5     |   20   |
| Z. Water / Waterfall / Mtn   |   7     |   28   |
| **Total**                    | **48**  | **192** |
