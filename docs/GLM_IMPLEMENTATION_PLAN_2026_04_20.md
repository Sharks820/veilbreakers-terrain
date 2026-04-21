# GLM Implementation Plan — 2026-04-20

This plan is the safe handoff for a follow-on GLM run after the live-readiness fixes landed on `main`.

## What Was Already Fixed

Do not spend GLM time re-implementing these:

- `TerrainMaskStack` schema/NPZ/hash gaps for live channels:
  `grass_density_map`, `ice_factor`, `cave_nav_issues_count`,
  `waterfall_velocity`, `shadow_map`, `stochastic_uv_mask`,
  `wet_surface_decal`.
- `pass_waterfall_mist` now writes its declared `wet_surface_decal` output to the stack.
- `pass_river_convergence` is now registered by the default pipeline.
- North/south seam application is corrected.
- Cross-tile seam validation now accepts `north/south/east/west` aliases.
- `pass_erosion` no longer double-attenuates the analytical hardness component.
- Waterfall orientation now matches the waterfall-module convention.
- `albedo_shift_rgb` is consumed by macro color.
- Blender 4.x guards:
  `terrain_caves.py` `use_auto_smooth`,
  `environment_scatter.py` `alpha_threshold`.
- Missing command handlers are registered:
  `env_create_cave_entrance`, `env_generate_road`.
- `sun_direction` now threads through the light handler.
- Spot lights retain `direction` / `spot_angle`, including after merge.
- Twelve-step road routing now passes world `cell_size` into `_astar`.

## Findings From The Second Audit Sheet

### Confirmed And Still Open

These are good GLM targets.

1. Real OpenSimplex 2D path in `_terrain_noise.py`
   - Status: confirmed still open.
   - Problem: `_OpenSimplexWrapper.noise2()` and `noise2_array()` still route 2D terrain through the Perlin fallback.
   - Goal: either use the real OpenSimplex backend for 2D, or explicitly rename/document the path as Perlin if performance constraints force that choice.
   - Required validation:
     - add targeted tests proving 2D scalar/array sampling no longer aliases `_PermTableNoise`
     - benchmark a representative terrain generation path so the fix does not quietly regress runtime beyond an acceptable envelope

2. Blender visual-QA utilities
   - Status: partially open.
   - Problem: there is still no complete repo-native camera setup / framing / render capture path for repeatable 3D visual QA.
   - Goal:
     - create camera if missing
     - frame terrain automatically
     - set viewport shading/material visibility
     - optionally render to file or capture viewport image
   - Constraint: keep this additive; do not entangle it with terrain generation logic.

3. Road-system unification
   - Status: confirmed open.
   - Problem: `terrain_twelve_step.py` still uses `_terrain_noise._astar`, while `road_network.py` remains a parallel, richer but orphaned system.
   - Goal:
     - extract a shared routing core
     - make twelve-step and environment road generation consume the same pathing logic
     - preserve existing public handler behavior unless explicitly versioned
   - Constraint: this is medium blast radius. Require tests first.

4. Water-surface mesh bridge
   - Status: architectural gap, not a fake finding.
   - Problem: water-related data exists, but the main mask-stack pipeline still lacks a coherent water-surface mesh generation bridge.
   - Goal:
     - define one canonical mesh handoff from `water_surface` + convergence/flow channels
     - only then connect waterfall mesh emission into it

### Confirmed But Deferred For Tonight

These are real, but not good “blind GLM patch” targets unless isolated first.

1. `terrain_god_ray_hints.py` claims
   - The second audit’s “reversed direction” statement was not proven well enough from the cited code path.
   - A different real lighting bug was fixed: the handler dropped `sun_direction`.
   - Do not patch god-ray marching logic without a direct repro and reference images.

2. Noise-stack normalization / ridged-range claims
   - Some may be real, but they are algorithmic tuning changes rather than crash/wiring fixes.
   - Treat as a separate benchmarked quality pass.

3. `detect_perched_lakes`
   - The inversion claim remains disputed because the function’s own docstring defines a narrower perched-lake concept than the audit assumed.
   - Require an expected-behavior test before changing it.

## Findings GLM Should Ignore Unless Re-Verified

- “`alpha_threshold` is a current runtime crash” — stale.
- “all seam validation is silently skipped” — overstated; the real issue was key aliasing.
- “`strict_tile_contract` is not enforced/persisted” — false as stated.
- “there is no render capability at all” — stale/overstated; there is limited preview scaffolding, but not a full Blender-native QA path.

## Suggested Execution Order For GLM

### Track A — Low Risk

1. Blender visual-QA helpers
2. OpenSimplex 2D correction with benchmarks
3. Add regression coverage around any touched handler plumbing

### Track B — Medium Risk

4. Road-system unification behind compatibility tests
5. Water-surface mesh bridge definition and implementation

### Track C — Explicitly Out Of Scope For A Blind Pass

6. Broad erosion rewrites
7. Hydrology solver rewrites
8. Large audit-driven grade-sheet churn
9. Unverified atmospheric/god-ray rewrites

## GLM Working Rules

- Work only from confirmed issues.
- Add tests before changing behavior on disputed findings.
- Do not touch the just-fixed live-readiness files unless the change is narrowly related and covered by new tests.
- Prefer bounded PR-sized slices:
  - noise
  - Blender QA
  - roads
  - water mesh

## Acceptance Bar

Every GLM change must include:

- a direct repro or failing test before the fix
- a passing targeted test after the fix
- a note on whether the change affects live-testing behavior tonight
- no broad “audit cleanup” commits that mix unrelated modules
