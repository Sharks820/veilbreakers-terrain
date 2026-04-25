# R12 Strict AAA Terrain Research References - 2026-04-25

Context7 was requested but no Context7 MCP/tool resource is exposed in this session; this audit uses web/GitHub primary-source research available to Codex.

## Sources

### UE_PCG: Unreal Engine 5.6 Procedural Content Generation Framework
- URL: https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-overview?application_version=5.6
- Audit standard: Graph-driven generation, designer-facing controls, biome/asset workflows, deterministic runtime exposure.

### UE_PCG_BIOME: Unreal Engine PCG Biome Core and Sample Plugins
- URL: https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-pcg-biome-core-and-sample-plugins-in-unreal-engine?application_version=5.6
- Audit standard: Attribute tables, feedback loops, recursive subgraphs, runtime hierarchical generation for biomes.

### HOUDINI_ERODE: SideFX HeightField Erode
- URL: https://www.sidefx.com/docs/houdini/nodes/sop/heightfield_erode.html
- Audit standard: Multi-scale hydraulic/thermal erosion, rainfall/weathering, erodability masks, sediment/debris/flow/flowdir outputs.

### GAEA_EROSION2: QuadSpinner Gaea Erosion2
- URL: https://docs.gaea.app/reference/nodes/simulate/erosion2.html
- Audit standard: Advanced hydraulic erosion with downcutting, deposition, orographic effects, deterministic performance.

### FROSTBITE_TERRAIN: Frostbite Battlefield 3 Terrain System
- URL: https://www.ea.com/frostbite/news/terrain-in-battlefield-3-a-modern-complete-and-scalable-system
- Audit standard: Hierarchy, high resolution at distance, realtime editing, procedural virtual texture cache, streaming/prioritization.

### INFINIGEN: Princeton VL Infinigen
- URL: https://github.com/princeton-vl/infinigen
- Audit standard: Procedural natural-world generator with configurable cameras, generated assets/materials, fluid simulation, export paths.

### SIMPLE_HYDROLOGY: SimpleHydrology
- URL: https://github.com/weigert/SimpleHydrology
- Audit standard: Particle hydrology extending hydraulic erosion to streams, pools, deterministic flooding, momentum/discharge maps.

### WORLDENGINE: WorldEngine
- URL: https://github.com/Mindwerks/worldengine
- Audit standard: Plate simulation, rain shadow, erosion, humidity, permeability, Holdridge life-zone biomes.

### MAPGEN2: Red Blob Games Mapgen2
- URL: https://www.redblobgames.com/maps/mapgen2/
- Audit standard: Polygon maps, water bodies, river networks, biome distribution, explicit design constraints.

### FASTNOISELITE: FastNoise Lite
- URL: https://github.com/Auburn/FastNoiseLite/wiki/Documentation
- Audit standard: Seeded coherent noise, bounded outputs, frequency/noise-type controls, deterministic defaults.

## Strict Grade Rule

- `B` requires runtime wiring, direct tests, and domain-appropriate live visual/engine proof for product terrain surfaces.
- `C+` means the callable may be useful and tested, but lacks true AAA terrain-generator evidence.
- `C` means runtime or production reachability is weak.
- `D+` means orphaned/missing wiring/no acceptable strict evidence.
