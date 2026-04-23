# Function-by-Function Upgrade Path to A

- Grade source: `docs\aaa-audit\GRADES_VERIFIED.csv`
- Total callables planned: **1740**
- P0 (missing/C-range and below): **625**
- P1 (B-range): **292**
- P2 (other/non-standard): **0**
- P3 (already A-range): **823**

## Domain distribution

- generic: 754
- ecology: 183
- hydrology: 168
- pipeline: 143
- mesh: 99
- materials: 96
- pathing: 83
- noise: 81
- geomorph: 72
- validation: 61

## Domain research references

- noise: https://docs.world-creator.com/; https://www.ea.com/frostbite/news/terrain-in-battlefield-3-a-modern-complete-and-scalable-system
- geomorph: https://www.sidefx.com/docs/houdini/nodes/sop/heightfield_erode; https://docs.quadspinner.com/Reference/Erosion/Erosion.html; https://help.world-machine.com/topic/device-thermalerosion/
- hydrology: https://www.sidefx.com/docs/houdini/nodes/sop/heightfield_erode; https://help.world-machine.com/topic/device-flowrestructure/; https://docs.quadspinner.com/Reference/Erosion/Erosion.html
- pathing: https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-framework-in-unreal-engine; https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-overview
- ecology: https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-pcg-biome-core-and-sample-plugins-in-unreal-engine?application_version=5.6; https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-framework-in-unreal-engine; https://www.world-machine.com/features.php
- materials: https://www.ubisoft.com/en-us/studio/laforge/news/1i3YOvQX2iArLlScBPqBZs/generative-base-material-an-open-source-prototype-for-pbr-material-estimation-debuting-at-siggraph-asia-2025; https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-framework-in-unreal-engine
- mesh: https://dev.epicgames.com/documentation/en-us/unreal-engine/geometry-scripting-through-blueprints-in-unreal-engine; https://www.ea.com/frostbite/news/adaptive-hardware-accelerated-terrain-tessellation
- pipeline: https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-framework-in-unreal-engine; https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-overview
- validation: https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-framework-in-unreal-engine; https://help.world-machine.com/topic/build-4046-hurricane-ridge-final/
- generic: https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-framework-in-unreal-engine; https://docs.world-creator.com/

## Execution order

1) Complete all P0 callables first with correctness and determinism gates.
2) Raise P1 callables with domain-specific best-practice upgrades.
3) Lock P3 callables using regression, performance, and golden CI protections.
4) Re-grade and re-run this planner until P0=0 and P1=0.
