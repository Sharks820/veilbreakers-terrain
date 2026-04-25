# R11 Dedicated AAA Terrain Research References — 2026-04-24

This file is the reference base used by `scripts/build_r11_research_aaa_callable_audit.py`.
The target is dark-medieval, RPG-style, large open-world terrain: mountains, cliffs, hills, flats, streams, rivers, roads/pathways, forest edges, biome transitions, scatter, materials, and validation.

## Sources

### UE_PCG: Unreal Engine PCG Framework / biome generation
- URL: https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-overview?application_version=5.6
- Applied standard: Graph-driven procedural tools for assets, biomes, and entire worlds; designer iteration is a first-class requirement.

### HOUDINI_HEIGHTFIELDS: SideFX Houdini Heightfields and terrains
- URL: https://www.sidefx.com/docs/houdini/heightfields/index.html
- Applied standard: Layered heightfields, masks, paintable controls, erosion, conversion to geometry for vertical detail, and scatter on vertical areas.

### HOUDINI_ERODE: SideFX HeightField Erode
- URL: https://www.sidefx.com/docs/houdini/nodes/sop/heightfield_erode.html
- Applied standard: Hydraulic and thermal erosion at controllable feature scales; rainfall/weathering, bank angle, flow/debris/sediment outputs, spatial masks.

### GAEA_EROSION: QuadSpinner Gaea Erosion
- URL: https://docs.gaea.app/using-gaea/crafting-the-surface/erosion
- Applied standard: Believable terrain comes from erosion layered with other processes, selective processing, downcutting, and deposits.

### GAEA_TERRAINS: QuadSpinner Gaea terrain tools
- URL: https://www.quadspinner.com/Gaea/Terrains
- Applied standard: Rock/sandstone/limestone tools, strata, sediment, fractures, protruding outcrops, draw/mask nodes, and volume-preserving surface detail.

### FROSTBITE_TERRAIN: Frostbite Battlefield 3 terrain system
- URL: https://www.ea.com/frostbite/news/terrain-in-battlefield-3-a-modern-complete-and-scalable-system
- Applied standard: Large open-world terrain requires hierarchy, high resolution at distance, in-game editing, procedural virtual texture caching, prioritization, and streaming.

## R11 Grade Meaning

- `A`: Runtime-shipped, visually proven, engine/import-proven, and comparable to the cited AAA/tool standards.
- `A-`: Strong implementation with runtime wiring and tests, but missing one major AAA proof such as rendered goldens or engine import smoke.
- `B+`: Solid algorithm/runtime surface, but visible/live-output gaps remain.
- `B`: Works structurally, but output quality is not AAA.
- `B-`: Test-only, weakly wired, or missing production proof.
- `C+` or lower: orphaned, missing wiring evidence, placeholder, degraded, or not a shipped terrain feature.
