# AAA Terrain Research References (Verifiable Sources) — 2026-04-22

This reference list is used by `scripts/build_function_upgrade_path.py` to ground upgrade guidance in publicly verifiable sources from major engines/tools/studio R&D.

## Core engine/tool references

- Unreal Engine PCG Framework (official):
  - https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-framework-in-unreal-engine
  - https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-overview
  - https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-pcg-biome-core-and-sample-plugins-in-unreal-engine?application_version=5.6
  - https://dev.epicgames.com/documentation/en-us/unreal-engine/geometry-scripting-through-blueprints-in-unreal-engine
- Houdini HeightField Erode (official):
  - https://www.sidefx.com/docs/houdini/nodes/sop/heightfield_erode
- Gaea Erosion (official):
  - https://docs.quadspinner.com/Reference/Erosion/Erosion.html
- World Machine terrain/erosion docs (official help center):
  - https://help.world-machine.com/topic/device-thermalerosion/
  - https://help.world-machine.com/topic/device-flowrestructure/
  - https://help.world-machine.com/topic/build-4046-hurricane-ridge-final/
  - https://www.world-machine.com/features.php
- World Creator docs (official):
  - https://docs.world-creator.com/

## AAA studio / engine technical references

- Frostbite terrain system talks/posts:
  - https://www.ea.com/frostbite/news/terrain-in-battlefield-3-a-modern-complete-and-scalable-system
  - https://www.ea.com/frostbite/news/adaptive-hardware-accelerated-terrain-tessellation
- Ubisoft La Forge material R&D (SIGGRAPH Asia 2025):
  - https://www.ubisoft.com/en-us/studio/laforge/news/1i3YOvQX2iArLlScBPqBZs/generative-base-material-an-open-source-prototype-for-pbr-material-estimation-debuting-at-siggraph-asia-2025

## How this is applied

The function upgrade planner maps each callable into a domain track (noise/hydrology/ecology/etc.) and attaches the relevant source links in `research_refs` for per-function verification and engineering traceability.
