# R8-A2: Validation, Semantics & Readability Audit

Auditor: Opus subagent (R8 dispatch wave)
Date: 2026-04-17
Scope (read in full):
- `veilbreakers_terrain/handlers/terrain_validation.py` (905 lines)
- `veilbreakers_terrain/handlers/terrain_readability_semantic.py` (245 lines)
- `veilbreakers_terrain/handlers/terrain_readability_bands.py` (232 lines)
- `veilbreakers_terrain/handlers/terrain_semantics.py` (1049 lines)
- `veilbreakers_terrain/handlers/terrain_twelve_step.py` (370 lines)
- `veilbreakers_terrain/handlers/terrain_quality_profiles.py` (282 lines)
- `veilbreakers_terrain/handlers/terrain_geology_validator.py` (332 lines)
- `veilbreakers_terrain/handlers/terrain_framing.py` (171 lines)
- `veilbreakers_terrain/handlers/terrain_saliency.py` (326 lines)
- `veilbreakers_terrain/handlers/terrain_rhythm.py` (192 lines)

Totals: 4,104 lines across 10 files. Known issues (Fix 1.1 ValidationIssue kwargs @L607-726, Fix 1.2 shadow-function duplication) are NOT re-reported below.

---

## NEW BUGS (not in FIXPLAN)

### BLOCKER / HIGH severity

| ID | File:Line | Severity | Description | Correct Fix |
|---|---|---|---|---|
| BUG-R8-A2-001 | `terrain_twelve_step.py:269-272 + 272-278` | HIGH | `erosion_params = compute_erosion_params_for_world_range(...)` is computed on line 269 and **never passed into `erode_world_heightmap`**. The params are only stashed into `metadata["erosion_params"]` (line 364). `erode_world_heightmap` at line 272 receives hardcoded `hydraulic_iterations=50`, `thermal_iterations=0`, `talus_angle` defaulting. The tunable erosion contract from `terrain_world_math` is dead-plumbed. | Pass `**erosion_params` to `erode_world_heightmap`, or at minimum extract `min_slope`/`capacity`/etc. keys and forward them. |
| BUG-R8-A2-002 | `terrain_twelve_step.py:272-278` | HIGH | `hydraulic_iterations=50` is hardcoded. **`TerrainQualityProfile.erosion_iterations` (ranges 2→48 across preview→aaa_open_world) is completely ignored by the orchestrator.** AAA users selecting `aaa_open_world` profile get identical erosion output as `preview`. Quality profiles affect nothing at this call site. | Read `load_quality_profile(intent.quality_profile).erosion_iterations` and pass as `hydraulic_iterations`. Also respect `erosion_strategy` enum (EXACT vs TILED_PADDED). |
| BUG-R8-A2-003 | `terrain_twelve_step.py:116` | MEDIUM | `waypoints: List[Tuple[int, int]] = getattr(intent, "road_waypoints", None) or []` — `TerrainIntentState` is a `@dataclass(frozen=True)` with NO `road_waypoints` field declared (see `terrain_semantics.py:771-828`). `getattr` with default silently swallows the missing attribute so this branch is **unreachable dead code in production**. Step 10 ALWAYS logs "skipped: fewer than 2 road waypoints" and returns `[]`. | Either declare `road_waypoints: Tuple[Tuple[int,int], ...] = ()` on `TerrainIntentState`, or source waypoints from `intent.composition_hints.get("road_waypoints")` and update the docstring. |
| BUG-R8-A2-004 | `terrain_twelve_step.py:68-80` | MEDIUM | `_detect_cave_candidates_stub` runs a nested `for y, for x` Python loop over the ENTIRE world heightmap (O(H*W) Python-level iterations). For the standard 2x2 grid with tile_size=128 this is ~66k iterations per call; at tile_size=1024 (AAA open world) it explodes to ~4.2M iterations calling `np.min(neighbours)` each time — minutes of wall time for what should be a vectorised `scipy.ndimage.minimum_filter` call in tens of milliseconds. Also: `centre <= np.min(neighbours)` includes the centre cell in the neighbourhood, so every cell equal to its 3x3 minimum is flagged — in perfectly flat regions every cell qualifies. | Vectorise: `local_min = scipy.ndimage.minimum_filter(world_hmap, size=3); coords = np.argwhere(world_hmap < local_min)`. Exclude plateaus with a strict-less-than or second-pass gradient test. |
| BUG-R8-A2-005 | `terrain_twelve_step.py:97-143` | MEDIUM | `_generate_road_mesh_specs` imports `from ._terrain_noise import generate_road_path` at function-scope (line 114). `_terrain_noise.py` is 60KB+ of noise routines — function-scope imports are fine as lazy pattern BUT the module still loads once at first call. Real bug: the `path, graded_hmap` returned from `generate_road_path` — `graded_hmap` is thrown away (line 126-131). The graded heightmap is the whole point of road-path carving; Step 10 runs road placement but never writes the graded terrain back into `world_hmap` or any tile stack. Roads don't actually cut into the terrain. | After generation, write `world_eroded[path_cells] = graded_hmap[path_cells]` (or blend via a path mask) before the per-tile extraction in Step 9. Note this requires re-ordering: Step 10 must happen BEFORE Step 9. As written the step ordering is upside-down for road baking. |
| BUG-R8-A2-006 | `terrain_twelve_step.py:276` | LOW-MEDIUM | Docstring comment says `hydraulic_iterations=50,  # small for deterministic test speed`. That's a production orchestrator hardcoded to test-mode erosion. Docstring (line 207-223) promises "canonical 12-step world terrain sequence" — in reality step 6 is permanently in test-speed mode. | Remove comment, source iterations from quality profile (BUG-002). |
| BUG-R8-A2-007 | `terrain_framing.py:54` | LOW | `feather_cells = max(2.0, 4.0 / 1.0)  # 4 cells feather` — `4.0 / 1.0` is literal noise. Either the divisor was meant to be `cell_size` (then the value is in world meters → cells, plausible) or it's leftover debugging. If `cell_size=0.5m` the feather should be 8 cells, not 4; right now it's constant 4 regardless of resolution. | Replace with `feather_cells = max(2.0, 4.0 / cell)` to feather a fixed 4-meter region. |
| BUG-R8-A2-008 | `terrain_framing.py:124-127` | MEDIUM | `pass_framing` accumulates sightline deltas with `total_delta = np.minimum(total_delta, enforce_sightline(...))` — this takes the **most aggressive cut** across all vantage×feature pairs. For N vantages × M features the call cost is O(N*M) full-tile operations; for 8 vantages × 20 hero features = 160 full-tile gauss evaluations per pass. No accumulation cap, no per-vantage budget. On 1024² tiles this is seconds of wall-clock time per tile just for framing. | Pre-rasterise vantage rays into a single sightline mask, then apply once. Or batch features sharing a vantage. Also: register a metric `sightlines_applied` is already there, just add `max_cut_m` budget (e.g., reject cuts > 20m as implausible). |
| BUG-R8-A2-009 | `terrain_framing.py:152-163` | MEDIUM | `register_framing_pass` declares `may_modify_geometry=False` but the pass body (line 131) calls `stack.set("height", new_height, "framing")`. **Height IS geometry.** This lies to `TerrainPassController` checkpoint/protection logic — protected zones that forbid `may_modify_geometry=True` passes will allow framing to carve them anyway. | Set `may_modify_geometry=True` on the PassDefinition. Same bug exists for `pass_saliency_refine` (it only modifies masks, which is correct, so `may_modify_geometry=False` is honest there). |
| BUG-R8-A2-010 | `terrain_validation.py:378-391` | MEDIUM | `validate_erosion_mass_conservation` computes `total_eroded = float(np.sum(np.abs(eros)))`. `erosion_amount` convention in `_terrain_erosion.py` is **already positive** (erosion magnitude, not signed). Taking `abs()` of already-positive values is a no-op but masks a real bug: if a future pass writes SIGNED erosion deltas (e.g., net erosion minus deposition in a single channel), `abs()` would corrupt the mass-balance check. The denominator `max(total_eroded, total_deposited, 1e-9)` also punishes asymmetric scenarios — 100 eroded vs 50 deposited is 50% imbalance but realistic for a drainage-out tile. | Document sign convention explicitly; drop `abs()`; use `abs(total_eroded - total_deposited) / (total_eroded + total_deposited + 1e-9)` for symmetric relative error. Threshold should probably be tile-aware (boundary tiles leak mass by design). |
| BUG-R8-A2-011 | `terrain_validation.py:554-587` | HIGH | `validate_unity_export_ready` checks `heightmap_raw_u16`, `splatmap_weights_layer`, `navmesh_area_id` but **not** `terrain_normals`, `physics_collider_mask`, `lightmap_uv_chart_id`, `lod_bias`, `tree_instance_points` — all of which are declared as Unity round-trip channels in `TerrainMaskStack.UNITY_EXPORT_CHANNELS` (terrain_semantics.py:485-501). The validator passes while half of the Unity manifest is empty. | Expand `required` tuple to cover every entry in `TerrainMaskStack.UNITY_EXPORT_CHANNELS` that is load-bearing for Unity import. At minimum add `terrain_normals` and `physics_collider_mask`. |
| BUG-R8-A2-012 | `terrain_validation.py:506-527` | MEDIUM | `_DTYPE_CONTRACT` is missing entries for several declared `TerrainMaskStack` channels: `cave_height_delta`, `waterfall_pool_delta`, `hero_exclusion`, `bank_instability`, `flow_direction`, `flow_accumulation`, `water_surface`, `wet_rock`, `biome_id`, `material_weights`, `roughness_variation`, `macro_color`, `audio_reverb_class`, `gameplay_zone`, `wind_field`, `cloud_shadow`, `traversability`, `strata_orientation`, `rock_hardness`, `snow_line_factor`, `sediment_accumulation_at_base`, `pool_deepening_delta`, `strat_erosion_delta`, `sediment_height`, `bedrock_height`, `coastline_delta`, `karst_delta`, `wind_erosion_delta`, `glacial_delta`, `physics_collider_mask`, `lightmap_uv_chart_id`, `lod_bias`, `tree_instance_points`, `ambient_occlusion_bake`. Roughly **34 of ~55 channels have no dtype enforcement.** A pass that writes `biome_id` as float64 instead of int would pass validation today. | Add every declared channel to the contract with its expected kind. Auto-generate the tuple from `TerrainMaskStack._ARRAY_CHANNELS` if that's the source of truth. |
| BUG-R8-A2-013 | `terrain_validation.py:295-346` | MEDIUM | `validate_tile_seam_continuity` uses `max_jump > height_span * 0.5` as a discontinuity threshold. For a vertical-cliff-heavy dark-fantasy tile (e.g., Witcher-style mountain cutoffs), a lip drop of 60% of range on a single edge is perfectly plausible terrain. The 0.5 ratio is a magic constant with no justification and will emit false-positive soft warnings whenever a hero cliff hits the tile border. | Raise the threshold to 0.8 or make it configurable via quality profile. Better: look at the **second** derivative (d²height) on the edge — real seam discontinuities spike there while cliffs just step smoothly at the pixel scale. |
| BUG-R8-A2-014 | `terrain_validation.py:820-843` | HIGH | `pass_validation_full` is the only place the 10 validators ever run, and by design it triggers rollback on hard failures. **`DEFAULT_VALIDATORS` (line 736-750) DOES NOT include `run_readability_audit` or any of the 4 readability checks.** Even after FIXPLAN 1.1 fixes the kwarg crash, the readability gate is wired to nothing — it can only be called manually from a test. The gate that supposedly enforces "cliffs readable at 100m" never runs during pipeline execution. | Either add an `("readability_audit", lambda s, i: run_readability_audit(s))` entry to `DEFAULT_VALIDATORS`, or spawn a separate `pass_readability_audit` pass and register it in Bundle D's registrar. |
| BUG-R8-A2-015 | `terrain_validation.py:803-809` | MEDIUM | `_ACTIVE_CONTROLLER` is a module-level mutable global set via `bind_active_controller`. **No unbinding on pass_validation_full completion.** A test that binds a controller, runs validation, then constructs a NEW controller for the next test will leak state — the first controller remains bound and the second will silently fail to rollback. Thread-unsafe as well. | Use a context manager: `with bind_active_controller(ctrl): report = run_validation_suite(...)`. Or pass controller explicitly to `pass_validation_full` instead of module global. |
| BUG-R8-A2-016 | `terrain_validation.py:845-853` | LOW | `consumed_channels=("height",)` on the PassResult is dishonest. `pass_validation_full` reads height, slope, curvature, erosion_amount, deposition_amount, splatmap_weights_layer, heightmap_raw_u16, navmesh_area_id, cliff_candidate, cave_candidate, waterfall_lip_candidate, + every channel in `_DTYPE_CONTRACT`. Claiming only `"height"` breaks any dependency-based scheduling that reads PassResult metadata. | Track actually-touched channels in the validators and aggregate. Minimum: list `("height", "slope", "erosion_amount", "deposition_amount", "splatmap_weights_layer", "heightmap_raw_u16", "navmesh_area_id", ...)`. |
| BUG-R8-A2-017 | `terrain_readability_bands.py:145-169` | MEDIUM | `_band_texture` builds a 3x3 box blur via 9× `np.roll` + accumulate. `np.roll` on a non-toroidal tile **wraps edges** — the last column's mean includes pixels from column 0. At tile seams, texture scores will be artificially inflated by wrap-around noise. | Use `scipy.ndimage.uniform_filter(h, size=3, mode="nearest")` which handles edges correctly. Or at minimum slice the `blurred` and `h` to inner region [1:-1, 1:-1] before computing `std`. |
| BUG-R8-A2-018 | `terrain_readability_bands.py:70-87` | MEDIUM | `_band_silhouette` uses `h.max(axis=0)` and `h.max(axis=1)` as "skyline profiles" but **only from two cardinal directions**. A tile with dramatic silhouette along the NE diagonal (classic mountain-corner composition) scores low because neither axis captures the diagonal profile. This is the "silhouette" band — the most important AAA readability metric — and it's measuring only 2 of the 8 possible camera azimuths. | Extend to 4 directions (axis-0, axis-1, and two diagonals via `np.diag`-like extraction), or accept a `vantage_points` arg and evaluate skyline from each. Minimum: compute max along both main diagonals. |
| BUG-R8-A2-019 | `terrain_readability_bands.py:162-163` | MEDIUM | `_band_texture` normalizes `std` by total `height_range = float(h.max() - h.min()) or 1.0`. For a flat plain with one tall mountain (range = 1000m, local detail = 0.5m), `normalized = 0.5/1000 = 0.0005` → score ~0.06/10. But the texture of the plain IS rich — it just doesn't compete with the mountain's absolute range. The metric conflates global amplitude with local texture. | Normalize by local-mean instead of global range. Or compute texture per-region (e.g., 64x64 blocks) and report worst/mean. |
| BUG-R8-A2-020 | `terrain_readability_bands.py:117-141` | LOW | `_band_value` computes `contrast = std / mean` on slope. **Mean slope can be ~0 for a flat plain**, and the `denom = max(mean, 1e-6)` clamp produces absurd contrast scores (e.g., std=0.01 / 1e-6 = 10000 → score pinned at 10.0). A perfectly flat tile with numerical jitter reports maximum "value" readability. | Use `std(slope)` alone, or `std / (mean + reference_mean)` where reference_mean is a fixed scale. Don't divide by something that can be zero. |
| BUG-R8-A2-021 | `terrain_readability_bands.py:172-197` | MEDIUM | `_band_color` on multi-channel macro_color computes `total_var = np.mean(per_channel)` — averaging per-channel std. This penalizes high-chroma regions: a tile that varies strongly in hue but not in luminance scores the same as a tile that varies equally on all channels. Color readability should measure CIELAB ΔE or at minimum separate luminance from chroma. | Convert to LAB, compute `np.std` on L alone for luminance band, use `sqrt(std(a)² + std(b)²)` for chroma. Or weight the per-channel std by perceptual sensitivity. |
| BUG-R8-A2-022 | `terrain_geology_validator.py:168-174` | MEDIUM | `validate_glacial_plausibility` iterates glacier path points in Python, converting world→cell per point. For a 1km glacier path with 1-meter sampling that's 1000 round-trips into `int(round(...))`. Also hardcodes `tree_line_altitude_m=1800.0` — tree line varies dramatically with latitude (e.g., 1800m at 45°N, 800m at 65°N, 3500m at 20°N). For a dark-fantasy world with multiple climate zones this is a blanket wrong number. | Vectorise via `np.asarray(path)` + single `np.round` + fancy-indexing. Source tree line from `intent.composition_hints.get("tree_line_altitude_m", ...)` or per-biome. |
| BUG-R8-A2-023 | `terrain_geology_validator.py:191-234` | LOW | `validate_karst_plausibility` hardcodes `min_hardness=0.35, max_hardness=0.75` as limestone solubility band. These are unitless rock_hardness values with no source citation. The `terrain_stratigraphy` pass produces these values — the validator should use the same constants the producer uses, not duplicate-hardcode. | Centralise the limestone hardness band in a `GEOLOGY_CONSTANTS` dict in `terrain_semantics.py` (or in `terrain_stratigraphy.py`) and import. |
| BUG-R8-A2-024 | `terrain_geology_validator.py:60-63` | MEDIUM | `validate_strata_consistency` computes 4-neighbor average via `np.roll` — same wrap-around bug as BUG-017. On tile edges the "neighbor" is the opposite edge, so strata orientation at the east edge is compared to the west edge. Plausibility check is broken at exactly the seams that matter for inter-tile geology continuity. Mitigated by line 77 `inner = angle_deg[1:-1, 1:-1]` — but only strips 1 cell per side; 4-neighbor roll contaminates 2 cells. | Strip `[2:-2, 2:-2]` or use `ndimage.generic_filter` with mode="nearest". |
| BUG-R8-A2-025 | `terrain_rhythm.py:71` | MEDIUM | `rhythm = float(np.clip(1.0 - cv, 0.0, 1.0))` — a fully-regular grid has `cv ≈ 0` → `rhythm = 1.0`. But docstring (line 43-46) claims **0.6 is the AAA target** (slightly structured). The comment says "grid" = 1.0, "random" = 0.0. That's backwards for composition — AAA wants ~0.6, so `validate_rhythm` with `min_rhythm=0.4` (line 166) accepts anything from 0.4 to 1.0, INCLUDING perfectly mechanical grids. No upper bound. Placing 100 features in a perfect 10×10 grid passes validation. | Add `max_rhythm` check: emit soft issue if `rhythm > 0.85` ("placement too mechanical — resemble a scatter grid"). Target band should be 0.4–0.75. |
| BUG-R8-A2-026 | `terrain_rhythm.py:109-132` | MEDIUM | `enforce_rhythm` runs 3 hardcoded iterations of Lloyd-like relaxation. **No convergence check.** For 3 features, 3 iterations is plenty; for 200 hero features in a large region, 3 iterations barely moves anything toward the target spacing. And the `nbrs = order[i, :3]` only considers 3 nearest neighbors — not enough to establish a stable hex lattice. | Loop until `max(|delta|) < epsilon` or cap at 30 iterations. Use 6 nearest neighbors for hex-lattice relaxation. |
| BUG-R8-A2-027 | `terrain_rhythm.py:138-156` | LOW | `enforce_rhythm` silently drops Z coordinate for dict-features: `"world_position": (float(pts[idx, 0]), float(pts[idx, 1]), float((f.get("world_position") or (0, 0, 0))[2] ...))`. If `f` has `"world_position": (x, y, z)` then `f.get("world_position")[2]` yields z → OK. If `f` has `"world_position"` absent, the whole `or (0, 0, 0)` kicks in → z=0. BUT the surrounding `if f.get("world_position")` conditional is INSIDE the `[2]` index — when `world_position` key exists but is explicit `None`, the fallback triggers, correct. Fragile chained conditional; any future refactor will break Z extraction silently. Also HeroFeatureSpec features are skipped entirely (line 139) — `idx += 1` still runs, meaning the corresponding `pts[idx]` row is unused. Wasted computation. | Rewrite as explicit `new_z = f["world_position"][2] if isinstance(f.get("world_position"), (tuple, list)) else 0.0`. Also don't increment `idx` for skipped frozen specs — use parallel list of moveable indices. |
| BUG-R8-A2-028 | `terrain_saliency.py:84-85` | MEDIUM | `sample_step = max(cell, max_dist / 256.0)` and `n_samples = max(4, int(max_dist / sample_step))`. For a 1024² tile with cell=0.5m: max_dist = 1024*1.5 = 1536m, sample_step = max(0.5, 6.0) = 6.0m. Rays sample at 6m steps → can STEP RIGHT OVER a 5m-wide cliff lip. Vantage silhouettes at AAA resolution under-sample the very features they're supposed to detect. | Scale sample_step by feature scale: `min(cell, 0.5 * min_feature_width)`. Or use DDA line rasterization for 1-cell-accurate traversal. |
| BUG-R8-A2-029 | `terrain_saliency.py:96-114` | MEDIUM | `compute_vantage_silhouettes` has a triple-nested Python loop (V × ray_count × n_samples) with per-iter `_sample_height_bilinear` Python call. For 8 vantages × 64 rays × 256 samples = **131,072 Python function calls**, each doing 4 array lookups. At typical 2x2 tile this is ~1 second; at 1024² tile it scales with `n_samples` so multi-second. Should be fully vectorised. | Vectorise: build (V, ray_count, n_samples) coordinate grid, single bilinear sample, reduce via `np.max(axis=-1)`. Cython/Numba-compatible pure-numpy formulation is straightforward. |
| BUG-R8-A2-030 | `terrain_saliency.py:283-284` | LOW-MEDIUM | `refined = np.clip(0.6 * base + 0.4 * vantage_mask, 0.0, 1.0)` — magic constants 0.6/0.4. No justification in the docstring (line 252 says "60% existing saliency + 40% vantage silhouette mask"). AAA compositors tune this per-tile based on whether the scene is panoramic (favor silhouette) or intimate (favor base). Hardcoded ratio blocks tuning. | Source from `intent.composition_hints.get("saliency_vantage_weight", 0.4)`. |
| BUG-R8-A2-031 | `terrain_saliency.py:124-191` | MEDIUM | `auto_sculpt_around_feature` is **completely unused** — not called from `pass_saliency_refine`, not exported in `__all__` of any other module, not in the registrar. Only referenced by its own `__all__` (line 323). Dead code that pretends to exist for automatic hero-sculpt nudging. | Either wire into `pass_saliency_refine` (call before the silhouette compute when silhouette for a feature is below a threshold), or delete. |
| BUG-R8-A2-032 | `terrain_twelve_step.py:340-342` | MEDIUM | Step 12 calls `validate_tile_seams(extracted_heights, atol=1e-6)` but **never checks the return value**. `seam_report` is stored in the return dict (line 356) but the orchestrator doesn't raise on failure. A seam discontinuity gets logged into the report and silently returned; any downstream test that doesn't inspect `seam_report` proceeds with broken seams. | After `seam_report = validate_tile_seams(...)`, check `if not seam_report.get("passed", True): raise RuntimeError(...)`. Or at minimum log ERROR. |
| BUG-R8-A2-033 | `terrain_readability_semantic.py:33-44` | LOW | `check_cliff_silhouette_readability` in the semantic module emits a `HARD` issue when cliff_candidate is present but slope is None. Meanwhile the same function in validation.py (line 595-618) checks cliff without requiring slope. **The two-module contract is inconsistent** — semantic version is strict, validation version is permissive. A caller can't know which version will run. (This IS related to Fix 1.2 but the SEMANTIC discrepancy — not the ValidationIssue kwargs — is not covered by the current FIXPLAN.) | After Fix 1.2 resolves, make the single surviving implementation explicit about its slope dependency and document in the function name or docstring. |
| BUG-R8-A2-034 | `terrain_readability_semantic.py:202-215` | LOW | `check_focal_composition` in semantic module asserts `d_min > 0.10` triggers a hard `FOCAL_COMPOSITION_OFF_THIRDS`. **Rule of thirds is a heuristic, not a hard law.** Centered composition ("focal point at (0.5, 0.5)") is classical landscape framing — Caspar David Friedrich's Wanderer is dead-center. Emitting a HARD (blocking) issue rejects legitimate compositions. | Downgrade to `soft`. Or make the 0.10 tolerance configurable via `intent.composition_hints["focal_tolerance"]`. |
| BUG-R8-A2-035 | `terrain_readability_semantic.py:128-168` | MEDIUM | `check_cave_framing_presence` receives `stack` as first arg but **never reads it** (line 128-168). The caves iteration is pure metadata — framing markers and damp signal come from the cave dict/object, not the mask stack. The `stack` parameter is a lie; caller thinks the function inspects terrain when it only inspects cave specs. | Remove `stack` parameter, or actually check that the `framing_markers` world positions correspond to non-zero `cliff_candidate`/`hero_exclusion` mask cells in the stack (the plausible real check). |
| BUG-R8-A2-036 | `terrain_quality_profiles.py:134-175` | MEDIUM | `_merge_with_parent` uses `max()` for numeric fields. This is the "child can only strengthen" contract. BUT `checkpoint_retention=max(...)` means a child profile that requests FEWER checkpoints (to save disk in CI) cannot. **AAA studios explicitly want `preview` profile to retain less than `production` for fast iteration.** The `preview` child inheriting from no parent is fine; but future "ci_smoke" profiles that want LESS would be impossible. Also `lock_preset=child.lock_preset or parent.lock_preset` means any locked parent permanently locks all descendants. | Rename the semantic: only erosion-quality fields (iterations, margin, bit depths) should use `max`. Retention should use `child_override if explicitly_set else max(child, parent)`. Lock propagation should be opt-in. |
| BUG-R8-A2-037 | `terrain_quality_profiles.py:199-248` | LOW | `write_profile_jsons` sandbox check (line 224-234) allows writing to either `tempfile.gettempdir()` OR `<repo>/Tools/mcp-toolkit/`. But the repo has NO `Tools/mcp-toolkit/` directory — `.mcp.json` at repo root serves that purpose. `repo_root` walks parents looking for a directory named `mcp-toolkit`; this walk NEVER finds one in this repo. **Production always falls through to tmp-only.** Any caller that wants to write profile JSON to a legitimate repo path gets rejected. | Adjust ancestor search to look for `veilbreakers_terrain` or repo root (presence of `.git`). Or remove the sandbox check if no real use case exists. |
| BUG-R8-A2-038 | `terrain_quality_profiles.py:50-60` | MEDIUM | `TerrainQualityProfile` has **no fields for**: water erosion strength, thermal erosion iterations, talus angle, river threshold, meander amplitude, min drainage area, biome-resolution threshold, scatter density per-class, LOD transition distances, grass density, tree density. **"Quality profile" in a AAA terrain pipeline means all of these** — in the current form it only scales erosion iterations + bit depths + checkpoint retention. Preview vs AAA open-world should differ in MAYBE 30 quality knobs, not 7. | Expand the dataclass. At minimum add: `thermal_erosion_iterations`, `talus_angle_deg`, `river_min_drainage_m2`, `biome_max_transition_ratio`, `grass_density_multiplier`, `tree_density_multiplier`, `lod_distance_m`. |
| BUG-R8-A2-039 | `terrain_semantics.py:836-846` | LOW | `ValidationIssue` dataclass has NO `__post_init__` to validate `severity` string. A typo like `severity="warn"` (instead of `"soft"`) silently accepts an invalid severity that `ValidationReport.add` then routes to `info_issues` (line 70-71 `else` branch). Bug reports get silently misclassified. | Add `__post_init__` that asserts `severity in ("hard", "soft", "info")`. |
| BUG-R8-A2-040 | `terrain_semantics.py:792` | LOW | `composition_hints: Dict[str, Any] = field(default_factory=dict)` on a `@dataclass(frozen=True)` — the comment "REVIEW-IGNORE PY-COR-17: frozen+mutable is safe here" acknowledges this. It IS a real footgun: two `TerrainIntentState` instances sharing a hint dict (one modifies, the other sees the change) break immutability guarantees. The pattern is used for `vantages`, `framing_clearance_m`, `unity_export_opt_out`, `road_waypoints` (per BUG-003), etc. A single leaked ref to `composition_hints` undermines the whole frozen contract. | Wrap in `types.MappingProxyType` on `__post_init__`, or convert to a `frozendict`/`tuple-of-tuples` representation. At minimum document the contract that callers MUST NOT mutate. |

---

## SHADOW FUNCTION ANALYSIS

Four shadow functions exist in `terrain_validation.py` (L595–715) that have same-named siblings in `terrain_readability_semantic.py` (L21–216). Their signatures and semantics diverge as follows:

### 1. `check_cliff_silhouette_readability`

| Aspect | validation.py:595-618 | readability_semantic.py:21-80 |
|---|---|---|
| Signature | `(stack) -> List[ValidationIssue]` | `(stack, view_distance_m: float = 100.0) -> List[ValidationIssue]` |
| Extra parameter | none | `view_distance_m` (affects error message only) |
| Slope requirement | slope is OPTIONAL (not read) | slope is REQUIRED — emits `CLIFF_READABILITY_NO_SLOPE` hard issue if missing |
| Area threshold | `cliff_area/total_area < 0.005` | `cliff_cells/total < 0.005` |
| Severity of small-footprint | `severity="warning"` (INVALID — not in ("hard","soft","info")) + `category="readability"` (INVALID kwarg) + `hard=False` (INVALID kwarg) | `severity="hard"`, `code="CLIFF_READABILITY_UNDERFOOTED"`, with remediation |
| Lip sharpness check | NONE | YES — `sharp = (stack.slope[cliff_mask] > 0.7).mean() < 0.25` → hard `CLIFF_READABILITY_SOFT_LIP` |
| Message content | Percentage of coverage | Same, plus view distance, plus lip sharpness |
| Runtime behavior | **Crashes on first hard issue** (TypeError from kwargs) | Works correctly |
| Return when no cliffs | empty list | empty list ("vacuously readable") |

**Diff:** semantic version is the complete implementation; validation.py is a broken stub with invalid kwargs and no lip-sharpness check.

### 2. `check_waterfall_chain_completeness`

| Aspect | validation.py:621-651 | readability_semantic.py:88-120 |
|---|---|---|
| Signature | `(stack) -> List[ValidationIssue]` | `(stack, chains: Sequence[Any]) -> List[ValidationIssue]` |
| What it checks | Whether `stack.waterfall_lip_candidate` has >0 cells AND corresponding `foam` and `mist` channels are populated | Iterates `chains` (external waterfall chain specs) and verifies each has `source`/`lip`/`pool`/`outflow` attributes present |
| Data source | Mask stack channels | External chain list (dict or object) |
| Issue codes | (none set in the call — `code` kwarg missing in validation.py version) | `"WATERFALL_CHAIN_INCOMPLETE"` per missing attr |
| Severity | invalid `severity="warning"` + invalid kwargs | `"hard"` with remediation |
| Can shadow substitute? | **NO — fundamentally different purpose.** Validation.py version checks foam/mist channel presence. Semantic version checks authoring chain completeness. These are non-overlapping checks. | |

### 3. `check_cave_framing_presence`

| Aspect | validation.py:654-677 | readability_semantic.py:128-168 |
|---|---|---|
| Signature | `(stack) -> List[ValidationIssue]` | `(stack, caves: Sequence[Any]) -> List[ValidationIssue]` |
| What it checks | If `cave_candidate > 0` anywhere AND `cave_height_delta` is None or all-zero → `"error"` severity, `hard=True` | For each cave, verify ≥2 framing markers AND damp_signal > 0 |
| Data source | `stack.cave_candidate`, `stack.cave_height_delta` | External caves list |
| Issue codes | invalid kwargs (no `code`) | `"CAVE_FRAMING_INSUFFICIENT"`, `"CAVE_DAMP_MISSING"` |
| Semantic version bug | N/A | BUG-035: `stack` parameter is unused — function is a pure metadata check |
| Can shadow substitute? | **NO — orthogonal checks.** Validation.py version: "did the erosion pass produce cave height deltas?". Semantic version: "are the authored caves well-framed?". | |

### 4. `check_focal_composition`

| Aspect | validation.py:680-715 | readability_semantic.py:176-216 |
|---|---|---|
| Signature | `(stack) -> List[ValidationIssue]` | `(stack, focal_point: Tuple[float, float]) -> List[ValidationIssue]` |
| What it checks | Terrain height range ≥ 1.0m AND ≥1% of cells have slope>30° | Focal point (u,v) in [0,1]^2 within 0.10 of a rule-of-thirds intersection |
| Data source | Mask stack (height, slope) | Input focal_point tuple |
| Issue codes | invalid kwargs | `"FOCAL_OUT_OF_FRAME"`, `"FOCAL_COMPOSITION_OFF_THIRDS"` |
| Severity | invalid `"warning"` + invalid kwargs | `"hard"` — see BUG-034 (should be soft) |
| Can shadow substitute? | **NO — different semantic layer.** Validation.py version: "is the terrain flat/uniform?". Semantic version: "is the camera framing rule-of-thirds compliant?". | |

### Caller-Adaptation Recommendation

Fix 1.2's "blind import" breaks `run_readability_audit(stack)` caller because 3 of 4 semantic functions require additional args (`chains`, `caves`, `focal_point`). The **correct remediation** is option (b): keep both modules, fix only the ValidationIssue kwargs in validation.py in place. The functions genuinely check different things despite sharing names.

Alternatively — and this is what an AAA studio would do — **rename** the validation.py versions to distinguish intent:
- `check_cliff_silhouette_readability` (validation) → `check_cliff_footprint_visible`
- `check_waterfall_chain_completeness` (validation) → `check_waterfall_foam_mist_populated`
- `check_cave_framing_presence` (validation) → `check_cave_height_delta_applied`
- `check_focal_composition` (validation) → `check_terrain_has_visual_interest`

Then both modules coexist without name collision and semantic drift is impossible.

---

## CALLER AUDIT

Every call site where `terrain_validation.py` touches `terrain_readability_semantic.py` or where the 4 readability checks are invoked.

### Call sites in `terrain_validation.py`

| Line | Callsite | Called function | Called signature in validation.py | Called signature in semantic module | Match? |
|---|---|---|---|---|---|
| 723 | `run_readability_audit(stack)` | `check_cliff_silhouette_readability(stack)` | validation.py L595: `(stack)` | semantic L21: `(stack, view_distance_m=100.0)` | PARTIAL — calling convention works because view_distance defaults, BUT validation.py's version is the one invoked (closest-scope binding). Semantic version never reached via this path. |
| 724 | `run_readability_audit(stack)` | `check_waterfall_chain_completeness(stack)` | validation.py L621: `(stack)` | semantic L88: `(stack, chains)` — required positional | **BROKEN if caller switches to semantic version.** Fix 1.2 blind-import breaks at runtime with `TypeError: missing 1 required positional argument: 'chains'`. |
| 725 | `run_readability_audit(stack)` | `check_cave_framing_presence(stack)` | validation.py L654: `(stack)` | semantic L128: `(stack, caves)` — required positional | **BROKEN if caller switches.** Same TypeError. |
| 726 | `run_readability_audit(stack)` | `check_focal_composition(stack)` | validation.py L680: `(stack)` | semantic L176: `(stack, focal_point)` — required positional | **BROKEN if caller switches.** Same TypeError. |

### Does `terrain_validation.py` currently import from `terrain_readability_semantic`?

NO. There is NO `from .terrain_readability_semantic import ...` anywhere in `terrain_validation.py`. The shadow is purely name-collision-by-definition, not name-collision-by-import. The two modules are independent; no symbol resolution conflict exists. The "shadow" is semantic duplication, not Python-level shadowing.

### Callers of the aggregate

`run_readability_audit(stack)` — called by:
- `terrain_validation.py:904` (in `__all__` — exported but unused)
- Tests: `veilbreakers_terrain/tests/test_terrain_validation.py` (inferred from GRADES_VERIFIED references, not directly confirmed in this audit scope)

`pass_validation_full` (`terrain_validation.py:812-853`) — the only Bundle D pass registered — **does NOT call `run_readability_audit`**. It only invokes `run_validation_suite` which runs `DEFAULT_VALIDATORS` (the 10 structural validators, no readability checks).

### Callers of the semantic module aggregate

`run_semantic_readability_audit(stack, *, chains=None, caves=None, focal=None)` — called by:
- `veilbreakers_terrain/tests/test_bundle_egjn_supplements.py:329` (single test call)
- No production callers.

**Conclusion:** Both aggregators are dead in production. Only tests exercise them. Fix 1.1 (kwarg fix) makes `run_readability_audit` runnable; BUG-014 (wire into `DEFAULT_VALIDATORS`) makes it actually execute during pipeline runs.

---

## SEMANTIC PIPELINE GAPS

What knowledge is missing from the semantic pipeline for an AI agent to generate AAA natural terrain?

### What EXISTS in terrain_semantics.py

Data contracts: `TerrainMaskStack` (55 channels), `TerrainIntentState`, `HeroFeatureSpec`, `WaterSystemSpec`, `ProtectedZoneSpec`, `TerrainAnchor`, `BBox`, `HeroFeatureBudget`, `TerrainSceneRead`, `TerrainCheckpoint`, `PassDefinition`, `PassResult`, `QualityGate`, `ValidationIssue`, `TerrainPipelineState`. Plus enums (`ErosionStrategy`) and transforms (`WorldHeightTransform`, `SectorOrigin`).

This is a solid **mechanical** contract. An agent can emit a stack and validate schema conformance.

### What is MISSING for AAA agent reasoning

1. **No biome taxonomy.** `biome_id: Optional[np.ndarray]` exists but there's no enum/dict mapping IDs → biome names, climate range, typical slope, typical elevation, characteristic flora, characteristic waterfall count, characteristic cave frequency. An AI agent asked "generate a dark-fantasy moor" has no grounding to output biome_id=7 means moor.
2. **No landform taxonomy.** `TerrainSceneRead.major_landforms: Tuple[str, ...]` — free-form strings. No canonical list. Agent can't validate whether "escarpment" vs "scarp" vs "cliff-face" are synonyms or distinct.
3. **No "what makes terrain good" rules.** There's a readability BAND system (silhouette/volume/value/texture/color) but no DESIGN RULES. Examples of missing rules:
   - "Every hero cliff must have a supporting mid-ground ridge within 50m to anchor the eye"
   - "Waterfall lip + pool + outflow triangle must form an angle between 60° and 120°"
   - "Cave entrance should sit at the base of a cliff, not on a plateau"
   - "Rule of thirds for focal points" — this IS in semantic module but as a HARD gate (BUG-034), not guidance
   - "Feature spacing should follow Voronoi-perturbed regularity (rhythm ~0.6)"
4. **No material plausibility rules.** `MaterialCoverage` validator (L458-501) checks weights sum=1 and no single layer > 80%. Nothing checks "sand should not appear on slopes > 35°" or "snow should not appear below snow_line_factor=0". Geologically-coherent material zoning is unvalidated.
5. **No hero hierarchy/tier rules.** `HeroFeatureSpec.tier` is a free string ("secondary" default). No canonical tiers (PRIMARY/SECONDARY/TERTIARY) and no rule "every tile of type X should have 1 PRIMARY + 2-4 SECONDARY features".
6. **No scale/composition guidance.** Nothing tells the agent "mountain ridges should be 40-60% of tile width" or "valley floors should occupy 15-25% of the tile area". The rhythm metric is feature-placement only, not landform mass ratios.
7. **No negative-space rules.** `terrain_negative_space.py` exists (found via grep) but there is no field on `TerrainIntentState` like `negative_space_ratio_target: float` for agents to target.
8. **No camera/vantage linkage to intent.** `TerrainIntentState.composition_hints` is a free dict with `vantages`, `framing_clearance_m` — both consumed by `pass_framing`/`pass_saliency_refine`. No typed field for camera specs, FOV, primary vs secondary vantage, screenspace composition target.
9. **No quality-profile semantic expansion.** Per BUG-038, profiles are 7 knobs — a fraction of what "AAA quality" means. An agent selecting `aaa_open_world` thinks it's getting AAA settings; it's getting hero-shot erosion iterations and nothing else.
10. **No narrative/gameplay semantics.** This is a DARK FANTASY game. There's no field for `tension_gradient: Callable[...]` (terrain should feel more oppressive toward the boss arena), `lighting_intent: str` (overcast/golden-hour/storm), `audio_character: str` (haunted/hushed/roaring). `gameplay_zone` channel exists but its values are unspecified.
11. **No "what the player experiences" metadata.** No traversal-time estimates, no line-of-sight continuity from the player's path to major landmarks, no wayfinding beacons encoded in the mask stack.
12. **No reference-image or style-anchor mechanism.** AAA terrain agents like Gaia / Mapping / UE5 PCG get a reference image or style target. `TerrainIntentState` has no `style_reference_image_path` or `mood_board_hash`.
13. **No cross-tile composition rules.** Validators run per-tile. No rule "adjacent tiles must agree on landform type within the boundary 20%" beyond seam continuity (which is numerical, not semantic).
14. **No feature occlusion/line-of-sight contract.** Hero features should be visible from authored vantages. `silhouette_vantages: Tuple[...]` is on `HeroFeatureSpec` but no validator checks that the feature IS visible from those vantages after erosion runs. Frames can carve away the feature and the test doesn't fire.
15. **`ValidationReport` carries no "how to explain this to the agent" field.** Just code + severity + message + remediation. No confidence score, no alternative-fix ranking, no "if you ignore this, downstream impact is X". For autonomous agent iteration this is thin.

### Score

Against a AAA studio's terrain-semantics layer (e.g., Rockstar's RAGE terrain DSL, Ubisoft Anvil's biome grammar, Unity HDRP terrain with Mapbox-style rules): this module is a **B+ on mechanics, D on design knowledge**. The data plumbing is clean; the design rules are nearly absent.

---

## QUALITY PROFILE ASSESSMENT

Are the quality thresholds AAA-realistic? What should they be?

### What the current profiles define

| Field | preview | production | hero_shot | aaa_open_world |
|---|---|---|---|---|
| erosion_iterations | 2 | 8 | 24 | 48 |
| erosion_strategy | TILED_PADDED | TILED_PADDED | EXACT | EXACT |
| checkpoint_retention | 5 | 20 | 40 | 80 |
| erosion_margin_cells | 4 | 8 | 16 | 32 |
| splatmap_bit_depth | 8 | 8 | 16 | 16 |
| heightmap_bit_depth | 16 | 16 | 32 | 32 |
| shadow_clipmap_bit_depth | 8 | 8 | 16 | 16 |

### Are these AAA-realistic?

**Partially.** The direction of scaling is correct (higher profile = more iterations, higher bit depth, bigger margin). The absolute values are plausible for the listed knobs. But:

1. **erosion_iterations:** AAA open-world titles (Horizon Forbidden West, Red Dead Redemption 2, Witcher 3) use **500–5000 hydraulic iterations** per world region for hero shots, not 48. World Machine / Gaea presets for "final" quality are 3000+. A value of 48 is "middle preview". The profile mislabels a preview-grade setting as AAA.
2. **erosion_strategy=EXACT for AAA:** CORRECT in principle — bit-exact seams require non-tiled erosion. But `EXACT` is memory-prohibitive at AAA tile counts (~512+ tiles). Real AAA pipelines use `TILED_DISTRIBUTED_HALO` (the third enum value, **never used by any profile**). The profile infrastructure supports the enum but doesn't exercise it. AAA open-world should be `TILED_DISTRIBUTED_HALO`, not `EXACT`.
3. **bit depths:** `heightmap_bit_depth=32` for AAA is float32 heightmap, correct. `splatmap_bit_depth=16` is generous (Unity Terrain default is 8-bit weights). `shadow_clipmap_bit_depth=16` suggests clipmap resolution not bit depth — the name is confusing.
4. **Missing knobs** (see BUG-038): no water-quality, no scatter density, no LOD, no biome-transition smoothing, no cliff detail level. A "quality profile" that doesn't control grass density is not a quality profile in the AAA sense.
5. **Numeric flat-ratio scaling:** preview has 2 iterations, production 8 (4x), hero 24 (3x), AAA 48 (2x). The scaling factor is monotonically DECREASING. For a "dramatic step up" to AAA, the final tier should jump to 100+ (~2x hero_shot at least), not 48 (~2x).
6. **`checkpoint_retention=80` for AAA:** reasonable for a complex pipeline. Preview's 5 is too low — any multi-step iteration burns through those quickly.
7. **No `max_wall_time_seconds` or `max_memory_gb` budget:** AAA profiles always carry resource caps. A preview run should abort after 30s, an AAA run can take 2 hours. No profile enforces this.

### What they SHOULD be (AAA baseline, using Horizon/RDR2/Witcher 3 as reference)

```python
# preview — sub-30-second iteration for artist scrubs
erosion_iterations=50
erosion_strategy=TILED_PADDED
hydraulic_strength=0.3  # new
thermal_iterations=0
talus_angle_deg=45.0
river_min_drainage_m2=5000.0
grass_density_multiplier=0.1
tree_density_multiplier=0.2
lod_distance_m=80.0
checkpoint_retention=3
max_wall_time_s=45.0
max_memory_gb=4.0

# production — per-level standard
erosion_iterations=500
erosion_strategy=TILED_PADDED
hydraulic_strength=0.5
thermal_iterations=100
talus_angle_deg=42.0
river_min_drainage_m2=2000.0
grass_density_multiplier=0.7
tree_density_multiplier=0.8
lod_distance_m=250.0
checkpoint_retention=20
max_wall_time_s=600.0
max_memory_gb=16.0

# hero_shot — cinematic sequences
erosion_iterations=2500
erosion_strategy=EXACT
hydraulic_strength=0.6
thermal_iterations=500
talus_angle_deg=40.0
river_min_drainage_m2=1000.0
grass_density_multiplier=1.0
tree_density_multiplier=1.0
lod_distance_m=400.0
checkpoint_retention=50
max_wall_time_s=3600.0
max_memory_gb=32.0

# aaa_open_world — full world streaming
erosion_iterations=5000
erosion_strategy=TILED_DISTRIBUTED_HALO  # note: different from EXACT
hydraulic_strength=0.6
thermal_iterations=1000
talus_angle_deg=38.0
river_min_drainage_m2=500.0
grass_density_multiplier=1.0
tree_density_multiplier=1.0
lod_distance_m=500.0
checkpoint_retention=100
max_wall_time_s=14400.0   # 4 hours
max_memory_gb=64.0
```

**Verdict:** current profiles are labelled correctly (the tier names are right) but the NUMBERS and the SET OF KNOBS are roughly **preview / preview+ / production / production+**, not preview through AAA. A VeilBreakers dev picking `aaa_open_world` gets production-tier output.

---

## GRADE CORRECTIONS NEEDED

Based on this audit, the following grades in `GRADES_VERIFIED.csv` should be updated:

| Function | File | Line | Current Grade | Suggested Grade | Reason |
|---|---|---|---|---|---|
| `validate_unity_export_ready` | terrain_validation.py | 554 | (check prior) | B- | BUG-011: only checks 3 of 10+ Unity export channels; half the Unity contract unvalidated |
| `validate_channel_dtypes` | terrain_validation.py | 530 | (check prior) | C+ | BUG-012: 34+ channels have no dtype contract; dtype drift invisible to validation |
| `validate_tile_seam_continuity` | terrain_validation.py | 295 | (check prior) | B- | BUG-013: 0.5 threshold false-positives on legitimate cliff tiles |
| `validate_erosion_mass_conservation` | terrain_validation.py | 349 | (check prior) | B | BUG-010: `abs()` on already-positive channel is defensive but misleading; threshold asymmetric |
| `run_readability_audit` | terrain_validation.py | 718 | F | F (already) | No change — BUG-014 adds: even after kwarg fix, not wired into DEFAULT_VALIDATORS. Still effectively dead. |
| `pass_validation_full` | terrain_validation.py | 812 | (check prior) | B- | BUG-014 (readability not run), BUG-015 (global controller leak), BUG-016 (consumed_channels lie) |
| `register_bundle_d_passes` | terrain_validation.py | 861 | A | B+ | BUG-014 corollary — registers only validation_full, not readability_audit. Half the Bundle-D promise unfulfilled. |
| `_band_silhouette` | terrain_readability_bands.py | 70 | (check prior) | C+ | BUG-018: measures 2 of 8 azimuths; diagonal compositions silently under-scored |
| `_band_value` | terrain_readability_bands.py | 117 | (check prior) | C | BUG-020: /max(mean,1e-6) produces absurd scores on flat terrain |
| `_band_texture` | terrain_readability_bands.py | 144 | (check prior) | C+ | BUG-017 (np.roll wrap-around) + BUG-019 (global-range normalization hides local detail) |
| `_band_color` | terrain_readability_bands.py | 172 | (check prior) | C+ | BUG-021: per-channel std average is not perceptually meaningful |
| `check_cliff_silhouette_readability` | terrain_readability_semantic.py | 21 | (prior A- ~) | A- | Correct implementation; matches known spec |
| `check_waterfall_chain_completeness` | terrain_readability_semantic.py | 88 | (prior A-) | A- | Correct |
| `check_cave_framing_presence` | terrain_readability_semantic.py | 128 | (prior A-) | B+ | BUG-035: `stack` parameter unused → false advertising in signature |
| `check_focal_composition` | terrain_readability_semantic.py | 176 | (prior A-) | B | BUG-034: hard severity for rule-of-thirds deviation is over-strict |
| `run_semantic_readability_audit` | terrain_readability_semantic.py | 224 | A- | A- | No change — correctly aggregates |
| `validate_strata_consistency` | terrain_geology_validator.py | 26 | (prior A?) | B | BUG-024: np.roll wrap-around contaminates inner region insufficient strip |
| `validate_glacial_plausibility` | terrain_geology_validator.py | 146 | (prior A?) | B | BUG-022: hardcoded tree line + O(N) Python loop |
| `validate_karst_plausibility` | terrain_geology_validator.py | 191 | (prior A?) | B+ | BUG-023: hardcoded limestone band, should centralize constants |
| `run_twelve_step_world_terrain` | terrain_twelve_step.py | 207 | B+ | C+ | BUG-001 (erosion_params ignored), BUG-002 (quality profile ignored), BUG-006 (hardcoded test-speed iteration), BUG-032 (seam_report silently discarded) |
| `_apply_flatten_zones_stub` | terrain_twelve_step.py | 42 | (prior - stub) | F (honest stub) | Known stub; no-op is flagged in docstring. Audit confirms stub is unwired: BUG-003 — intent has no flatten_zones field either. Entire step 4 is dead. |
| `_apply_canyon_river_carves_stub` | terrain_twelve_step.py | 47 | (prior - stub) | F (honest stub) | Same — step 5 is dead. |
| `_detect_cave_candidates_stub` | terrain_twelve_step.py | 68 | (prior -) | D | BUG-004 — O(N) Python loop; plateau false-positives |
| `_generate_road_mesh_specs` | terrain_twelve_step.py | 97 | (prior - "real A*") | D+ | BUG-005 — produces graded_hmap but throws it away. Road generation without road carving = cosmetic only. |
| `_generate_water_body_specs` | terrain_twelve_step.py | 146 | (prior - "real") | B | Correct shape; threshold 0.7 of max is arbitrary (BUG-tbd magic constant) but reasonable. Doesn't write water surface back to any tile. |
| `pass_framing` | terrain_framing.py | 87 | (prior A-?) | B | BUG-007 (feather_cells dead expression), BUG-008 (O(N*M) performance), BUG-009 (may_modify_geometry lie) |
| `enforce_sightline` | terrain_framing.py | 27 | (prior -) | B+ | Correctly additive, feathered, idempotent within pass. Same feather_cells bug as BUG-007. |
| `register_framing_pass` | terrain_framing.py | 149 | A | B | BUG-009 — may_modify_geometry=False is incorrect; height is geometry. |
| `pass_saliency_refine` | terrain_saliency.py | 245 | (prior -) | B | BUG-028 (ray under-sampling), BUG-029 (O(N³) Python loop), BUG-030 (magic 0.6/0.4 blend) |
| `compute_vantage_silhouettes` | terrain_saliency.py | 66 | (prior -) | C+ | BUG-029 — full Python loops over 131k iterations on standard tile |
| `auto_sculpt_around_feature` | terrain_saliency.py | 124 | (prior -) | F (unused) | BUG-031 — dead code; not called from any registered pass |
| `register_saliency_pass` | terrain_saliency.py | 302 | A- | A- | No change |
| `analyze_feature_rhythm` | terrain_rhythm.py | 37 | (prior -) | B+ | Clean implementation; correct nearest-neighbor CV approach |
| `enforce_rhythm` | terrain_rhythm.py | 91 | B+ | B- | BUG-026 (no convergence check; 3 hardcoded iters inadequate for >10 features), BUG-027 (silent Z-coord drop) |
| `validate_rhythm` | terrain_rhythm.py | 163 | (prior -) | B | BUG-025 — accepts `rhythm=1.0` (perfect grid), no upper bound on mechanical-looking placements |
| `TerrainQualityProfile` | terrain_quality_profiles.py | 38 | (prior A?) | C+ | BUG-038 — only 7 knobs for "quality" in an AAA terrain pipeline; missing 20+ load-bearing fields |
| `_merge_with_parent` | terrain_quality_profiles.py | 134 | (prior -) | B- | BUG-036 — `max()` semantics prevent legitimate child overrides (CI smoke profile can't request fewer checkpoints) |
| `write_profile_jsons` | terrain_quality_profiles.py | 199 | (prior -) | B- | BUG-037 — sandbox path search targets non-existent `Tools/mcp-toolkit` directory in this repo; always falls through to tmp only |
| `ValidationIssue` | terrain_semantics.py | 836 | (prior -) | B | BUG-039 — no `__post_init__` severity validation; typos route to info bucket silently |
| `TerrainIntentState` | terrain_semantics.py | 771 | (prior -) | B+ | BUG-040 — `composition_hints` mutable dict on frozen dataclass; documented footgun that loses immutability guarantees |
| `TerrainMaskStack` | terrain_semantics.py | 200 | (prior A?) | A- | Strong data contract. Clean hash, clean serialization, well-documented Unity export. Only nit is the channel explosion (55+) without grouping sub-contracts. |

---

## TWELVE-STEP PIPELINE ASSESSMENT

Does `terrain_twelve_step.py` implement a complete, ordered 12-step terrain generation?

**Step-by-step status:**

| Step | Status | Quality |
|---|---|---|
| 1. parse_params | REAL | B — correct validation, error on grid<1 or tile_size<=0 |
| 2. compute_world_region | REAL | A — trivial but correct |
| 3. generate_world_heightmap | REAL | B — calls production function, but `terrain_type="mountains"` hardcoded (not sourced from intent) |
| 4. apply_flatten_zones | **STUB / PASS-THROUGH** | F — `_apply_flatten_zones_stub` returns input unchanged. Intent has no `flatten_zones` field anyway (BUG-003 pattern). Step is dead. |
| 5. apply_canyon_river_carves | **STUB / PASS-THROUGH** | F — Same. Step is dead. |
| 6. erode_world_heightmap | REAL (degraded) | C — BUG-001/002/006 — quality profile + erosion_params both ignored; test-speed hardcoded |
| 7. compute_flow_map | REAL | B — uses erosion result's flow_map when present, fallback to recomputation |
| 8. detect_hero_candidates | REAL (weak) | D — BUG-004: detect_cave_candidates has plateau false-positives + O(N) loop. Others threshold-based and crude |
| 9. per_tile_extract | REAL | A- — correct extraction, builds TileTransform correctly, Z bounds derived from tile min/max |
| 10. generate_road_meshes | REAL (but useless) | D — BUG-003 (intent.road_waypoints doesn't exist → always empty path), BUG-005 (graded_hmap thrown away) |
| 11. generate_water_bodies | REAL (shallow) | B- — detects high-accumulation cells as water candidates; doesn't write water surfaces back to tiles |
| 12. validate_tile_seams | REAL (but ignored) | C — BUG-032: seam_report produced but never checked as a gate |

**Dead steps:** 4, 5 (stubs admit this in docstring).
**Zombie steps:** 10 (real function never runs due to missing intent field).
**Undone gates:** 12 (validator runs but no raise).
**Configuration-ignored:** 6 (erosion_iterations, erosion_params, quality_profile all bypassed).

**Overall 12-step honesty:** roughly **6 of 12 steps do meaningful work** as wired. The remaining 6 are stubs, zombies, or degraded.

---

## SUMMARY OF NEW BUGS

Total new bugs discovered: **40** (BUG-R8-A2-001 through BUG-R8-A2-040).

By severity:
- HIGH / BLOCKER: 4 (BUG-001, BUG-002, BUG-011, BUG-014)
- MEDIUM: 22
- LOW / LOW-MEDIUM: 14

By file:
- `terrain_twelve_step.py`: 6 bugs (BUG-001 through BUG-006, BUG-032) — the most-broken file in scope
- `terrain_validation.py`: 7 bugs (BUG-010 through BUG-016)
- `terrain_readability_bands.py`: 5 bugs (BUG-017 through BUG-021)
- `terrain_geology_validator.py`: 3 bugs (BUG-022 through BUG-024)
- `terrain_rhythm.py`: 3 bugs (BUG-025 through BUG-027)
- `terrain_saliency.py`: 4 bugs (BUG-028 through BUG-031)
- `terrain_framing.py`: 3 bugs (BUG-007 through BUG-009)
- `terrain_quality_profiles.py`: 3 bugs (BUG-036 through BUG-038)
- `terrain_semantics.py`: 2 bugs (BUG-039, BUG-040)
- `terrain_readability_semantic.py`: 2 bugs (BUG-033, BUG-034, BUG-035)

By category:
- Dead code / unused parameter: 5 (BUG-003, BUG-007 partial, BUG-027 partial, BUG-031, BUG-035)
- Wrong/hardcoded constants: 7 (BUG-002, BUG-006, BUG-013, BUG-022, BUG-023, BUG-030, BUG-038)
- Performance bugs: 4 (BUG-004, BUG-008, BUG-022 partial, BUG-029)
- Correctness bugs: 10 (BUG-001, BUG-005, BUG-010, BUG-011, BUG-012, BUG-014, BUG-015, BUG-017, BUG-020, BUG-024, BUG-025, BUG-026, BUG-028, BUG-032)
- Contract lies: 5 (BUG-009, BUG-016, BUG-033, BUG-035, BUG-039)
- Schema/design gaps: 6 (BUG-034, BUG-036, BUG-037, BUG-038, BUG-040, plus pipeline-gap section above)

Top 5 priority fixes:
1. **BUG-014** — Wire `run_readability_audit` into `DEFAULT_VALIDATORS`. The readability gate is disconnected in production.
2. **BUG-002 / BUG-006** — Plumb quality_profile.erosion_iterations into `erode_world_heightmap`. Currently preview=AAA output.
3. **BUG-005** — Write `graded_hmap` back to world_eroded after road generation. Roads don't carve.
4. **BUG-011** — Expand `validate_unity_export_ready` to cover all 10+ Unity channels.
5. **BUG-038** — Expand `TerrainQualityProfile` to 20+ AAA-relevant knobs.
