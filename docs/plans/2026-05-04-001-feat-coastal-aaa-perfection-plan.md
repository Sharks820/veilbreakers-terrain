---
title: Coastal Biome AAA Visual Perfection
type: feat
status: active
date: 2026-05-04
origin: docs/aaa-audit/BIOME_VISUAL_HONING_SESSION_HANDOFF_2026_05_05.md
deepened:
---

# Coastal Biome AAA Visual Perfection

## Summary

Perfect VeilBreakers' Coastal biome (4096m × 4096m full-size game node) to AAA visual + functional quality with verified Blender 4.5 render proofs at every pass and a clean Unity 2023 round-trip. Establishes the per-biome AAA template (mesh strategy, PBR materials, animated water, lighting/atmosphere, vegetation w/ wind, props, mesh quality, Unity export, signoff gates) that subsequent biomes (Mountain, Grassland, Volcanic, Frozen, Desert) inherit. Locks the choice of vegetation stack (L-Py + PlantGL + Modular Tree v5.5.1 GoodPie + OpenScatter), texture sources (ambientCG + Poly Haven CC0), hero-asset provider (Hunyuan3D-2.1 local), and the required visual-proof workflow (named-camera renders, never `mcp__blender__.get_viewport_screenshot`).

---

## Problem Frame

The current Coastal node (`output/visual_nodes/VB_Correct_Fullsize_Coastal_Terrain_4096m.blend`) reads as a flat sheet with a jagged grid shoreline, primitive vertex-color materials, separate stacked water meshes, no vegetation, no props, basic test-render lighting, and no Unity round-trip. Ten open buckets in the handoff (shoreline, terrain form, materials, water, mesh quality, props/vegetation, lighting, viewport bug, Unity export, QA) plus several P0 audit blockers (biome-name fragmentation, pass_water_flow_speed unsequenced, coastline wave_dir hardcoded to 0, dual splatmap systems, foam-implementation drift) keep AAA out of reach. The user is away during execution; progress visibility comes only from PR + git-committed render PNGs (`renders/coastal/<unit-name>/<camera>.png`).

(See origin: `docs/aaa-audit/BIOME_VISUAL_HONING_SESSION_HANDOFF_2026_05_05.md`)

---

## Assumptions

*This plan was authored without synchronous user confirmation. The items below are agent inferences that fill gaps in the input — un-validated bets that should be reviewed before implementation proceeds.*

- **Sequencing**: Foundation passes (render harness, preflight cleanup, Bezier-SDF shoreline, landform zones) land before visual passes (PBR, water shader, lighting); vegetation/props land after terrain is stable; Unity export is last gate before signoff. Inferred from the handoff "Next Immediate Work Order" but reordered to put the render-proof harness first so every later unit has a verifier.
- **Per-unit PR cadence**: Each unit lands as its own squash-merge PR into `main` from `feat/dynamic-quality-audit` (or sub-branch per AGENTS.md branch protocol). Commits include the unit's render PNGs at the standard three Coastal cameras (full-node, shore, player) plus close-camera oblique angles where a single front shot wouldn't expose artifacts. Inferred from "submit photo visuals to git for every biome update".
- **Vegetation tooling**: L-Py + PlantGL via conda-forge `openalea3` channel (NOT pip on Windows — wheels missing), Modular Tree v5.5.1 GoodPie fork, OpenScatter v1.0.7. Confirmed in research.
- **Hero asset provider**: Hunyuan3D-2.1 via the WinPortable build (`YanWenKun/Hunyuan3D-2-WinPortable`). Confirmed commercial-OK to 1M MAU.
- **Texture sources**: ambientCG + Poly Haven CC0 for terrain detail maps; never Substance Painter student license for shipped assets (CLAUDE.md guidance).
- **Best-practices doc location**: `docs/biome-best-practices/COASTAL.md` with cross-biome carryover template at `docs/biome-best-practices/_TEMPLATE_BIOME_PERFECTION.md`.
- **Toolchain pin**: Python 3.11 across the foliage stack until Blender 5.0 / Python 3.13 catches up. Modular Tree binaries are 3.11-only.

---

## Requirements

- R1. Coastal node renders without jagged shoreline at the close `VB_CORRECT_COASTAL_SHORE_CAMERA` (≤ 50 m). Origin: Bucket 1. (Delivered by U3.)
- R2. Terrain reads as relief, not a sheet, at `VB_CORRECT_COASTAL_PLAYER_CAMERA`. Authored zones (low beach / backshore / headland / drainage gullies / inland ridge) are visible. Origin: Bucket 2. (Delivered by U4.)
- R3. Material stack is real PBR (albedo + normal + roughness + AO + height blend) with macro/micro tiling, slope blend, wet-sand band, and cliff/rock detail — not vertex-color blend, not face-bucket, not greyed wash. Origin: Bucket 3. (Delivered by U5.)
- R4. Water shader has depth fade, Gerstner wave displacement, animated normals, scene-depth foam at shore contact, refraction, and animation visible in a 60-frame loop. Origin: Bucket 4. (Delivered by U6.)
- R5. Mesh strategy is documented: terrain grid + curve-conforming high-res shoreline strip welded into terrain + overlapping water plane with alpha fade + hero cliff meshes. No visible stacked-layer edges at close camera. Origin: Bucket 5. (Delivered by U11.)
- R6. Coastal vegetation set installed and placed via real density fields: 4 dark-fantasy tree variants (twisted oak, dead pine, mangrove, gnarled hawthorn), 4 grass species, 2 shrub species. Wind animation works in Blender preview AND survives Unity export (Pivot Painter 2.0 vertex data). Origin: Bucket 6.
- R7. Coastal hero prop set generated via Hunyuan3D-2.1: driftwood logs ×3, coastal boulders ×4, reed clumps ×3, low shrubs ×2, foam-decal patches. Each has LOD0/LOD1 and a manifest entry. Origin: Bucket 6.
- R8. Coastal lighting rig produces game-environment imagery: sun + sky probe + horizon fog + coastal mist volumetric + color grade preset. Origin: Bucket 7.
- R9. Render-proof harness produces deterministic non-black PNGs at named cameras. `mcp__blender__.get_viewport_screenshot` is bypassed. Origin: Bucket 8.
- R10. Unity 2023 round-trip succeeds: RAW16 heightmap, splatmap weights, water JSON, shoreline mask, material manifest, mesh GLBs, vegetation prototypes with wind data, prop manifest. `veilbreakers-unity-export-check` passes. Camera-scale Unity proof scene rendered. Origin: Bucket 9.
- R11. Mechanical visual gates pass: nonblack render, camera framing, mesh scale, shoreline smoothness metric, no-checker/no-layer-artifact assertion, water-reaches-shore mask, AAA-reference comparison images side-by-side. Origin: Bucket 10.
- R12. Coastal best-practices doc is published, includes every locked decision, the carryover template, and is linked from the next-biome (Mountain) entry point. Captures gaps surfaced by ce-learnings-researcher (Bezier-SDF, wet-sand shader, Pivot Painter wind, Unity round-trip protocol, single-source biome registry). Origin: user request "documenting best practices on a per biome basis".
- R13. Preflight P0 unblockers landed before they block downstream units: single biome registry (P0-S1/S2), `pass_water_flow_speed` + `pass_river_convergence` inserted into pipeline (B15-P0-33), `coastline.apply_coastal_erosion` consumes real `wave_dir` not 0.0 + `_hash_noise` replaced with OpenSimplex/FastNoiseLite, dual-splatmap merge (P0-M1).
- R14. No P0 regressions: do not reintroduce `pool_deepening_delta` to `_DELTA_CHANNELS`, do not default `erosion_profile` to `"temperate"`, do not write legacy `water_surface` (use `water_surface_elevation_m`).

---

## Scope Boundaries

- Coastal-only this iteration — Mountain, Grassland, Volcanic, Frozen, Desert are not touched. The carryover template is the bridge.
- No work on the Visual QA framework rebuild (P0-M3) beyond what U1 needs for proof renders. The full VisualQA P0 stays as a separate plan.
- No mass refactor of `terrain_pipeline.py` beyond the two missing pass insertions in U2.
- No work on cave systems, waterfalls, rivers/streams *interior* features — Coastal scope is shoreline + ocean + beach + headland + bluff. Inland streams/waterfalls handled when Mountain biome runs.
- No commit to e-on PlantCatalog ($129+ commercial) — vegetation stack is L-Py + Modular Tree GoodPie + OpenScatter (free).
- No Substance Painter student-license textures (CLAUDE.md prohibition for shipped work).
- No work on Mesh Quality / mesh decimation strategy beyond U10's adaptive shoreline + cliff hero meshes — full LOD pipeline is a separate plan.

### Deferred to Follow-Up Work

- **Mountain biome perfection**: separate plan; uses the carryover template U13 publishes.
- **VisualQA rebuild (P0-M3)**: separate plan; U1's render-proof harness is a small slice that informs the larger rebuild.
- **Unity HDRP integration polish**: the round-trip in U12 produces a verified terrain + water + foliage scene. HDRP shader-graph polish for water/terrain is a separate plan.
- **Caustics, light shafts, screen-space reflections beyond Eevee Next defaults**: U6 ships Eevee Next defaults + irradiance volume. Custom HDR caustics is deferred.
- **AAA tree LOD pipeline + impostor billboards**: U8 ships LOD0/LOD1 from Modular Tree. Full impostor system is deferred.
- **Cave + cliff interior detail**: U11 ships outer cliff hero mesh; cave interior is mountain/cave biome work.

---

## Context & Research

### Relevant Code and Patterns

- `scripts/create_correct_fullsize_coastal_terrain.py` (current builder; full rewrite spans U2-U10).
- `scripts/send_correct_fullsize_coastal_terrain_to_blender.py` (driver; minor edits for harness wiring in U1).
- `scripts/blender_port_proxy_9877_to_9876.py` (proxy bridge; unchanged unless U1 needs viewport-screenshot patch).
- `scripts/dynamic_quality_renderer.py` (canonical v2 prove-path; inspired by but does NOT replace U1 — U1 is biome-specific named-camera renderer).
- `veilbreakers_terrain/handlers/_water_network.py` (`pass_water_flow_speed`, `pass_hydrology`, `pass_hydrology_post_erosion`).
- `veilbreakers_terrain/handlers/terrain_water_variants.py` (`apply_seasonal_water_state`, `pass_water_variants`).
- `veilbreakers_terrain/handlers/terrain_materials_v2.py` (Brucks blend at line 368, snow line at 414, SDF road blend at 520, triplanar at 279, `pass_materials` at 1015).
- `veilbreakers_terrain/handlers/terrain_texture_layer_stack.py:38` (`TerrainTextureLayerStack` exists; populate albedo/normal/rough/AO arrays in U5).
- `veilbreakers_terrain/handlers/_scatter_engine.py` (poisson_disk_sample, lloyd_relax_points, biome_filter_points).
- `veilbreakers_terrain/handlers/environment_scatter.py:3194` (`handle_scatter_vegetation`, `_write_tree_instance_points` at 1257; biome filter `_canonical_biome` at 3022).
- `veilbreakers_terrain/handlers/terrain_foliage_catalog.py` (`SpeciesSpec`, `species_for_biome`, `AssetManifest`).
- `veilbreakers_terrain/handlers/terrain_unity_export.py:1853` (`export_unity_manifest`; required stack fields, RAW heightmap, splatmap, water JSON at 1001, foliage scatter manifest at 248, particle emitter specs at 1186, biome manifest at 1399).
- `veilbreakers_terrain/handlers/terrain_unity_export_contracts.py` (`UnityExportContract`, `validate_mesh_attributes_present`, `validate_bit_depth_contract`).
- `veilbreakers_terrain/handlers/coastline.py` (`apply_coastal_erosion` — wave_dir hardcoded 0; `_hash_noise` placeholder).
- `veilbreakers_terrain/sim/foam.py` (5-component AAA foam — use this; retire `_water_network_ext` foam branch).
- `veilbreakers_terrain/socket_server.py` (`BlenderMCPServer` — bpy-free, queue-drained on main thread).
- `veilbreakers_terrain/src/veilbreakers_mcp/blender_server.py:28` (`_LOC_HANDLERS` location → command map; add `visual_render_camera_proof` here in U1).
- `veilbreakers_terrain/handlers/__init__.py:50` (`_build_command_handlers`; register U1's new command).

### Institutional Learnings

- `docs/AAA_MASTER_IMPLEMENTATION_GUIDE_2026_04_27.md` — domain grades + 10 P0 blockers + Hunyuan3D-2 integration spec.
- `docs/aaa-audit/AAA_MASTER_AUDIT_2026_05_03.md` — 24 new P0s, three systemic root causes (biome fragmentation, dual splatmap, broken iteration stack).
- `docs/aaa-audit/BIOME_VISUAL_HONING_SESSION_HANDOFF_2026_05_05.md` — origin doc; ten open buckets.
- `docs/aaa-audit/deep_dive_2026_04_16/wave2/B2_water_waterfalls_coastline.md` — coastline wave_dir bug + `_hash_noise` placeholder + `detect_tidal_zones` pattern (A-).
- `docs/aaa-audit/deep_dive_2026_04_27/A2_water_systems.md` — full water research baseline (foam, refraction, depth fade).
- `docs/aaa-audit/batch15_2026_05_04/MASTER_AUDIT_BATCH15.md` — `pass_water_flow_speed` and `pass_river_convergence` are pass-orphans (B15-P0-33).
- `docs/solutions/architecture-patterns/biome-grammar-features-orphaned-pass-wiring-2026-05-03.md` — every `register_*_pass()` must be called from `register_default_passes()`.
- `docs/solutions/logic-errors/erosion-profile-hardcoded-temperate-2026-05-03.md` — recurrence guardrail; do NOT default to `"temperate"`.
- `docs/solutions/logic-errors/pool-deepening-delta-double-apply-2026-05-03.md` — recurrence guardrail; do NOT add to `_DELTA_CHANNELS`.
- `docs/VEGETATION_TOOL_DECISION_2026_05_03.md` / `docs/WATER_TOOL_DECISION_2026_05_03.md` / `docs/SCATTER_TOOL_RESEARCH_2026_05_03.md` — locked tool selections.

### External References

- Blender 4.5 LTS release notes (developer.blender.org) — Eevee Next Raytraced Transmission, Geometry Nodes 4.5, BSDF v2 inputs.
- Andersson SIGGRAPH 2007 Frostbite terrain talk — height-blend (Brucks) formula.
- Ben Golus, "Normal mapping for a triplanar shader" — pinstripe-free triplanar via per-axis tangent reconstruction.
- Inigo Quilez, "2D distance functions" — quadratic Bezier SDF math.
- Tencent Hunyuan3D-2.1 (`Tencent-Hunyuan/Hunyuan3D-2.1`) — license, VRAM, Windows install.
- Pivot Painter 2.0 (Epic) — vertex data layout (UV2: U=instance-id, V=hierarchy-level; pivot in RGB).
- L-Py 3.14 + OpenAlea PlantGL — install via `mamba create -n lpy -c openalea3 -c conda-forge openalea.plantgl openalea.lpy openalea.mtg python=3.11`.
- Modular Tree v5.5.1 (`GoodPie/modular_tree`) — Blender 4.5 compatible.
- OpenScatter v1.0.7 (`GitMay3D/OpenScatter`) — Blender 4.5 compatible.
- Unity 2023 TerrainData, HDRP Water System, glTFast.

---

## Key Technical Decisions

- **Bezier-shoreline as SDF, not grid mask**: Tessellate the Bezier shore curve to a polyline, build a 2D KDTree of polyline samples, query each terrain vertex for the nearest segment, sign the distance via cross product of segment tangent vs vertex-to-segment vector. Grade the heightfield by `h_new = lerp(h_ocean, h_terrain, smoothstep(-beach_w, +cliff_w, sd))`. Eliminates jagged grid edge at the cost of one O(N log M) preprocess per build. *Rationale:* Grid masks produce square-grid shoreline; smoothing foam over it does not fix the underlying mesh boundary. Curve-driven SD grading is the only known correct fix.
- **Brucks height-blend (Andersson 2007 formula)**: `b = max(h1+a1, h2+a2) - depth; w_i = max(h_i+a_i-b, 0)` then normalize. Replaces vertex-color terrain blend with height-aware multi-layer blend. *Rationale:* Vertex-color blend produces washed/grey results; height-blend produces sharp pebbly material transitions matching AAA terrain.
- **Triplanar with per-axis tangent reconstruction (Ben Golus)**: Reconstruct tangent-space normals per planar axis before blending. `tightening = pow(saturate(abs(N) - threshold), k)` with k=4..8 to crush minor axes. *Rationale:* Naive triplanar blending of normal maps produces diagonal pinstripe artifacts (audited as P0).
- **Eevee Next "Raytraced Transmission" + "Screen + Light Probes"**: Required for water refraction with off-screen rays falling back to probes. `Tracing Method = Screen + Light Probes`. *Rationale:* Off-screen rays produce missing-data black gaps in ocean horizon without probe fallback; this is a Blender 4.5 specific decision.
- **Gerstner waves via Geometry Nodes vertex displacement on a 512×512 water plane**: 4-6 directional sums of sines, each with steepness `Q ∈ [0, 1/(w*A*N)]` to avoid loops. Animate via `Scene Time` driver. Plane is `4096m × 4096m` so cell ≈ 8 m, giving Nyquist headroom for the shortest 20m wavelength (2.5 samples/wave). *Rationale:* Eevee can't displace at the shader level; GN displacement is the only path that produces real wave silhouette and survives the Unity round-trip via baked frames or HDRP equivalent. 256² (16 m cells) was insufficient for a 20m wave (Nyquist failure); 512² is the minimum that resolves all 4 designed wavelengths.
- **Foam from scene depth + curl-noise UV**: `1 - smoothstep(0, foam_dist, scene_depth − water_depth)` plus animated curl-noise mask. *Rationale:* Depth-fringe foam reads as physical contact; static foam strips read as decals.
- **Unified biome registry (P0-S1/S2 fix)**: `veilbreakers_terrain/handlers/terrain_biome_registry.py` already exists with 18 canonical VB dark-fantasy biome IDs and alias resolution. U2 audits and migrates remaining consumers (vegetation_system, _biome_grammar, terrain_foliage_catalog, environment_scatter, terrain_unity_export) to route through `resolve_to_canonical`, and adds a static-grep regression test to prevent re-introducing local tables. The handoff's six-biome roadmap maps to canonical IDs as: Coastal → `coastal`, Mountain → `mountain_pass`, Grassland → `grasslands`, Volcanic → `ashen_wastes`, Frozen → `frozen_hollows`, Desert → `desert`. *Rationale:* Three disjoint biome-name vocabularies cause zero foliage placements for VB biomes; this is the highest-leverage P0 fix.
- **`coastline.apply_coastal_erosion` reads `composition_hints["dominant_wave_dir_rad"]` and `_hash_noise` is replaced with OpenSimplex**: thread real wave direction through pass; replace placeholder noise. *Rationale:* Hardcoded `wave_dir = 0` and sin-hash noise produce uniform shoreline regardless of authoring intent.
- **Splatmap merge (P0-M1)**: `terrain_materials.auto_assign_terrain_layers` reads from `stack.splatmap_weights_layer` rather than re-deriving. *Rationale:* Blender preview and Unity export must agree on weights.
- **Foam from `sim/foam.py` (5-component AAA), retire `_water_network_ext` foam branch**: pick one source. *Rationale:* AAA foam includes shoreline + Froude + Kelvin wake; ad-hoc 3-component is deprecated.
- **Render-proof workflow**: `bpy.ops.render.render(write_still=True)` with absolute-path filepath + nonblack pixel assertion. New repo command `visual_render_camera_proof` registered via `_LOC_HANDLERS`. *Rationale:* `mcp__blender__.get_viewport_screenshot` returns black on this Windows + Blender 4.5 + MCP combination; cannot be trusted.
- **Toolchain pin Python 3.11**: All foliage tools are 3.11-only. Do not bump until Blender 5.0 / Python 3.13 has support across L-Py + Modular Tree + OpenScatter.
- **Per-unit PR cadence**: Each unit lands as its own squash-merge PR with render PNGs committed to `renders/coastal/<unit-name>/`. Required CI checks `ci (3.11)`, `ci (3.12)`, `pyright`, `callable-census`, `Analyze (python)`, `Analyze (actions)` must pass before merge.
- **Render output convention**: `renders/coastal/<unit-id>_<unit-slug>/<camera-name>.png`. Three primary cameras every unit: `full_node`, `shore`, `player`. Plus close-camera oblique (`shore_close_oblique_45`, `bluff_close_oblique_30`) when shoreline or cliff geometry is the deliverable.

---

## Open Questions

### Resolved During Planning

- **Vegetation stack choice**: L-Py + PlantGL (conda-forge) for procedural species + Modular Tree v5.5.1 GoodPie for hero trees + OpenScatter v1.0.7 for placement. Rejected: e-on PlantCatalog (paid), BlenderKit (background-disabled), Botaniq (GUI-only), Geo-Scatter (EULA prohibits scripted), SpeedTree (no Blender bridge).
- **Hero asset provider**: Hunyuan3D-2.1 via WinPortable. Rejected: paid Tripo/Meshy (cost), Megascans (commercial-OK but generic, not dark-fantasy), Poly Haven assets (great for textures, narrow asset set for coastal).
- **Texture sources**: ambientCG + Poly Haven (CC0). Rejected: Substance Painter student license (CLAUDE.md prohibition).
- **Render proof workflow**: named-camera bpy.ops.render.render with nonblack assertion. Rejected: `mcp__blender__.get_viewport_screenshot` (returns black).
- **Bezier-SDF vs Geometry-Nodes shoreline-cut**: tessellate→KDTree→signed-by-tangent (Python preprocess) chosen over Geometry Nodes node graph. *Why:* Python is testable in CI; GN is harder to verify headless. Builder script does the SD compute, terrain mesh is built with graded heights.
- **Water animation in Blender preview**: Geometry Nodes vertex displacement with `Scene Time` driver, frame range 1-60 at 30fps. Verified in U5 by rendering frame 1 + frame 30 + frame 60 and comparing.

### Deferred to Implementation

- **Per-zone landform parameters in U4**: low-beach extent, headland height/radius, gully count and depth — tunable. First pass uses defensible defaults; iterate based on render review.
- **Per-species L-Py grammar files in U7**: exact .lpy rule sets for twisted oak, dead pine, mangrove, hawthorn — author with reference to dark-fantasy concept art. First pass is parametric, refine after review.
- **OpenScatter density-mask UV channel name**: depends on splatmap export naming after U2-d (splatmap merge).
- **Hunyuan3D-2.1 prompt set in U10**: exact prompts for driftwood × 3, boulders × 4, reeds × 3, shrubs × 2, foam decals — author per asset, refine if topology fails.
- **Wind animation strength in U9**: Pivot Painter wind frequency/amplitude defaults — tune visually.
- **Unity prefab structure in U12**: TerrainData + WaterSurface + foliage prototypes + props as a `CoastalGameNode_4096m.unity` scene; prefab variants for re-use TBD.

---

## Output Structure

```
docs/
├── plans/
│   └── 2026-05-04-001-feat-coastal-aaa-perfection-plan.md      (this plan)
├── biome-best-practices/
│   ├── _TEMPLATE_BIOME_PERFECTION.md                            (carryover template, U13)
│   └── COASTAL.md                                               (locked decisions, U13)
└── solutions/
    ├── architecture-patterns/
    │   ├── single-biome-registry-2026-05-04.md                  (U2)
    │   ├── bezier-sdf-shoreline-2026-05-04.md                   (U3 + U13 ce-compound)
    │   ├── splatmap-headless-blender-merge-2026-05-04.md        (U2 + U13)
    │   └── pass-orphan-sequencing-2026-05-04.md                 (U2)
    └── best-practices/
        ├── visual-render-camera-proof-2026-05-04.md             (U1)
        ├── brucks-triplanar-pbr-2026-05-04.md                   (U5)
        ├── gerstner-eevee-water-2026-05-04.md                   (U6)
        ├── pivot-painter-wind-coastal-2026-05-04.md             (U9)
        └── unity-coastal-roundtrip-2026-05-04.md                (U12)
renders/
└── coastal/
    ├── u01_render_harness/                                       (U1 self-test)
    ├── u02_preflight_cleanup/                                    (U2 regression renders)
    ├── u03_bezier_sdf_shoreline/                                 (U3)
    ├── u04_landform_zones/                                       (U4)
    ├── u05_pbr_terrain/                                          (U5)
    ├── u06_water_shader/                                         (U6 — frame 1, 30, 60)
    ├── u07_lighting_atmosphere/                                  (U7)
    ├── u08_vegetation_install/                                   (U8 — species swatches)
    ├── u09_wind_animation/                                       (U9 — frame 1, 30, 60)
    ├── u10_props_hunyuan/                                        (U10)
    ├── u11_adaptive_mesh_cliffs/                                 (U11)
    └── u12_unity_export_proof/                                   (U12 Blender + Unity side-by-side)
veilbreakers_terrain/
├── handlers/
│   ├── terrain_biome_registry.py                                 (NEW, U2)
│   ├── coastline.py                                              (MODIFIED, U2)
│   ├── _water_network.py                                         (MODIFIED — sequencing only, U2)
│   ├── terrain_pipeline.py                                       (MODIFIED, U2)
│   ├── terrain_materials.py                                      (MODIFIED — splatmap merge, U2)
│   ├── terrain_materials_v2.py                                   (MODIFIED — Brucks/triplanar, U5)
│   ├── terrain_texture_layer_stack.py                            (MODIFIED — populate arrays, U5)
│   └── visual_render_camera_proof.py                             (NEW, U1)
├── coastal/
│   ├── shoreline_sdf.py                                          (NEW, U3)
│   ├── landform_zones.py                                         (NEW, U4)
│   ├── water_shader_eevee.py                                     (NEW, U6)
│   ├── lighting_atmosphere.py                                    (NEW, U7)
│   ├── vegetation_pipeline.py                                    (NEW, U8)
│   ├── wind_pivot_painter.py                                     (NEW, U9)
│   ├── props_hunyuan.py                                          (NEW, U10)
│   └── adaptive_mesh.py                                          (NEW, U11)
└── tests/
    ├── test_visual_render_camera_proof.py                        (U1)
    ├── test_terrain_biome_registry.py                            (U2)
    ├── test_shoreline_sdf.py                                     (U3)
    ├── test_landform_zones.py                                    (U4)
    ├── test_brucks_triplanar.py                                  (U5)
    ├── test_water_shader_eevee.py                                (U6)
    ├── test_lighting_atmosphere.py                               (U7)
    ├── test_vegetation_pipeline.py                               (U8)
    ├── test_wind_pivot_painter.py                                (U9)
    ├── test_props_hunyuan.py                                     (U10)
    ├── test_adaptive_mesh.py                                     (U11)
    └── test_unity_coastal_roundtrip.py                           (U12)
scripts/
├── render_coastal_camera_proof.py                                (NEW, U1)
├── coastal_build.py                                              (NEW; replaces create_correct_fullsize_coastal_terrain.py iteratively)
└── coastal_unity_export.py                                       (NEW, U12)
```

---

## Implementation Units

- U1. **Render-Proof Harness**

**Goal:** Build a stable, deterministic render-proof harness that takes named cameras and writes verified non-black PNGs to `renders/coastal/<unit-id>_<slug>/<camera>.png`. Bypasses the broken `mcp__blender__.get_viewport_screenshot` for all subsequent units.

**Requirements:** R9, R11.

**Dependencies:** None.

**Files:**
- Create: `veilbreakers_terrain/handlers/visual_render_camera_proof.py`
- Create: `scripts/render_coastal_camera_proof.py`
- Create: `veilbreakers_terrain/tests/test_visual_render_camera_proof.py`
- Create: `docs/solutions/best-practices/visual-render-camera-proof-2026-05-04.md`
- Modify: `veilbreakers_terrain/src/veilbreakers_mcp/blender_server.py` (register `visual_render_camera_proof` in `_LOC_HANDLERS`)
- Modify: `veilbreakers_terrain/handlers/__init__.py` (register command)

**Approach:**
- Handler accepts `{cameras: [name, ...], engine: 'BLENDER_EEVEE_NEXT', resolution: [w, h], samples: int, view_transform: 'Standard'|'AgX'|..., out_dir: absolute_path, prefix: str}`.
- Per camera: switch active camera, set absolute filepath via `pathlib.Path(...).as_posix()`, set engine + resolution + samples, call `bpy.ops.render.render(write_still=True)`, then read the PNG with PIL and assert ≥ 0.5% of pixels are non-black + total file size > 50 KB. Raises `RenderProofFailedError` on assertion failure.
- Driver script `scripts/render_coastal_camera_proof.py` is the externally-callable entry; takes `--unit-id <e.g. u01>`, `--cameras <comma-list>`, computes target dir, dispatches over the bridge.
- Result manifest written to `renders/coastal/<unit-id>_<slug>/RENDER_MANIFEST.json` recording which cameras rendered, frame number, file paths, byte sizes, nonblack ratios. `ce-work` reads this when committing renders.

**Patterns to follow:**
- `scripts/dynamic_quality_renderer.py` — engine setup, sample counts, view transform handling.
- `veilbreakers_terrain/socket_server.py` — main-thread queue draining.
- `veilbreakers_terrain/src/veilbreakers_mcp/blender_server.py:28` — `_LOC_HANDLERS` extension pattern.

**Test scenarios:**
- Happy path: render 3 named cameras, verify 3 PNGs exist, all non-black, manifest recorded with correct paths and byte sizes.
- Edge: camera name missing — raises `CameraNotFoundError` with the missing name.
- Edge: empty filepath silently no-writes under `--background` — assertion catches it via byte-size + nonblack check; raises `RenderProofFailedError` mentioning the empty-filepath gotcha.
- Error: filesystem permission denied on out_dir — raises `OSError` early before render starts (precheck writeability).
- Integration: handler is reachable via the typed Blender bridge (`socket_server.py` queue) at port 9876; dispatches on the main thread.
- Integration: driver script exits non-zero when any camera fails proof; CI-friendly.

**Verification:**
- Calling `python scripts/render_coastal_camera_proof.py --unit-id u01 --cameras VB_CORRECT_COASTAL_FULL_NODE_CAMERA,VB_CORRECT_COASTAL_SHORE_CAMERA,VB_CORRECT_COASTAL_PLAYER_CAMERA` writes 3 PNGs to `renders/coastal/u01_render_harness/` and the manifest file. PNGs visibly show the current Coastal node from each camera; no black frames.
- Test suite passes for `test_visual_render_camera_proof.py`.

---

- U2. **DELETED — fresh-build pivot.** Original "Preflight P0 Cleanup" replaced by "build new, do not audit" direction (user, 2026-05-04). All Coastal AAA work happens in fresh `veilbreakers_terrain/coastal/` modules (U3-U13) that do NOT depend on the legacy pipeline registry/coastline/splatmap. If the new modules need biome IDs, they import directly from `terrain_biome_registry.resolve_to_canonical` (already exists) but do not migrate consumers. Plan continues at U3.

*Original U2 content retained below for archival reference only — DO NOT execute.*

**Goal:** ~~Land the four P0 unblockers that gate Coastal vegetation, water, shoreline, and Unity export from working at AAA quality.~~ **(Skipped per fresh-build pivot.)**

**Requirements:** R13, R14.

**Dependencies:** U1.

**Files:**
- Modify (NOT create — file already exists): `veilbreakers_terrain/handlers/terrain_biome_registry.py` — extend if needed; verify `coastal`, `grasslands`, `desert`, `mountain_pass`, `frozen_hollows`, `ashen_wastes` (volcanic) are all canonical; add any missing aliases. Existing canonical IDs: thornwood_forest, deep_forest, mushroom_forest, corrupted_swamp, blighted_mire, grasslands, desert, coastal, ashen_wastes, mountain_pass, frozen_hollows, cemetery, ruined_citadel, ruined_fortress, abandoned_village, battlefield, crystal_cavern, veil_crack_zone.
- Audit + Modify: `veilbreakers_terrain/handlers/vegetation_system.py` (verify uses `terrain_biome_registry.resolve_to_canonical`; drop any local biome lookup table).
- Audit + Modify: `veilbreakers_terrain/handlers/_biome_grammar.py` (verify uses registry; verify every `register_*_pass` is called from `register_default_passes`).
- Audit + Modify: `veilbreakers_terrain/handlers/terrain_foliage_catalog.py` (verify `biome_mask` keys are canonical IDs from registry; rewrite any legacy strings).
- Audit + Modify: `veilbreakers_terrain/handlers/environment_scatter.py:3022` (verify `_canonical_biome` is `resolve_to_canonical`).
- Audit + Modify: `veilbreakers_terrain/handlers/terrain_unity_export.py` (verify biome export uses canonical IDs).
- Modify: `veilbreakers_terrain/handlers/terrain_pipeline.py:204-247` (insert `pass_water_flow_speed` after `pass_hydrology_post_erosion`; insert `pass_river_convergence` after `bathymetry`).
- Modify: `veilbreakers_terrain/handlers/coastline.py` (`apply_coastal_erosion` reads `composition_hints["dominant_wave_dir_rad"]`; replace `_hash_noise` with OpenSimplex via `opensimplex.OpenSimplex(seed)`; write `wave_energy` channel).
- Modify: `veilbreakers_terrain/handlers/terrain_materials.py` (`auto_assign_terrain_layers` reads from `stack.splatmap_weights_layer`; map to vertex colors; do NOT re-derive).
- Create: `veilbreakers_terrain/tests/test_terrain_biome_registry_consumers.py` (NEW — verifies every consumer module routes through `resolve_to_canonical`; static-grep test).
- Create: `docs/solutions/architecture-patterns/single-biome-registry-2026-05-04.md` (audit-result doc explaining which consumers were already aligned and which were migrated).
- Create: `docs/solutions/architecture-patterns/pass-orphan-sequencing-2026-05-04.md`
- Create: `docs/solutions/architecture-patterns/splatmap-headless-blender-merge-2026-05-04.md`

**Approach:**
- **Registry already exists** at `veilbreakers_terrain/handlers/terrain_biome_registry.py` with 18 canonical IDs (VB dark-fantasy themed: thornwood_forest, deep_forest, mushroom_forest, corrupted_swamp, blighted_mire, grasslands, desert, coastal, ashen_wastes, mountain_pass, frozen_hollows, cemetery, ruined_citadel, ruined_fortress, abandoned_village, battlefield, crystal_cavern, veil_crack_zone) and alias resolution. The handoff's six-biome roadmap (Coastal, Mountain, Grassland, Volcanic, Frozen, Desert) maps to canonical IDs as: `coastal` → `coastal`, `mountain` → `mountain_pass`, `grassland` → `grasslands`, `volcanic` → `ashen_wastes`, `frozen` → `frozen_hollows`, `desert` → `desert`. Add any missing aliases at the same time.
- Audit each consumer (vegetation_system, _biome_grammar, terrain_foliage_catalog, environment_scatter, terrain_unity_export) — confirm each routes through `resolve_to_canonical` rather than its own local mapping. Migrate any holdouts. Static-grep test in `test_terrain_biome_registry_consumers.py` enforces single-source going forward.
- Pipeline pass insertion: read `terrain_pipeline.py:204-247`, find the existing sequence, insert the two passes at correct points, verify via running existing test suite (primary agent only — sub-agents must NOT run pytest).
- Coastline fix: thread `wave_dir` through call chain from `pass_coastline` (which reads `composition_hints["dominant_wave_dir_rad"]`) → `apply_coastal_erosion(..., wave_dir)`. Replace `_hash_noise(x, y, seed)` with `OpenSimplex(seed).noise2(x*scale, y*scale)`.
- Splatmap merge: `auto_assign_terrain_layers` reads from `stack.splatmap_weights_layer` directly. Fail loud (`StackChannelNotPopulatedError`) if missing.

**Patterns to follow:**
- `docs/solutions/architecture-patterns/biome-grammar-features-orphaned-pass-wiring-2026-05-03.md` (pass orphan pattern).
- `veilbreakers_terrain/handlers/terrain_semantics.py` `PassDefinition` overrides discipline.

**Test scenarios:**
- Happy path: registry returns canonical biome ID for each known alias; `BiomeNotFoundError` for unknown.
- Edge: case-insensitive lookup; trim whitespace; unicode normalization for any user-facing strings.
- Edge: alias collision (registering same alias under two canonicals) raises `AliasCollisionError` at import time.
- Error path: pass_water_flow_speed runs against synthetic state with empty `flow_dir` channel — raises explicit `ChannelNotPopulatedError` (not silent zero).
- Error path: coastline pass without `dominant_wave_dir_rad` in hints — uses configured default; logs warning; never silently uses 0.0.
- Integration: full pipeline run on `coastal` biome with synthetic 256² heightmap completes; `tree_instance_points`, `splatmap_weights_layer`, `flow_speed`, `wave_energy` are all populated.
- Regression: U1 harness renders on Coastal and Mountain match committed baselines (no visual regression from migration).

**Verification:**
- `grep -rn 'biome.*=.*\["coastal"\|"coast"' veilbreakers_terrain/handlers/` returns only `terrain_biome_registry.py`.
- `grep -rn '_hash_noise' veilbreakers_terrain/handlers/coastline.py` returns no results (or only a deprecation comment).
- `grep -n 'pass_water_flow_speed\|pass_river_convergence' veilbreakers_terrain/handlers/terrain_pipeline.py` shows both inserted.
- Regression renders for coastal + mountain show no visible differences from pre-U2 baseline (committed in U1).

---

- U3. **Bezier-SDF Shoreline (kill jagged grid edge)**

**Goal:** Replace the grid-mask shoreline with a Bezier-curve-driven signed-distance field that grades the heightfield and wells the water mesh. Shoreline reads as smooth at close camera; underlying mesh is correct, not a smoothing trick.

**Requirements:** R1.

**Dependencies:** U1 (proof renders), U2 (clean coastline pass).

**Files:**
- Create: `veilbreakers_terrain/coastal/shoreline_sdf.py` (`ShorelineSDF` class — `from_bezier_curve(curve_obj, samples_per_segment=64)`, `sample_signed_distance(xy_array)`, `grade_heightfield(z, beach_w, cliff_w, ocean_h)`, `tessellate_polyline()`).
- Create: `veilbreakers_terrain/tests/test_shoreline_sdf.py`
- Create: `docs/solutions/architecture-patterns/bezier-sdf-shoreline-2026-05-04.md`
- Modify: `scripts/create_correct_fullsize_coastal_terrain.py` → graduate to `scripts/coastal_build.py` (or stage rewrite). `heightfield()` consumes ShorelineSDF instead of `shore_x_norm` grid analytic.

**Approach:**
- Tessellate the Bezier curve via `mathutils.geometry.interpolate_bezier` with N=64 per segment to produce a high-density polyline (≈ 1100 points for 18 control points).
- Build a 2D `mathutils.kdtree.KDTree` over polyline points.
- For each terrain vertex (or heightfield grid point), query the nearest polyline point, get the closest segment by checking neighbors, project onto the segment, compute unsigned distance, sign by `cross(tangent, vertex_to_segment_start) > 0`.
- Grade heightfield: `h_new = lerp(h_ocean, h_terrain, smoothstep(-beach_w, +cliff_w, sd))` where `sd > 0` is land. `beach_w = 35m`, `cliff_w = 80m` first pass.
- Water mesh remains a separate plane that overlaps land by `min(beach_w, ocean_overlap)` with alpha fade by `1 - smoothstep(0, ocean_overlap, sd)` so the water/terrain boundary is masked.

**Technical design:**
> *Directional guidance for review, not implementation.*
>
> ```
> # heightfield() pseudo-flow
> z_ocean_bathy = bathymetry_field(xx, yy)              # < 0
> z_inland = inland_relief_field(xx, yy)                 # > 0, includes broad/mid/fine + zones
> sdf = ShorelineSDF.from_bezier_curve(shore_curve_obj)
> sd = sdf.sample_signed_distance(stack(xx, yy))         # negative = sea, positive = land
> blend_t = smoothstep(-beach_w, +cliff_w, sd)
> z = lerp(z_ocean_bathy, z_inland, blend_t)
> # Water mesh (separate)
> water_alpha = 1.0 - smoothstep(0.0, ocean_overlap, sd)
> ```

**Patterns to follow:**
- Inigo Quilez quadratic-Bezier SDF math (research output).
- `mathutils.kdtree.KDTree` usage from existing repo scripts (search `kdtree` in handlers).

**Test scenarios:**
- Happy path: a straight horizontal Bezier curve produces SD that increases linearly perpendicular to the curve.
- Happy path: a curved Bezier produces SD with correct sign on both sides (cross-product test).
- Edge: tessellation density `samples_per_segment=8` vs 64 — 64 produces smoother SD; 8 produces visibly faceted SD; assert max SD-error budget per density.
- Edge: terrain vertex exactly on the curve — SD ≈ 0; sign defined and stable (not NaN).
- Edge: degenerate curve (all control points collinear) — SD computation does not divide by zero; KDTree still builds.
- Error: zero-length curve raises `EmptyCurveError`.
- Integration: with real Coastal Bezier curve, compute SD for full 1025² grid, time < 5 s on dev machine.
- Visual: U1 render at `VB_CORRECT_COASTAL_SHORE_CAMERA` shows smooth shoreline, no jagged grid triangles.
- Visual: close-camera oblique 30° at the bluff/cove transition shows continuous mesh, no stacked-layer artifacts.

**Verification:**
- Render manifest `renders/coastal/u03_bezier_sdf_shoreline/RENDER_MANIFEST.json` shows shore camera + close-oblique have nonblack ratio > 5%.
- Visual diff (PIL pixel compare) of u03 shore render vs u02 baseline shows the jagged-edge region is now smooth (jagged-edge pixel-variance metric drops by >50%).

---

- U4. **Authored Coastal Landform Zones (relief, not flatness)**

**Goal:** Add the five authored landform zones — low beach, rolling backshore, hard headland/bluff, eroded drainage gullies, secondary inland ridge. Player camera reads as relief, not a sheet. Erosion-derived gullies, not the old notched river.

**Requirements:** R2.

**Dependencies:** U2 (coastline real wave_dir/noise), U3 (SD-graded heightfield).

**Files:**
- Create: `veilbreakers_terrain/coastal/landform_zones.py` (`LandformZones`, `low_beach_zone`, `backshore_zone`, `headland_zone`, `gully_field_from_erosion`, `inland_ridge_zone`).
- Create: `veilbreakers_terrain/tests/test_landform_zones.py`
- Modify: `scripts/coastal_build.py` (integrate zones into `heightfield()`).

**Approach:**
- Each zone returns a `(weight, contribution)` pair: weight is a soft-falloff mask (gaussian or smoothstep on SD + slope), contribution is meters added/subtracted from the base SD-graded heightfield.
- Low beach: `weight = exp(-(sd / beach_w)²) * (1 - smoothstep(0, 4, slope))`; flatten to ~1-3 m.
- Backshore: `weight = smoothstep(beach_w, beach_w+30, sd) * (1 - smoothstep(40, 80, sd))`; gentle dunes.
- Headland: anchor 2-4 random Poisson-disk-spaced points on land; raise to 60-90 m via `exp(-r²/60²)` falloff.
- Drainage gullies: derive from `pass_river_convergence` output (now in pipeline post-U2); carve down by 4-8 m along flow lines reaching the shore.
- Inland ridge: `weight = exp(-((sd - ridge_dist) / ridge_w)²)`; contribute 30-50 m elevation.
- Compose: `z_final = z_sdf_graded + Σ weight_i * contribution_i`.

**Patterns to follow:**
- `wave_field` and `smooth_noise` in existing builder.
- `_scatter_engine.poisson_disk_sample` for headland anchors.
- `pass_river_convergence` channel output for gully placement.

**Test scenarios:**
- Happy path: each zone returns weight in `[0,1]` and contribution in meters; zone composition is associative (order-independent).
- Edge: zero headland anchors (Poisson didn't place any) — falls back to single anchor at center-of-mass land area.
- Edge: gully density depends on `pass_river_convergence` — when river_convergence channel is empty, gully field is empty (not a crash).
- Visual: U1 render at `VB_CORRECT_COASTAL_PLAYER_CAMERA` shows visible relief; pixel-variance over the framed area > some threshold (define via baseline).
- Visual: U1 render at oblique 30° on `bluff_close_oblique_30` shows headland silhouette > 40 px tall in the frame.

**Verification:**
- Renders at full_node, shore, player, bluff_close all show relief, not flat sheet.
- Histogram of heightfield Z values has spread > 80 m within the framed 4096m × 4096m tile (vs ≈ 30-40m in pre-U4 builder).

---

- U5. **AAA Terrain PBR Shader (Brucks blend + Ben Golus triplanar + slope/wet/elevation)**

**Goal:** Build the real PBR terrain shader: 4-6 layers (sand, wet sand, grass, moss, rock, cliff) blended via Brucks height-blend, sampled triplanar with per-axis tangent reconstruction, gated by slope/elevation/SD-wetness masks. Replace the vertex-color blend; populate `TerrainTextureLayerStack`.

**Requirements:** R3.

**Dependencies:** U2 (splatmap merged), U3 (SD available for wet-sand band).

**Files:**
- Create: `veilbreakers_terrain/coastal/pbr_terrain_shader.py` (Eevee-Next + GN node-graph builder for the 4-6 layer Brucks/triplanar shader).
- Create: `veilbreakers_terrain/tests/test_brucks_triplanar.py`
- Create: `docs/solutions/best-practices/brucks-triplanar-pbr-2026-05-04.md`
- Modify: `veilbreakers_terrain/handlers/terrain_materials_v2.py` (Brucks blend at line 368 — verify formula matches Andersson; add per-axis tangent reconstruction at triplanar lines 279-).
- Modify: `veilbreakers_terrain/handlers/terrain_texture_layer_stack.py:38` (populate albedo/normal/rough/AO arrays via texture sampling pass).
- Modify: `scripts/coastal_build.py` (replace vertex-color material with PBR builder).
- Add: `assets/textures/coastal/{sand,wet_sand,grass,moss,rock,cliff}/` (downloaded from ambientCG / Poly Haven; document source URLs and licenses in `docs/biome-best-practices/COASTAL.md`).

**Approach:**
- Texture set per layer: `albedo.exr`, `normal_gl.exr` (OpenGL Y+), `roughness.exr`, `ao.exr`, `displacement.exr` (height in meters at 1m UV tile scale). Sourced from ambientCG/Poly Haven.
- Blender shader: build a node group `VB_TerrainBrucksTriplanar`. Inputs: 6 texture sets + 6 weight masks + slope + SD + elevation. Output: BSDF-ready Color, Normal, Roughness, AO.
- Triplanar: 3 sample positions (XY/XZ/YZ); per-axis tangent reconstruction; tightening exponent k=6.
- Brucks: `b = max(h_i + a_i for all i) - depth=0.06`; `w_i = max(h_i + a_i - b, 0)`; renormalize.
- Wet-sand: `wet_factor = smoothstep(-2.0, +2.0, sd_meters) * (1 - smoothstep(0, 8, slope_deg))`; pull sand layer toward `wet_sand` layer in Brucks.
- Slope-driven cliff: `slope_mask = 1 - dot(world_normal, up)`; pipe into `a_cliff` so height keeps stones jutting through grass.
- Elevation grass→moss: `elev_t = smoothstep(60, 180, z_m)`; blend grass to moss via Brucks.
- Color management: ensure all non-color textures have `image.colorspace_settings.name = 'Non-Color'`. Albedo stays sRGB.
- Populate `TerrainTextureLayerStack`: write per-layer arrays so headless export has the same layer set as Blender preview.

**Patterns to follow:**
- `terrain_materials_v2.apply_brucks_blend:368` (existing; verify or correct formula).
- `terrain_materials_v2.triplanar_blend:279` (existing; add per-axis tangent reconstruction).
- Andersson SIGGRAPH 2007 Frostbite formula.
- Ben Golus normal-mapped triplanar reference.

**Test scenarios:**
- Happy path: 4-layer Brucks blend with two equal heights returns equal weights (within float epsilon).
- Happy path: triplanar at world-up normal selects XY plane only; at world-right selects YZ; at 45° between selects equal mix of two.
- Edge: all input layer weights zero — output is fallback gray; does not divide by zero.
- Edge: normal map inputs are pre-converted to OpenGL Y+ (or detected and flipped); test with both Y+ and Y- input maps.
- Edge: very high slope (90°) on a flat tile (no slope) — slope mask is 1.0 only at actual cliffs.
- Visual: U1 render at shore camera shows distinct sand/wet-sand band along the SD=0 line; no visible grid pattern in materials.
- Visual: U1 render at player camera shows slope-driven cliff material on bluffs; smooth transition to grass.
- Visual: triplanar renders at a vertical wall show no diagonal pinstripes.

**Verification:**
- Renders show real-PBR materials (sharp pebbly transitions, normal-mapped detail visible at close camera, no grey wash).
- `TerrainTextureLayerStack.validate()` passes with non-empty albedo/normal/rough/AO arrays.

---

- U6. **Animated Water Shader (Gerstner waves, depth foam, Eevee Next refraction)**

**Goal:** Build the AAA water shader: Gerstner sum-of-sines via Geometry Nodes vertex displacement, animated normals, scene-depth foam at shore contact, Eevee Next Refraction BSDF + Raytraced Transmission with screen+probe fallback, wet-sand contact via SD. Animate over a 60-frame loop.

**Requirements:** R4.

**Dependencies:** U1, U2 (`pass_water_flow_speed` sequenced), U3 (SD for foam mask), U5 (wet-sand band exists in terrain).

**Files:**
- Create: `veilbreakers_terrain/coastal/water_shader_eevee.py` (`build_gerstner_water_geometry_nodes`, `build_water_shader_node_group`, `attach_to_water_plane`, `setup_eevee_raytraced_transmission`).
- Create: `veilbreakers_terrain/tests/test_water_shader_eevee.py`
- Create: `docs/solutions/best-practices/gerstner-eevee-water-2026-05-04.md`
- Modify: `veilbreakers_terrain/sim/foam.py` (export 5-component foam mask via `compute_foam_mask(stack, sd, scene_depth, water_depth, ...)` for the shader to read).
- Modify: `veilbreakers_terrain/handlers/_water_network_ext.py` (deprecate ad-hoc 3-component foam path for Coastal; add deprecation comment).
- Modify: `scripts/coastal_build.py` (use new water shader; subdivide water plane to 256×256 for GN displacement).

**Approach:**
- Water plane: 512×512 subdivision over 4096m × 4096m tile (cell ≈ 8 m). Sized for Nyquist: shortest 20m wavelength ≈ 2.5 samples/wave; 30m ≈ 3.75; 50m ≈ 6.25; 80m ≈ 10.
- Gerstner GN: 4 directional waves; per wave amp 0.6 m / 1.0 m / 0.4 m / 0.3 m; wavelength 80 / 50 / 30 / 20 m; steepness `Q ∈ [0, 1/(w*A*N)]`. Animate via `Scene Time` driver.
- Normals: derived from displacement (analytical or `Set Mesh Normal` 4.5 node).
- Shader: Refraction BSDF + Volume Absorption (Beer-Lambert depth tint) — `IOR=1.33`, `Roughness=0.04`, transmission color from depth attribute.
- Foam: scene-depth difference `1 - smoothstep(0, foam_dist_m=2.0, scene_depth - water_depth)` plus animated curl-noise UV at `noise_scale=0.05`, `time_scale=0.3`. Mask blended with shore SD: foam intensity peaks where `sd ∈ [-3m, +1m]`.
- Wet-sand contact: pass `wet_factor` into terrain shader (already in U5 via SD). Verify the band aligns with foam.
- Eevee Next: `Tracing Method = Screen + Light Probes`, place an irradiance volume + plane reflection probe over the water area.
- Animation loop: 60 frames @ 30fps; render frame 1, 30, 60 for proof.

**Technical design:**
> *Directional guidance for review, not implementation.*
>
> ```
> # GN displacement (per wave i):
> P += (Q*A*Dx*cos(w*dot(D,p) + φ*t),
>       A*sin(w*dot(D,p) + φ*t),
>       Q*A*Dz*cos(w*dot(D,p) + φ*t))
> # Foam:
> foam = (1 - smoothstep(0, 2.0, scene_depth - water_depth))
>      * smoothstep(-3, 1, sd)
>      * curl_noise(uv*0.05 + time*0.3)
> ```

**Patterns to follow:**
- `veilbreakers_terrain/sim/foam.py` 5-component pattern.
- Inigo Quilez ocean shader patterns (research output).
- HDRP Water System for Unity-side parity.

**Test scenarios:**
- Happy path: 4-wave Gerstner sum at known position and time produces expected (P+ΔP) within float epsilon.
- Edge: steepness `Q` exceeds `1/(w*A*N)` — geometry would loop; raise `WaveSteepnessError` (or clamp with warning).
- Edge: scene-depth not available (depth pass disabled) — foam falls back to SD-only mask, logs warning.
- Edge: animation at frame 0 and frame 60 produce different vertex positions (loop is not static).
- Visual: render frame 1, 30, 60 — wave displacement visibly different.
- Visual: shore camera shows foam at SD=0 contact; no foam in deep water.
- Visual: refraction visible at the headland-cove water — light bends through water into bathymetry.

**Verification:**
- Render manifest for u05 includes 3 frames per camera (1, 30, 60); pixel difference frame 1 vs frame 30 > 2% (waves moved).
- Foam mask aligns with U3 SD line; visual diff at SD=0 shows continuous foam band.

---

- U7. **Coastal Lighting / Atmosphere Rig**

**Goal:** Replace the test-render lighting with a coastal lighting rig: sun at appropriate elevation, sky color, horizon fog, coastal mist volumetric, color grade preset, time-of-day. Scene reads as game environment.

**Requirements:** R8.

**Dependencies:** U1, U5 (terrain materials work under real lighting), U6 (water shader respects light direction).

**Files:**
- Create: `veilbreakers_terrain/coastal/lighting_atmosphere.py` (`build_coastal_lighting_rig`, `add_volumetric_mist`, `setup_color_grade`, `place_irradiance_volume`).
- Create: `veilbreakers_terrain/tests/test_lighting_atmosphere.py`
- Modify: `scripts/coastal_build.py` (replace `add_lighting_and_cameras` lighting block with the new rig).

**Approach:**
- Sun: Nishita sky world-shader at low-mid elevation (40-60° altitude), warm color (5800-6200 K).
- Area fill: ambient sky color, low intensity.
- Volumetric mist: world volume Principled Volume with density 0.002, anisotropy 0.4, color (0.85, 0.90, 0.93). Layered density gradient: dense at sea level, thinning above 50 m.
- Horizon fog: distance-based exponential fog in compositor or world volume.
- Color grade: filmic-compatible preset; mid-gray at 0.18; subtle teal-shadow / orange-highlight split.
- Irradiance volume + plane reflection probe over water area (Eevee Next requires bake).
- Three time-of-day presets for variety: `morning`, `overcast_noon`, `golden_hour`. Default to overcast_noon.

**Patterns to follow:**
- Existing `add_lighting_and_cameras` in current builder script.
- Blender 4.5 Volume Light Probe usage (research output).

**Test scenarios:**
- Happy path: build_coastal_lighting_rig produces 1 sun + 1 area fill + 1 world volume + 1 irradiance volume + 1 reflection probe.
- Edge: irradiance volume cache stale — bake invocation forced via `bpy.ops.scene.light_cache_bake`.
- Edge: TOD preset name not in {morning, overcast_noon, golden_hour} — raises `UnknownTODPreset`.
- Visual: render at full_node camera shows readable horizon (not blown out), atmospheric perspective on distant mountains.
- Visual: render at shore camera shows coastal mist density visible, sun-direction shadows on bluffs.

**Verification:**
- Renders read as game environment (not test render); subjective gate, but committed images should show fog, sun direction, atmosphere.

---

- U8. **Vegetation Stack Install (L-Py + Modular Tree GoodPie + OpenScatter)**

**Goal:** Install and verify the three foliage tools end-to-end. Generate 4 dark-fantasy tree variants, 4 grass species, 2 shrub species — each with LOD0/LOD1 and a manifest entry. Confirm headless invocation works.

**Requirements:** R6.

**Dependencies:** U1 (proof renders), U2 (canonical biome registry — vegetation system reads from it).

**Files:**
- Create: `veilbreakers_terrain/coastal/vegetation_pipeline.py` (`generate_tree_lpy`, `generate_tree_modular`, `scatter_via_openscatter`, `bake_lods`).
- Create: `veilbreakers_terrain/tests/test_vegetation_pipeline.py`
- Create: `assets/lpy/{twisted_oak,dead_pine,mangrove,gnarled_hawthorn}.lpy` (L-Py grammar files).
- Create: `assets/modular_tree/{coastal_oak,coastal_pine}.json` (Modular Tree node-graph exports).
- Create: `veilbreakers_terrain/coastal/species_manifest.json` (locked species manifest with LOD paths).
- Modify: `pyproject.toml` (document conda env + dependency comment; do not pip-install L-Py).
- Add: `scripts/install_vegetation_stack.ps1` (Windows install script with conda-forge L-Py + Modular Tree zip + OpenScatter zip).

**Approach:**
- L-Py via conda: `mamba create -n vb_lpy -c openalea3 -c conda-forge openalea.plantgl openalea.lpy openalea.mtg python=3.11`.
- Author 4 .lpy grammars for dark-fantasy coastal trees.
- Run L-Py headless via subprocess from main script: `python -m openalea.lpy run twisted_oak.lpy --output trees/twisted_oak.obj --seed N`.
- Import OBJ in Blender via `bpy.ops.wm.obj_import`. Apply leaf instancing via Geometry Nodes (already exported separately).
- Modular Tree: install Blender addon zip, register, invoke via `bpy.ops.mtree.execute_tree()` with each saved node-graph.
- OpenScatter: install Blender addon zip, register, expose Density Mask layer with `Image Texture` → `UV: TerrainSplat`.
- LOD bake: decimate each tree to LOD0 ≤ 5k tris, LOD1 ≤ 1k tris; export glTF.
- Manifest: each species has `{name, lpy_or_modular, source_path, lod0_glb, lod1_glb, biome_mask: ["coastal"], wind_capable: bool}`.

**Patterns to follow:**
- `veilbreakers_terrain/handlers/terrain_foliage_catalog.SpeciesSpec` schema.
- Existing scatter integration in `environment_scatter.handle_scatter_vegetation`.

**Test scenarios:**
- Happy path: install script completes with conda env present and Blender addons registered.
- Happy path: each species generates an OBJ/GLB without errors; LOD0 and LOD1 written.
- Edge: conda env missing — install script bootstraps it.
- Edge: subprocess L-Py invocation timeout > 60s — log + fail unit, do not hang.
- Integration: scatter tests in `test_environment_scatter_handlers.py` produce non-zero placement counts on `coastal` biome (post-U2 registry fix).
- Visual: U1 render of "species_swatch" scene (grid of 10 species side-by-side) shows distinct silhouettes for each.

**Verification:**
- `assets/lpy/`, `assets/modular_tree/`, `output/coastal-staging/species/` populated; manifest has 10 entries with valid LOD paths.
- Render `renders/coastal/u08_vegetation_install/species_swatch.png` shows all 10 species placed.

---

- U9. **Wind Animation (Pivot Painter 2.0 bake + Geometry-Nodes preview shader)**

**Goal:** Add Pivot Painter 2.0 vertex data to grass/tree variants. Author Blender geometry-node wind shader for live preview. Author Unity-compatible Shader Graph for round-trip. Wind survives Blender → Unity bake.

**Requirements:** R6.

**Dependencies:** U8 (species generated).

**Files:**
- Create: `veilbreakers_terrain/coastal/wind_pivot_painter.py` (`bake_pivot_painter`, `build_wind_geometry_nodes`, `bake_unity_wind_shader_graph`).
- Create: `veilbreakers_terrain/tests/test_wind_pivot_painter.py`
- Create: `docs/solutions/best-practices/pivot-painter-wind-coastal-2026-05-04.md`
- Add: `assets/wind/pivot_painter_export_template.fbx` (Unity-side import reference).

**Approach:**
- Use Modular Tree's built-in Pivot Painter 2.0 bake operator for trees (writes 16-bit EXR + UV2 channel).
- For L-Py-generated trees, author a custom bake: assign instance-id to UV2.x, hierarchy-level to UV2.y, write pivot-position into a vertex-color RGB attribute.
- Geometry-Nodes preview wind: per-instance offset = `sin(time * freq + instance_id * phase) * amp * pivot_axis`. Strength scales by `hierarchy_level`.
- Unity Shader Graph: build matching graph; sample EXR for pivot data; expose Wind Vector + Wind Strength.
- Test by rendering Blender frame 1 / 30 / 60 of a populated coastal tile and confirming foliage motion.

**Patterns to follow:**
- Modular Tree built-in Pivot Painter operator.
- Epic Pivot Painter 2.0 reference (research output).

**Test scenarios:**
- Happy path: bake assigns UV2 channel and EXR; verify EXR is 16-bit and has correct dimensions.
- Edge: tree with > 30k vertices — Pivot Painter limit; raises `PivotPainterCapacityError`.
- Edge: wind strength 0 — vertex positions match base rest position (within epsilon).
- Visual: U1 render of populated tile at frame 1 vs frame 30 — grass and tree leaves moved.

**Verification:**
- Render manifest for u09 has frame 1 + frame 30 + frame 60 per camera; pixel diff > 1% in foliage areas.

---

- U10. **Coastal Hero Props (Hunyuan3D-2.1 — driftwood, boulders, reeds, shrubs, foam decals)**

**Goal:** Generate the Coastal hero prop set via Hunyuan3D-2.1: 3 driftwood logs, 4 coastal boulders, 3 reed clumps, 2 low shrubs, 5 foam decals. LOD0/LOD1 + manifest. Wire scatter via OpenScatter using density fields, slope masks, shoreline SD.

**Requirements:** R7.

**Dependencies:** U8 (vegetation pipeline + scatter), U3 (SD for foam decals + driftwood placement near shore).

**Files:**
- Create: `veilbreakers_terrain/coastal/props_hunyuan.py` (`generate_hero_prop`, `decimate_for_lod`, `build_prop_manifest`).
- Create: `veilbreakers_terrain/tests/test_props_hunyuan.py`
- Create: `assets/props/coastal/{driftwood_*, boulder_*, reeds_*, shrub_*, foam_decal_*}/` (generated GLBs + LODs).
- Create: `output/coastal-staging/props/PROMPTS.md` (locked Hunyuan prompts).
- Modify: `veilbreakers_terrain/providers/hunyuan3d2_provider.py` (verify path + WinPortable invocation; ensure `pipeline.float()` not `.half()` for stability).

**Approach:**
- Generate via Hunyuan3D-2.1 WinPortable (`Hunyuan3DDiTFlowMatchingPipeline` shape + `Hunyuan3DPaintPipeline` PBR texture).
- Each prop: image prompt → shape → PBR texture (albedo + MRO) → GLB.
- Decimate to LOD0 ≤ 20k tris, LOD1 ≤ 5k tris.
- Manifest: `{name, source_prompt, lod0_glb, lod1_glb, biome_mask, scatter_density_mask, placement_rules: {min_slope, max_slope, sd_range_m, max_per_chunk}}`.
- Scatter rules:
  - Driftwood: place along shore SD ∈ [-2, +5] m, slope < 5°, max_per_chunk 4.
  - Coastal boulders: SD ∈ [+2, +50] m, slope > 25°, max_per_chunk 8.
  - Reed clumps: SD ∈ [-1, +3] m, slope < 3°, max_per_chunk 12.
  - Shrubs: SD ∈ [+5, +200] m, max_per_chunk 6.
  - Foam decals: SD ∈ [-3, +0] m, plane-projected.

**Patterns to follow:**
- `veilbreakers_terrain/providers/hunyuan3d2_provider.py` (existing).
- `veilbreakers_terrain/handlers/terrain_foliage_catalog.AssetManifest`.

**Test scenarios:**
- Happy path: prompts produce GLBs with valid topology (no orphan vertices); LOD decimation succeeds.
- Edge: VRAM exhausted — falls back to `--low_vram_mode` (12 GB); logs the fallback.
- Edge: NaN textures on RTX 30-series — uses `pipeline.float()` automatically.
- Edge: prop decimation produces < 100 tris — flag as failed asset; do not write to manifest.
- Visual: render of populated tile shows driftwood, boulders, reeds, shrubs visible at appropriate camera scales.

**Verification:**
- 17 GLBs in `assets/props/coastal/`; manifest has 17 entries.
- U1 render of populated coastal tile at shore camera shows driftwood + boulders at appropriate scale (a 2 m human cylinder for reference is in the scene).

---

- U11. **Adaptive Mesh Strategy (curve-conforming shoreline strip + cliff hero meshes)**

**Goal:** Add a curve-conforming high-resolution shoreline strip welded into terrain. Add separate hero cliff meshes where bluffs need real silhouette. No visible stacked-layer edges at close camera.

**Requirements:** R5.

**Dependencies:** U3 (Bezier-SDF + curve), U4 (zones), U5 (PBR materials so the strip can share the shader).

**Files:**
- Create: `veilbreakers_terrain/coastal/adaptive_mesh.py` (`build_shoreline_strip_mesh`, `weld_to_terrain`, `extract_cliff_hero_meshes`).
- Create: `veilbreakers_terrain/tests/test_adaptive_mesh.py`
- Modify: `scripts/coastal_build.py` (call adaptive_mesh post-terrain-build).

**Approach:**
- Shoreline strip: along the Bezier curve, generate a 4-cell-wide strip at 1m cell resolution (4 m wide × ≈ 4096 m long ≈ 16384 cells). Each row sampled from the curve normal direction.
- Weld: vertices along the strip's land-side edge are snapped to the nearest terrain grid vertex (within tolerance ε=0.5 m); vertices along the seaward edge dive into bathymetry. Bridge triangles fill the gap.
- Cliff hero meshes: for each headland zone with elevation > 60 m and slope > 50°, extract a higher-resolution box-bounded mesh (bake to ≤ 30k tris each), shade-smooth, weld to terrain.
- Both inherit U5 PBR shader; layer weights authored locally.

**Patterns to follow:**
- Existing `make_strip_mesh` in current builder.
- Blender weld modifier + remesh patterns.

**Test scenarios:**
- Happy path: strip vertices match terrain grid vertices at land-side within ε; no T-junctions.
- Edge: a cove tighter than the strip width — strip self-intersects; detected and reported, fallback to narrower width.
- Edge: no headlands above threshold — cliff hero meshes empty list (not a crash).
- Visual: U1 render at oblique 30° on shore_close shows continuous mesh at the strip-terrain join; no T-junction artifacts.
- Visual: cliff hero meshes visible at bluff_close render with detail not present in base terrain.

**Verification:**
- Strip + cliff meshes welded; close-camera renders show no visible seams.
- Pre/post visual diff: edge-fragmentation metric (count of pixels showing high-frequency triangle edges along shore) drops > 60%.

---

- U12. **Unity Export Bundle + Round-Trip Verification**

**Goal:** Export the Coastal node to Unity 2023: RAW16 heightmap, splatmap weights, water JSON, shoreline mask, material manifest, mesh GLBs, vegetation prototypes with wind data, prop manifest. Run `veilbreakers-unity-export-check`. Render Unity-side scene at matching cameras; commit Blender + Unity side-by-side.

**Requirements:** R10, R11.

**Dependencies:** U2 (splatmap merged), U5 (terrain layers), U6 (water JSON), U8/U9 (vegetation + wind), U10 (props), U11 (mesh).

**Files:**
- Create: `scripts/coastal_unity_export.py` (driver).
- Create: `veilbreakers_terrain/tests/test_unity_coastal_roundtrip.py` (integration).
- Create: `docs/solutions/best-practices/unity-coastal-roundtrip-2026-05-04.md`
- Output: `output/unity-export/coastal/CoastalGameNode_4096m/{heightmap.raw, splatmap.png, water.json, shoreline.png, material_manifest.json, meshes/*.glb, vegetation_prototypes.json, props/*.glb, props_manifest.json}`.

**Approach:**
- Heightmap: write `1025 × 1025 × uint16 little-endian` (Unity import bit-depth=16, byte-order=Windows). Rename to `.raw` (Unity won't read `.r16`).
- Splatmap: alphamapResolution `1024`; write `float[H,W,Layer]` from `stack.splatmap_weights_layer` directly (no re-derive). Each cell weights sum to 1.0.
- Water JSON: surface elevation, depth field, flow_speed (now non-zero post-U2), shoreline_mask path, wave parameters from U6.
- Shoreline mask: 8-bit grayscale PNG, white = land, black = ocean, derived from U3 SD.
- Mesh GLBs: terrain + shoreline strip + cliff hero meshes via `bpy.ops.export_scene.gltf` with `export_apply=True`.
- Vegetation prototypes: per species `{prefab_glb, lod0, lod1, wind_capable, wind_data_uv2_path}`.
- Prop manifest: per prop `{prefab_glb, lod0, lod1, scatter_density_mask, placement_rules}`.
- Run `veilbreakers-unity-export-check` (existing repo skill) — must pass.
- Unity scene: open `Assets/CoastalGameNode_4096m.unity` (via Unity MCP if available, else manual instructions in best-practices doc); place TerrainData, water surface, foliage prototypes, props; render Unity-side from matching camera positions.

**Patterns to follow:**
- `veilbreakers_terrain/handlers/terrain_unity_export.py:1853` `export_unity_manifest`.
- `terrain_unity_export_contracts.UnityExportContract`.

**Test scenarios:**
- Happy path: export bundle is complete, all files present, manifest validates.
- Edge: heightmap resolution not `2^k+1` — raises `HeightmapResolutionError`.
- Edge: splatmap weights don't sum to 1.0 within ε — re-normalize or raise.
- Edge: water flow_speed channel still zero — raises `WaterFlowSpeedZeroError` (catches U2 regression).
- Edge: a vegetation prototype missing LOD0 GLB — raises and fails check.
- Integration: round-trip on synthetic coastal node passes `veilbreakers-unity-export-check`.
- Visual: Blender render and Unity render at matching camera positions show < 10% pixel difference (post-color-grade).

**Verification:**
- Bundle in `output/unity-export/coastal/`; check passes.
- `renders/coastal/u12_unity_export_proof/{blender_full_node.png, unity_full_node.png, blender_shore.png, unity_shore.png, blender_player.png, unity_player.png}` committed.
- Side-by-side composite at `renders/coastal/u12_unity_export_proof/SIDE_BY_SIDE.png`.

---

- U13. **Coastal Best-Practices Doc + Carryover Template + ce-compound Captures**

**Goal:** Publish the locked Coastal best-practices doc and the carryover template for next biome. Capture every gap surfaced by ce-learnings-researcher as a `docs/solutions/` entry.

**Requirements:** R12.

**Dependencies:** U1-U12 all landed.

**Files:**
- Create: `docs/biome-best-practices/COASTAL.md`
- Create: `docs/biome-best-practices/_TEMPLATE_BIOME_PERFECTION.md`
- Verify present: `docs/solutions/architecture-patterns/single-biome-registry-2026-05-04.md` (U2)
- Verify present: `docs/solutions/architecture-patterns/bezier-sdf-shoreline-2026-05-04.md` (U3)
- Verify present: `docs/solutions/architecture-patterns/splatmap-headless-blender-merge-2026-05-04.md` (U2)
- Verify present: `docs/solutions/architecture-patterns/pass-orphan-sequencing-2026-05-04.md` (U2)
- Verify present: `docs/solutions/best-practices/visual-render-camera-proof-2026-05-04.md` (U1)
- Verify present: `docs/solutions/best-practices/brucks-triplanar-pbr-2026-05-04.md` (U5)
- Verify present: `docs/solutions/best-practices/gerstner-eevee-water-2026-05-04.md` (U6)
- Verify present: `docs/solutions/best-practices/pivot-painter-wind-coastal-2026-05-04.md` (U9)
- Verify present: `docs/solutions/best-practices/unity-coastal-roundtrip-2026-05-04.md` (U12)

**Approach:**
- COASTAL.md sections: Overview · Locked Decisions (vegetation stack, asset provider, texture sources, render workflow) · Mesh Strategy · Shoreline (Bezier-SDF) · Landform Zones · Materials (Brucks/triplanar) · Water Shader · Lighting · Vegetation (species, wind) · Props (manifest) · Unity Round-Trip · Visual Reference (committed PNGs) · AAA Comparison (side-by-side with real-world Coastal references).
- Template: parameterizes the same sections so Mountain/Grassland/etc inherit the structure.
- Run `ce-compound` for each gap: capture the Bezier-SDF technique, the wet-sand band shader, Pivot Painter wind for Coastal foliage, Unity round-trip protocol, and the `visual_render_camera_proof` pattern.

**Test scenarios:**
- N/A — documentation unit. Test expectation: none — pure documentation.

**Verification:**
- `docs/biome-best-practices/COASTAL.md` exists with all locked decisions; all 9 docs/solutions/ entries exist; template exists and references COASTAL.md.

---

## System-Wide Impact

- **Interaction graph:** U2 changes the shape of the biome-name vocabulary that propagates to every consumer in the pipeline (vegetation_system, _biome_grammar, foliage_catalog, environment_scatter, terrain_unity_export). U2 also adds two passes to the canonical pipeline order. Confirm via U1 regression renders on `mountain` (the biome U2 most likely affects beyond Coastal).
- **Error propagation:** Render harness assertion failures (U1) bubble to per-unit driver scripts; non-zero exit blocks PR merge. Unity export validation failures (U12) raise typed errors with channel names. Splatmap/water/scatter-channel-not-populated failures raise loud and early.
- **State lifecycle risks:** Modular Tree binary load + bpy state — re-loading on multiple invocations is known to leak; budget memory recycle between species generation. Hunyuan3D pipeline VRAM not released between calls — use `pipeline = None; torch.cuda.empty_cache()` after each prop.
- **API surface parity:** `terrain_unity_export.export_unity_manifest` adds wind_capable + scatter_density_mask fields to the prototype schema (additive). Existing consumers are not broken.
- **Integration coverage:** U2 + U6 + U12 together exercise the full pipeline → export → Unity round-trip. Cross-layer coverage in `test_unity_coastal_roundtrip.py`.
- **Unchanged invariants:** `_DELTA_CHANNELS` does NOT gain `pool_deepening_delta`; `composition_hints["erosion_profile"]` defaults are read from real config not hardcoded; legacy `water_surface` channel is deprecated but reads still raise loud, not silent zero.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Hunyuan3D-2.1 VRAM exhaustion on dev hardware (16-24GB) | Use `--low_vram_mode` (12 GB); use `Hunyuan3D-2mini` (5 GB shape / 6 GB total) as fallback for non-hero props. Document in U10. |
| Modular Tree v5.5.1 binary not loading on Blender 4.5 (binary compiled for 4.3) | Pin Blender 4.5 LTS; if binary fails, fall back to L-Py-only tree set; document fallback in U8. |
| L-Py conda install on Windows 11 fails (Qt OpenGL stack) | Don't pip-install; use `mamba` with `openalea3` channel. If still fails, run L-Py in WSL2 subprocess and pipe OBJ through. |
| `mcp__blender__.get_viewport_screenshot` regresses or is needed by another caller | U1 builds the bypass; do not depend on viewport screenshot anywhere. |
| Visual quality is subjective; "AAA" target is not pixel-defined | Use real Frostbite/RDR2/KCD2 reference imagery; commit side-by-side composites; accept user signoff before moving to Mountain biome. |
| Squash-merge per-unit cadence creates noisy PR queue | Acceptable; each PR is small and reviewable, and CI enforces required checks. |
| Pyright strictness on new `coastal/` package | Type-annotate all new modules from the start; run `pyright` locally before PR. |
| Unity 2023 HDRP Water System not available in URP | If project is URP, use Crest or Stylized Water 2 asset (paid or community). Confirm renderer choice in U12. |
| Bezier-SDF compute cost on 1025² grid > 5s (threshold) | Use KDTree query; batch via numpy vectorization; cache the SD per build. Acceptable budget: < 10s. |
| Pivot Painter EXR data lost in glTF export | Use FBX for vegetation prototypes if glTF mangles UV2; document in U9. |
| Determinism CI is in-process theatre (audit P0-I1) — does not catch RNG leakage in new modules | Use explicit RNG seeds in every new module; do not rely on default `random` state. Document in tests. |
| Splatmap merge breaks an existing biome's preview | U1 regression renders on all 6 biomes after U2; revert if any visible regression. |
| Per-unit PR cadence + required CI = slow throughput on 13-unit plan | Pipeline checks run < 10 min typically; 13 PRs ≈ 2-3 days of CI time. Acceptable. |

---

## Documentation / Operational Notes

- Each unit's PR description must include: render PNGs (linked), test status, validation summary, before/after comparison if visible.
- `docs/biome-best-practices/COASTAL.md` is the human-readable handoff for the next biome. The carryover template is the structural blueprint.
- `ce-compound` runs at U13 for every gap surfaced. Future agents searching `docs/solutions/` for these topics find captured patterns.
- Render artifacts (`renders/coastal/`) are committed to git. They are display-quality PNGs, not large EXRs. Each ≤ 2 MB; total budget ≈ 50-100 MB across all units.
- Memory update: after U13, update `MEMORY.md` to add a "Coastal AAA perfected" entry with the lock-date and signoff state.
- Branch protocol: each unit either lands as a separate squash-merge PR into `main`, or as multi-unit batches when units are tightly coupled (e.g., U8+U9 vegetation + wind together).

---

## Sources & References

- **Origin document**: [docs/aaa-audit/BIOME_VISUAL_HONING_SESSION_HANDOFF_2026_05_05.md](../aaa-audit/BIOME_VISUAL_HONING_SESSION_HANDOFF_2026_05_05.md)
- Master implementation guide: [docs/AAA_MASTER_IMPLEMENTATION_GUIDE_2026_04_27.md](../AAA_MASTER_IMPLEMENTATION_GUIDE_2026_04_27.md)
- Latest audit: [docs/aaa-audit/AAA_MASTER_AUDIT_2026_05_03.md](../aaa-audit/AAA_MASTER_AUDIT_2026_05_03.md)
- Coastline deep-dive: [docs/aaa-audit/deep_dive_2026_04_16/wave2/B2_water_waterfalls_coastline.md](../aaa-audit/deep_dive_2026_04_16/wave2/B2_water_waterfalls_coastline.md)
- Water systems deep-dive: [docs/aaa-audit/deep_dive_2026_04_27/A2_water_systems.md](../aaa-audit/deep_dive_2026_04_27/A2_water_systems.md)
- Pass orphan batch: [docs/aaa-audit/batch15_2026_05_04/MASTER_AUDIT_BATCH15.md](../aaa-audit/batch15_2026_05_04/MASTER_AUDIT_BATCH15.md)
- Tool decisions: [docs/VEGETATION_TOOL_DECISION_2026_05_03.md](../VEGETATION_TOOL_DECISION_2026_05_03.md), [docs/WATER_TOOL_DECISION_2026_05_03.md](../WATER_TOOL_DECISION_2026_05_03.md), [docs/SCATTER_TOOL_RESEARCH_2026_05_03.md](../SCATTER_TOOL_RESEARCH_2026_05_03.md)
- External: Blender 4.5 release notes; Andersson SIGGRAPH 2007 Frostbite; Ben Golus normal-mapped triplanar; Inigo Quilez 2D distance functions; Pivot Painter 2.0 (Epic); L-Py docs; Modular Tree v5.5.1 (GoodPie fork); OpenScatter v1.0.7; Tencent Hunyuan3D-2.1; Unity 2023 TerrainData + HDRP Water System.
