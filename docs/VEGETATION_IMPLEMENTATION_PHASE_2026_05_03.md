# Vegetation Implementation Phase - 2026-05-03

## Goal

Replace placeholder vegetation and broken prop scatter with a real asset-backed vegetation pipeline that stays editable in Blender, exportable to Unity, and auditable from manifests.

Do not rebuild scatter as a Blender-only trick. VeilBreakers owns terrain masks, biome rules, `ScatterPointTable`, and Unity export manifests.

## Tool Decisions

| Tool | Decision | Role | Do Not Use For |
|---|---|---|---|
| PlantFactory 2023 | Use | Primary procedural plant authoring/export | Runtime scatter truth |
| PlantCatalog | Use | Free species library, fast high-quality source assets | Resellable standalone model packs |
| PlantFactory 2024 | Test only | Beta export/hierarchy/UV/Pivot Painter experiments | Default production |
| VUE | Reference/look-dev | EcoSystem rules, Function Editor concepts, atmospherics, Export Central UX | Production scatter truth |
| The Plant Library | Use | Immediate free Blender vegetation library and biome visual benchmark | Direct Unity runtime contract |
| PRO Forest Bundle | Use after official license proof | Conifer/background forest starter assets | Procedural generation |
| EZ-Tree | Use for prototypes | MIT seeded GLB tree generation and recipe schema | Final AAA plant library alone |
| Infinigen | Reference | Procedural architecture, annotations, ground-truth sidecars | Heavy dependency in current pipeline |
| MTree / Geometry Nodes tree repos | Reference/patterns | Function-graph tree authoring, curve-to-mesh workflow | Copying GPL add-on code |
| Hunyuan/Meshy | Selective use | Hero props, weird/fantasy vegetation variants | Dense vegetation library replacement |
| Ivy Generator Geometry Nodes | Use | Ruins/walls/trunks/cliffs ivy authoring | Dense foliage scatter replacement |
| Vegeta Blender Addon | Maybe use | Cheap Blender asset/scatter helper if license passes | Repo scatter truth |
| Freeze Generator Geometry Nodes | Reference/use after bake | Frozen props, icicles, ice crust, winter ruins | Snow/ice runtime truth |
| OpenScatter | Reference | AAA scatter rule design: masks, culling, proximity, ecosystem layers | GPL code vendoring or runtime scatter truth |
| Blender Scatter Objects | Reference only | Fast manual composition tests | Production biome scatter |
| GScatter Assets / GScatter | Reference/intake candidate | Effect-layer model and possible assets | Unverified asset import |
| Blender Real Snow | Reference | Frozen-biome surface eligibility, snow-depth mesh/material contract | Blind snow material overlay |
| Blender IvyGen | Reference | Surface-following climber/vine algorithm for ruins/cliffs/trunks | Copying GPL code or unsupported floating vines |
| Blender Sapling | Reference/prototype | Tree recipe schema: branch levels, pruning, leaves, seed, shape | Final AAA vegetation by itself |
| Blender RockGen | Reference/prototype | Rock recipe and material-variant schema | Ungated boulder placement |
| ANT Landscape Eroder | Reference | Erosion debug channels feeding vegetation masks | Replacement for current erosion stack |

## Production Architecture

Required path:

1. Source asset or recipe: PlantFactory, PlantCatalog, The Plant Library, PRO Forest, EZ-Tree, Hunyuan/Meshy, Freeze/Ivy generators, verified asset stores.
2. Asset intake staging: source file, license file, source URL, tool version, seed/recipe if generated.
3. Blender QA: scale, origin, pivot at base, orientation, UVs, PBR materials, alpha leaves, triangle counts, LOD meshes, screenshot/render.
4. Mesh-library registration: `assets/foliage_mesh_library.json` or successor manifest.
5. Species registration: `terrain_foliage_catalog.py` species/spec metadata.
6. Rule graph: material/biome/slope/altitude/wetness/water-distance predicates resolve to baked point tables.
7. Scatter truth: `ScatterPointTable` only.
8. Unity export: `foliage_placement_manifest.json`, LOD/collider/wind/material metadata, GPU renderer path.

Existing repo contracts to preserve:

- `veilbreakers_terrain/handlers/terrain_foliage_catalog.py`
- `veilbreakers_terrain/handlers/terrain_scatter_points.py`
- `veilbreakers_terrain/handlers/environment_scatter.py`
- `veilbreakers_terrain/handlers/vegetation_system.py`
- `veilbreakers_terrain/handlers/terrain_unity_export.py`
- `docs/FOLIAGE_MANIFEST_PIPELINE.md`

## Manifest Fields To Add

Every accepted asset needs:

- `asset_id`
- `source_tool`
- `source_version`
- `source_url`
- `source_file`
- `license_origin`
- `license_allows_commercial`
- `resale_allowed`
- `plantcatalog_derivative`
- `mesh_lod_paths`
- `texture_paths`
- `material_variant_ids`
- `pivot_policy`
- `bounds_m`
- `triangle_budget_lod0`
- `collider_policy`
- `wind_profile`
- `impostor_policy`
- `blender_qa_render`
- `unity_import_status`

Every scatter point should carry:

- `species_id`
- `variant_id`
- `source_rule_id`
- `source_mask_ids`
- `biome_id`
- `material_layer_id`
- `altitude_m`
- `slope_deg`
- `wetness`
- `water_distance_m`
- `export_zone_id`
- `lod_bucket`
- `material_variant_id`
- `mask_stack_hash`
- `rule_graph_hash`
- `candidate_status`
- `rejected_reason`
- `embed_depth_m`
- `support_score`
- `proxy_mesh_id`
- `viewport_density_factor`
- `render_density_factor`

Every rejected candidate should carry:

- `candidate_id`
- `source_rule_id`
- `source_layer_id`
- `species_or_prop_id`
- `sampled_position`
- `sampled_slope_deg`
- `sampled_material_layer_id`
- `sampled_wetness`
- `sampled_deposition`
- `sampled_talus`
- `nearest_water_distance_m`
- `support_score`
- `embed_depth_m`
- `collision_reason`
- `budget_reason`
- `rejected_reason`

## VUE Best Practices To Import

Use VUE as design reference:

- material-driven EcoSystem placement
- altitude and slope bands
- wetness/water-distance predicates
- painted masks and exclusion masks
- function graph nodes: ramps, noises, filters, masks, decay fields
- published parameters: density, scale variance, clustering, falloff, LOD cutoff
- export profile separation: global defaults, biome overrides, species overrides

Reject:

- dynamic-only EcoSystems as final artifact
- hidden procedural placement without baked point tables
- VUE runtime dependency

## Scatter Tool Best Practices To Import

Use OpenScatter/GScatter/Blender scatter tools as design evidence:

- scatter layers: grass, leaves, clover, shrubs, rocks, debris, trees
- density per unit area plus global/biome/species density multipliers
- deterministic seed per layer
- self-collision/min-distance controls
- slope, elevation, and aspect/angle masks
- vertex-group/paint-mask equivalent controls
- geometry and curve proximity seek/avoid
- ecosystem attraction/repulsion between layers
- camera/export-zone culling
- viewport/render quality separation
- low-poly/LOD fallback per layer
- wind/collision as authored metadata, not hidden scene-only simulation

VeilBreakers implementation target:

- `VegetationRuleGraph`: layer nodes, mask nodes, math ops, proximity nodes, ecosystem links.
- `ScatterPointTable`: baked point output with sampled predicates and source rule IDs.
- `ScatterCandidateTable`: accepted/rejected candidates with reason codes.
- `SurfaceSupportGate`: embed depth, contact patch, slope support, material compatibility, overhang/host support.
- `ProxyLodProfile`: viewport proxy, render LOD, Unity LOD/impostor kept separate.
- `foliage_placement_manifest.json`: Unity runtime truth with LOD/collider/wind/material data.

Reject:

- invisible Blender-only scatter systems
- scene collections as the only source of truth
- unbounded random scatter without min-distance/culling/export zones
- GPL code copying
- viewport proxy assets exported as final render assets
- final renders containing placeholder primitives: cube, cone, cylinder, block, brick

## Source-Dive Patterns Added After Deeper Review

OpenScatter release source:

- latest release found: `v1.0.7_5.0+`, published 2026-01-13
- source is a large Blender UI wrapper around Geometry Nodes sockets plus bundled `.blend`
- useful controls: slope/elevation/angle masks, vertex-group masks, proximity, ecosystem attraction/repulsion, wind/collision, viewport density, optimized mesh, proxy object, camera culling, master seed, convert-to-mesh
- license conflict: README says GPL-3.0; Blender manifest says `GPL-2.0-or-later`; treat as GPL reference-only

GScatter/Graswald public asset docs:

- assets ship with variant groups; public docs claim up to 6 variant groups and up to 30 models per group
- 3 LODs per model
- texture resolutions up to 2k/4k/8k/16k depending on asset
- textures are PNG, with 16-bit height data and pixel-per-meter texel-density framing
- formats: FBX for DCC plugins/manual import, `.gscatter`, and Alembic
- GScatter version compatibility has public failure reports around Blender 4.1/4.2, so any use must be pinned and baked

Blender bundled generator source:

- Real Snow proves frozen surfaces need eligible faces, coverage, height/depth, generated mesh stats, and material displacement budget.
- IvyGen proves climbers need root seeds, host-surface BVH/adhesion, gravity/random/primary direction weights, max floating length, branch caps, and leaf probability.
- Sapling proves tree generation needs persisted recipes: seed, branch levels, branch count vector, pruning envelope, taper/radius, crown shape, leaves.
- RockGen proves rock variation should be recipe-based: base shape, skewed size distributions, displacement profile, moss/wetness/color.
- ANT Landscape Eroder reinforces that vegetation masks need erosion debug channels: water, sediment, capacity, flowrate, sediment percentage, rain/spring maps.

## PlantFactory / PlantCatalog Intake

Default:

- PlantFactory 2023 for production exports.
- PlantFactory 2024 only for isolated tests.
- FBX into Blender first.
- Alembic only for baked wind/animation tests.
- OBJ only as static fallback.

Block asset if:

- PlantCatalog-derived asset lacks `resale_allowed=false`.
- pivot is not at base.
- LODs are absent and no local LOD/impostor plan exists.
- alpha cards render as black boxes.
- Unity import creates unmanaged material sprawl.
- wind metadata is assumed instead of recorded.

## The Plant Library Intake

Use immediately for visual uplift, especially:

- grass clumps
- shrubs
- branches
- dryland plants
- forest floor assets
- small trees/background trees

Use Geo-Scatter/Biome-Reader only to study/preview biome composition. If a biome looks good, translate it into VeilBreakers rule graphs and `ScatterPointTable`; do not depend on `.scatpack` as runtime truth.

## Coastal Ruins Cleanup Phase

First visual target:

- keep current sunken coastal terrain, sand, shore, water composition
- remove cube/brick/block placeholder scatter
- replace low-poly cone pines
- replace bad boulder-on-dune placements
- replace crude dock/column/wall placeholder props with validated assets

Acceptance:

- no placeholder cube/cone/cylinder props in final render
- object manifest names every vegetation/prop source
- Blender render proof from hero, waterline, orbit, and top shots
- point-table evidence for all dense vegetation
- rock/boulder placements pass `SurfaceSupportGate`
- dune boulders require `support_score >= threshold`, `embed_depth_m > 0`, and material compatibility
- trees use approved asset variants, not repeated cone/trunk placeholders
- square/block/brick debris must be classified as intentional ruin kit assets with source mesh IDs, not generated primitives

Immediate coastal fix order:

1. Detect and quarantine placeholder primitive scatter by mesh name, primitive topology, and source manifest absence.
2. Preserve existing coastal terrain/water/sand channels.
3. Replace trees with Plant Library or PlantFactory/PlantCatalog validated variants.
4. Replace dune boulders with validated rock assets and support-gated placements.
5. Replace brick/block noise with ruin-kit asset instances or remove.
6. Re-bake scatter point/candidate tables.
7. Render hero/waterline/orbit/top proof before quality claim.

## Erosion Lessons From ErosionR

Use ErosionR only as reference. Our erosion architecture is stronger, but ErosionR exposes better artist debug channels.

Add VeilBreakers erosion debug/export overlays:

- `water_volume`
- `sediment_load`
- `sediment_capacity`
- `flowrate`
- `scour_delta`
- `deposition_amount`
- `erosion_amount`

Fix/gate:

- wind erosion must remain delta-only
- `pass_erosion` produced channels must list every written channel
- stream-power erosion must not silently fall back to uniform drainage without a hard warning/gate in production
- erosion goldens need before/after height, drainage, wetness, capacity, deposition, and flow overlays

## Water Tool Notes

Alt Tab Ocean & Water:

- free Superhive Blender add-on
- Blender 4.0-4.5
- GPL
- good material/look-dev reference for ocean/pond surface, foam, color, waves
- do not vendor code into repo without GPL review
- not a Unity water contract by itself

RealTimeFlow:

- $5 Superhive Blender add-on
- Blender 4.1
- MIT per Superhive listing
- uses dynamic paint/effectors for real-time water behavior
- useful for studying local ripples/interaction masks
- Blender simulation state must be baked/exported into VeilBreakers channels before production use

Optional stronger reference:

- Dynamic Flow is terrain-aware Geometry Nodes water/foam for Blender 5.0+, $8.
- Interesting for shore/river look-dev, but Blender 5.0 dependency is a risk for current pipeline.

VeilBreakers water must keep these channels as truth:

- `water_surface_elevation_m`
- `water_depth_m`
- `flow_direction_xy`
- `flow_speed_mps` or equivalent
- `flow_accumulation`
- `foam_mask`
- `mist_mask`
- wet rock / shoreline material masks

## Implementation Order

1. Create asset intake manifest schema and validation command.
2. Import 5 Plant Library assets and 3 PlantFactory/PlantCatalog assets as test fixtures.
3. Convert one Plant Library biome preview into VeilBreakers rule graph + point table.
4. Add license/provenance gates to foliage mesh library.
5. Add scatter point provenance fields.
6. Add `ScatterCandidateTable` with rejected reasons.
7. Add `SurfaceSupportGate` for boulders, ruins debris, trees, cliff props, and roots.
8. Add primitive-placeholder detector and final-render blocker.
9. Add Blender QA render/report command for accepted foliage assets.
10. Add Unity import smoke for foliage manifest + LOD/collider/material metadata.
11. Replace coastal ruins placeholder vegetation/props.
12. Add erosion debug channels and wind delta-only regression test.
13. Add water look-dev reference manifest for Alt Tab / RealTimeFlow without making either runtime truth.
14. Add ivy authoring intake: generate on ruins/cliffs, realize or bake curves/meshes, record mesh stats, support ratio, LOD/collider policy, and Blender render proof.
15. Trial Vegeta on a disposable Blender scene; accept only if license is clear and outputs can be converted to mesh-library entries plus `ScatterPointTable`.
16. Prototype `VegetationRuleGraph` from OpenScatter/GScatter patterns: density math, slope/elevation/aspect masks, proximity seek/avoid, ecosystem attraction/repulsion, self-collision, export culling.
17. Add frozen-biome intake: Freeze Generator/RealSnow-style outputs become validated ice-crust/icicle/snow mesh/material assets plus snow/ice/wetness channel metadata.

## Required Gates

Run before PR:

```powershell
python scripts\callable_census_gate.py --strict-zero
python scripts\scan_callable_wiring.py --strict-no-risk
pyright -p pyrightconfig.json
python -m pytest veilbreakers_terrain\tests\test_terrain_geology.py -q
python -m pytest veilbreakers_terrain\tests\test_terrain_pipeline_smoke.py veilbreakers_terrain\tests\test_terrain_master_registrar.py veilbreakers_terrain\tests\test_terrain_iteration.py -q
python scripts\visual_testing_readiness_gate.py
```

Visual proof required before quality claims:

- Blender runtime available
- non-placeholder renders
- hero/waterline/orbit/top shots
- no black alpha-card boxes
- no dense scatter without point table

## Current Push Blockers

Do not push/PR as complete until these are green or explicitly scoped out:

- callable strict-zero gate
- wiring strict-no-risk gate
- pyright
- focused pipeline pytest
- visual readiness gate
- dirty generated outputs reviewed and either intentionally staged or ignored
