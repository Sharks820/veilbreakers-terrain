# Terrain Callable Usage Guardrail

This guide is generated from the industry best-practice callable matrix.
Use it before editing or invoking terrain generation code.

## Required Rule

Every callable used for terrain generation must satisfy its matrix row: best-practice contract, setup, upgrade actions, validation gates, anti-pattern blockers, and output artifacts.

## Domain Routing

- Use `export_runtime` callables for Unity/engine exports, water shader manifests, terrain layers, detail layers, particle emitters, scale factors, and runtime artifact schemas. Matrix rows: 112. P0 blockers: 0.
- Use `external_ai_assets` callables for provider-neutral generated model assets, Rodin-style async asset packages, validation, ingestion, scale, UV, PBR, collision, LOD, and license checks. Matrix rows: 46. P0 blockers: 0.
- Use `foliage_assets` callables for species catalogs, vegetation prototypes, LOD paths, impostors, billboards, wind profiles, and asset fallback metadata. Matrix rows: 19. P0 blockers: 0.
- Use `generic` callables only for small shared helpers; connect them to a domain contract before they become production terrain behavior. Matrix rows: 379. P0 blockers: 0.
- Use `heightfield_geomorph` callables for terrain shape, heightfields, cliffs, caves, erosion, talus, strata, geology, weathering, slope, curvature, and landform masks. Matrix rows: 201. P0 blockers: 0.
- Use `hydrology` callables for water systems: rivers, lakes, waterfalls, wetlands, flow direction, velocity, depth, foam, mist, wet rock, caustics, and seam continuity. Matrix rows: 164. P0 blockers: 0.
- Use `mesh_blender` callables for Blender/DCC bridge work: mesh creation, named attributes, GLB import safety, viewport/scene readback, Geometry Nodes-style recipes, and screenshot proof. Matrix rows: 171. P0 blockers: 0.
- Use `pathing_roads` callables for roads, paths, navmesh, A*, bridges, fords, splines, cost fields, and traversal constraints. Matrix rows: 62. P0 blockers: 0.
- Use `scatter_ecology` callables for point distribution, vegetation placement, biome/ecotone logic, wildlife zones, density masks, and exclusion rules. Matrix rows: 164. P0 blockers: 0.
- Use `terrain_pipeline` callables for canonical pass orchestration, dependency contracts, handler registration, checkpoints, and generated-map provenance. Matrix rows: 145. P0 blockers: 0.
- Use `terrain_texturing` callables for terrain texture/PBR work: material weights, splatmaps, base color, normal, roughness, height, AO, Quixel/Substance-style layers, stochastic shaders, and texel density. Matrix rows: 126. P0 blockers: 0.
- Use `validation_qa` callables for quality gates, visual QA, callable audits, deterministic checks, performance budgets, golden snapshots, scene inspection, and issue reporting. Matrix rows: 145. P0 blockers: 0.

## Hard Blocks

- Do not add one-shot terrain builders that bypass canonical passes.
- Do not use flat color or slope-only texturing for production terrain.
- Do not scatter foliage or props without a typed point table and asset manifest.
- Do not create water bodies without surface elevation, depth, flow, and export metadata.
- Do not use raw Blender Python as the normal production path when a typed terrain recipe should exist.
- Do not let external AI asset providers place assets directly into terrain without validation.

## Duplicate callable names requiring review

No duplicate callable names detected.

## Matrix

Full callable-by-callable rules live in `output/spreadsheet/INDUSTRY_BEST_PRACTICE_CALLABLE_MATRIX_2026_05_02.csv`.
