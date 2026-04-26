# Terrain Tool Deep Research Dossier - 2026-04-26

Status: research dossier only. This is not the implementation plan.

Purpose: consolidate external terrain-generation practices from Houdini, World Creator, Gaea, World Machine, Unreal PCG, Unity Terrain, Blender Geometry Nodes/API, Maya/Bifrost/MASH, SpeedTree, VUE/PlantFactory, and open-source terrain generators, then map those practices against the current VeilBreakers callable/wiring evidence.

## 0. Source Confidence Rule

This dossier must not treat a random GitHub repository as industry best practice.

Source confidence tiers:

- Tier 1 - official vendor/engine documentation: SideFX Houdini, World Creator, QuadSpinner Gaea, World Machine, Epic Unreal Engine, Unity, Blender, Autodesk Maya/Bifrost/MASH, SpeedTree, Bentley/e-on. These define the primary practice standard.
- Tier 2 - vendor sample projects, official technical talks, and official bridge/plugin docs. These can support or clarify Tier 1 patterns.
- Tier 3 - open-source repositories and academic/demo projects. These are useful references for algorithms and implementation examples, but they do not establish "best practice" unless the same pattern is also present in Tier 1 or Tier 2 sources.
- Tier 4 - blogs, forums, Reddit, tutorials, and unverified comparisons. These are not used as authority for architecture decisions.

Validated Tier 1 patterns across multiple professional tools:

- Layered heightfield/mask data, not direct final mesh edits only.
- Erosion/water outputs preserved as channels/layers: flow, flow direction, sediment/wear/deposits/debris, water depth, velocity/speed.
- Scatter driven by masks/distributions/point data with density, seed, normal/orientation, scale, and instance/prototype metadata.
- Separation between procedural density/detail masks, exact instance point clouds, and manual/hero object placement.
- Exportable intermediate artifacts such as heightmaps, splat/weight maps, detail density maps, point/instance tables, tiles, regions, and selected node ports.
- Debuggable graph/node/attribute workflows rather than opaque one-shot scripts.
- Performance strategies for production scenes: tiles/regions, lower-resolution previews, caches, instancing, LODs, billboards/impostors, and display percentages/proxies.

GitHub/open-source references in this document are therefore kept as algorithmic examples only. They are not allowed to override the Tier 1 professional-tool standard.

### Verified Industry-Practice Matrix

| Practice | Official sources that verify it | Notable evidence |
|---|---|---|
| Layered terrain fields/channels | Houdini HeightFields; World Machine Erosion; Gaea Build Options | Houdini HeightField Erode produces `height`, `sediment`, `debris`, `flow`, and `flowdir`; World Machine erosion outputs flow/wear/deposition masks; Gaea exports selectable ports such as Out, Flow, Wear, and Deposits. |
| Multi-scale hydraulic/thermal erosion | Houdini HeightField Erode; Gaea Erosion/Erosion2; World Machine Erosion/Thermal Erosion | Houdini explicitly supports chaining erosion at multiple scales; Gaea Erosion2 exposes downcutting, sediment/deposition, erosion scale, and rainfall/orographic controls; World Machine exposes flow/wear/deposition masks for texturing. |
| Water as data, not a flat plane | World Machine Water; Houdini flow fields; Gaea river/erosion outputs | World Machine water includes elevation/depth/velocity concepts; Houdini flow fields produce flow and flow direction; Gaea exposes flow/wear/deposit outputs. |
| Scatter as points/attributes/masks | World Creator Objects; Blender Geometry Nodes; Maya Bifrost; Unreal PCG | World Creator separates `Instance` point-cloud export from `Detail` mask export; Blender Distribute Points on Faces transfers attributes, normals, rotations, stable ids, density, and Poisson spacing; Bifrost scatter supports density weights, overlap culling, property transfer, and normal/tangent orientation; Unreal PCG uses point properties and density/seed/attributes. |
| Procedural vs. manual/hero placement separation | World Creator Objects/Object Collections; Unreal PCG workflows | World Creator uses biome object layers/distribution stacks for procedural placement and scene object collections for manual/hero placement. |
| Exportable intermediate artifacts | Gaea Build Options; Unity TerrainData; World Machine outputs | Gaea supports regions, tiles, selectable ports, and command-line builds; Unity TerrainData separates heightmaps, detail layers, tree instances, and alpha maps; World Machine outputs erosion masks/weightmaps/splatmaps. |
| Performance path for weak hardware | Gaea Build Options/Build Swarm; Blender instancing/Geometry Nodes; Unity/SpeedTree LOD/detail systems | Gaea supports regions, tiles, profiles, and cache-related build controls; Blender/PCG-style scatter can remain points/instances before final realization; SpeedTree documents LOD/billboards/wind LOD for dense vegetation. |

If a claim in this dossier only appears in an open-source project and not in this matrix or a Tier 1/Tier 2 source, it should be treated as a research lead, not an implementation requirement.

### GitHub Research Validation Result

The GitHub/open-source findings were reclassified after source review:

- Infinigen: useful procedural-world reference, not an industry best-practice authority by itself. Its usable takeaways are only the ones also supported by official tools: procedural assets as inspectable data, generated materials/assets with metadata, camera/render validation, and exportable outputs.
- WorldEngine: useful climate/biome algorithm reference, not a 3D terrain production standard. Its plate/rainfall/humidity/biome concepts are supporting evidence for the same layered climate/biome approach used by terrain tools, not standalone proof.
- SimpleHydrology: useful hydrology/erosion algorithm reference, not a production terrain pipeline standard. Its stream/pool/flooding ideas support, but do not replace, the official water-channel evidence from Houdini, Gaea, and World Machine.
- FastNoiseLite: useful seeded noise primitive, not terrain generation best practice by itself. It remains a primitive underneath a larger layered pipeline.
- Red Blob Mapgen2: useful map-design and river/biome constraint reference, not AAA 3D terrain proof.

No GitHub repository in this research is allowed to define the architecture standard alone. The accepted standards in this dossier are the patterns independently verified in Tier 1/Tier 2 sources: Houdini, World Creator, Gaea, World Machine, Unreal PCG, Unity Terrain, Blender Geometry Nodes/API, Maya/Bifrost/MASH, SpeedTree, and official vendor bridge/export documentation.

## 1. Core Finding

The current generated scene failure is not primarily an art-tuning problem. It is a pipeline-contract problem.

Every serious terrain tool researched treats the world as layered procedural data first:

- height/elevation fields
- masks/distributions
- erosion products such as flow, sediment, debris, wear, deposits
- water surface/depth/velocity/flow direction
- scatter points with attributes
- material splat/weight layers
- exportable/inspectable intermediate artifacts
- debug views and deterministic build variants

The current repo contains many of those pieces, but the local audits show that the richer implementations are often orphaned, bypassed, duplicated, or not proven by live render/engine evidence. A one-shot Blender script that directly composes a heightmap, water plane, tree scatter, and material cannot hit the AAA bar because it skips the data contracts that professional tools depend on.

## 2. External Tool Practices

### Houdini

Primary sources:

- https://www.sidefx.com/docs/houdini/heightfields/index.html
- https://www.sidefx.com/docs/houdini/nodes/sop/heightfield_erode
- https://www.sidefx.com/docs/houdini/nodes/sop/heightfield_scatter.html
- https://www.sidefx.com/docs/houdini/heightfields/scatterattribs.html
- https://www.sidefx.com/docs/houdini/heightfields/texturelayers.html
- https://www.sidefx.com/docs/houdini/heightfields/flowfields.html

Relevant practices:

- Houdini HeightFields are not just mesh output. They are volumes/layers where the base `height` layer is accompanied by terrain masks and derived data.
- HeightField Erode produces named outputs/layers such as `sediment`, `debris`, `flow`, and `flowdir`. This is exactly the kind of information our water, material, cliff, and scatter systems should consume.
- HeightField Erode supports multi-scale erosion: large feature erosion can shape landforms, then smaller feature erosion can add gullies and local detail.
- Houdini keeps layer names configurable through layer bindings. This avoids silent assumptions about where water/flow/debris data live.
- Texture layering is driven by stored terrain layers/masks. The docs explicitly describe using layers like `flow`, `debris`, `sediment`, `water`, and custom masks for material mixing.
- HeightField Scatter emits point geometry from masks and density/coverage settings, with safety caps such as point-count limits.
- Houdini scatter workflows lean on point attributes like `orient`, `pscale`, hue/saturation, height, distance, temperature, and wind direction to control instances and shaders.

Implication for VeilBreakers:

- Our terrain passes must preserve, validate, and export layered channels rather than only final mesh/render output.
- Scatter must be point/attribute based, not just random mesh placement.
- Water/foam/material/foliage must consume erosion and flow products.
- Any callable claiming to generate cliffs/water/scatter/materials without producing or consuming the relevant channels should be treated as below the AAA bar until proven otherwise.

### World Creator

Primary sources:

- https://docs.world-creator.com/reference/terrain/distributions
- https://docs.world-creator.com/reference/terrain/biome/objects
- https://docs.world-creator.com/reference/terrain/shape-layers/path
- https://docs.world-creator.com/reference/scene/object-collection
- https://docs.world-creator.com/reference/terrain/shape-layers

Relevant practices:

- Distributions are procedural or simulated masks based on terrain features, including cavity, curvature, height, flow, rocks, path, rivers, slope, steepness, roughness, sea level, and more.
- Distributions are layer-stack based with operations such as multiply, add, subtract, min, and max.
- Object Layers exist at biome level. Object Collections operate at whole-terrain level and are intended for final hero-object placement and shot finishing.
- Object Layers expose seed, instance distance, density, push, height offset, normal offset, normal alignment, scale ranges, rotation ranges, and distribution-linked density/scale/gradient.
- World Creator explicitly separates object export modes:
  - `Instance`: synchronize/export object as a point cloud.
  - `Detail`: export object as a mask for procedural renderer-side scattering.
- Sub-objects are first-class: mushrooms around a stump, plants around a parent, etc.
- Path layers modify terrain at a low structural level and support width, falloff, noise on path width, height offset, flattening, procedural width modes, and spline export.
- Object Collection scatter brush is distinct from procedural biome/object layer scatter; it is for manual/hero finishing after procedural placement.

Implication for VeilBreakers:

- We should copy the separation of procedural scatter from hero/manual placement.
- The repo needs a clear distinction between exact point clouds and density/detail masks.
- Species scatter should support parent/sub-object relationships, not only independent placement.
- Roads/rivers/paths should be structural terrain layers with exported splines/masks, not post-hoc decals.
- Existing `environment_scatter._scatter_pass`, `vegetation_system.scatter_biome_vegetation`, and provider-neutral asset catalog callables need one canonical role each.

### Gaea

Primary sources:

- https://docs.gaea.app/reference/nodes/simulate/erosion
- https://docs.gaea.app/reference/nodes/simulate/erosion2.html
- https://docs.gaea.app/reference/nodes/simulate/rivers.html
- https://docs.gaea.app/reference/nodes/simulate/thermal2
- https://docs.gaea.app/using-gaea/build-and-export/build-options
- https://docs.gaea.app/using/advanced-topics/build-swarm/index.html
- https://docs.gaea.app/ui/interface/options/build.html

Relevant practices:

- Gaea Erosion emphasizes resolution parity: a 512 preview should preserve the essential erosion features of 4K/8K builds.
- Erosion exposes rock softness, strength, downcutting, inhibition, base level, feature scale, real scale, terrain scale, verticality, flow/debris volume, sediment removal, and selective processing.
- Erosion2 adds advanced hydraulic erosion with downcutting, sediment deposition, suspended load, bed load, coarse sediment, shape sharpness/detail scale, and orographic/rain-shadow controls.
- Rivers can create river networks with headwater masks and subtly reshape terrain to provide unbroken pathways.
- Thermal2 models talus/debris with duration, strength, anisotropy, talus angle, sediment removal, and feature scale.
- Build Options export specific ports such as Out, Flow, Wear, and Deposits; output can be single image or tiled, with tile size, overlap, blending, leading zeroes, and Y-flip options.
- Build Swarm is a separate command-line build engine; it saves machine-readable post-action reports.
- Gaea build preferences include cache purge for lower-memory machines, EXR heightfields, PNG16 masks/color maps, and timeout control for background build processes.

Implication for VeilBreakers:

- Our preview-vs-final behavior must be deterministic and feature-preserving; low-res previews should not lie.
- Erosion output channels should be exported and consumed, not discarded.
- Rivers need headwater/catchment control plus terrain reshaping.
- On this PC, high-res work should be tile/region/profile based with cache purging and small previews, not monolithic full-world renders.

### World Machine

Primary sources:

- https://help.world-machine.com/topic/device-erosion/
- https://help.world-machine.com/topic/device-thermalerosion/
- https://help.world-machine.com/topic/water/
- https://help.world-machine.com/topic/device-create-water/
- https://help.world-machine.com/topic/device-river/
- https://help.world-machine.com/topic/device-flowrestructure/
- https://help.world-machine.com/topic/device-splatmap/

Relevant practices:

- Erosion produces masks for flow, wear, and deposition. Those masks are intended for texturing.
- Erosion can take hardness masks and water channel inputs. Existing water acts as a sediment sink.
- Thermal Erosion models talus production, repose angle, fracture size, talus size, simulation length, and outputs talus mask/depth.
- World Machine treats water as a data type containing elevation, depth, and velocity, not merely a flat visual surface.
- Create Water automatically places rivers and lakes; rivers grow based on uphill contributing area and precipitation input.
- Flow Restructure makes terrain hydrologically valid by carving through ridges and sedimenting basins until every cell can drain.
- River Device supports manually defined hero rivers with networks/tributaries, GCS river character, bankfull depth, channel profile, flow speed, and valley parameters.
- Weightmap/Splatmap device packs input masks into normalized runtime texture weights that obey sum-to-one behavior for engines like Unity/Unreal.

Implication for VeilBreakers:

- The current `water_surface` ambiguity is a blocker. We need separate water mask, surface elevation, depth, flow direction, flow speed, and foam/wetness channels.
- Rivers need automatic hydrology plus optional hero-river control.
- Material weights must be normalized and proven, not loosely blended.
- Talus should be a generated terrain/material channel around cliffs, not only loose rock prop scatter.

### Unreal Engine PCG

Primary sources:

- https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-overview?application_version=5.6
- https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-pcg-biome-core-and-sample-plugins-in-unreal-engine?application_version=5.6
- https://dev.epicgames.com/documentation/en-us/unreal-engine/electric-dreams-procedural-content-generation-glossary?application_version=5.6

Relevant practices:

- PCG is graph-driven and designer-facing.
- Points contain transform, bounds, color, density, steepness, seed, and user-defined attributes.
- Point density is a probability-like control used by graph nodes.
- PCG separates static attributes such as `$Position` from runtime dynamic metadata.
- It has point, data, and element metadata domains.
- Graphs are debuggable by enabling node debug rendering, inspecting generated attributes, and toggling nodes.
- Biome plugins demonstrate Attribute Set Tables, feedback loops, recursive subgraphs, and runtime hierarchical generation.
- PCG supports world partition/data layer/HLOD integration.

Implication for VeilBreakers:

- Every scatterable output should be inspectable as a point table with attributes.
- Agents need callable access to points, masks, density, seed, and debug inspection instead of screenshot-only judgment.
- Biome scatter should be hierarchical and recursive where necessary: canopy -> understory -> ground cover -> debris.

### Unity Terrain

Primary sources:

- https://docs.unity3d.com/kr/2022.1/ScriptReference/TerrainData.html
- https://docs.unity3d.com/cn/2023.2/ScriptReference/TerrainData.SetDetailLayer.html
- https://docs.unity3d.com/cn/2023.1/ScriptReference/TerrainData.SetTreeInstances.html
- https://docs.unity3d.com/cn/2022.2/ScriptReference/DetailPrototype.html
- https://docs.unity3d.com/kr/6000.0/Manual/urp/shader-terrain-lit.html

Relevant practices:

- `TerrainData` stores heightmaps, detail mesh positions, tree instances, and terrain texture alpha maps.
- Detail layers are density maps; each pixel stores how many detail objects are placed in a terrain area.
- Trees are prototype-indexed instances and can be snapped to the terrain heightmap.
- `DetailPrototype` controls align-to-ground, density, dry/healthy color, min/max size, noise seed/spread, position jitter, GPU instancing, and mesh/billboard mode.
- URP Terrain Lit supports up to eight terrain layers and height-based blending via the blue channel of a mask map.

Implication for VeilBreakers:

- Export contracts must preserve heightmaps, splat/alpha maps, tree instance tables, detail density maps, and prototype catalogs separately.
- Foliage color variation cannot be arbitrary; it should be data-driven via health/dryness/moisture/biome attributes.
- Terrain material blending should support height-based mask input, not only slope.

### Blender Geometry Nodes / API

Primary sources:

- https://docs.blender.org/manual/en/3.6/modeling/geometry_nodes/point/distribute_points_on_faces.html
- https://docs.blender.org/manual/en/3.6/modeling/geometry_nodes/instances/instance_on_points.html
- https://docs.blender.org/manual/en/latest/modeling/geometry_nodes/attribute/store_named_attribute.html
- https://docs.blender.org/manual/en/latest/modeling/geometry_nodes/geometry/read/named_attribute.html
- https://docs.blender.org/manual/en/5.0/modeling/geometry_nodes/attributes_reference.html
- https://docs.blender.org/api/current/bpy.types.AttributeGroupMesh.html

Relevant practices:

- Distribute Points on Faces transfers point/corner/polygon attributes from input geometry to generated points.
- It can produce stable `id` attributes, supports Poisson disk minimum distance, density per square meter, selection masks, normals, and rotations.
- Instance on Points adds geometry references to points and can pick instances from a collection using an instance index.
- Point attributes are available on the instance domain.
- Named attributes can be stored on specific geometry domains and then read elsewhere.
- Blender mesh attributes are scriptable through the API (`attributes.new(name, type, domain)`).

Implication for VeilBreakers:

- Blender should be used as the renderer/instancer/validator for point and attribute data, not as the place where one-off terrain logic is re-invented.
- Current MCP/bridge tools expose low-level Geometry Nodes creation, but not enough recipe-level terrain scatter operations.
- Needed recipe-level Blender callables include:
  - create mesh from heightfield and channel pack
  - write/read named mesh attributes
  - apply standard scatter recipe to point cloud
  - apply standard material recipe from layer stack
  - validate Geometry Nodes modifier inputs/tree
  - capture QA renders with channel/debug overlays

### Maya / Bifrost / MASH

Primary sources:

- https://help.autodesk.com/view/MAYAUL/2026/ENU/?guid=Bifrost_Common_reference_Modeling_Points_Modeling_Points_scatter_points_html
- https://help.autodesk.com/cloudhelp/2025/ENU/Maya-Tech-Docs/MASH/MASH.html
- https://help.autodesk.com/cloudhelp/2023/ENU/Maya-MotionGraphics/files/GUID-B718F1FE-8688-4A57-95DD-5B22C4D40F1A.htm
- https://help.autodesk.com/cloudhelp/2022/ENU/Maya-MotionGraphics/files/GUID-033261E4-44EB-4721-9A47-6CCD25F334DE.htm
- https://help.autodesk.com/view/MAYAUL/2025/ENU/?guid=Bifrost_MayaPlugin_bifrost_usd_in_maya_instancing_html

Relevant practices:

- Bifrost `scatter_points` distributes points on geometry and supports `density_weights`.
- Scatter can cull overlapping points by radius.
- Scatter can transfer properties from source geometry to points.
- Scatter can create orientations from geometry normals/tangents.
- Maya instancer uses point arrays for position, id, visibility, scale, shear, rotation/aim metadata.
- MASH can distribute on meshes in scatter/vertex/face/voxel/edge modes and exposes viewport display percentage for performance.
- Bifrost-USD can feed scattered points into USD point instancers.

Implication for VeilBreakers:

- Our scatter system must transfer terrain properties to points and maintain instance metadata, not just object transforms.
- Overlap culling/min-distance must be a first-class validated option.
- For low-spec hardware, display percentage/proxy preview should be built into the agent workflow.

### SpeedTree

Primary sources:

- https://docs.speedtree.com/doku.php?id=generators
- https://docs.speedtree.com/doku.php?id=zones
- https://docs.speedtree.com/doku.php?id=zone_generator
- https://docs.speedtree.com/doku.php?id=forces
- https://docs.speedtree.com/doku.php?id=lod
- https://docs.speedtree.com/doku.php?id=compiler_billboards
- https://docs.speedtree.com/doku.php?id=wind_overview

Relevant practices:

- Trees/plants are generator hierarchies, not single static meshes.
- Zones can grow geometry off disc or mesh surfaces.
- Mesh zones can use masks based on grayscale texture, slope, elevation, or UV range.
- Area influence prevents clustering on small mesh faces and gives even growth over varied triangle sizes.
- Forces can push, pull, twist, obstruct, or localize growth and can be enabled per generator/node.
- LOD is tuned per tree; branches/fronds/leaves/zones can all have LOD.
- Billboards are part of large-forest performance and should smoothly match lighting/wind.
- Wind is vertex-shader driven and can vary by instance, with wind LOD fading from full effects to global sway or billboard behavior.

Implication for VeilBreakers:

- Foliage assets need generator-style metadata: biome role, parent/subobject behavior, wind profile, LOD profile, billboard/impostor data, seasonal/color variation.
- Natural-looking foliage requires growth logic and ecological grouping, not only model scatter.
- Current external-model GLBs can be useful as prototypes, but they need catalog metadata and scatter/growth recipes to stop looking copy-pasted.

### VUE / PlantFactory

Primary source:

- https://www.bentley.com/software/e-on-software-free-downloads/

Relevant facts:

- Bentley made VUE, PlantFactory, and PlantCatalog free perpetual downloads after ending sales.
- They are not currently proven open source from the official Bentley page.
- VUE 2023 and PlantFactory 2023 are the last official stable e-on releases.
- VUE/PlantFactory 2024 are offered as unfinished beta/as-is builds.
- Development is discontinued; support is limited to critical security patches at Bentley's discretion.
- PlantCatalog content remains copyrighted by Bentley.

Implication for VeilBreakers:

- Treat VUE/PlantFactory as reference/free tooling, not as a future-safe open-source dependency unless Bentley actually publishes source code and licensing.
- PlantFactory remains a useful reference for plant proceduralism, but it should not replace our catalog/metadata/LOD/wind contracts.

### Open-Source References

Primary sources:

- https://github.com/princeton-vl/infinigen
- https://arxiv.org/abs/2306.09310
- https://github.com/Mindwerks/worldengine
- https://worldengine.readthedocs.io/_/downloads/en/manual/pdf/
- https://github.com/Auburn/FastNoiseLite/wiki/Documentation
- https://github.com/weigert/SimpleHydrology
- https://www.redblobgames.com/maps/mapgen2/

Relevant practices:

- Infinigen generates natural worlds procedurally with configurable generators, Blender-based procedural assets/materials, export paths, camera controls, and ground-truth outputs.
- Infinigen's public materials emphasize procedural assets from mathematical rules, not AI/random asset dumps.
- WorldEngine uses plate simulation, erosion, rain shadows, humidity, permeability, and Holdridge life-zone biomes.
- FastNoiseLite is a seeded coherent-noise primitive; useful but not sufficient by itself for natural terrain.
- SimpleHydrology is useful as a hydrology/erosion reference, especially for streams/pools/flooding/discharge-style outputs.
- Red Blob Mapgen2 is useful for explicit map constraints, rivers, water, and biome design, but it is not a 3D AAA terrain renderer.

Implication for VeilBreakers:

- Our world model needs climate/biome/hydrology layers before asset scatter.
- Noise is only a base signal. It is not terrain generation by itself.
- Research-grade procedural systems expose configuration and intermediate data for inspection; our agents need the same.

## 3. Local Callable/Wiring Evidence

Current read-only audits show:

- `scripts/callable_census_gate.py --report`
  - Total callables: 1546
  - Graded: 1416
  - Uncovered: 130
  - Coverage: 91.6%
  - Baseline uncovered: 161
- `output/spreadsheet/CALLABLE_WIRING_SUMMARY_2026_04_19.md`
  - Live handler callables scanned: 1820
  - Missing from grade sheet: 477
  - Without R9 grade: 859
  - `test_only_or_unwired`: 229
  - `orphan_candidate`: 92
- `docs/aaa-audit/R13_FULL_MANUAL_CALLABLE_REVIEW_SUMMARY.md`
  - Rows reviewed: 2711
  - Strict output-gated B rows: 23
  - Below-B remediation required: 2675
  - No output proof: 2422
  - Actions include 748 `ADD_DIRECT_TESTS`, 516 `WIRE_OR_DEPRECATE`, 296 `ADD_LIVE_VISUAL_GOLDEN`, and 259 `RELOCATE_ASSET_LIBRARY_OR_PROVE_SCATTER_RENDER_PATH`.
- `output/verification/CALLABLE_VERIFICATION_SUMMARY.md`
  - Total callables: 1504
  - Blockers: 81
  - High risk: 16
  - Tool/Blender callables needing blocker/high evidence: 92

Important local failure patterns already documented:

- `scripts/build_scene_v3.py` bypasses the canonical pipeline and defines local terrain, water, material, scatter, and grass generation.
- Similar one-shot bypass risk exists in `scripts/build_scene_v2.py`, `scripts/build_aaa_node_v1.py`, and `scripts/build_aaa_node_v2.py`.
- The richer `environment_scatter._scatter_pass` is defined but not called by the production `handle_scatter_vegetation` path.
- There are two vegetation scatter pipelines:
  - `environment_scatter.handle_scatter_vegetation`
  - `vegetation_system.scatter_biome_vegetation`
- Water extensions such as richer foam/mist logic exist but are not production callers in the documented audit.
- Road systems have duplicate implementations; the richer `road_network._astar_24dir` is not used by the environment-scoped road handler.
- `terrain_materials_ext.compute_height_blended_weights` exists but is not wired into the registered material pass.
- Blender bridge currently exposes useful low-level capabilities but not recipe-level terrain/agent operations.

## 4. Domain Standards Extracted From Research

### Terrain Shape

Minimum standard:

- Terrain shape must be a multi-pass layered field with base landform, macro erosion, local erosion, thermal/talus, stratigraphy, cliff/cave deformation, hydrology reshape, and final seam validation.
- Every structural pass must declare consumed and produced channels.
- Recompute derived masks after final height changes.
- Low-res preview and high-res final must preserve major features.

Relevant local callable families:

- `_terrain_noise.py`
- `_terrain_world.py`
- `terrain_pipeline.py`
- `terrain_twelve_step.py`
- `terrain_pass_dag.py`
- `terrain_delta_integrator.py`
- `terrain_cliffs.py`
- `terrain_caves.py`
- `terrain_glacial.py`
- `terrain_karst.py`
- `terrain_stratigraphy.py`
- `terrain_geology_validator.py`

### Water / Rivers / Lakes / Waterfalls

Minimum standard:

- Water cannot be a flat plane plus a shader.
- Required data channels:
  - water mask
  - water surface elevation
  - water depth
  - velocity/flow speed
  - flow direction
  - flow accumulation/discharge
  - wet rock
  - foam
  - mist/spray
  - caustics candidate
- Lakes and rivers should be generated from hydrology, precipitation/catchment, and optionally artist/headwater/hero path constraints.
- Waterfalls should consume flow speed/drop/lip geometry and emit foam/mist/particle seed zones.

Relevant local callable families:

- `_water_network.py`
- `_water_network_ext.py`
- `terrain_waterfalls.py`
- `terrain_waterfalls_volumetric.py`
- `terrain_water_variants.py`
- `coastline.py`

Known gap:

- `water_surface` is ambiguous and should not be treated as both mask and elevation.

### Foliage / Scatter / Ecology

Minimum standard:

- Scatter must be point/attribute based with deterministic seeds.
- Each point should carry enough metadata to validate and render:
  - position
  - normal/orient
  - scale
  - species/prototype id
  - biome
  - moisture
  - slope
  - altitude
  - density/source mask
  - LOD bucket/screen-size metadata
  - wind profile
  - color/health/dryness variation
- Scatter must separate:
  - exact instance point clouds
  - density/detail masks
  - hero/manual object placements
- Species rules need ecological grouping: parent/sub-object relationships, understory, ground cover, wet-bank species, cliff species, deadfall, debris, negative space, gameplay clearings.

Relevant local callable families:

- `environment_scatter.py`
- `_scatter_engine.py`
- `vegetation_system.py`
- `vegetation_lsystem.py`
- `terrain_foliage_catalog.py`
- `terrain_vegetation_depth.py`
- `terrain_ecotone_graph.py`
- `terrain_assets.py`
- external model validation/provider integration module to be selected

Known gap:

- The richer `_scatter_pass` appears unreachable from production, while simpler scatter remains exposed.

### Materials / Textures

Minimum standard:

- Materials must consume slope, height, curvature, flow, wear, sediment/debris, wetness, biome, moss, snow, cliff, cave, shore, and path masks.
- Weights must be normalized for export and stable under tiling.
- Height-based layer blending is required for believable terrain transitions.
- Macro color variation and stochastic tiling should break repetition.
- Foliage and terrain color must share environmental parameters so greens/browns do not look disconnected.

Relevant local callable families:

- `terrain_materials.py`
- `terrain_materials_v2.py`
- `terrain_materials_ext.py`
- `terrain_stochastic_shader.py`
- `terrain_macro_color.py`
- `procedural_materials.py`
- `vertex_paint_live.py`

Known gap:

- Height-blended weights are implemented in extension code but not proven wired into the canonical material pass.

### Blender / AI Agent Tooling

Minimum standard:

- Agents should call canonical recipe-level operations rather than hand-building terrain in one-off scripts.
- Blender calls should validate the scene and the data contract:
  - named attributes exist
  - point clouds match density masks
  - material layers exist and are assigned
  - Geometry Nodes modifiers are present and valid
  - render QA captures are tied to specific channel/debug overlays

Existing useful local tools:

- `bmesh_op`
- modifier add/apply/remove/list
- UV projection
- render engine/still
- collection create/link
- parenting
- empty create
- Geometry Nodes create/add/link/assign/dump
- high-level visual QA, terrain LOD, procedural material, terrain biome setup, scene/viewport read, addon health, safety guards

Missing recipe-level tool shapes:

- `mesh_from_heightfield`
- `mesh_attribute_write`
- `mesh_attribute_read`
- `terrain_channel_pack_to_mesh_attributes`
- `scatter_point_cloud_create`
- `scatter_recipe_apply`
- `scatter_point_table_validate`
- `material_layer_stack_apply`
- `water_surface_from_depth_velocity`
- `waterfall_vfx_from_lip_flow_zones`
- `render_qa_capture_channels`
- `scene_analyze_for_agent`
- `mutation_preflight`
- `scene_snapshot`
- `scene_restore`

## 5. Guardrail Standards For Future Agents

These are research-derived standards, not implementation steps.

- A terrain-producing script is suspect if it defines its own heightmap, scatter, material, water, road, or waterfall generation instead of calling canonical handlers/passes.
- A callable is not AAA-ready because it exists or has a unit test. It needs production wiring and direct output proof.
- A Blender render is not proof unless the render is tied back to channel data and callable provenance.
- Scatter without point attributes is not acceptable.
- Water without depth/velocity/flow direction is not acceptable.
- Terrain material without normalized layer weights and height/flow/wear/sediment masks is not acceptable.
- Foliage asset scatter without LOD/wind/color/species metadata is not acceptable.
- Any user request for a terrain edit should resolve to a canonical pass/handler, not new one-shot script logic.
- Duplicate callables must be assigned one of three statuses:
  - canonical production path
  - helper behind canonical path
  - deprecated/removed/test-only
- Agents must be able to inspect available callables and know which one is canonical before editing.

## 6. PC-Spec / Low-Memory Constraints

Research implications for a weaker PC:

- Prefer previews at reduced resolution that preserve feature structure.
- Use tiles/regions/profiles instead of full-world monolithic builds.
- Use cache purge/limited cache modes for high-res builds.
- Use viewport/display percentage or proxy objects for dense scatter.
- Use point clouds and instancing until final export/render.
- Use billboards/impostors for far foliage.
- Avoid generating all real geometry before validation.
- Run localized golden fixtures before full map generation.

## 7. Research Conclusion

The next correct move is not to add more random foliage assets or tune colors in the current one-shot scene. The official-tool evidence from Houdini, World Creator, Gaea, World Machine, Unreal PCG, Unity Terrain, Blender Geometry Nodes, Maya/Bifrost/MASH, and SpeedTree points to the same standard:

VeilBreakers needs a strict layered terrain data model, canonical callable routing, point/attribute scatter, hydrology-backed water, erosion-backed materials, and live output proof.

The repo already has many promising pieces, but the audits show that they are not consistently wired, proven, or protected against bypass scripts. Any future implementation plan should start from those facts rather than from another scene-builder script.
