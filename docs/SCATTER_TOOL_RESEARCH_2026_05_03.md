# Scatter Tool Research - 2026-05-03

## Decision

Use external scatter tools as reference, QA, and asset-authoring helpers. Do not make any external Blender scatter system the production truth.

Production truth remains:

- terrain channels and biome masks
- `VegetationRuleGraph` or equivalent repo-owned rule schema
- `ScatterPointTable`
- foliage mesh library / asset manifest
- Unity `foliage_placement_manifest.json`

## OpenScatter

Source says:

- Free/open-source Blender addon for advanced scattering.
- GitHub README uses GPL-family wording, but latest release manifest says `SPDX:GPL-2.0-or-later`; treat as GPL-family/reference-only until legal review.
- Superhive lists Blender 4.2-5.0 and $1/$10 support tiers.
- GitHub main branch only exposes README/license in normal clone; the actual addon code ships in GitHub release zips.
- Latest release found: `v1.0.7_5.0+`, published 2026-01-13, asset `openscatter_1.0.7.zip`.
- Release archive contains `openscatter/__init__.py`, `blender_manifest.toml`, a bundled `assets/OpenScatterGN_01.blend`, and icons.
- Docs describe scatter systems as layer-like units, e.g. grass, leaves, clover.
- Docs expose density, seed, density math operations, and self-collision.
- Docs expose slope, elevation, and angle masks.
- Docs expose geometry/curve proximity with seek/avoid and smooth transitions.
- Docs expose ecosystem attraction/repulsion between scatter systems.
- OpenScatter site advertises camera culling, auto low-poly generation, separate viewport/render controls, wind animation, and object collisions.
- Release source confirms a Blender UI wrapper driving Geometry Nodes modifier sockets, not a clean Python scatter library.
- Release source confirms sections for `Abiotic`, `Culling`, `Dynamics`, `Ecosystem`, `Optimization`, `Proximity`, `Emitter`, `Instances`, `Master Seed`, quick viewport scatter, and convert-to-mesh.
- Release source appends proxy objects from `OpenScatterGN_01.blend`: cone, cube, icosphere, rock, pebbles, flowers, grass clumps, bush, and tree proxies.
- Abiotic source-level controls include slope cutoff/falloff/invert, elevation height/falloff/invert/randomize amount/scale, and angle cutoff/offset/falloff.
- Culling source-level controls include vertex group masks, invert, weight-paint entry, and smooth transitions.
- Ecosystem source-level controls include attraction/repulsion to another scatter system with distance and smooth transition.
- Optimization source-level controls include viewport density reduction, optimized mesh type, proxy object, proxy scale, and camera culling.

Why it matters:

- Best open reference for the exact missing AAA scatter behaviors.
- Its UX maps cleanly to rule graphs, baked point tables, and Unity manifests.
- Its source proves the correct user-facing control model: artists edit readable controls, but production should bake deterministic point rows and sampled predicates.
- Its proxy collection explains how to keep Blender interactive with huge scatter counts without pretending proxy meshes are shipping assets.

Implement clean-room:

- scatter layers with stable IDs
- density math stack: multiply/divide/add/subtract
- seed per layer
- self-collision/min spacing
- slope/elevation/aspect masks
- geometry/curve proximity seek/avoid
- ecosystem links: repel/attract from other layers/species
- camera/export-zone culling metadata
- viewport/render/Unity LOD quality separation

Reject:

- copying GPL code into repo/runtime
- Blender collection state as production source of truth
- hidden wind/collision state unless baked into channels
- shipping OpenScatter proxy assets as final art

Affected files:

- `veilbreakers_terrain/handlers/environment_scatter.py`
- `veilbreakers_terrain/handlers/terrain_scatter_points.py`
- `veilbreakers_terrain/handlers/terrain_foliage_catalog.py`
- `veilbreakers_terrain/handlers/vegetation_system.py`
- `veilbreakers_terrain/handlers/terrain_unity_export.py`

## GScatter Assets / GScatter

Source says:

- GScatter is a free Blender scatter tool.
- Official page describes effect layers for masking, including height, texture, slope, optimization, and object effects.
- Public asset docs say GScatter assets use variant groups, up to 6 variant groups per asset and up to 30 individual models per group.
- Public asset docs say each model has 3 LODs and up to 4 texture resolutions: 2k, 4k, 8k, and 16k depending on asset.
- Public asset docs say download formats include DCC plugin FBX, GScatter `.gscatter`, and Alembic `.abc` with textures.
- Public asset docs say textures are PNG, with 16-bit height data, and use pixel-per-meter texel-density measures.
- CG Channel coverage for GScatter 0.10 says it added multi-emitters, linked effects, point-cloud proxy system, and active-camera culling.
- Same coverage says GScatter scatters via emitter plus effect layers controlling distribution, scale, rotation, procedural controls, and painted weight masks.
- Public user reports flag Blender-version fragility around 4.1/4.2. Use only with pinned Blender version and export/bake verification.

Why it matters:

- Effect-layer model is useful for VeilBreakers rule-graph design.
- Store assets may be useful, but only after direct license/format validation.
- Asset format model is exactly what our foliage library is missing: many variants, explicit LODs, texture-res budgets, and texel density metadata.
- Point-cloud proxy model belongs in our Blender QA and Unity handoff path.

Implement clean-room:

- effect layers as explicit rule nodes
- per-layer masks ordered and inspectable
- optimization/culling layer as manifest data, not hidden Blender runtime state
- asset variant groups: age/size/dead/live/seasonal/form
- texture resolution budget policy per biome and camera class
- point-cloud/proxy preview mode separate from render/export LODs
- painted masks imported as named mask channels, not anonymous Blender vertex groups

Defer:

- asset intake from store until license, file formats, texture sizes, LODs, and Unity import path are verified from the actual downloaded product/account page.

## Blender Scatter Objects

Source says:

- Official Blender manual lists Scatter Objects as a bundled add-on.
- Purpose: distribute object instances on another object.
- Blender-addons community docs describe painting scatter strokes, then controlling density, radius, scale, randomness, rotation, offset, and seed; instances save memory.

Why it matters:

- Good throwaway composition tool.
- Useful for artist studies and quick visual experiments.

Reject for production:

- no built-in biome provenance
- no required channel sampling
- no Unity manifest contract
- too manual for generated terrain

Use:

- reference-only visual/blockout pass
- optional import if a manual placement set gets exported into a point table with provenance

## Blender Bundled / Adjacent Generator Source Dive

All items in this section are GPL Blender add-on source references. Use ideas and contracts. Do not copy code into repo unless the repo deliberately accepts GPL obligations.

### Real Snow

Source says:

- Add-on creates snow meshes for selected mesh objects.
- User-facing controls include coverage percentage, snow height, and selected-faces-only mode.
- It filters to upper faces by comparing face normals against downward direction, deletes non-snow faces, computes surface area, then derives particle count from area, height, and coverage.
- It adds particles/metaballs, decimate/subdivision modifiers, adaptive subdivision, parent links back to source object, and a procedural snow material with noise/voronoi/displacement.

Why it matters:

- Frozen biome generator should not be a pretty material pasted everywhere.
- It needs face/surface eligibility, coverage, height/depth, selected mask support, mesh stats, parent/source object provenance, and material/displacement budget.

Implement clean-room:

- `snow_coverage_mask`, `snow_depth_m`, `ice_crust_mask`, and `frost_edge_mask` channels.
- Upper-face/normal eligibility plus temperature, shade/aspect, wetness, elevation, water-distance, and wind exposure.
- Snow/ice mesh outputs recorded as generated assets with source terrain cell, parent object, triangle count, material ID, and QA render.

### IvyGen

Source says:

- Ivy grows from root seeds into nodes.
- Growth blends primary direction, random direction, adhesion vector, and gravity.
- Adhesion is computed against a BVH/tree surface; collision clamps growth to the target object.
- Floating length kills unsupported branches after a threshold.
- Branching probability and max parent depth cap runaway branching.
- Leaf generation depends on branch/node weight, adhesion alignment, ground/facing state, random angle variation, and leaf probability.

Why it matters:

- Ruins/coastal cliffs need surface-following ivy/moss/vines, not random green cards.
- The missing contract is support geometry and adhesion evidence.

Implement clean-room:

- `ClimberRule`: root candidates, host surface ID, adhesion distance, gravity weight, random weight, branch probability, max floating length, max recursion, leaf density.
- Output as curve/mesh asset with node count, host object, support hit ratio, floating segment ratio, leaf count, material IDs, and LOD policy.
- Reject ivy if host support ratio is low or if leaves float through walls.

### Sapling Tree Gen

Source says:

- Sapling exposes seed, recursive branch levels, branch counts, curve resolution, length/length variation, splits, split angle/variation, vertical/outward attraction, shapes, branch distribution, base size, pruning envelope, taper/radius controls, and leaf angle/rotation/scale.
- It supports preset import/export.

Why it matters:

- This is a real tree recipe schema, even if final art comes from PlantFactory/PlantCatalog/The Plant Library.
- Our tree generator should store species recipes, not just duplicate one mesh with random scale.

Implement clean-room:

- `TreeRecipe`: seed, species archetype, branch levels, branch count vector, trunk taper, crown envelope, prune envelope, leaf recipe, wind profile, LOD/impostor budget.
- Use only for prototypes/background silhouettes unless PlantFactory/PlantCatalog quality is unavailable.

### RockGen

Source says:

- Rock generator chooses from multiple base shapes.
- It uses seeded random/skewed Gaussian sizing across X/Y/Z, displacement scale, material parameters, mossiness, color, and wetness/shininess.
- Comments call out river rock, asteroid, quarried rock-style presets.

Why it matters:

- Current coastal ruins complaint includes boulders sitting on sand hills and random blocks everywhere.
- We need two fixes: better rock assets and placement gates.

Implement clean-room:

- `RockRecipe`: geological family, base shape, size distribution, displacement profile, wetness/moss material variant, LOD/collider.
- Placement gates: no large boulders on unsupported sand-dune crests; require embed depth, slope support, material compatibility, local contact patch, and erosion/deposition context.
- Point rows must record `embed_depth_m`, `support_score`, `sampled_material`, `sampled_slope_deg`, and `rejected_reason` for rejected candidates.

### ANT Landscape Eroder

Source says:

- Grid explicitly stores `water`, `sediment`, `flowrate`, `sedimentpct`, and `capacity`.
- It supports rain maps, springs, river generation, fluvial erosion, diffuse smoothing, avalanche/thermal erosion, water mesh output, and sediment/water debug printing.

Why it matters:

- Confirms ErosionR lesson from a second source: erosion needs inspectable water/sediment/capacity/flow channels.
- This also gives scatter a data source: vegetation should follow stable wetness/deposition zones, not raw noise.

Implement clean-room:

- Feed vegetation masks from drainage, wetness, deposition, talus, erosion amount, and material layers.
- Export debug overlays for water/sediment/capacity/flow whenever erosion changes scatter eligibility.

## Freeze Generator

Source says:

- CGDive lists it as a free Blenderesse/Gumroad Geometry Nodes Fields setup for Blender 3.0.
- Secondary coverage describes applying it to objects, driving freeze progression with an Empty, generating icicles, and adjusting icicle angle/length plus ice material detail.
- A Blender Stack Exchange report says some converted text meshes may need edge cleanup/merge-by-distance before generator works.

Why it matters:

- Frozen biomes need ice crust, icicles, frozen props, frozen ruins, frost transitions, and material masks.
- Tool is useful as target behavior/reference, not runtime truth.

Implement:

- frozen-surface mask channel from temperature, elevation, shade/aspect, wetness, and water distance
- icicle placement candidates on overhangs/cliff lips/ruin edges
- frost material overlay with normalized weights
- generated ice mesh assets recorded with source, triangle count, material slots, and render proof

Reject:

- animated freeze effect as production metadata unless baked
- geometry-node state with no mesh/material/channel export

## OpenScatter Patterns To Add To VeilBreakers

Rule graph fields:

- `rule_id`
- `layer_id`
- `species_id`
- `density_per_m2`
- `seed`
- `density_math_ops`
- `mask_inputs`
- `slope_min_deg`
- `slope_max_deg`
- `elevation_min_m`
- `elevation_max_m`
- `aspect_angle_min_deg`
- `aspect_angle_max_deg`
- `paint_mask_id`
- `proximity_targets`
- `proximity_mode`: `seek` or `avoid`
- `proximity_distance_m`
- `proximity_falloff_m`
- `ecosystem_links`
- `min_spacing_m`
- `export_zone_id`
- `viewport_lod_profile`
- `render_lod_profile`
- `unity_lod_profile`
- `proxy_lod_profile`
- `mask_order`
- `mask_blend_mode`
- `smooth_transition_m`
- `invert_mask`
- `randomized_threshold_amount`
- `randomized_threshold_scale`
- `paint_mask_channel_id`
- `source_tool_version`

Point table fields to add:

These are additive fields for `ScatterPointTable`; canonical base fields such as `position`, `normal`, `orient`, `scale`, and `prototype_id` remain required.

- `source_rule_id`
- `source_layer_id`
- `sampled_slope_deg`
- `sampled_elevation_m`
- `sampled_aspect_deg`
- `sampled_wetness`
- `sampled_material_weight`
- `nearest_proximity_target_id`
- `nearest_proximity_distance_m`
- `ecosystem_link_id`
- `culled_by_camera`
- `culled_by_export_zone`
- `proxy_mesh_id`
- `viewport_density_factor`
- `render_density_factor`
- `mask_stack_hash`
- `rule_graph_hash`
- `candidate_status`: `accepted` or `rejected`
- `rejected_reason`
- `embed_depth_m`
- `support_score`

Validation gates:

- fail if dense vegetation lacks point table
- fail if point count exceeds budget without culling/LOD
- fail if slope/elevation masks are declared but sampled values are missing
- fail if ecosystem rules have circular attraction/repulsion without deterministic resolution
- fail if external scatter output is accepted without source-rule provenance
- fail if boulder/ruin/prop placement lacks contact/support evidence
- fail if placeholder primitives (`cube`, `cone`, `cylinder`, `brick`, `block`) reach final render manifest
- fail if trees use fewer than 4 approved variants per biome tier unless explicitly scoped
- fail if Blender preview scatter count differs from baked point-table accepted count beyond tolerance
- fail if viewport proxy assets are exported as final Unity render assets

## AAA Generator Backlog From This Research

1. `VegetationRuleGraph` schema: layer stack, mask stack, blend mode, seed, density, spacing, proxy/render/Unity LOD, source tool metadata.
2. `resolve_scatter_rules_to_points`: deterministic bake from terrain channels to `ScatterPointTable`.
3. `ScatterCandidateTable`: accepted/rejected candidates with reason codes for QA. This catches random blocks and boulders before render.
4. Proximity system: geometry/curve seek/avoid, smooth falloff, infinite-Z option for roads/rivers/shorelines.
5. Ecosystem system: species/layer attraction and repulsion with cycle detection and deterministic priority.
6. Surface support system: embed depth, contact patch, slope support, overhang support, host object support.
7. Proxy/LOD system: point-cloud/proxy preview in Blender, LOD/impostor in Unity, render density separate from viewport density.
8. Asset variant system: age/size/health/season/dead/live variant groups, minimum 4 variants for repeated vegetation, hero/background tiers.
9. External scatter importer: convert OpenScatter/GScatter/Blender manual scatter object transforms into point rows with provenance; never treat scene state as truth.
10. Frozen biome system: RealSnow/Freeze-style surface eligibility, snow depth, frost overlay, icicle candidates, generated mesh manifests.
11. Climber/vine system: Ivy-style root/support/adhesion/leaf contracts for ruins, cliffs, trunks, and wet stone.
12. Rock system: generated or imported rock recipes plus terrain-aware placement gates to stop dune-top boulders and square blocks.
13. Visual QA: hero, waterline, orbit, top shots, plus primitive-detector manifest scan.

## Recommended Implementation Order

1. Add `VegetationRuleGraph` schema and JSON serializer.
2. Extend `ScatterPointTable` with sampled rule/proximity/elevation/slope fields.
3. Add `ScatterCandidateTable` with rejected reasons.
4. Add rule resolver to bake masks into point tables.
5. Add OpenScatter-style proximity seek/avoid.
6. Add ecosystem repel/attract between layers.
7. Add surface support/embed-depth gates for rocks, ruins debris, boulders, trees, and props.
8. Add export-zone/camera culling fields.
9. Add proxy/LOD/render-density separation.
10. Add frozen-biome mask and icicle candidate channels.
11. Add ivy/climber host-surface pipeline.
12. Add Blender QA report that compares external scatter preview to baked point-table output.
13. Add primitive-placeholder detector and final-render manifest blocker.

## Sources

- OpenScatter Superhive: https://superhivemarket.com/products/openscatter
- OpenScatter docs: https://openscatter.notion.site/OpenScatter-Documentation-1af0def6628280868c48d20d0def802b
- OpenScatter docs mirror: https://openscatter-documentation.neocities.org/
- OpenScatter GitHub: https://github.com/GitMay3D/OpenScatter
- OpenScatter latest release inspected locally from GitHub release asset `openscatter_1.0.7.zip`
- OpenScatter site: https://openscatter.neocities.org/
- Blender Scatter Objects manual: https://docs.blender.org/manual/en/2.90/addons/object/scatter_objects.html
- GScatter: https://gscatter.com/gscatter
- GScatter asset docs: https://graswald.notion.site/Learn-About-Our-Assets-2dbfeb017c604fee93863dce5057911d
- GScatter CG Channel coverage: https://www.cgchannel.com/2023/04/graswald-releases-gscatter-0-10/
- CGDive Freeze Generator: https://addons.cgdive.com/tools/freeze-generator-setup-for-geometrynodes-fields-blender-30
- Blender Geometry Nodes / assets docs queried via Context7 official Blender manual.
- Blender add-ons source inspected locally: `real_snow.py`, `add_curve_ivygen.py`, `add_curve_sapling`, `add_mesh_rocks/rockgen.py`, `ant_landscape/eroder.py`.
