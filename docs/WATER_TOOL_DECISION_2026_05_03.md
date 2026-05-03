# Water Tool Decision - 2026-05-03

## Decision

Use Blender water add-ons as look-dev/reference only unless their outputs are converted into VeilBreakers water channels and manifests.

Current best calls:

- **Alt Tab Ocean & Water**: use as free Blender water material/ocean/pond reference.
- **RealTimeFlow**: use as low-cost interaction/ripple/flow-mask reference.
- **Dynamic Flow**: optional paid terrain-aware reference, but Blender 5.0 requirement is a pipeline risk.

Do not replace VeilBreakers water contracts with add-on scene state.

## Alt Tab Ocean & Water

Source: Superhive.

Observed facts:

- free/full addon listed at $0
- Blender 4.0-4.5
- GPL license
- 800+ sales, 53k+ downloads, 18 ratings
- marketed for ocean/water material, waves, pond water, foam, animated water

Use for:

- Blender render look-dev
- water material node reference
- ocean/pond presets
- foam/color/wave parameter benchmarks

Risks:

- GPL code cannot be copied into proprietary repo/runtime without review.
- Blender material quality does not prove Unity runtime correctness.
- Must still export/audit water data channels.

## RealTimeFlow

Source: Superhive.

Observed facts:

- $5
- Blender 4.1
- MIT license per listing
- uses dynamic paint and effectors for real-time water behavior

Use for:

- local interaction/ripple studies
- flow-mask authoring reference
- obstacle/effectors behavior reference

Risks:

- dynamic paint/effectors are Blender scene mechanisms, not Unity runtime contract.
- must bake or translate output into water masks/flow fields before production use.

## Required VeilBreakers Water Contract

Every accepted water upgrade must preserve or improve:

- `water_surface_elevation_m`
- `water_depth_m`
- `flow_direction_xy`
- `flow_speed_mps` or equivalent
- `flow_accumulation`
- `foam_mask`
- `mist_mask`
- shoreline wetness / wet-rock masks
- caustic/material metadata
- Unity water shader manifest

Acceptance:

- no flat plane without depth/surface/flow metadata
- no foam without water-distance or flow basis
- no add-on dependency for Unity runtime
- Blender render proof plus channel proof
