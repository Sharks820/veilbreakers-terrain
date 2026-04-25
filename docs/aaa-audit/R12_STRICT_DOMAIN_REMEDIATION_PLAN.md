# R12 Strict Domain Remediation Plan

This is the implementation plan produced from the strict audit. It is intentionally not a grade inflation sheet.

## Immediate Rule

No product terrain callable returns to `B` until the audit row has runtime wiring, direct tests, and live visual or engine proof where applicable.

## Work Waves

1. `WIRE_OR_DEPRECATE`: remove dead/orphan generator surfaces or wire them into command/pass/runtime paths with fail-closed errors.
2. `ADD_DIRECT_TESTS`: add deterministic unit/integration tests for every callable that remains reachable.
3. `ADD_LIVE_VISUAL_GOLDEN`: build Blender/live golden scenes for water, mountains, cliffs, roads, scatter, materials, and biome transitions.
4. `PROVE_PARENT_CONTRACT_OR_INLINE`: either prove helper behavior through parent-surface tests or inline/delete the helper.
5. `REVIEW_FOR_B`: manually inspect remaining C+ rows after evidence is attached.

## Domain Baselines

### terrain_shape (197 below-B rows)

Best practice: Use deterministic seeded coherent noise with macro/meso/micro layers; drive mountains/hills/flats/cliffs from explicit terrain family controls; apply multi-scale erosion/deposition masks; verify tiled seams and rendered landform readability.

Remediation counts:
- `ADD_LIVE_VISUAL_GOLDEN`: 82
- `ADD_DIRECT_TESTS`: 59
- `WIRE_OR_DEPRECATE`: 56

### cliffs (44 below-B rows)

Best practice: Generate cliff faces with strata/fracture/talus/outcrop masks; avoid heightmap-only vertical smearing; prove silhouette, scale, projection/triplanar materials, and foothill transitions in rendered goldens.

Remediation counts:
- `ADD_DIRECT_TESTS`: 21
- `ADD_LIVE_VISUAL_GOLDEN`: 16
- `WIRE_OR_DEPRECATE`: 7

### water (151 below-B rows)

Best practice: Carve beds/banks before water surfaces; solve basins/spillways/outflow; export flow/flowdir/sediment/wetness masks; verify seam continuity, held water levels, material margins, and live renders.

Remediation counts:
- `ADD_DIRECT_TESTS`: 63
- `WIRE_OR_DEPRECATE`: 46
- `ADD_LIVE_VISUAL_GOLDEN`: 42

### roads_paths (98 below-B rows)

Best practice: Route splines/paths against slope and obstacles; deform terrain with shoulders/drainage/worn blends; prove path continuity, biome-aware side dressing, and rendered road-to-terrain integration.

Remediation counts:
- `ADD_LIVE_VISUAL_GOLDEN`: 39
- `ADD_DIRECT_TESTS`: 35
- `WIRE_OR_DEPRECATE`: 24

### biome_transition (54 below-B rows)

Best practice: Use shared ecotone masks for height, materials, scatter, water, atmosphere, and gameplay; avoid abrupt scatter/material stops; verify transitions in multi-biome live scenes.

Remediation counts:
- `ADD_DIRECT_TESTS`: 24
- `WIRE_OR_DEPRECATE`: 19
- `ADD_LIVE_VISUAL_GOLDEN`: 11

### scatter_foliage (214 below-B rows)

Best practice: Use species catalogs, density falloffs, forest core/edge/sparse bands, slope/moisture/altitude constraints, LOD/instancing/export budgets, and rendered grass/tree variety proof.

Remediation counts:
- `ADD_DIRECT_TESTS`: 93
- `WIRE_OR_DEPRECATE`: 76
- `ADD_LIVE_VISUAL_GOLDEN`: 45

### materials (41 below-B rows)

Best practice: Use layered PBR terrain materials with triplanar/height blends, macro color breakup, wetness/sediment integration, texel-density checks, and engine/render import proof.

Remediation counts:
- `WIRE_OR_DEPRECATE`: 17
- `ADD_DIRECT_TESTS`: 15
- `ADD_LIVE_VISUAL_GOLDEN`: 9

### lod_streaming_export (60 below-B rows)

Best practice: Use world hierarchy, deterministic chunking, screen-error/LOD budgets, virtual texture/cache strategy, engine import smoke tests, and streaming performance gates.

Remediation counts:
- `ADD_LIVE_VISUAL_GOLDEN`: 26
- `ADD_DIRECT_TESTS`: 22
- `WIRE_OR_DEPRECATE`: 12

### validation_visual (111 below-B rows)

Best practice: Use rendered golden scenes, adjacent-tile seam proof, pixel/readability metrics, engine import gates, and fail-closed validator wiring.

Remediation counts:
- `WIRE_OR_DEPRECATE`: 63
- `ADD_DIRECT_TESTS`: 25
- `ADD_LIVE_VISUAL_GOLDEN`: 23

### tooling_wiring (102 below-B rows)

Best practice: Expose deterministic command/pass contracts with clear errors, no silent fallbacks, dispatch tests, and designer iteration surfaces comparable to PCG graph tools.

Remediation counts:
- `ADD_DIRECT_TESTS`: 43
- `WIRE_OR_DEPRECATE`: 26
- `PROVE_PARENT_CONTRACT_OR_INLINE`: 23
- `REVIEW_FOR_B`: 10

### generic (1639 below-B rows)

Best practice: Prove runtime relevance, deterministic behavior, direct tests, caller wiring, typed contracts, and no dead/orphan code before claiming generator quality.

Remediation counts:
- `WIRE_OR_DEPRECATE`: 953
- `ADD_DIRECT_TESTS`: 326
- `PROVE_PARENT_CONTRACT_OR_INLINE`: 184
- `REVIEW_FOR_B`: 176
