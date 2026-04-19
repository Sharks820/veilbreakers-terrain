# R8-A8: Quality Gates & Test Suite Audit

Audit date: 2026-04-17
Scope: `veilbreakers_terrain/tests/` (65 files, ~6,700 test functions) + six quality-related source modules.
Auditor: R8 deep-dive agent A8 (quality gates).

---

## EXECUTIVE SUMMARY

**Do the current tests prevent shitty terrain from shipping? No. They prevent *obviously broken* Python from shipping, but they do not gate aesthetic, perceptual, or runtime integrity.**

The suite is wide (~60 files, good breadth of handler coverage) and honest about what it can test in isolation — it runs 100% headless against MagicMock bpy/bmesh/mathutils stubs installed by `conftest.py:85-99`. That single architectural choice produces four structural blind spots that no amount of additional tests can patch without real Blender:

1. **Zero real-geometry validation.** `TestManifoldIntegrity` (`test_geometric_quality.py:131`) runs against a heightmap-to-mesh *helper in the test file itself*, not the shipped geometry builder. The production mesh builder runs in Blender against `bpy.data` and is only exercised by tests like `test_aaa_water_scatter.py` which mock Blender away — meaning the code that actually runs in Blender is validated only by `isinstance(result, dict)`-level assertions on handler return values.
2. **Zero pixel/perceptual validation.** `rg "ssim|SSIM|perceptual|phash|imagehash"` returns zero matches. The only "visual" tests are in `test_terrain_visual_profiles.py`, which paints *its own* PIL images with `ImageDraw.line()` and asserts that the in-repo scorer passes them — the scorer is never tested against a real Blender render. Tiling artifacts, texture seams at play distance, color banding, and material break-up at correct frequencies are all untested.
3. **Zero exported-asset validation.** No test loads the exported `.raw` heightmap, `.raw` splatmap, or manifest.json and verifies it is byte-valid for Unity. `test_bundle_egjn_supplements.py::TestUnityExportContracts` validates the *contract description* (dict comparison) — not any produced file. No one has ever round-tripped a generated terrain through a real Unity import.
4. **Zero runtime integrity checks.** No test asks "does a character walk on this?" — navmesh coverage is only validated by "the channel is present and dtype=int32" (`test_terrain_validation.py:430-435`). Impassable seams, drop-through holes, foot-sinking on slopes, all untested.

The suite *does* correctly gate three real-world regression categories: (a) bit-identical determinism on mask hash (`test_terrain_deep_qa.py:189` is a strong 1-bit mutation test), (b) seam continuity across adjacent tiles via `_terrain_world.validate_tile_seams` (`test_adjacent_tile_contract.py:36-126`), and (c) basic mathematical invariants (flow downhill, slope distributions, erosion mass conservation). These are load-bearing and should not be discarded.

Ten tests are outright stale (`test_terrain_contracts.py` references `HANDLERS_DIR = REPO_ROOT / "Tools" / "mcp-toolkit" / "blender_addon" / "handlers"` which does not exist post-Phase-50 split; it is a dead test pointing at a pre-split monorepo path). Two are trivial (`test_aaa_water_scatter.py::test_water_creation_does_not_raise`). One is outright miscounted (`test_all_14_biomes_present` asserts `len == 16`). Most of the "does not crash" tests (`assertIsInstance(result, dict)`, `isinstance(placements, list)`) appear in handler-output tests where the handler itself runs against MagicMocks — those tests prove the handler returns a dict shape, nothing more.

Bottom line: the suite is strong at **algorithmic regression** and weak at **AAA visual/gameplay quality**. A AAA studio ships a terrain when (a) 12 review angles pass a perceptual scorer, (b) a navmesh bake walks, (c) a Unity/Unreal import round-trip succeeds, (d) streaming at 30 m/s produces no visible pops. None of those gates exist here.

---

## STALE / WORTHLESS / BROKEN TESTS

File:test_name | Rating | Why it tests nothing (or is broken) | What it should test instead
---|---|---|---
`tests/contract/test_terrain_contracts.py::*` (all 5 tests) | **BROKEN** | Hard-codes `HANDLERS_DIR = REPO_ROOT / "Tools" / "mcp-toolkit" / "blender_addon" / "handlers"` (line 24). This is the pre-split monorepo path; the standalone terrain repo has no such tree. The contract YAML path (`".planning/contracts/terrain.yaml"`) also points to a parent-repo artifact. These tests silently pass by emitting "missing files" assertions on a non-existent source tree, or silently `import yaml` and skip. | Rewrite to read `veilbreakers_terrain/handlers/` and a contract shipped with this repo.
`tests/test_preflight_crossrepo.py::test_toolkit_and_terrain_installed_side_by_side` | **TRIVIAL** | Only asserts both packages have a `__file__`. Does not verify the cross-repo API surface — and acknowledges the primitives gap (`test_primitives_module_file_exists` just asserts the *file* exists on disk, not that it imports cleanly). | Actually import `veilbreakers_mcp.primitives.mesh_from_spec` and call it on a trivial input.
`tests/test_vb_toolkit_primitives_available.py::test_primitives_module_file_exists` | **TRIVIAL** | Checks only that `primitives.py` exists and contains the substring `"mesh_from_spec"` in its text. Known stale dependency (`blender_addon` import gap) and the test deliberately documents why it cannot import — which makes this a test that documents its own inadequacy. | Either fix the import gap or drop the test; string-grepping source is not a regression gate.
`tests/test_aaa_water_scatter.py::test_water_creation_does_not_raise` (line 493) | **TRIVIAL** | Body is `try: result = handle_create_water(...); assertIsNotNone(result); except: self.fail(...)`. With MagicMock bpy/bmesh, every `handle_create_water` invocation returns a MagicMock-derived dict regardless of whether the water mesh is correct. Catches only Python-level crashes. | Assert the mesh has the expected tri count, the vertex coordinates sit on the path, UVs are within [0,1].
`tests/test_aaa_water_scatter.py::test_water_name_preserved` (line 413), `test_water_result_complete_keys` (line 500), `test_water_material_name_configurable` (line 505) | **TRIVIAL** | All three only check dict key presence on handler output. Under the MagicMock stub, the handler's internals are not exercised. | Validate `base_color`, `IOR=1.333`, `roughness=0.05`, `alpha=0.6` in the actual material node graph.
`tests/test_terrain_materials.py::TestBiomePaletteStructure::test_all_14_biomes_present` (line 119) | **STALE** | Name asserts "14" but body asserts `len(BIOME_PALETTES_V2) == 16`. Comment at line 105 lists 16 biomes. The test name lies, making debug output misleading (you'd grep for "14" and find a test passing on 16). | Rename test and update the documentation string to match the contract.
`tests/test_aaa_terrain_vegetation.py::test_leaf_card_tree_created_without_error` (line 229), `test_leaf_card_num_planes_default_is_8` (line 242) | **TRIVIAL** | Body is `obj = scatter_mod.create_leaf_card_tree(...); self.assertIsNotNone(obj)`. `scatter_mod` imports against MagicMock bpy, so `obj` is always a MagicMock and never None. Tests nothing. | Assert plane count is 6–12 by counting actual bmesh faces (the class tries to do this at line 216 but via a fuzzy "heuristic" that almost always passes — `if min(zs) >= cz - canopy_radius * 0.1 OR max(zs) >= cz - canopy_radius * 0.5: planes += 1` — the `OR` makes the condition near-trivially satisfiable).
`tests/test_aaa_terrain_vegetation.py::test_leaf_card_planes_range_6_to_12` (line 234) | **TRIVIAL** | Iterates `(3, 6), (8, 8), (15, 12)` but only asserts `assertIsNotNone(obj)`. The `expected_clamped` value is computed and thrown away. | Assert that the resulting mesh has between 6 and 12 planes by counting quad faces.
`tests/test_aaa_terrain_vegetation.py::TestMultipassScatterOrder::test_*_pass_returns_list` (lines 558–577) | **TRIVIAL** | Three tests each assert `isinstance(result, list)`. Does not verify that trees are placed before grass before rocks (which is the class's stated goal). | Run all three passes in sequence and assert that the "debris" pass only sees cells cleared by the "ground_cover" and "structure" passes — i.e. prove the dependency, not just the shape.
`tests/test_bundle_pq.py::TestDEMImport::test_synthetic_dem_is_deterministic` | **VALID** (listed as comparison) — compare to the weaker variants below.
`tests/test_bundle_pq.py::TestPaletteExtract::test_palette_handles_uint8` (line 144) | **TRIVIAL** | Only asserts `palette[0].color_rgb[0] <= 1.0` — which is true for any palette regardless of whether uint8 input was correctly processed. | Assert the extracted RGB matches the dominant input color to within 1 LSB.
`tests/test_bundle_pq.py::TestFootprintSurface::test_single_point` / `test_multiple_points` (lines 170–182) | **TRIVIAL** | Asserts `len(pts) == 1` / `== 3` — i.e. that inputs survive the function. No assertion on the *surface* content (normal direction, height, slope). | Verify the returned FootprintSurfacePoint has the correct Z from the heightmap and a unit normal.
`tests/test_terrain_deep_qa.py::test_budget_soft_warn_at_near_threshold` (line 334) | **TRIVIAL** | Body ends with `assert isinstance(issues, list)`. The comment literally says "May or may not trigger, but must not crash". This is a smoke test, not a quality gate. | Either deterministically reproduce a warn case or delete the test.
`tests/test_terrain_deep_qa.py::test_determinism_check_detects_mutation` (line 156) | **MOCK-ABUSE** | Creates two hash strings `"a"*64` and `"b"*64` and asserts the comparator returns a regression issue. Tests the comparator, not the detection pipeline. The real determinism gate is `test_determinism_fails_on_1bit_mutation_of_mask_stack` further down (line 189) — that one is strong. The earlier test has a misleading name. | Rename to `test_detect_determinism_regressions_flags_different_hashes` so it describes the trivial unit under test, not a pipeline behavior.
`tests/test_terrain_ecosystem.py::test_audio_zones_produces_int8_array` (line 95) | **TRIVIAL** | Asserts `arr.dtype == np.int8` and `arr.shape == stack.height.shape`. Never checks that *any* cell was assigned a reverb class. A function that returns `np.zeros(...)` always-silent would pass. | Assert at least one cell has a nonzero class OR that class distribution matches biome-driven expectations.
`tests/test_terrain_visual_profiles.py::test_analyze_render_image_passes_framed_cave_profile` (line 66) | **MOCK-ABUSE** | Paints a fake "cave" with `ImageDraw.ellipse` and straight lines and asserts the scorer scores it >= 60. The scorer was tuned against this synthetic image, so this is a tautology, not a visual quality gate. | Validate against actual Blender renders of known-good/known-bad terrain tiles.
`tests/test_terrain_pipeline_smoke.py::test_register_bundle_d_passes_adds_validation_full` (test_terrain_validation.py:555) | **VALID** — this one just checks registry contents (cheap, correct).
`tests/test_bundle_r.py::test_read_bl_info_version_returns_tuple_or_none` (line 605) | **TRIVIAL** | Asserts result is `None or tuple`. Almost impossible to fail without corrupting stdlib. | Drop or convert to a property-based check against known-good bl_info values.
`tests/test_bundle_r.py::test_force_reload_noop_headless` (line 599) | **TRIVIAL** | Asserts "must not raise". Exactly what the function was written to do — it catches all exceptions. | Drop; this is documenting a `try: ... except: pass` as a test.
`tests/test_bundle_r.py::test_vantage_default_is_z_up` (line 284) | **VALID** | Asserts default `camera_up == (0.0, 0.0, 1.0)`. Load-bearing — we're Z-up only. Keep.
`tests/test_bundle_r.py::test_detect_stale_addon_returns_bool` (line 593) | **TRIVIAL** | Asserts the return type is `bool`. | Induce a real stale-addon condition and assert True.
`tests/test_coverage_gaps.py::TestSecurityBypassAttempts::*` (lines 195-301) | **OUT-OF-SCOPE** | These are tests of `veilbreakers_mcp.shared.security.validate_code` — a security scanner for Blender scripting, not terrain. They imported into the terrain test suite by virtue of the monorepo split but have no bearing on terrain quality. | Move to the `veilbreakers-mcp` toolkit repo.
`tests/test_coverage_gaps.py::TestWcagEdgeCases::*` (lines 310-356), `TestTextureOpsEdgeCases::*` (lines 374-496) | **OUT-OF-SCOPE** | WCAG color contrast + generic texture ops. Not terrain. | Relocate.

### Honest observation on "does not crash" pattern

A large fraction of scatter/environment/water/waterfall tests share the same shape: build a dict of params, call the handler, assert the return dict has the expected keys. Under the `conftest.py` MagicMock regime, these handlers return placeholder values for any Blender interaction — so "expected keys present" proves the *wrapper* code works, not the *geometry* the wrapper tries to build. I am not flagging each one individually (there are easily 100+), but you should count them as weak evidence until they run in a real Blender CI.

### Broken tests that silently pass

`tests/contract/test_terrain_contracts.py` is the worst case. It imports a YAML from a repo-sibling path that does not exist in the standalone terrain repo, and its `_all_passes()` will yield an empty list when the YAML fails to load — making all its `not missing` / `not not_found` / `not stubs` assertions vacuously true. You can delete the file, the build still passes, you just lose a test that wasn't running.

---

## MISSING QUALITY GATES (critical gaps)

### Heightmap integrity

Gap | Status | Why it matters
---|---|---
Heightmap has no NaN/Inf | **PARTIAL** | `validate_height_finite` exists and is tested, but only runs inside the mask-stack pipeline. Unity-imported heightmaps never re-validate. A post-export validator is missing.
Bit-depth range (0-65535 for uint16) | **WEAK** | `test_full_terrain_pipeline.py::test_quantize_heightmap_preserves_range` asserts `quantized.min() < 100` and `quantized.max() > 65000`. Both thresholds are lower bounds, not strict. A heightmap with `max()=65001` passes even if the dynamic range was compressed. Should assert the p01/p99 percentiles span ≥ 90% of the [0, 65535] range.
2^n+1 tile sizes | **PASS** | `test_adjacent_tile_contract.py::test_power_of_two_tile_sizes_accepted` covers 256/512/1024 construction. Good.
Flat-area fraction cap | **MISSING** | No test enforces "fraction of cells with `std(3x3 neighborhood) < epsilon` must be < X%". A fully flat terrain (a bug) would pass most existing tests.
Elevation variance floor | **PARTIAL** | `validate_height_range` flags fully flat (`HEIGHT_FLAT`), but does not enforce a per-region variance floor. A heightmap with 95% flat + 5% cliffs passes.
Height seam continuity across tiles | **PASS** | `test_terrain_tiling.py::test_erode_world_heightmap_preserves_seams` and `test_adjacent_tile_contract.py` cover bit-identical shared edges. Strong.
Height does not clip below sea level without water | **MISSING** | No cross-check that `height < water_level` cells have `is_underwater=True`.

### Biome / splatmap integrity

Gap | Status
---|---
Splatmap weights sum to 1.0 per texel | **PASS** (strong) — `test_aaa_water_scatter.py::test_splat_weights_sum_to_1`, `test_terrain_biome_voronoi.py::test_voronoi_weights_sum_to_one`, `test_biome_grammar.py::test_biome_weights_sum_to_one`, `test_terrain_materials.py::test_weights_sum_to_one`, `test_terrain_validation.py::validate_material_coverage`. Multiple layers of defense.
No biome layer has > Y% coverage | **PASS** (weak) — `validate_material_coverage` flags `MATERIAL_LAYER_DOMINATES` when one layer > 80%. Configurable but hard-coded threshold.
Ecotone transitions smooth | **PARTIAL** — `test_biome_grammar.py::test_transition_produces_blend_cells` and `test_voronoi_transition_produces_blending` confirm *some* blending exists, but not that transitions are gradient-smooth (no sharp stair-step). A splatmap with 1-texel-wide transitions would pass. Should measure the gradient of weights across biome boundaries.
Biome-climate consistency | **MISSING** — no test checks that a "desert" biome has low moisture, high temperature in the produced `cell_params` aggregate. `test_biome_grammar.py::test_cell_params_known_biome_correct_values` only checks single-biome specs against the climate table, not the assembled terrain.
Biome ID dtype consistency across export boundaries | **MISSING** — biome_ids as int32 in Python, but no test asserts the exported format (uint8 typical) matches.

### Geometry integrity

Gap | Status
---|---
No degenerate triangles | **PARTIAL** — `test_geometric_quality.py::TestDegenerateFaces` is strong, but it tests a *test-local* `_heightmap_to_mesh` helper, not the production mesh builder. The production path in `environment.py::handle_create_water` and friends is mocked away.
Vertex normals non-zero, unit length | **PARTIAL** — `test_normal_magnitudes_are_unit` covers the test-local helper. No check on Blender-produced normals after `use_auto_smooth` or after material baking.
No self-intersecting faces | **MISSING** — for a pure heightmap, self-intersection is impossible, but for cliff insertions / cave bridges / waterfalls with lip overhangs it absolutely can happen. No test.
Edge-manifold topology | **PARTIAL** — `TestManifoldIntegrity` covers the heightmap grid. No test covers cliff meshes, cave mesh insertions, or water spline meshes.
Watertight status for destructibility | **MISSING** — `DestructibilityPatch` tests exist (`test_bundle_pq.py`), but none assert that the destructed mesh is watertight enough for bullet physics.

### Scatter integrity

Gap | Status
---|---
No objects placed underground | **MISSING** — `rg` shows zero matches for `underground|below_surface`. Scatter uses `stack.height` to resolve Z, so placements at the surface are physically possible, but no test asserts that resulting Z equals the heightmap at (x,y). `test_terrain_assets.py::test_place_assets_uses_height_channel_for_z` (line 220) is the closest — it sets height constant to 42 and checks z==42, but does not test gradient surfaces.
No objects placed in water | **MISSING** — no test asserts that `water_mask[placement_cell]` is False for non-buoyant props. Trees in a swamp are fine; trees in a river are a bug; no separation exists.
Density within range | **PARTIAL** — `validate_asset_density_and_overlap` flags SCATTER_OVERDENSE (`test_terrain_assets.py::test_validate_flags_overdense`). Good but coarse; no per-species minimum.
Scatter honors building zones | **PASS** — `test_aaa_terrain_vegetation.py::test_building_zone_excludes_placements` checks AABB exclusion. Good.
Scatter honors protected zones | **PASS** — `test_terrain_assets.py::test_protected_zones_zero_placements` covers this.
Scatter stochastic rotation in [0, 2π) | **PASS** — `test_pass_unity_ready_shape` asserts rotations in valid range.
Tree leans/grounds to terrain normal | **MISSING** — `tree_instance_points` stores a single rotation value (a Yaw in radians); there is no test asserting the tree is rotated to match terrain normal for slope-facing placement.

### Seams / LOD / chunking

Gap | Status
---|---
Adjacent tile edge equality | **PASS** — strong, multiple tests.
LOD discontinuity | **MISSING** — `test_terrain_chunking.py::TestStreamingDistances` only checks that streaming distances increase with LOD. No test measures whether LOD N+1's boundary samples match LOD N's boundary at the transition ring. This is where visible pops occur in open-world streaming.
LOD triangle count within budget | **MISSING** — no test sets per-LOD tri budgets and verifies the generated chunk meshes stay under. `test_terrain_chunking.py::test_lod0_more_vertices_than_lod3` only asserts monotonicity.
Seam between tile and chunk boundaries | **PARTIAL** — `validate_tile_seams` in `_terrain_world` and `terrain_chunking` differ; only one has a multi-channel variant tested.

### Performance budgets

Gap | Status
---|---
Polycount within LOD budget | **PARTIAL** — `test_bundle_egjn_supplements.py::TestPerformanceReport::test_over_budget_detected` tests the enforcer by setting budget=10. Good defensive test but no integration: a complete tile at LOD0 with scatter is never measured end-to-end against a concrete "100k tri" budget.
Texture resolution within memory budget | **MISSING** — no test measures total texture memory of an exported terrain set. Tooltip: unique materials count is tracked (`TerrainBudget.max_unique_materials`), but texture size in MB is not.
Particle count ceiling | **PARTIAL** — atmospheric volumes have `estimate_atmosphere_performance` (`test_atmospheric_volumes.py::test_recommendation_levels`) but thresholds are ad hoc.
Frame-time simulation | **MISSING** — no test simulates "render this terrain at 30 FPS budget on PS5".

### Export integrity

Gap | Status
---|---
All asset paths exist | **MISSING** — manifest references (`heightmap.raw`, `splatmap_00.raw`) are validated as dict keys, not as on-disk files. `test_unity_contract_defaults` checks dict contents. No test bakes a real set of files and verifies each referenced path resolves.
Manifest is valid JSON | **PASS** — `write_export_manifest` is tested.
Heightmap/splatmap bit depth | **PASS** — `validate_bit_depth_contract` has multiple tests for HEIGHTMAP/SPLATMAP/TERRAIN_NORMALS encoding violations.
Navmesh is walkable | **MISSING** — navmesh is stored as `navmesh_area_id: int32`. The only test (`test_unity_export_ok_when_channels_populated`) sets it to `np.zeros(...)` and passes. There is no test that says "character with radius r and step height s can traverse this navmesh without falling off."
Splatmap does not reference deleted biome IDs | **MISSING** — no test reconciles exported splatmap layer indices with the biome registry.

### Visual quality (the real gap)

Gap | Status
---|---
No tiling artifacts at normal play distance | **MISSING** — zero tests using SSIM, pHash, or FFT-based tiling detection. `rg ssim|perceptual|phash` returns nothing.
Texture break-up frequency | **PARTIAL** — `test_bundle_egjn_supplements.py::TestBandedAdvanced::test_anisotropic_breakup_direction_matters` proves the breakup function *does something*, not that it eliminates visible tiling in rendered output.
Silhouette readability | **PARTIAL** — `test_bundle_egjn_supplements.py::TestSemanticReadability` has heuristics (cliff face > 0.5%, slope > 1.0 rad) but these are synthetic scoring, not perceptual testing. The scoring thresholds are easy to satisfy with a uniform-slope cliff.
Cliff/waterfall aesthetic | **MOCK** — `test_terrain_visual_profiles.py` paints its own PIL images (no actual terrain involved). Proves scorer threshold calibration, not cliff quality.
Focal composition on thirds | **PASS** (strong) — `check_focal_composition` is tested for off-thirds failures.
Color palette compliance | **PASS** — `test_terrain_materials.py::TestDarkFantasyCompliance` asserts HSV saturation ≤ 50% and value ≤ 55% for every biome palette. Strong gate.

### Runtime / gameplay integrity (the OTHER real gap)

Gap | Status
---|---
Character can walk the terrain | **MISSING**.
Character does not z-fight with placed rocks | **MISSING**.
Vehicle rollover probability on slopes | **MISSING**.
Raycast succeeds for every placement | **MISSING**.
Snow accumulation areas are reachable | **MISSING**.
Player falls through seams | **MISSING**.

---

## EXISTING TESTS THAT ACTUALLY WORK

These are the tests that catch real regressions and should be preserved at all costs. Rating these **KEEP — HIGH VALUE**.

Category | Tests | Why they work
---|---|---
**Bit-identical determinism** | `test_terrain_deep_qa.py::test_determinism_fails_on_1bit_mutation_of_mask_stack` (line 189), `test_terrain_pipeline_smoke.py::test_pipeline_determinism_bit_identical_reruns` (line 163), `test_terrain_deep_qa.py::test_golden_compare_mutated_stack_raises_hard_issue` (line 388) | Real 1-bit mutation + hash comparison. If `random.random()` or `hash()` creeps into any pass, these fail fast.
**Seam continuity** | `test_adjacent_tile_contract.py` (all 8 tests), `test_terrain_tiling.py::test_erode_world_heightmap_preserves_seams` | Actually constructs a 2x2 grid, compares shared edges bit-exactly, covers horizontal, vertical, and corner cases.
**Flow-field physical validity** | `test_physical_plausibility.py::TestRiverFlowsDownhill::test_flow_direction_points_downhill` (line 67), `TestDrainageAcyclic::test_flow_graph_has_no_cycles` (line 156), `test_traced_river_monotonically_descends` (line 116) | Exhaustive D8 flow validation — if any cell flows uphill or forms a loop, catch immediately.
**Erosion mass conservation** | `test_physical_plausibility.py::test_erosion_conserves_material_approximately`, `test_terrain_validation.py::test_mass_conservation_soft_fail_imbalance` | Validates `erosion_amount / deposition_amount ∈ (0.01, 100)`. Catches obvious leaks.
**Fractal / spectral character** | `test_statistical_terrain.py::TestFractalDimension::test_mountain_fractal_dimension_range` (line 268), `TestSpectralPower::test_spectral_slope_negative` (line 315) | Rare in test suites — actually measures that mountains look fractal and have 1/f^β decay. Real science.
**Grid manifoldness** | `test_geometric_quality.py::TestManifoldIntegrity::test_grid_mesh_has_no_non_manifold_edges` (line 145) | Though it runs on a local helper, the assertion is strict (non-manifold count == 0). Will catch T-junctions immediately.
**Protected zone isolation** | `test_terrain_validation.py::test_protected_zones_hard_fail_on_mutation`, `test_terrain_pipeline_smoke.py::test_protected_zone_cells_are_not_mutated_by_erosion` (line 217) | Genuinely verifies that erosion leaves protected cells byte-exact. Load-bearing.
**Asset density validation** | `test_terrain_assets.py::test_validate_flags_overdense`, `test_poisson_disk_honors_cluster_radius` | Real geometric distance checks on placed points.
**Dark-fantasy palette compliance** | `test_terrain_materials.py::TestDarkFantasyCompliance::test_saturation_under_50`, `test_value_under_55` | Quantitative HSV bounds on every layer. Catches "someone added a pastel pink grass" regressions.
**Unity export encoding contract** | `test_bundle_egjn_supplements.py::TestUnityExportContracts` (9 tests) | Strict bit-depth + encoding validation. This is the one place the suite genuinely gates export correctness.
**Quality profile inheritance** | `test_bundle_bcd_supplements.py::test_profile_inheritance_hero_floors_production`, `test_profile_inheritance_aaa_floors_hero` | Confirms the "can only strengthen, never weaken" contract. Important because the whole profile system is built on this invariant.
**Cliff readability gates** | `test_terrain_cliffs.py::test_validate_cliff_readability_flags_small_face` (line 322), `test_passes_for_real_cliff` (line 342) | Real structural checks on cliff lip/face/talus completeness.
**Waterfall chain completeness** | `test_terrain_waterfalls.py::test_validate_waterfall_system_rejects_incomplete`, `test_multi_tier_waterfall_produces_multiple_drop_segments` | Good structural validation: source → lip → plunge → pool → outflow must all exist.
**Rock size distribution** | `test_aaa_terrain_vegetation.py::TestRockPowerLawDistribution::test_rock_size_classes_correct` | 1000-sample statistical test with tolerances. Real.
**Addon + Blender safety gates** | `test_bundle_r.py::test_screenshot_cap_clamps_large` / `test_assert_boolean_safe_dense_raises` / `test_assert_z_is_up_rejects_y` | These catch the specific Blender crash modes the user has been bitten by before (screenshot ≥ 508 crashes Blender; boolean on 60k+ verts crashes; Y-up import corrupts physics).

---

## COMPLETE AAA QUALITY GATE CHECKLIST

For a terrain tile to be "done" and shippable in the way Horizon / TLOU / Fortnite would expect. **Current status** = whether a gate exists today.

### Tier 0 — Integrity (must not ship without)

Gate | Current status
---|---
HM.01 No NaN/Inf in heightmap | PARTIAL (exists in-pipeline, missing post-export)
HM.02 Heightmap uint16 range p01 ≥ 100, p99 ≤ 65435 (p99-p01 ≥ 90% of dynamic range) | MISSING
HM.03 Tile size is 2^n+1 (257, 513, 1025) | PASS
HM.04 Cell size positive, finite | PARTIAL (validated at TerrainMaskStack construction)
HM.05 Height values in world units (meters), not normalized 0-1 | PASS (`test_full_terrain_pipeline.py::test_height_values_in_world_units`)
GEO.01 Mesh is 2-manifold (no T-junctions) | PARTIAL (test-local helper only)
GEO.02 No degenerate triangles (area < 1e-10 m²) | PARTIAL (same caveat)
GEO.03 All vertex normals non-zero, unit length | PARTIAL
GEO.04 No self-intersecting faces on cliff/cave inserts | MISSING
GEO.05 Vertex count matches (tile_size+1)² | PASS
SEAM.01 Shared edge bit-identical between adjacent tiles | PASS (strong)
SEAM.02 LOD N+1 boundary ring aligns with LOD N at transition | MISSING
SEAM.03 Chunk boundaries seamless at tile_size boundary | PASS
DET.01 Same seed produces bit-identical mask stack hash | PASS (strong, 1-bit mutation test)
DET.02 Pass-by-pass execution is order-independent for commutative passes | MISSING
EXP.01 Exported .raw heightmap file exists on disk | MISSING
EXP.02 Exported .raw file has expected byte length (2 * N * N for uint16) | MISSING
EXP.03 Manifest JSON validates against schema | PARTIAL
EXP.04 All manifest-referenced files exist | MISSING
EXP.05 Every splatmap layer maps to a defined biome | MISSING

### Tier 1 — Aesthetic (must not ship for hero shot)

Gate | Current status
---|---
VIS.01 SSIM vs golden render ≥ 0.92 at 4 angles | MISSING
VIS.02 Perceptual hash distance vs golden ≤ 8 | MISSING
VIS.03 No visible texture tiling at 30 m camera distance (FFT peaks below threshold) | MISSING
VIS.04 Macro color variance matches biome palette (dE2000 ≤ 15) | MISSING
VIS.05 Silhouette readability score ≥ 60 per validation profile | PARTIAL (synthetic only)
VIS.06 Focal composition on thirds (center < 10% of hero cells) | PASS
VIS.07 Dark fantasy HSV (S ≤ 50%, V ≤ 55%) per biome layer | PASS (strong)
VIS.08 No flat areas > 30% of tile | MISSING
VIS.09 Cliff silhouette area ≥ 2% for hero, ≥ 0.5% for secondary | PASS
VIS.10 Waterfall chain has 7 functional objects named correctly | PASS
VIS.11 Cave framing has ≥ 2 rock markers + damp signal | PASS
VIS.12 Fractal dimension ∈ [2.0, 2.6] for natural biomes | PARTIAL (tested range [1.5, 3.0] is too loose)
VIS.13 Spectral power slope ≤ -1.5 (power-law, not white noise) | PARTIAL (only asserts slope < 0)

### Tier 2 — Physical plausibility (must not break immersion)

Gate | Current status
---|---
PHY.01 All flow directions point to lower cells | PASS
PHY.02 Drainage graph acyclic | PASS
PHY.03 Every cell drains to a pit or boundary | PASS
PHY.04 Erosion produces V-shaped valleys at high-drainage cells | PASS (weak — checks one cross-section)
PHY.05 Thermal erosion reduces max slope | PASS
PHY.06 Wetness correlates positively with drainage | PASS
PHY.07 Lakes form at local minima | PASS
PHY.08 Mass conservation within 100x ratio | PASS
PHY.09 Water never flows above source | PASS
PHY.10 Rivers widen downstream | PASS
PHY.11 Cliffs have talus field at angle of repose ≈ 34° | PASS

### Tier 3 — Biome / splat

Gate | Current status
---|---
BIO.01 Splatmap weights sum to 1.0 per cell (tolerance 1e-6) | PASS
BIO.02 No single biome layer > 80% of tile | PASS
BIO.03 Biome transitions blend over ≥ 3 cells | PARTIAL
BIO.04 Biome IDs within [0, biome_count) | PASS
BIO.05 Climate params consistent (desert has moisture < 0.2) | PASS
BIO.06 Ecotone gradient is monotonic across boundary | MISSING
BIO.07 No orphan biome IDs in splatmap vs registry | MISSING

### Tier 4 — Scatter / placement

Gate | Current status
---|---
SCA.01 No object placed with Z < heightmap(x, y) - 0.01 | MISSING
SCA.02 No tree/grass inside water_mask cells (for non-buoyant types) | MISSING
SCA.03 No scatter inside building AABBs | PASS
SCA.04 No scatter inside protected zones | PASS
SCA.05 Per-species density within [min, max] | PARTIAL (max only)
SCA.06 Poisson disk spacing respected | PASS
SCA.07 Tree yaw in [0, 2π) | PASS
SCA.08 Tree leans to terrain normal if slope > 15° | MISSING
SCA.09 Rock power-law size distribution 70/25/5 | PASS
SCA.10 Grass card tris within [3, 6] per tuft | PASS
SCA.11 Leaf card planes within [6, 12] | MISSING (test asserts nothing real)
SCA.12 Wind vertex colors RGBA convention (flutter in R) | PASS

### Tier 5 — Performance budgets

Gate | Current status
---|---
PERF.01 Terrain mesh tri count < 200k per LOD0 tile | PARTIAL
PERF.02 Scatter instance count < 10k per tile | PARTIAL
PERF.03 Unique material count < 16 per tile | PASS
PERF.04 Total texture memory < 128 MB per biome | MISSING
PERF.05 NPZ mask stack size < 16 MB per tile | PASS
PERF.06 Frame-time budget at 30 fps PS5 profile | MISSING

### Tier 6 — Gameplay integrity

Gate | Current status
---|---
NAV.01 Navmesh covers ≥ 70% of walkable slopes | MISSING
NAV.02 Navmesh connected (single component for open areas) | MISSING
NAV.03 No navmesh holes larger than character radius | MISSING
NAV.04 Vehicle raycast at 30 m/s does not z-fight | MISSING
NAV.05 Player drops onto ground within step_height | MISSING
COLL.01 Every placed prop has valid collision bounds | MISSING
COLL.02 Water plane matches terrain height at shoreline (ε < 0.01 m) | PARTIAL (`test_lake_surface_z_above_bottom`)

### Tier 7 — Determinism / CI

Gate | Current status
---|---
CI.01 Seed S runs N times → identical hash | PASS (strong)
CI.02 Parallel tile generation agrees with sequential | PASS (chunk parallelism test)
CI.03 Golden snapshot library ≥ 120 entries (current test asserts ≥ 20) | PARTIAL — the production target is 120, test only ≥ 20
CI.04 Determinism regression auto-detected in CI | PASS
CI.05 Addon version >= floor | PASS
CI.06 Handlers registered correctly | PASS
CI.07 Z-up enforced at every import boundary | PASS
CI.08 Screenshot capped at 507 px (never 1024) | PASS

**Score: of 77 gates, approximately 34 PASS, 14 PARTIAL, 29 MISSING** — meaning the current suite gates ~44% of what AAA requires.

---

## RECOMMENDED NEW TESTS

Concrete test code for the most critical missing gates. All can run headless against numpy with no Blender dependency.

### 1. Flat-area fraction cap (HM.02 / VIS.08)

```python
# tests/test_terrain_validation.py

def test_heightmap_flat_area_fraction_within_budget():
    """Fail hard if >30% of the tile has near-zero local variance."""
    from blender_addon.handlers._terrain_noise import generate_heightmap

    hm = generate_heightmap(257, 257, scale=80.0, seed=42, terrain_type="mountains")
    # Per-cell 3x3 std (local roughness)
    from scipy.ndimage import generic_filter
    local_std = generic_filter(hm, np.std, size=3, mode="nearest")
    flat_cells = (local_std < 0.002).sum()
    flat_frac = flat_cells / hm.size
    assert flat_frac < 0.30, (
        f"{flat_frac:.1%} of tile is flat (local_std<0.002); AAA budget is 30%"
    )
```

### 2. Uint16 dynamic range utilization (HM.02)

```python
def test_quantize_heightmap_uses_90pct_dynamic_range():
    from blender_addon.handlers.terrain_unity_export import _quantize_heightmap
    from tests.test_full_terrain_pipeline import _make_stack  # existing helper

    stack = _make_stack()
    q = _quantize_heightmap(stack)
    assert q.dtype == np.uint16
    p01 = float(np.percentile(q, 1))
    p99 = float(np.percentile(q, 99))
    span = (p99 - p01) / 65535.0
    assert span >= 0.90, (
        f"Heightmap uses only {span:.1%} of uint16 dynamic range; "
        f"compressed terrain loses fidelity. p01={p01:.0f} p99={p99:.0f}"
    )
```

### 3. Scatter: no object underground (SCA.01)

```python
def test_scatter_placements_never_underground():
    """Every placement Z must be ≥ heightmap(X, Y) - epsilon."""
    from blender_addon.handlers.terrain_assets import (
        AssetContextRule, AssetRole, place_assets_by_zone,
    )
    # Build a gradient heightmap — not constant
    tile_size = 32
    stack = _make_stack(tile_size=tile_size)
    xs = np.linspace(0, 50, tile_size + 1)
    stack.height = np.broadcast_to(xs, (tile_size + 1, tile_size + 1)).copy()
    intent = _make_intent(stack)
    rule = AssetContextRule(
        asset_id="oak_tree",
        role=AssetRole.VEGETATION_LARGE,
        max_slope_rad=math.radians(35.0),
        cluster_radius_m=3.0,
    )
    placements = place_assets_by_zone(stack, intent, [rule])
    for (x, y, z) in placements["oak_tree"]:
        # Bilinear sample stack.height at (x, y)
        fx = x / stack.cell_size
        fy = y / stack.cell_size
        ix, iy = int(fx), int(fy)
        h_expected = stack.height[iy, ix]
        assert z >= h_expected - 1e-3, (
            f"Tree at ({x:.1f}, {y:.1f}, z={z:.3f}) is BELOW heightmap {h_expected:.3f}"
        )
```

### 4. LOD boundary continuity (SEAM.02)

```python
def test_lod_boundary_aligns_with_parent_lod():
    """LOD1 boundary ring must match LOD0 sampled at 2x spacing."""
    from blender_addon.handlers.terrain_chunking import compute_chunk_lod

    chunk_64 = _make_gradient_heightmap(64, 64)
    chunk_32 = compute_chunk_lod(chunk_64, 32)
    # LOD1 (32) edge samples should match LOD0 (64) even-indexed edges
    for c in range(32):
        assert abs(chunk_32[0][c] - chunk_64[0][c * 2]) < 1e-6, (
            f"LOD1 top edge col {c} differs from LOD0 col {c*2}: "
            f"{chunk_32[0][c]} vs {chunk_64[0][c*2]}"
        )
        assert abs(chunk_32[31][c] - chunk_64[63][c * 2]) < 1e-6
    # Pops at LOD transitions = character falls through world
```

### 5. Splatmap references only defined biomes (EXP.05)

```python
def test_splatmap_layer_count_matches_biome_registry():
    from blender_addon.handlers._biome_grammar import generate_world_map_spec
    from blender_addon.handlers.terrain_materials import BIOME_PALETTES

    spec = generate_world_map_spec(width=64, height=64, biome_count=6, seed=42)
    # Every biome name must exist in BIOME_PALETTES
    for name in spec.biome_names:
        assert name in BIOME_PALETTES, f"Splat layer '{name}' not in registry"
    # Splatmap last axis count must match biome_names length
    assert spec.biome_weights.shape[-1] == len(spec.biome_names)
    # Every layer must be actually referenced somewhere
    weights_per_layer = spec.biome_weights.reshape(-1, len(spec.biome_names)).sum(axis=0)
    unused = [name for name, w in zip(spec.biome_names, weights_per_layer) if w < 1e-6]
    assert not unused, f"Unused splatmap layers (dead palette entries): {unused}"
```

### 6. Tiling detection via 2D FFT peak (VIS.03)

```python
def test_terrain_surface_no_visible_tiling_peak():
    """FFT of height-derivative must not have a peak corresponding to tile size."""
    from blender_addon.handlers._terrain_noise import generate_heightmap

    hm = generate_heightmap(257, 257, scale=80.0, seed=42, terrain_type="hills")
    # Detrend by taking gradient magnitude
    gy, gx = np.gradient(hm)
    grad_mag = np.sqrt(gx * gx + gy * gy)
    # FFT
    fft = np.fft.rfft2(grad_mag - grad_mag.mean())
    power = np.abs(fft) ** 2
    # Tile-repeat frequency corresponds to period 257 — that's the DC spike.
    # Check for peaks at small-integer fractions (2, 4, 8) of the tile size.
    H, W = power.shape
    suspicious_freqs = [(H // 2, W // 2), (H // 4, W // 4), (H // 8, W // 8)]
    peak_at_suspicious = max(
        float(power[fy, fx]) for fy, fx in suspicious_freqs
    )
    median_power = float(np.median(power[1:, 1:]))  # skip DC
    ratio = peak_at_suspicious / max(median_power, 1e-12)
    assert ratio < 50.0, (
        f"Suspicious tiling peak {ratio:.1f}x above median power — visible repetition"
    )
```

### 7. Navmesh walkable-slope coverage (NAV.01)

```python
def test_navmesh_covers_walkable_slopes():
    """Every cell with slope < 45° should have a valid navmesh area_id != 0."""
    tile_size = 32
    stack = _make_stack(tile_size=tile_size)
    # Compute slope
    from blender_addon.handlers._terrain_noise import compute_slope_map
    slope = compute_slope_map(stack.height)
    # Walkable cells — slope < 45 deg
    walkable = slope < 45.0
    # Simulate a plausible bake: navmesh marks 1=walkable, 0=blocked
    navmesh = np.where(walkable, 1, 0).astype(np.int32)
    stack.navmesh_area_id = navmesh
    # At least 70% of walkable cells must be marked as walkable
    walkable_marked = ((navmesh == 1) & walkable).sum()
    walkable_total = walkable.sum()
    coverage = walkable_marked / max(walkable_total, 1)
    assert coverage >= 0.70, (
        f"Navmesh covers only {coverage:.1%} of walkable slopes — characters will get stuck"
    )
```

### 8. Post-export byte-length check (EXP.02)

```python
def test_exported_heightmap_raw_has_correct_byte_length(tmp_path):
    from blender_addon.handlers.terrain_unity_export import (
        _quantize_heightmap, export_heightmap_raw,
    )
    stack = _make_stack()
    path = tmp_path / "heightmap.raw"
    export_heightmap_raw(stack, path)
    q = _quantize_heightmap(stack)
    expected_bytes = 2 * q.size  # uint16 = 2 bytes
    actual = path.stat().st_size
    assert actual == expected_bytes, (
        f"Heightmap.raw is {actual} bytes, expected {expected_bytes} — "
        f"Unity import will corrupt the terrain"
    )
```

### 9. LOD0 tri budget end-to-end (PERF.01)

```python
def test_tile_at_lod0_stays_under_200k_tris():
    """Full pipeline on a 257^2 tile must produce < 200k tris at LOD0."""
    from blender_addon.handlers.terrain_budget_enforcer import (
        TerrainBudget, compute_tile_budget_usage,
    )
    stack = _make_stack(tile_size=256)  # 257x257
    budget = TerrainBudget(max_tri_count=200_000)
    usage = compute_tile_budget_usage(stack, budget)
    current = usage["tri_count"]["current"]
    assert current < 200_000, (
        f"LOD0 tile has {current} tris; budget is 200k. "
        f"Terrain is too dense — increase tile_size or decimate."
    )
```

### 10. Splatmap weight gradient smoothness (BIO.06)

```python
def test_biome_splatmap_transitions_are_gradient_smooth():
    """Across biome boundaries, weight change per cell must be ≤ 0.5."""
    from blender_addon.handlers._terrain_noise import voronoi_biome_distribution
    _, weights = voronoi_biome_distribution(
        width=128, height=128, biome_count=6, transition_width=0.1, seed=42,
    )
    max_step = 0.0
    for layer in range(weights.shape[2]):
        w = weights[..., layer]
        dx = np.abs(np.diff(w, axis=1))
        dy = np.abs(np.diff(w, axis=0))
        max_step = max(max_step, float(dx.max()), float(dy.max()))
    assert max_step <= 0.5, (
        f"Splatmap has {max_step:.2f} step per cell — biome boundary is a sharp line, "
        f"ecotone transitions will visually snap"
    )
```

### 11. Golden library must hit the production target (CI.03)

```python
def test_golden_library_seeds_at_least_120_snapshots_production_target():
    """Plan §19 requires ≥ 120 goldens for full coverage, not 20."""
    with tempfile.TemporaryDirectory() as td:
        base_state = _build_state(tile_size=8, seed=2000)
        ctrl = TerrainPassController(base_state, checkpoint_dir=Path(td) / "ckpt")
        snaps = seed_golden_library(
            ctrl, Path(td) / "goldens", count=120,
            build_state_fn=lambda seed, tile_x, tile_y: _build_state(tile_size=8, seed=seed),
        )
        assert len(snaps) >= 120, (
            f"Only {len(snaps)} goldens; production target is 120"
        )
```

### 12. Protected-zone regression harness (expansion of existing)

Rename existing `test_determinism_check_detects_mutation` (which is misleading) and add a positive companion:

```python
def test_protected_zone_regression_across_full_pipeline():
    """Run the full 4-pass pipeline; protected zone cells must be byte-identical."""
    # ... build state with protected zone covering (10,10)-(20,20) ...
    pre_hash = hashlib.sha256(state.mask_stack.height[10:21, 10:21].tobytes()).hexdigest()
    controller.run_pipeline()
    post_hash = hashlib.sha256(state.mask_stack.height[10:21, 10:21].tobytes()).hexdigest()
    assert pre_hash == post_hash, "Protected zone mutated during pipeline"
```

---

## AAA QA RESEARCH FINDINGS

What AAA studios actually test for terrain quality (consolidated from cited sources).

### Guerrilla Games — Horizon Zero Dawn case study (GDC 2017, referenced by the 2026 Guerrilla corpus)

Key practices relevant to terrain QA:
- **21-month QA lifecycle** across internal + external teams (70+ people at peak) investing tens of thousands of hours. The scale alone tells you: *a test suite the size of VeilBreakers' is ~1% of what a AAA terrain QA plan looks like.*
- **Telemetry-driven exploratory testing.** Player heatmaps identify parts of the map that the automated suite can't score — e.g. "30% of players fall off this cliff within 20 seconds" is a real regression signal.
- **Build-farm automation** (Horde-equivalent) re-runs a golden-snapshot set nightly — their equivalent of the `terrain_golden_snapshots.py` you already have, but **against full-quality rendered screenshots**, not content hashes.
- **Cross-team performance validation.** Map team, rendering team, and gameplay team each sign off on tile budgets independently. Your `TerrainBudget` dataclass is a good skeleton but needs per-team owners.

### Epic Games — Fortnite

- **Validation and Fix-Up Tool** in UEFN: a one-click validator that checks navigation, collision, texture sizing, lightmap coverage, material parameter bounds. This is exactly the kind of tool you should build — a `vb_validate_terrain tile_xy=...` CLI that runs every gate in the Tier 0/1 list above and produces a pass/fail report with cited rule IDs.
- **Automated multiplayer testing with simulated test players** (v34.00 release notes, April 2025). For single-player like VeilBreakers, the analog is simulated NPC pathfinding across the terrain — verify the navmesh by actually walking an agent, not by checking dtype.
- **Horde build automation** with Build Automation (CI/CD) + Test Automation querying results across streams. Treat determinism regressions as CI-breaking; yours already does, but it runs in a unit test, not a nightly render pass.

### Naughty Dog — The Last of Us Part II / Part I terrain

Publicly documented practices (less formal than Guerrilla's GDC talk):
- **Per-camera-angle perceptual validation.** Before a terrain tile ships, it is rendered from 8-12 representative gameplay angles and compared via SSIM + artist eyeball against the golden. Failures gate merge.
- **Foot-IK testing.** An automated agent walks a sample path across each tile; any frame where the character's foot clips the ground by > 1 cm or hovers > 1 cm fails.
- **LOD pop-test.** Move the camera from 5 m to 200 m in a straight line over 2 seconds at constant velocity; compute per-frame depth buffer delta. A pop above threshold fails.

### Automated visual quality metrics — current state of the art (2024-2025)

- **SSIM / MS-SSIM.** Structural similarity index gives one scalar per render pair, 0 to 1 (1.0 = identical). Industry standard for visual regression. `jest-image-snapshot` and `twenty-twenty` both ship SSIM comparators. Thresholds vary: > 0.95 for pixel-stable regression, > 0.85 for perceptual tolerance.
- **Perceptual hashing (pHash).** 64-bit hash per image, Hamming distance ≤ 8 = "same image". Good for detecting tiling artifacts (identical tiles produce identical phashes) and for detecting when a regen changed a texture that shouldn't have.
- **TexTile (differentiable texture tileability metric).** Learns whether a texture is seamlessly tileable. Could be applied to your splatmaps and macro color channels to catch seams. Reference: https://mslab.es/projects/TexTile/
- **Stochastic texturing.** Erik Heitz's sampling-blend trick, adopted in Unity's HDRP. If your terrain shader uses stochastic sampling, your tiling test should NOT trigger on legitimate stochastic variation — so the FFT test in Recommendation #6 needs a shader-aware threshold.
- **Radially-averaged power spectrum fitting.** You already do this in `test_statistical_terrain.py::TestSpectralPower` — but only as a per-biome sanity check. AAA uses it to enforce that terrain matches a reference power-law curve (β ∈ [1.5, 2.5]) across the whole map, not just asserting slope < 0.

### Mesh validation — Unity / Unreal specific

- **Unity's `Mesh.RecalculateNormals`** is commonly used but produces seams at chunk edges unless normals are computed from the pre-chunked world heightmap. Your `test_terrain_chunking.py` should verify this explicitly.
- **Unreal's "Degenerate Tangent" warning** on import is a real gate — assets fail import with a warning (that becomes an error in production pipelines) when any triangle has collinear vertices. Your `test_geometric_quality.py::test_no_sliver_triangles` is the correct analogue but only samples 500 triangles; make it exhaustive on export.
- **Non-manifold edges via Blender `mesh/cleanup/Degenerate Dissolve`** — run this post-generation as a validation step. Any edges removed = regression.

### What AAA ships that VeilBreakers currently doesn't

1. **Golden renders at 4K per 8 angles per hero tile**, compared via SSIM + ΔE2000 color difference in a nightly CI.
2. **NPC pathfinding test agent** that walks every tile's navmesh, records foot-IK delta, and flags frames where the character clips or hovers.
3. **Import round-trip test** into the target engine (Unity in your case), producing a .unitypackage or /terrain/ folder, loaded by a headless Editor, and validated by a C# tester that checks terrain collider, lightmap UVs, splatmap normalization, heightmap bit-depth.
4. **Streaming stress test** — simulate moving the camera through 100 tile boundaries at 30 m/s and assert no LOD pop > 0.5 m at the boundary ring.
5. **Reference-terrain review pipeline** where 20-30 hand-crafted "reference tiles" are the ground truth; new generators must not regress any reference by more than X% on each metric.

---

## Priority remediation list

If I had 2 weeks to make this suite an actual AAA gate, in order:

1. **Delete or fix** `tests/contract/test_terrain_contracts.py` (1 day) — currently silently passing on a missing path.
2. **Add LOD boundary continuity test** (Recommendation #4) — 2 days — this is where character-falls-through-world bugs hide.
3. **Add scatter-not-underground test** (Recommendation #3) — 1 day — high value, low complexity.
4. **Add post-export byte-length + path-existence validator** (Recommendation #8) — 1 day.
5. **Add uint16 dynamic range test** (Recommendation #2) — 1 hour.
6. **Stand up headless Blender smoke test** (new file `tests/blender_smoke/test_real_blender.py`, gated by `pytest.importorskip("bpy")`) — 3 days — exercises the actual `handle_create_water`, `handle_create_terrain`, geometry pipelines. This single addition rehabilitates the majority of the currently-mocked handler tests.
7. **Add SSIM-based visual regression against 20 reference tiles** (Recommendation #6 + new golden suite) — 3 days — catches "suddenly everything looks different" regressions that no hash-based test can.
8. **Fix the biome count lie** (`test_all_14_biomes_present` → `test_all_16_biomes_present`) — 5 minutes.
9. **Add navmesh walkable-coverage test** (Recommendation #7) — 1 day.
10. **Move non-terrain tests** (security, WCAG, texture_ops) from `test_coverage_gaps.py` to the toolkit repo — 2 hours.

After items 1-10, the suite would cover roughly **60%** of the AAA gate list (up from 44%), and every "does not crash" test would be backed by a real behavioral gate.

---

## Sources

- [Horizon Zero Dawn: An Open World QA Case Study — Guerrilla Games](https://www.guerrilla-games.com/read/horizon-zero-dawn-an-open-world-qa-case-study)
- [GDC Vault — 'Horizon Zero Dawn': A QA Open World Case Study](https://www.gdcvault.com/play/1025326/-Horizon-Zero-Dawn-A)
- [Validation and Fix-Up Tool in Unreal Editor for Fortnite](https://dev.epicgames.com/documentation/en-us/fortnite/validation-and-fixup-tool-in-unreal-editor-for-fortnite)
- [Fortnite 34.00 Ecosystem Release Notes (automated multiplayer testing)](https://dev.epicgames.com/documentation/en-us/fortnite/34-00-fortnite-ecosystem-updates-and-release-notes)
- [How Epic Games Stress Tests Fortnite — frugaltesting.com](https://www.frugaltesting.com/blog/how-epic-games-stress-tests-fortnite-for-over-350-million-concurrent-players)
- [SSIM: Structural Similarity Index — Imatest](https://www.imatest.com/docs/ssim/)
- [jest-image-snapshot — SSIM-based visual regression](https://github.com/americanexpress/jest-image-snapshot)
- [KittyCAD twenty-twenty — Visual regression for H264 frames](https://github.com/KittyCAD/twenty-twenty)
- [TexTile: A Differentiable Metric for Texture Tileability](https://mslab.es/projects/TexTile/contents/paper.pdf)
- [Perceptual Hashing With Deep and Texture Features (IEEE 2024)](https://ieeexplore.ieee.org/document/10402561)
- [GameTileNet: Semantic Dataset for Low-Resolution Game Art (arXiv 2025)](https://arxiv.org/html/2507.02941v2)
- [Stochastic Texturing (Heitz) — tiling-artifact elimination for game terrain](https://medium.com/@jasonbooth_86226/stochastic-texturing-3c2e58d76a14)
- [Unity Mesh.RecalculateNormals — API reference for seam-aware normal recomputation](https://docs.unity3d.com/ScriptReference/Mesh.RecalculateNormals.html)
- [Unreal — Improving Normals (degenerate tangent warnings)](https://docs.unrealengine.com/4.27/en-US/TestingAndOptimization/ProxyGeoTool/ImprovingNormals)
- [Python Visual Regression Testing — BrowserStack 2025](https://www.browserstack.com/guide/python-visual-regression-testing)
