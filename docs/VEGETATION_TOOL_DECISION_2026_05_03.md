# Vegetation Tool Decision - 2026-05-03

## Decision

Primary free vegetation authoring/source stack:

**PlantFactory + PlantCatalog**

Use **PlantFactory** to create, customize, and export vegetation. Use **PlantCatalog** as the free species library. Use **The Plant Library** and **PRO Forest Bundle** as starter asset packs after import/license validation. Use **VUE** only as reference/optional authoring for ecosystem-scatter ideas, atmospherics, terrain look-dev, and graph/function best practices.

This supersedes the earlier TreeBox-first decision. TreeBox remains a good Blender-native fallback under $30, but e-on is now the better value if export/import tests pass.

## Why

Bentley officially made VUE, PlantFactory, and PlantCatalog free perpetual downloads. The official FAQ says:

- Commercial use is allowed.
- Assets exported from VUE/PlantFactory may be used commercially.
- Stock content shipping with VUE/PlantFactory may be retextured, remodeled, and resold.
- PlantCatalog plants may be used commercially in games/projects/client files.
- PlantCatalog-derived models may not be resold as marketplace model assets.
- Perpetual builds need no online activation and do not expire.

## Tool Roles

### PlantFactory

Primary vegetation generator.

Use for:

- trees
- shrubs
- grasses
- reeds
- vines/organic plant forms
- hero vegetation
- biome-specific variants
- LOD/export prep
- wind/hierarchy metadata experiments

Best fit because it is a real procedural plant app, not a small Blender node preset.

### PlantCatalog

Primary free plant asset/species library.

Use for:

- fast quality jump over placeholder pines
- real species coverage
- biome reference
- exported game/project vegetation assets

Restriction:

- Do not resell PlantCatalog-derived models as marketplace assets.
- For assets we may someday sell as standalone model packs, create from scratch in PlantFactory without PlantCatalog textures/metanodes.

### VUE

Reference and optional look-dev tool.

Use for:

- EcoSystem scatter best practices
- density functions
- painted ecosystem masks
- material/altitude/slope driven vegetation placement concepts
- atmospheres/clouds
- export-central and published-parameter UX ideas
- function graph organization/performance ideas

Do not use VUE EcoSystems as production scatter truth. VeilBreakers scatter point tables remain canonical.

### The Plant Library

Primary free Blender-ready starter vegetation library.

Use for:

- immediate replacement of placeholder ground cover, shrubs, branches, grass clusters, flowers, dryland plants, and some tree/floor assets
- Blender Asset Browser intake
- quick biome look-dev through Geo-Scatter/Biome-Reader biomes
- visual benchmarks for plant density, layer composition, and material variety

Restrictions:

- Treat `.scatpack` / biome data as Blender look-dev/reference only unless license review confirms redistribution path.
- Do not make Geo-Scatter or Biome-Reader the production scatter source of truth.
- Do not ship raw `.blend` library state as Unity runtime contract.

Pipeline call:

- **Use.** Best immediate free library for fast visual uplift.
- Register accepted assets through the VeilBreakers foliage mesh library and scatter manifests.

### PRO Forest Bundle

Free/low-cost conifer forest starter pack, pending official Gumroad metadata verification.

Use for:

- conifer replacement set
- LOD/OBJ import tests
- large-scale forest background assets

Restrictions:

- Secondary sources report 17 OBJ assets, 4K diffuse/gloss/normal/opacity maps, LODs, and CC0. Verify this from the official Gumroad download/license before production import.
- OBJ import means materials, pivots, colliders, and LOD hierarchy need explicit repair/manifesting.

Pipeline call:

- **Use after license proof.** Good immediate background forest pack, not a procedural generator.

### TreeBox

Fallback only.

Use if:

- e-on export/import into Blender fails
- we need fast Blender-native Geometry Nodes editing
- we need stylized/anime trees specifically

### Ivy Generator Geometry Nodes

Use for ruins, walls, trunks, cliffs, and abandoned-coast overgrowth.

Observed fit:

- free Gumroad Geometry Nodes setup for Blender 3.0+
- Royalty Free per secondary usage writeups
- node-tree append workflow, no heavy external runtime
- good match for sunken ruins and fantasy overgrowth

Restrictions:

- Treat as Blender authoring/reference unless the generated ivy is realized, validated, and registered as mesh assets or scatter records.
- Watch polygon count; ivy can get heavy fast.
- Prefer BagaIvy/BagaPie successor only if we later accept a paid/extra dependency.

Pipeline call:

- **Use.** Best free ivy-specific generator found so far.

### Vegeta Blender Addon

Use as optional under-budget Blender vegetation/scatter convenience pack.

Observed fit:

- $10+
- Blender 3.0+
- add-on zip, 152 MB
- asset scatter onto selected objects
- Geometry Nodes workflow available
- 4.9 rating with 1000+ Gumroad ratings

Restrictions:

- Gumroad page did not expose a clear license in scraped text. Verify license before production intake.
- Treat its scatter output as Blender look-dev/reference until converted into VeilBreakers point tables.
- Do not let it bypass asset manifests, source metadata, LOD/collider checks, or Unity import QA.

Pipeline call:

- **Maybe use.** Worth trying because cheap and highly rated, but below PlantFactory/PlantCatalog and Plant Library until license/output quality are verified.

### Freeze Generator Geometry Nodes

Use as frozen-biome look-dev/reference and possible Blender authoring input.

Observed fit:

- free CGDive/Gumroad resource
- Blender 3.0 Geometry Nodes fields setup
- secondary source describes object freezing, icicle creation, adjustable icicle angle/length, fine ice material controls, and animated freeze progression through an Empty

Restrictions:

- Treat as reference until generated ice/frost/particles are realized and validated.
- Do not use as runtime truth for snow, ice, wetness, or temperature channels.
- Mesh-input fragility exists: a Blender Stack Exchange report notes text converted to mesh may need merge-by-distance/remesh cleanup before the generator works.

Pipeline call:

- **Use as reference.** Good frozen-biome shader/geometry target, especially for ice crust, icicles, frozen props, cliff ice, and winter ruins.

### OpenScatter

Use as primary open-source scatter reference.

Observed fit:

- free/open-source Blender addon
- `GPL-2.0-or-later` per latest release manifest SPDX metadata; GitHub/Superhive text also describes OpenScatter as GPL-family.
- Blender 4.2-5.0 on Superhive
- GitHub repo has addon code, assets, and docs
- layer-style scatter systems
- density/seed/math controls
- self-collision limit
- slope/elevation/angle masks
- geometry and curve proximity seek/avoid
- ecosystem attraction/repulsion between scatter systems
- camera culling, auto low-poly generation, separate viewport/render controls
- wind animation and object collision features

Restrictions:

- GPL code cannot be copied into repo/runtime without license review.
- Blender scatter output cannot replace `ScatterPointTable`.
- Treat animation/collision/wind as design reference unless baked into explicit channels and Unity-side contracts.

Pipeline call:

- **Use as reference and possible external Blender QA tool.** Mine behavior patterns. Reimplement clean-room inside VeilBreakers manifests/rule graphs if needed.

### Blender Scatter Objects

Use as lowest-friction manual/reference scatter tool.

Observed fit:

- bundled with Blender
- official manual says it distributes object instances on another object
- useful for quick artist placement studies and throwaway composition tests

Restrictions:

- Too manual and limited for production terrain.
- No biome/rule provenance unless we export/annotate it ourselves.

Pipeline call:

- **Reference only.** Useful for quick visual tests, not production scatter.

### GScatter Assets / GScatter

Use as source of asset-pack and effect-layer references.

Observed fit:

- GScatter is described as a free Blender scatter tool.
- Official GScatter page calls out effect layers for masking, including height, texture, slope, optimization, and object effects.
- Store page was not crawlable in this pass; per-asset license/format details still need direct download/account-side verification.

Restrictions:

- Do not assume store assets are production-safe without per-asset license, format, texture, LOD, and Unity import proof.
- Do not rely on GScatter as production runtime scatter.

Pipeline call:

- **Reference plus possible asset intake.** Use effect-layer structure as rule-graph inspiration; treat assets like any other external library.

## Release Choice

Install both if practical:

- **2023**: production-proven/stable.
- **2024**: beta/as-is, but has useful new export, UV, graph, LOD, and Unreal/Pivot Painter features.

Default production path: **PlantFactory 2023 first**, then test 2024 side-by-side for features.

## Pipeline Use

Our repo still owns placement/runtime truth:

- `terrain_foliage_catalog.py`
- `vegetation_system.py`
- `_scatter_engine.py`
- `procedural_grass.py`
- `environment_scatter.py`
- `terrain_unity_export.py`

Required flow:

1. Author/customize plant variants in PlantFactory.
2. Export to a staging asset library.
3. Import into Blender for visual QA and material/scale/pivot validation.
4. Register each variant in `assets/foliage_mesh_library.json` or equivalent manifest.
5. Add/resolve species in `terrain_foliage_catalog.py`.
6. Scatter only through `ScatterPointTable`.
7. Export Unity foliage placement manifests with LOD, wind profile, collider, impostor, and material metadata.
8. For Plant Library / PRO Forest assets, normalize imported meshes into the same manifest path; no bypass.

## Import/Export Gate

Before accepting e-on as production-ready, validate:

- exported format path into Blender: FBX/OBJ/Alembic/USD as available
- texture maps present and correctly linked
- scale/origin/pivot sane
- material slot count acceptable
- UVs valid
- LODs exported or generated locally
- wind/hierarchy data usable or safely ignored
- Unity import path clean
- license metadata records whether asset is PlantFactory-original or PlantCatalog-derived

## Hard Rules

- No generated vegetation enters terrain without asset manifest entry.
- No VUE/PlantFactory scatter replaces repo `ScatterPointTable`.
- No Geo-Scatter/Biome-Reader `.scatpack` replaces repo `ScatterPointTable`.
- No PlantCatalog-derived models get marked resale-safe.
- No Plant Library or PRO Forest asset enters production without license/source metadata.
- No generated ivy enters production without realized mesh/curve stats and LOD/collider policy.
- No OpenScatter/GScatter/Blender Scatter Objects output enters production without conversion to `ScatterPointTable` plus source-rule provenance.
- No frozen-biome generator output enters production without realized mesh/material stats and water/ice/snow channel metadata.
- No visual quality claim without Blender render/viewport proof.
- No placeholder cone/cube vegetation in final terrain output.

## Source Notes

- Bentley e-on free-download FAQ: free perpetual VUE, PlantFactory, PlantCatalog; commercial use/export allowed; PlantCatalog resale restriction; no activation/no expiry.
- Bentley FAQ recommends 2023 as production-proven and 2024 as unfinished beta/as-is with newer features.
- Bentley FAQ lists PlantFactory 2024 improvements: UV preview/options, custom mesh hierarchy, Pivot Painter 2.0 support for Unreal wind, material/LOD/export improvements, graph node improvements, published parameters.
- Bentley FAQ lists VUE 2024 improvements: Export Central, Published Parameters Editor, Function Editor node/performance/annotation improvements, OpenVDB/cloud/export updates.
- Superhive Plant Library page lists 170+ HQ vegetation assets, 31 free biomes, Blender Asset Browser readiness, Blender 3.3-4.3 support, and Royalty Free license.
- Geo-Scatter legal/docs say Biome-Reader scripts are GPL, the scatter engine is under a royalty-free-like EULA, commercial use is allowed, and `.scatpack`/biome data redistribution is restricted.
- PRO Forest Bundle secondary coverage reports OBJ assets, 4K maps, LODs, and CC0; official Gumroad proof still required before intake.
- Blenderesse/Antoine Bagattini Ivy Generator page and secondary writeups describe a free Blender 3.0+ Geometry Nodes ivy generator; CG Journal reports personal/commercial use and Royalty Free license.
- Vegeta Gumroad page lists Blender 3.0+, asset scatter, Geometry Nodes workflow, $10+ price, 152 MB add-on zip, and 4.9/1000+ ratings; license not visible in scraped page.
- CGDive lists Freeze Generator as a free Blenderesse/Gumroad Geometry Nodes Fields resource for Blender 3.0; secondary coverage describes animated object freezing, icicles, and ice material controls.
- Superhive and GitHub list OpenScatter as free/open-source/GPL-family advanced Blender scattering; latest release manifest inspected as `GPL-2.0-or-later`. Docs cover layer-style scatter systems, density/seed/math, self-collision, culling, slope/elevation/angle masks, proximity seek/avoid, and ecosystem attraction/repulsion.
- Blender manual lists Scatter Objects as a bundled addon for distributing object instances on another object.
- GScatter official page describes a free Blender scatter tool with effect layers for masking, optimization, and object effects; asset store details still need direct per-asset verification.
