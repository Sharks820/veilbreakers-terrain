# AAA Environment And Terrain Pipeline Memo

Date: 2026-04-19

This memo prioritizes studio talks, engine docs, and vendor guidance. The pipeline order below is a synthesis from those sources; when a recommendation combines multiple references, treat it as an informed production inference rather than a direct quote.

## Bottom Line

The strongest recurring pattern across Ubisoft, Treyarch, Frostbite, Sucker Punch, Epic, Unity, and Blender guidance is:

1. Lock macro terrain, drainage, and biome logic first.
2. Generate or sculpt cliffs, mountains, roads, and water as integrated terrain systems, not isolated hero assets.
3. Solve terrain-material blending and mesh-to-ground blending before heavy prop dressing.
4. Use non-destructive layers and DCC round-trips for hero corrections, overhangs, road cuts, waterfalls, and silhouette fixes.
5. Run visual QA in distance bands with debug views for material complexity, shadow stability, overdraw, and seam detection before final polish.

## Recommended Pipeline Order

1. **Macro landform + hydrology**
   Build the mountain ranges, basins, river paths, and coastline logic before texturing or prop passes. Ubisoft repeatedly describes world generation as sequential: biomes, terrain texturing, freshwater networks, cliffs, and more. Unity's hydraulic erosion guidance likewise treats water flow and sediment transport as terrain-defining, not polish work.

2. **Non-destructive terrain layers**
   Keep hand sculpt, erosion, roads, cuts, and gameplay flattening in separate edit layers/overlays. Frostbite explicitly describes non-destructive GPU layer compositing; Unreal Landscape sculpt mode also frames splines and procedural brushes as part of hybrid non-destructive terrain editing.

3. **Mountains and cliffs as a hybrid of heightfield + meshes**
   Use the terrain system for broad massing and traversal continuity, then add mesh cliffs/overhangs for shapes a heightfield cannot express. Far Cry 5 and Call of Duty both stress terrain systems that support generated cliffs and seamless blending of artistic elements through virtual texturing.

4. **Terrain material stack before scatter**
   Establish slope/height rules, macro color, and blend masks before vegetation and prop placement. REDengine, Call of Duty, Unreal RVT, and Unity Terrain Lit all point toward layered terrain shading with height/slope-aware blending and seamless terrain/mesh integration.

5. **Roads and paths as spline-driven deformation + material blend**
   Roads should carve terrain and carry their own material logic, not just sit on top. Unreal Landscape Splines are explicitly for carving landscape and deforming meshes into roads; RVT guidance shows splines and decals being composited into the terrain surface so the primitive itself disappears.

6. **Water bodies and waterfalls after terrain cuts are stable**
   Rivers, lakes, shorelines, and waterfalls should inherit from the locked terrain profile and use a unified shading/meshing approach. Epic's Water System is spline-based and terrain-aware; Blizzard and Ubisoft both describe water as a multi-system problem spanning lighting, shaders, wetness, particles, and level art.

7. **Environmental props and vegetation from rule sets first, hand pass second**
   Start with procedural/object-rule scattering for density, then hand-tune hero zones, landmarks, and traversal corridors. Ghost of Tsushima, REDengine, Frostbite, and Ghost Recon all emphasize rule-driven placement at scale, with artists reinvesting time into focal areas instead of manual blanket placement.

8. **Lighting and atmosphere after the material/readability pass**
   Do not tune final lighting against placeholder terrain materials. Lumen guidance, Far Cry 6 weather work, and Unreal environment-light docs all point to lighting, fog, clouds, wetness, and translucency as systems that must be tuned against near-final terrain/water materials.

9. **Blender round-trip for hero corrections**
   Use Blender for non-destructive hero edits: cliff cap kits, overhang inserts, road retaining walls, waterfall lips, rock breakup, and mesh cleanup. Keep these as linked or instanced assets where possible, then export through the engine's supported import path.

10. **Visual QA and budget gates before final polish**
    Run distance-band reviews, seam checks, water-edge checks, shadow invalidation checks, and material/overdraw diagnostics before adding more detail. The common AAA failure mode is over-detailing content that still has macro silhouette, blending, or budget problems.

## Topic Guidance

### Texturing

- Prefer terrain materials driven by height, slope, and masks, with macro-to-micro breakup.
- Use virtual texturing or equivalent blend caches where possible so cliff meshes, decals, and roads inherit terrain color and reduce seams.
- For Unity terrain, enable height-based blend and per-pixel normal where the project budget allows; for erosion-driven terrains, keep heightmap resolution high enough to preserve fluvial detail.

### Lighting

- Treat lighting as a readability system first: macro shape, traversal cues, wetness response, and silhouette depth.
- Validate foliage, translucency, fog, and single-layer water under the final lighting model, not in a neutral graybox.
- Use debug/visualization modes to inspect GI, normals, Nanite state, shadow invalidation, and shader/material complexity.

### Environmental Props

- Separate systemic props from authored hero props.
- Let terrain layers drive first-pass rock/vegetation distribution, then spend manual time on landmarks, vista framing, road shoulders, stream edges, and encounter spaces.
- Maintain species/prop variants and scale jitter to avoid visible repetition in midground bands.

### Roads / Paths

- Drive roads from splines or equivalent parametric curves so profile, width, banking, cut/fill, and shoulder blending remain editable.
- Blend the road material into the terrain underlay; avoid a visibly separate ribbon mesh unless the art style wants that.
- Review roads in top-down, player-height, and long-distance camera passes; spline deformation that looks acceptable close up can break silhouette or LOD behavior at range.

### Water / Waterfalls

- Build water from layered components: base surface, shoreline blend, foam, splash/mist, wetness darkening, and lighting/fog integration.
- Treat waterfalls as mesh + particle + mist + wet decal/material response, not only a shader plane. This is an inference from the Diablo IV, Far Cry 5, Far Cry 6, and Unreal water guidance, which consistently describe water as a composed multi-system effect.
- Review river-to-lake/ocean transitions, far-distance meshes, and underwater/post-process continuity early.

### Cliffs / Mountains

- Use terrain for the navigable base form and mesh inserts for undercuts, vertical faces, and hero silhouettes.
- Align cliff kits to terrain through shared masks, RVT/virtual texture blending, and matched macro color/roughness, not just mesh placement.
- Validate mountains in horizon view first. If the skyline reads poorly, close-up detail will not save the shot.

### Blender Utilization

- Use Geometry Nodes for repeatable, non-destructive generators and terrain-adjacent kitbashing.
- Use Asset Browser linking for reusable kits so objects can be made local while meshes/materials stay linked and update from the library.
- Be careful with FBX when relying on true shared instances: Blender documents that object instancing does not round-trip as shared data in standard FBX export.
- Prefer glTF/GLB when the engine path supports it and you want compact delivery plus custom properties in `extras`; otherwise use the engine's main static-mesh pipeline.

## Quality Bar And Visual QA

Use these gates before sign-off:

- **Horizon band:** mountain silhouettes, skyline rhythm, atmospheric depth.
- **Midground band:** terrain-material breakup, prop repetition, road width consistency, cliff/ground seam visibility.
- **Near band:** texel density, normal/roughness response, puddle logic, shoreline/waterfall edge quality, collision plausibility.
- **Debug band:** Nanite visualization, Virtual Shadow Map visualization, Lumen overview, shader/material complexity, water debug/scalability views.

Ship blockers:

- Road ribbons floating or clipping at switchbacks.
- Cliff meshes reading as pasted-on because albedo/roughness/macro color do not match terrain.
- Waterfalls lacking landing-zone splash, mist, or wetted receiving surfaces.
- Mountain skylines that look noisy at close range but bland at gameplay distance.
- Prop scatter that fills every empty space instead of preserving negative space and gameplay read.

## Source Notes

| Date | Source | Why it matters | Link |
| --- | --- | --- | --- |
| 2014 | CD Projekt RED, **Landscape Creation and Rendering in REDengine 3** | Automates terrain and vegetation editing; advocates procedural vegetation and moving beyond simple linear terrain blends. | https://www.gdcvault.com/play/1020394/Landscape-Creation-and-Rendering-in |
| 2017 | Ubisoft, **Ghost Recon Wildlands: Terrain Tools and Technology** | Shows tool-driven world building, procedural roads/paths, river carving, water mesh/flow, density balancing, and a small team operating a large automated pipeline. | https://www.gdcvault.com/play/1024029/-ghost-recon-wildlands-terrain |
| 2018 | Ubisoft, **Procedural World Generation of Far Cry 5** | Explicit sequential open-world terrain workflow: generate biomes, texture terrain, set up freshwater networks, generate cliff rocks, then iterate. | https://www.gdcvault.com/play/1025557/Procedural-World-Gen |
| 2018 | Ubisoft + AMD, **Water Rendering in Far Cry 5** | Water system covers waterfalls and lakes, compositing multiple water systems with scalable performance and a single-pass lighting/composite approach. | https://www.gdcvault.com/play/1025033/Advanced-Graphics-Techniques-Tutorial-Water |
| 2021 | Treyarch / Activision Research, **Boots on the Ground: The Terrain of Call of Duty** | GPU real-time terrain editing, procedural biome tools, and virtual texturing for seamless blending under strict 60 fps budgets. | https://research.activision.com/publications/2021/09/boots-on-the-ground--the-terrain-of-call-of-duty |
| 2021 | Sucker Punch, **Samurai Landscapes: Building and Rendering Tsushima Island on PS4** | Texture and placement rules for generated data; instance-heavy natural environment population at large scale. | https://sandbox.gdcvault.com/play/1027352/Samurai-Landscapes-Building-and-Rendering |
| 2022 | Ubisoft Toronto / Montreal, **Simulating Tropical Weather in Far Cry 6** | Wetness pipeline, terrain puddles, fog, atmospheric scattering, wind, and weather-state transitions. | https://sandbox.gdcvault.com/play/1027725/Simulating-Tropical-Weather-in-Far |
| 2023 | Electronic Arts / Frostbite, **From Battlegrounds to Fairways: Terrain Procedural Tools in Frostbite** | Interdependent terrain data layers, seamless terrain/object integration, object scattering, and non-destructive GPU compositing. | https://www.gdcvault.com/play/1029086/From-Battlegrounds-to-Fairways-Terrain |
| 2024 | Blizzard, **H2O in H3LL: The Various Forms of Water in Diablo IV** | Shorelines, puddles, rivers, snow/ice/wetness, and the requirement that water presentation span lighting, textures, material parameters, and level art. | https://sandbox.gdcvault.com/play/1034779/Technical-Artist-Summit-H2O-in |
| UE 5.6/5.7 docs | Epic, **Landscape Splines**, **Runtime Virtual Texturing Quick Start**, **Water System**, **Lumen**, **Nanite**, **Virtual Shadow Maps**, **FBX Static Mesh Pipeline** | Practical engine-side guidance for road deformation, terrain/mesh blending, water bodies, dynamic GI, debug views, shadow inspection, and DCC import expectations. | https://dev.epicgames.com/documentation/en-us/unreal-engine/landscape-splines-in-unreal-engine<br>https://dev.epicgames.com/documentation/en-us/unreal-engine/runtimevirtual-texturing-quick-start-in-unreal-engine?application_version=5.6<br>https://dev.epicgames.com/documentation/en-us/unreal-engine/water-system-in-unreal-engine<br>https://dev.epicgames.com/documentation/en-us/unreal-engine/lumen-global-illumination-and-reflections-in-unreal-engine<br>https://dev.epicgames.com/documentation/unreal-engine/nanite-virtualized-geometry-in-unreal-engine<br>https://dev.epicgames.com/documentation/ru-ru/unreal-engine/virtual-shadow-maps-in-unreal-engine<br>https://dev.epicgames.com/documentation/en-us/unreal-engine/fbx-static-mesh-pipeline-in-unreal-engine |
| 2025-12-09 docs build | Unity, **Terrain Tools 5.0.6: Hydraulic Erosion** | Water-flow-driven erosion and the importance of terrain resolution for fluvial detail. | https://docs.unity3d.com/Packages/com.unity.terrain-tools@5.0/manual/erosion-hydraulic.html |
| 2025-12-15 docs build | Unity, **Unity 6 URP Terrain Lit shader** | Height-based blend and per-pixel normals for terrain layering and preserved detail. | https://docs.unity3d.com/6000.0/Documentation/Manual/urp/shader-terrain-lit.html |
| 2026-04-19 manual update | Blender, **Asset Browser**, **Geometry Nodes**, **FBX**, **glTF 2.0** | Linked asset workflows, non-destructive geometry authoring, FBX instancing caveats, and glTF delivery/custom-property support. | https://docs.blender.org/manual/en/latest/editors/asset_browser.html<br>https://docs.blender.org/manual/en/latest/modeling/geometry_nodes/introduction.html<br>https://docs.blender.org/manual/en/latest/addons/import_export/scene_fbx.html<br>https://docs.blender.org/manual/en/latest/addons/import_export/scene_gltf2.html |
