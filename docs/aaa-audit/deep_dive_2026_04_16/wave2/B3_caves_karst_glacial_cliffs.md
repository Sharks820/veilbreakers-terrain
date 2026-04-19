# B3 — Caves / Karst / Glacial / Cliffs — Deep Re-Audit (Wave 2)

## Date: 2026-04-16
## Auditor: Opus 4.7 ultrathink (max reasoning, 1M context)
## Scope: 4 files, 35 functions
- `veilbreakers_terrain/handlers/terrain_caves.py` (1246 lines, 22 functions/methods)
- `veilbreakers_terrain/handlers/terrain_karst.py` (266 lines, 5 functions + 1 dataclass post-init)
- `veilbreakers_terrain/handlers/terrain_glacial.py` (316 lines, 6 functions)
- `veilbreakers_terrain/handlers/terrain_cliffs.py` (699 lines, 12 functions + 2 dataclasses)

## Method
- AST enumeration (`ast.walk(tree)`) — every function/method graded.
- Read every line of each function before grading.
- Cross-referenced **prior grades** in `docs/aaa-audit/GRADES.csv` and `TERRAIN_UPGRADE_MASTER_AUDIT.md` (Sections 4, 5, 7, 8, 9, Appendix B.4, Appendix C, Appendix D.3).
- AAA reference baseline: Houdini Heightfield + Voxel SOPs, UE5 Voxel Plugin / Voxel Farm, Megascans cliff scans, RDR2 cave authoring (GDC 2019 talk), Elden Ring cliff stratification, scikit-image marching cubes, scipy.ndimage (label, distance_transform_edt, binary_dilation, minimum_filter), Worley/3D Perlin for chamber noise.

## Distribution (35 functions)
**A = 0, A- = 4, B+ = 5, B = 9, B- = 7, C+ = 6, C = 2, D = 1, F = 1.**

This is the **worst-graded module group in the audit so far** — caves and cliffs collectively earn a B-/C+ aggregate against AAA. The infrastructure (archetype enum, pass wiring, validation hooks) is honest A-/B+ — the **geometry is fundamentally 2D heightmap-only** and that costs the entire module group its claim to AAA. Hidden 6-face chamber boxes (caves), point-cloud lip "polylines" (cliffs), and a flat-bottom U-valley that depends on a quadruple-nested Python loop (glacial) drag everything down.

## Top 5 worst (blocker / serious bugs)

1. **`terrain_karst.py:100` — `h.ptp()` BREAKING NumPy ≥2.0** — confirmed by master BUG-36 (still present on HEAD as of this audit, line 100). `ndarray.ptp()` was removed in NumPy 2.0; `numpy.ptp(h)` or `h.max() - h.min()` is required. This will hard-crash `pass_karst` on any modern install. **F-severity at the module level even if the function is otherwise C+.**
2. **`terrain_caves.py:1079` — `_build_chamber_mesh` is a hidden 6-face box.** This is exactly the "F = placeholder" example in the rubric prompt. The chamber is invisible (compose_map sets `visibility=False`), its only role is "marker / parent". You promised AAA caves; you ship 8 verts and 6 quads and hide them. **F.**
3. **`terrain_cliffs.py:188` — `carve_cliff_system` returns 2D heightmap face_mask only, no overhang carve, no stratification, no fault-plane offset.** Real Elden Ring / RDR2 cliffs have horizontal sedimentary strata, vertical jointing, talus chutes, and overhangs. This produces flat triangular cliff slabs from steep slope cells. **C.**
4. **`terrain_cliffs.py:147` — `_label_connected_components` is 250+ line Python BFS for what scipy.ndimage.label does in 1 C call.** Master AAA D.3 ranks this #3 priority (50-200× speedup). On a 4096×4096 tile with a 100k-cell cliff cluster the BFS pushes ~800k tuples through a Python list. **C+.**
5. **`terrain_glacial.py:47` — `carve_u_valley` is a quadruple-nested Python loop** computing per-cell minimum distance to a dense path point cloud. For a 60-meter wide, 200-meter long U-valley at cell_size=1m that's ~60×200 cells × 200 path samples = 2.4M Python iterations. Should be `scipy.ndimage.distance_transform_edt(~path_mask)`. **C.**

## Top 3 best

1. **`terrain_caves.py:152` — `make_archetype_spec`** — A. Clean factory pattern over a frozen archetype-default table; the per-archetype defaults table is genuinely tuned (lava-tube vs sea-grotto have different damp_intensity, ceiling_irregularity, occlusion_shelf_depth — these are the right parameters in the right ranges). This is the strongest function in the module group.
2. **`terrain_caves.py:618` — `generate_damp_mask`** — A-. Properly vectorized `np.mgrid` per waypoint with max-merge across multiple caves and existing wet_rock preservation. Linear falloff is OK for a damp signal. The only ding is no downslope bias.
3. **`terrain_glacial.py:168` — `compute_snow_line`** — A-. Genuinely vectorized: snow line ramp + slope-shedding penalty with proper broadcasting; no Python loops; respects optional `slope` channel; clamps without violating Rule 10 (the clamp is on the [0,1] factor, not on world heights).

---

# terrain_caves.py (22 functions, 1246 lines)

## `class CaveArchetype` (line 49) — Grade: A
**Prior grade:** not in CSV (enum-only). 
**What it does:** Five-value `str, Enum` for archetypes (LAVA_TUBE, FISSURE, KARST_SINKHOLE, GLACIAL_MELT, SEA_GROTTO).
**Reference:** Houdini's `cave_type` attribute on the cave SOP, RDR2's authored cave manifest. 
**Bug/Gap:** none. Five archetypes is a defensible spread (not 1, not 25). 
**AAA gap:** Skyrim's CK has `Falmer/Frostbite/IceCave/DwarvenRuin/MossyCave/SteamCave` — 6+ types with material slots. Megascans cave kit has 8. Five is the floor of acceptable.
**Severity:** none.
**Upgrade to A+:** add MOSS_GROTTO + LIMESTONE_CHAMBER (with stalactites) — 7 archetypes is RDR2-parity.

## `class CaveArchetypeSpec` (line 72) — Grade: B+
**Prior grade:** none directly (parent of `make_archetype_spec`).
**What it does:** Frozen dataclass holding per-archetype parameters. 13 fields, two of which (`ambient_light_factor`, `sculpt_mode`) are dead per master Section 8 LOW.
**Reference:** Houdini cave archetype attribute set; UE5 PCG element parameter struct.
**Bug/Gap:** **2 dead fields** (`ambient_light_factor`, `sculpt_mode`) — declared but read by NOBODY in the cave subsystem. Confirmed by grep across all caves/depth/entrance/atmospheric handlers — `ambient_light_factor` only appears in the spec dict and CSV docstring. Dead spec.
**AAA gap:** missing material_slot, light_emitter_kind, decal_kit_id — needed for Tripo/Quixel ingest.
**Severity:** polish.
**Upgrade to A:** wire `ambient_light_factor` to `pass_atmospheric_volumes` for cave ambient light placement; remove or wire `sculpt_mode`.

## `make_archetype_spec` (line 152) — Grade: A
**Prior grade:** A- (R3 Codex), A (Gemini) — **AGREE** with A.
**What it does:** Returns a `CaveArchetypeSpec` preloaded from `_ARCHETYPE_DEFAULTS[archetype]`, applying overrides that aren't `None`.
**Reference:** classic factory; equivalent to UE5 `UDataAsset` clone-with-overrides.
**Bug/Gap:** none — `params.update({k: v for k, v in overrides.items() if v is not None})` correctly handles the "no override" case.
**Severity:** none.
**Upgrade to A+:** validate that overrides are valid CaveArchetypeSpec field names (currently silently drops typos).

## `class CaveStructure` (line 168) — Grade: B+
**Prior grade:** not in CSV.
**What it does:** Mutable dataclass aggregating cave_id, archetype, spec, world position, path, masks, height delta, debris points, tier, cell_count.
**Reference:** analogous to `CliffStructure` in Bundle B.
**Bug/Gap:** `interior_mask: Optional[np.ndarray] = None` is **always None** in `pass_caves` (`interior_mask=None,` line 839) — never populated. The "interior" is in `cave_candidate` (the stack channel) but the per-cave reference is dead.
**AAA gap:** missing `material_slots`, `audio_zone_id`, `light_emitters`. Houdini's cave node attaches these per-component.
**Severity:** polish.
**Upgrade to A-:** fix the interior_mask wiring or delete the field; add Quixel material slot reference.

## `_world_to_cell` (line 190) — Grade: B
**Prior grade:** A- (consensus) — **DISPUTE downward to B**.
**What it does:** Round-and-clamp world (x,y) → grid (row, col).
**Reference:** baseline coord transform.
**Bug/Gap:** **CONFLICT-03 (master Section 7).** Uses `int(round(...))` while `terrain_waterfalls.py:130-131` uses `int(...)` (floor) and `_water_network.py:424` uses cell-corner not cell-center. Net **2-meter drift per handoff at cell_size=4m** when caves hand off cave_candidate to waterfalls. This is one of 6 implementations of the same primitive.
**AAA gap:** Houdini and UE Landscape have ONE coordinate transform per project; this codebase has 6.
**Severity:** important.
**Upgrade to A-:** consolidate to `terrain_coords.world_to_cell` (master Section 7 Recommended Utility 1).

## `_cell_to_world` (line 202) — Grade: A-
**Prior grade:** A — **AGREE within ±1**.
**What it does:** Cell-center (col+0.5, row+0.5) × cell_size + world_origin.
**Reference:** Houdini grid sample center.
**Bug/Gap:** Correct. The +0.5 cell-center convention is the right one (matches `terrain_waterfalls.py:118`); but `_world_to_cell` above does NOT have the matching -0.5 offset. **Round-trip is broken** — `_cell_to_world(_world_to_cell(x,y))` is shifted by ½ cell.
**Severity:** important (the round-trip bug is the bug, not this function alone).
**Upgrade to A:** fix `_world_to_cell` to subtract 0.5 first.

## `_region_to_slice` (line 210) — Grade: A
**Prior grade:** A — **AGREE**.
**What it does:** Trivial pass-through to `BBox.to_cell_slice`.
**Reference:** standard.
**Bug/Gap:** none.

## `_protected_mask_for_caves` (line 221) — Grade: B+
**Prior grade:** B+ — **AGREE**.
**What it does:** Builds an OR-aggregate per-cell mask of every protected zone that does NOT permit "caves".
**Reference:** RDR2-style protected zones.
**Bug/Gap:** rebuilds the meshgrid every call (line 232-233). Caches `xs`, `ys`, `xg`, `yg` would be cheap.
**AAA gap:** Houdini caches the protected-zone footprint per scene-revision — this rebuilds per pass.
**Severity:** polish.
**Upgrade to A-:** memoize meshgrid by (rows, cols, world_origin, cell_size) tuple.

## `pick_cave_archetype` (line 252) — Grade: B-
**Prior grade:** B (Codex), C+ (Gemini), B- (consensus) — **AGREE B-**.
**What it does:** Score 5 archetypes via altitude/slope/wetness/basin/concavity, take argmax with deterministic jitter.
**Reference:** Houdini cave-type heuristic node.
**Bug/Gap:** **Bug:** line 333 uses `hash(k.value) % 7` for jitter — `hash()` of string is PYTHONHASHSEED-randomized per Python process. Violates the file's own Rule 4 ("never hash() / random.random()"). Two runs of the same seed in two processes produce DIFFERENT archetype picks at edge ties. **Determinism violation.**
**Bug 2:** `concavity` is read but no pass produces it (master Section 5 LOW lists `convexity` as dead; concavity is similar). The score for KARST_SINKHOLE silently defaults to its rng-jitter only.
**AAA gap:** real archetype picking uses geological context (proximity to water table, rock_hardness, fault lines) — this picks on slope alone.
**Severity:** important.
**Upgrade to B+:** replace `hash(k.value) % 7` with `(seed_int >> (i*3)) & 7` for archetype index `i`. Wire `rock_hardness` and `proximity_to_river` channels.

## `_sample` (line 282, nested in pick_cave_archetype) — Grade: B+
**Prior grade:** none.
**What it does:** Inner closure that fetches a channel from the stack with a default fallback.
**Reference:** standard fallback.
**Bug/Gap:** Type check `if arr_np.shape != stack.height.shape` is correct guard. Returning `default` silently for shape mismatch is permissive — should at least emit a warning so misaligned debug doesn't go undetected.
**Severity:** polish.
**Upgrade to A-:** log a warning when a channel exists but has wrong shape.

## `generate_cave_path` (line 344) — Grade: B+
**Prior grade:** B (Codex), B+ (Opus), A- (Gemini) — **AGREE B+**.
**What it does:** Per-archetype 3D polyline (LAVA_TUBE meander, FISSURE drop, KARST plunge+arm, GLACIAL meander, SEA_GROTTO shallow).
**Reference:** Houdini curve-based cave authoring; UE5 Voxel Farm cave curve.
**Bug/Gap:** **No branching** (Y-splits), **no chamber hubs**, **no inclination variation within an archetype**. Real RDR2 caves have 3-7 branch points and 1-2 chamber expansions. This is a single-arm tube. Also, FISSURE produces zero horizontal extent if `length × 0.4 = 8m` and the rest is vertical — visually indistinguishable from a hole punched into the ground.
**Bug 2:** for `archetype == FISSURE` the path samples (line 376) include `t=0/(n-1) → 0/0 division` if `n_samples=1`; protected by `max(6, ...)` at line 370 → safe.
**AAA gap:** Houdini's `cave_path` SOP supports branching, chamber expansion, slope-snapped inclination. This is a 1980s-era polyline.
**Severity:** important.
**Upgrade to A-:** add per-archetype branch_probability + chamber_node_probability; sample inclination from a per-archetype cubic-Hermite spline rather than linear.

## `carve_cave_volume` (line 436) — Grade: B (DISPUTE)
**Prior grade:** B (Codex), A- (Opus), B (Gemini), B+ (consensus) — **DISPUTE downward to B**.
**What it does:** Vectorized footprint along the path; deepest-delta merge per cell; populates `cave_candidate`.
**Reference:** UE5 Voxel Plugin spline carve, Houdini Voxel cave carve.
**Bug/Gap (CRITICAL):** **The "carve" produces a 2D height delta, not a 3D voxel cavity.** A real cave needs to add **ceiling, walls, AND floor as separate surfaces** — a heightmap can only express a single Z per (X,Y). This carve LOWERS the surface where the cave should be — the player walks INTO terrain that sinks below their feet, not into a cave with a ceiling. Master Section 8 CRITICAL #2 ("Cave entrance geometry") confirms: "NO geometry carved. Caves are invisible metadata."
**Bug 2:** double-write — line 490 sets `cave_candidate` here, then `pass_caves` line 826 sets it again (master Section 5 R3: "pass_caves writes cave_candidate twice").
**Bug 3:** `radius_cells` clamped to `max(1, ...)` — if cell_size=4m and entrance_width=2.5m (FISSURE), radius_m=1.25m, radius_cells=1 — entire footprint is 1 cell. Sub-cell cave entrances vanish.
**Bug 4 (R3 Master):** writes `cave_height_delta` at pass-level (line 867) but this channel is **silently discarded** because `pass_integrate_deltas` is not registered (master GAP-06 / BUG-44). The delta computed here never reaches the heightmap.
**AAA gap:** Houdini Voxel SOP, UE5 Voxel Plugin, Marching Cubes via skimage, Dual Contouring for sharp cave walls. Even storing dual heightmaps (floor + ceiling) would be a 10× improvement. RDR2 caves use SDF voxels.
**Severity:** critical.
**Upgrade to A-:** dual-heightmap (floor_z, ceiling_z) channels OR wire to a true voxel field (sparse VDB-style). Register the delta integrator. Single-write `cave_candidate`.

## `build_cave_entrance_frame` (line 499) — Grade: B+
**Prior grade:** B- (Codex), A- (Opus), A (Gemini), B+ (consensus) — **AGREE**.
**What it does:** Returns metadata dict with 2-3 framing rocks (left jamb, right jamb, optional lintel), lip dims, vegetation_screen flag, occlusion_shelf intent.
**Reference:** Skyrim/ESO cave portal kit; CK creation kit "cave_entrance" prefab.
**Bug/Gap:** Framing rocks are ONLY `world_pos` + `radius_m` — no asset reference, no rotation, no per-archetype material slot. Downstream consumer must invent rock geometry.
**AAA gap:** ESO `cave_portal_kit` ships 12 rock variants with material slots and snap points; this gives 3 spheres of position+radius.
**Severity:** polish.
**Upgrade to A:** add `asset_id`, `rotation_yaw`, `material_slot` per rock; per-archetype rock kit table.

## `scatter_collapse_debris` (line 568) — Grade: B+
**Prior grade:** B (Codex), B+ (Opus), A (Gemini), B+ (consensus) — **AGREE**.
**What it does:** Deterministic random debris positions along path; lateral normal jitter; capped at 200.
**Reference:** UE5 PCG debris scatter.
**Bug/Gap:** **No clustering** — real talus debris piles in clusters of 3-7 per pile, not Poisson-uniform along the path. Also no rotation, no scale variance, no asset_id (just (x,y,z) tuples). All "debris" is type-less.
**AAA gap:** Megascans rock kit + PCG cluster scatter (3-7 rocks per cluster, scale 0.5-2.0, random rotation, ground-snap).
**Severity:** polish.
**Upgrade to A:** Poisson cluster sampling (3-7 rocks per cluster), scale/rotation, asset_id from per-archetype rock kit.

## `generate_damp_mask` (line 618) — Grade: A-
**Prior grade:** B+ (Codex), A- (Opus), B (Gemini), B+ (consensus) — **DISPUTE upward to A-**.
**What it does:** Vectorized radial falloff per waypoint; max-merge with existing `wet_rock`; respects shape match.
**Reference:** UE5 wetness mask shader driver, Houdini `wet_rock` field.
**Bug/Gap:** Linear falloff is correct for a damp mask (smooth gradient). Could be sharper near floor and softer toward ceiling but in 2D heightmap-only that distinction can't be expressed.
**AAA gap:** real damp follows seepage paths (downslope preference + below-water-table). This is isotropic.
**Severity:** polish.
**Upgrade to A:** bias falloff in the downslope direction; respect water_table channel.

## `validate_cave_entrance` (line 666) — Grade: A-
**Prior grade:** A- (Codex), A (Gemini), A (consensus) — **AGREE A-**.
**What it does:** Returns ValidationIssue list for missing framing, short lip, empty damp, zero occlusion shelf.
**Reference:** Houdini constraint check node.
**Bug/Gap:** the `code=` and `severity=` kwargs match the actual `ValidationIssue` dataclass — UNLIKE the `terrain_validation.check_*` functions (master BLOCKER 1 + BUG referenced in A1). This one is correct.
**Severity:** none.
**Upgrade to A:** add a "lip_to_face_ratio" check (lip width relative to entrance width) and an "occlusion_shelf_depth ≥ 1m for hero caves" gate.

## `_find_entrance_candidates` (line 740) — Grade: B-
**Prior grade:** B (consensus) — **DISPUTE downward to B-**.
**What it does:** Returns scene_read.cave_candidates filtered by region.
**Reference:** standard scene-read consumer.
**Bug/Gap:** **Critical:** docstring says "Falls back to scanning cave_candidate mask if scene_read has none" — **but the fallback is not implemented.** Lines 750-756: if scene_read has nothing, returns empty list. The fallback path returns `[]`. Caves never auto-discover from heightmap features.
**Bug 2:** `tuple(pos)` may not be a 3-tuple if `pos` is something else — no length validation.
**AAA gap:** Houdini's cave SOP auto-discovers from cliff edges + slope + basin proximity. This depends on a hand-authored scene_read.
**Severity:** important.
**Upgrade to A-:** implement the documented fallback — scan cliff_candidate ∩ slope > 60° ∩ basin > 0.3 for entrance candidates.

## `pass_caves` (line 759) — Grade: B+
**Prior grade:** A- (Codex), B (Opus), A- (Gemini), B+ (consensus) — **AGREE B+**.
**What it does:** Full orchestrator: derive seed → init channels → protected mask → for each entrance candidate (pick archetype, gen path, carve volume, frame, debris, damp) → accumulate height delta into `cave_height_delta`.
**Reference:** UE PCG cave authoring graph.
**Bug/Gap:** **Bug:** double-write to `cave_candidate` (line 490 inside `carve_cave_volume`, then line 826 here after `&~protected`). The first write inside `carve_cave_volume` is overwritten — wasteful and confusing. (Master Section 5 R3.)
**Bug 2:** `cell_count = int(cc.sum())` (line 845) — `cc` is the GLOBAL cave_candidate after this cave's carve; `cell_count` for cave[i] includes all of caves [0..i-1]. So tier=hero cave[0] has the smallest cell_count and cave[last] has the largest. **`cell_count` is meaningless per-cave.**
**Bug 3:** declared `consumed_channels=("height", "slope", "basin", "wetness")` but body also reads `concavity` — DECL DRIFT (same issue master cataloged for pass_erosion).
**AAA gap:** no auto-discovery (see `_find_entrance_candidates`); the produced delta is silently discarded (master BUG-44).
**Severity:** important.
**Upgrade to A-:** fix double-write, fix per-cave cell_count, declare `concavity` in consumed_channels, register the delta integrator.

## `register_bundle_f_passes` (line 890) — Grade: B (DISPUTE)
**Prior grade:** A (consensus) — **DISPUTE downward to B**.
**What it does:** Registers `pass_caves` with `requires_channels=("height",)`, `produces_channels=("cave_candidate", "wet_rock", "cave_height_delta")`.
**Reference:** standard pass registration.
**Bug/Gap:** **DECL DRIFT (master Section 5):** `produces_channels` includes `cave_height_delta` but the body's `pass_caves` actually writes it (good). However `requires_channels=("height",)` is the BARE MINIMUM — body reads `slope`, `basin`, `wetness`, `concavity`, `cave_candidate`, `wet_rock`. PassDAG dependency resolution will run caves before slope/basin if it relies on this declaration. Master G1 catalogues this exact pattern as a hazard.
**AAA gap:** Houdini node-type registration declares ALL inputs explicitly.
**Severity:** important.
**Upgrade to A-:** `requires_channels=("height", "slope", "basin", "wetness")`.

## `get_cave_entrance_specs` (line 908) — Grade: B+
**Prior grade:** B (Codex), A- (Gemini), B+ (consensus) — **AGREE B+**.
**What it does:** Returns MeshSpec dicts at random positions sampled from `cave_candidate` channel via `generate_cave_entrance_mesh` (the perfect-semicircular-tube generator at `_terrain_depth.py:121`).
**Reference:** standard sampler.
**Bug/Gap:** **Geometry quality is bad** — `generate_cave_entrance_mesh` (verified at `_terrain_depth.py:121-219`) is a flat-walled semicircular arch with `random.gauss(0.0, 0.05)` displacement. Master Section 4 grades this generator C/D+ ("perfect semicircular tube"). This sampler inherits that grade for output quality.
**Bug 2:** `wx = stack.world_origin_x + c * stack.cell_size` — uses cell-corner convention, INCONSISTENT with `_cell_to_world` (line 205) which uses cell-center (+0.5). Half-cell drift between caves entrance positions and where the carve happened.
**Severity:** important.
**Upgrade to A-:** fix coord-corner inconsistency; replace `generate_cave_entrance_mesh` with the strata + overhang variant.

## `_build_synthetic_state` (line 982) — Grade: B+
**Prior grade:** B+ (consensus) — **AGREE**.
**What it does:** Builds a minimal `TerrainPipelineState` (flat noise heightmap + single center anchor) so the MCP `handle_generate_cave` adapter can run `pass_caves` without coupling compose_map to the full pipeline.
**Reference:** test fixture builder pattern.
**Bug/Gap:** flat heightmap (uniform [0, 0.5]) means `pick_cave_archetype` has effectively no signal; archetype is determined almost entirely by deterministic rng jitter. The "5-archetype intelligent picker" reduces to "rng pick" in this codepath.
**AAA gap:** real synthetic state would synthesize a small ridge + basin so the picker actually exercises its heuristics.
**Severity:** polish.
**Upgrade to A-:** synthesize a single ridge or basin into the synthetic state so archetype selection is meaningful.

## `_build_chamber_mesh` (line 1079) — Grade: F (DISPUTE downward)
**Prior grade:** A- (consensus) — **STRONG DISPUTE: F**.
**What it does:** Builds an 8-vertex, 6-quad-face axis-aligned box. Returns a Blender Object that compose_map sets `visibility=False`.
**Reference:** the rubric prompt EXPLICITLY says "Hidden 6-face chamber boxes = F". This function IS that function.
**Bug/Gap:** **This is the literal rubric F-grade example.** No interior, no walls of any thickness, no ceiling detail, no stalactites, no floor variation. 6 quad faces. Hidden from the player. The docstring even acknowledges: "compose_map's cave dispatch hides this object" and "uses it purely as a marker / parent". You shipped a marker box and called it a chamber.
**AAA gap:** Houdini cave chamber + UE5 voxel cave + Megascans cave kit are all complete 3D rooms with stalactites, stalagmites, wall plates, floor rubble, light shafts. This is a hidden cube.
**Severity:** critical.
**Upgrade to A-:** generate a true chamber mesh — wall rings extruded around the path, floor plate with rubble, ceiling with stalactite hooks. Or ship marching-cubes-on-SDF voxel volume. Even a simple icosphere with noise displacement would beat this.

## `handle_generate_cave` (line 1127) — Grade: B-
**Prior grade:** B (consensus) — **DISPUTE downward to B-**.
**What it does:** MCP handler shim — builds synthetic state, runs `pass_caves`, extracts archetype + entrance specs, builds chamber mesh (the F-grade box), returns dict.
**Reference:** standard MCP handler.
**Bug/Gap:** **Inherits the F-grade chamber from `_build_chamber_mesh`.** Returns `meta.bundle = bundle` directly — the entire `PassResult` object is JSON-serialized into the response. PassResult contains numpy arrays via the embedded ValidationIssue list, may not serialize.
**Bug 2:** outer `try/except Exception` hides ALL errors including AttributeError on missing imports — anti-pattern flagged in master "Round 3".
**Bug 3:** `picked_archetype` parsing is fragile — splits on `:` then `=`, depends on side_effect string format never changing. Should attach picked archetype as a structured field on PassResult.
**Severity:** important.
**Upgrade to B+:** narrow except clauses; structured archetype field on bundle; replace box chamber.

---

# terrain_karst.py (5 functions + 1 dataclass post-init, 266 lines)

## `class KarstFeature` + `__post_init__` (line 35, 43) — Grade: A-
**Prior grade:** not in CSV.
**What it does:** Dataclass with kind/world_pos/radius_m, validating kind ∈ {sinkhole, disappearing_stream, cenote, polje} and radius_m > 0.
**Reference:** Houdini karst SOP feature spec.
**Bug/Gap:** clean validation. Could enrich with hardness, depth, drainage_basin_area.
**Severity:** none.
**Upgrade to A:** add `cone_angle_deg` per kind so `carve_karst_features` can vary profiles.

## `detect_karst_candidates` (line 60) — Grade: C+
**Prior grade:** not in CSV.
**What it does:** Returns karst features at local minima within a "limestone-ish" hardness band (0.4 ≤ h ≤ threshold+0.15), subsampled on a coarse grid.
**Reference:** Houdini karst detection on rock_hardness.
**Bug/Gap:** **MULTIPLE bugs**.
1. **BUG-36 (master, BREAKING):** line 100 `h.ptp()` — removed in NumPy ≥2.0. Will hard-crash. Replace with `h.max() - h.min()`. **This single line gates the whole module on a NumPy version.**
2. The 5×5 window check `h[r-2:r+3, c-2:c+3]` (line 93) requires `r ≥ 2`; the loop start `r in range(step, H-step, step)` with `step = max(4, H//16)` ensures r ≥ 4, so safe — but the test for "local minimum" `> window.min() + 0.1` admits any cell within 10cm of its neighbors as "minimum"; on a high-relief tile this matches everywhere.
3. Coordinate convention (line 104-105) uses cell-CORNER not cell-center (master CONFLICT-03), inconsistent with `terrain_caves._cell_to_world` and `terrain_waterfalls`.
4. `radius = float(stack.cell_size * 2.0)` — fixed 2-cell radius regardless of hardness or kind. A polje (which can be 1-50 km wide in real karst) gets the same radius as a 1m sinkhole.
5. Step `max(4, H//16)` — for H=512 step=32; you get a 16×16 grid of candidates max. Fine for budget, but no local-density variation.
**AAA gap:** Houdini's karst SOP uses `find_local_minima` with proper non-max suppression + per-feature size from drainage area + hardness gradient.
**Severity:** **critical (NumPy crash)**.
**Upgrade to B:** fix `h.ptp()` → `np.ptp(h)` or `h.max() - h.min()`; size each feature by drainage area; non-max-suppression instead of grid step.

## `carve_karst_features` (line 125) — Grade: C+
**Prior grade:** not in CSV.
**What it does:** Per-feature double-nested Python loop carving cone (sinkhole/cenote) or flat-bottom (polje) depressions.
**Reference:** Houdini karst carving via heightfield_distort.
**Bug/Gap:** 
1. **Pure Python double loop** (lines 154-168) — should be vectorized via `np.meshgrid` + boolean mask + numpy arithmetic. For a 50-cell-radius polje that's ~7800 Python iterations per feature, ~80k total for 10 features. Master Appendix A flagged similar carve loops as Tier 2 (100×) targets.
2. Sinkhole "cone" depth `f.radius_m * 0.5 * t` — depth scales with radius; radius is fixed 2-cell × cell_size = 2-8m → max depth 1-4m. Real sinkholes are 5-100m deep. **Wrong physical scale by 10×.**
3. Depth is a delta added to existing height; per master BUG-44 the `karst_delta` channel is silently discarded by `pass_integrate_deltas` (not registered). The carve never reaches the heightmap.
4. `min(delta[r,c], -depth)` — picks deepest. Correct.
5. `cenote` has no bottom-cave wiring (the `has_bottom_cave` flag in `get_sinkhole_specs` is a separate path).
**AAA gap:** Houdini karst uses noise-modulated radial profile + concentric ring undulation; this is a smooth analytic cone.
**Severity:** important.
**Upgrade to B:** vectorize via `np.where(dist <= rad_cells, ...)`; fix depth scale (scale to ~5×radius); add noise modulation.

## `pass_karst` (line 177) — Grade: B-
**Prior grade:** not in CSV.
**What it does:** detect → carve → write `karst_delta` if features found; computes `delta_mean`. derive_pass_seed unused (commented as "required by contract" but actually not used downstream).
**Reference:** standard pass.
**Bug/Gap:**
1. **Inherits BUG-36** from `detect_karst_candidates` — will crash on NumPy ≥2.0.
2. `karst_delta` is conditionally produced but **NOT in `produces_channels`** declaration (master BUG/G2 — this exact pattern is flagged for `pass_glacial`, `pass_coastline`, `pass_karst`). Parallel DAG silently drops the channel.
3. `derive_pass_seed` result discarded (`_ = derive_pass_seed(...)`) — unused. The pass is deterministic by construction (no RNG inside detect/carve), so this is OK but the discard is wasteful.
4. No quality gate (master "0/40 passes have a QualityGate").
5. Status hardcoded `"ok"` even on empty `karst_delta`. Should report `"warning"` if karst was enabled but no features detected.
6. There is no `register_bundle_*_passes` call in this file — `pass_karst` is unwired from the registry unless registered elsewhere. Grep confirms it's registered in `terrain_master_registrar.py` — OK but the file itself can't self-register.
**AAA gap:** Houdini's karst node has parameters for sinkhole density, cenote probability, polje minimum_area_m².
**Severity:** important.
**Upgrade to B+:** declare karst_delta in produces_channels conditionally OR always-produce zeros; add quality gate (≥1 feature when enabled and rock_hardness has limestone band); fix BUG-36.

## `get_sinkhole_specs` (line 224) — Grade: B-
**Prior grade:** not in CSV.
**What it does:** Calls `detect_karst_candidates`, filters to sinkhole/cenote, calls `generate_sinkhole` from `terrain_features` per feature, returns mesh_spec + world_pos.
**Reference:** standard mesh spec extractor.
**Bug/Gap:**
1. **Inherits BUG-36** from `detect_karst_candidates`.
2. Calls `generate_sinkhole` (terrain_features.py:1304) which has master BUG-4: "Sinkhole inverted profile (funnel not bell)". So even when called, geometry is wrong.
3. `depth=f.radius_m * 1.2` — depth proportional to radius; with fixed `radius_m = cell_size * 2.0` from `detect_karst_candidates`, depth is 2.4-9.6m for cell_size 1-4m. Real cenotes (Yucatán) are 30-100m deep. **Wrong scale by 10×.**
4. No deduplication if a feature already has a placed mesh (idempotency).
**AAA gap:** Megascans cenote kit + Houdini cenote SOP have proper depth, water plane at base, vine drape, light shaft.
**Severity:** important.
**Upgrade to B+:** fix `generate_sinkhole` (BUG-4); proper depth scale; cenote water plane.

---

# terrain_glacial.py (6 functions, 316 lines)

## `_path_to_cells` (line 32) — Grade: A-
**Prior grade:** not in CSV.
**What it does:** World (x,y) path → (row, col) cells with bounds check.
**Reference:** standard.
**Bug/Gap:** Uses `int(round((x - origin_x) / cell_size))` — same CONFLICT-03 (master) coordinate convention drift. Drops out-of-bounds cells silently (no warning if path is mostly outside tile).
**Severity:** polish.
**Upgrade to A:** consolidate via shared `terrain_coords.world_to_cell`.

## `carve_u_valley` (line 47) — Grade: C
**Prior grade:** not in CSV (master Appendix A: "100x speedup target").
**What it does:** Returns U-shaped valley height delta along path; flat bottom < 30% half-width then smooth wall via `sqrt(1-t²)`.
**Reference:** Houdini glacier-valley node.
**Bug/Gap:**
1. **Quadruple-nested Python loop** (rows × cols × dense path samples × distance compute), lines 95-110. Master Section 9 / Appendix A flag as **100× speedup target**. For width=60m, depth=30m, length=200m at cell_size=1m: bbox is ~64×204 cells × ~200 path samples = **2.6M Python iterations per valley**. Should be `scipy.ndimage.distance_transform_edt(~path_mask)`.
2. Lines 87-88 are dead code: `_ = np.arange(H).reshape(-1, 1)` and `_ = np.arange(W).reshape(1, -1)` — assigned to `_` and never used.
3. Profile is symmetric circular-ish (sqrt(1-t²)) not the proper U with a true flat bottom and steep parabolic walls; real glacial valleys have aspect ratio ~5:1 (depth:half-width is ~1:5).
4. `delta[r, c] = -depth_m * carve` — assigns, doesn't merge. If two valleys overlap, the LAST one wins (no `min(delta, ...)` for "deepest").
5. `glacial_delta` channel produced by `pass_glacial` is NOT in `pass_glacial`'s `produces_channels` declaration (master G2). Silently lost in parallel DAG.
**AAA gap:** Houdini glacier-valley uses cross-section noise, lateral terrace formation, hanging-valley junctions. This is a smooth analytic carve.
**Severity:** important.
**Upgrade to B:** vectorize via `scipy.ndimage.distance_transform_edt`, OR via `np.minimum.reduce` over a small per-segment loop. Add cross-section noise. Fix overlap merge to `np.minimum(delta, local_delta)`.

## `scatter_moraines` (line 120) — Grade: B
**Prior grade:** not in CSV. Master Section 6 lists it as **"exists, never called"** (orphan).
**What it does:** Lateral + terminal moraine placements (x, y, radius_m) along glacier path.
**Reference:** geological glacier-moraine theory; Houdini scatter on glacier path.
**Bug/Gap:**
1. **Orphan** (master Section 6) — defined but `pass_glacial` never calls it. The `glacier_paths` hint produces U-valleys but no moraines.
2. `rng.random()` (line 149) — legacy random API, the file otherwise uses `default_rng`. Should be `rng.uniform(0, 1) > 0.5` or `rng.choice([-1.0, 1.0])`.
3. Lateral perpendicular `nhat = [-seg[1], seg[0]] / seg_len` — correct 2D perpendicular.
4. Per-segment fixed `2 lateral moraines` regardless of segment length — long segments under-populated.
5. No `medial moraine` (between two confluent glacier branches) — incomplete glacial moraine taxonomy.
6. Returns `(x, y, radius)` with no z; downstream consumers have to look up height per moraine.
**AAA gap:** real moraine systems have lateral, terminal, medial, recessional, ground; Houdini glacier_moraine ships with all 5 types.
**Severity:** important.
**Upgrade to B+:** **wire it into `pass_glacial`**; add medial + recessional types; scale lateral count by segment length; return z.

## `compute_snow_line` (line 168) — Grade: A-
**Prior grade:** not in CSV. Master Section 9 / Appendix B.4 implicit: "vectorized snow line" — A-/A.
**What it does:** Computes snow factor [0,1] from altitude with 50m transition band; reduces by up to 50% on steep slopes.
**Reference:** atmospheric snow-line model.
**Bug/Gap:**
1. **Genuinely vectorized** — pure numpy broadcasting; no loops. Master Appendix B.4 confirms.
2. `slope_penalty = clip(slope/(π/2), 0, 1) * 0.5` — uses **radians** for slope (correct since the file's slope channel is in radians per `terrain_masks` convention).
3. Hardcoded 50m band — should be a parameter or scale with terrain relief.
4. `np.clip(raw, 0, 1)` is on a unit-less factor not on world heights — Rule 10 honored.
5. Doesn't account for **aspect** (north-facing slopes hold snow longer than south) — basic alpine model only.
**AAA gap:** Real snow-line models (e.g., Houdini's snow_pile) use aspect, wind exposure, drift accumulation. This is a baseline.
**Severity:** polish.
**Upgrade to A:** parameterize transition band; add aspect-driven asymmetry (N-facing +20%, S-facing -20%).

## `pass_glacial` (line 202) — Grade: B
**Prior grade:** not in CSV. Master Section 5 R3 confirms `glacial_delta` silently lost.
**What it does:** Computes snow_line_factor; if `glacier_paths` hint provided, calls `carve_u_valley` per path and accumulates `glacial_delta`.
**Reference:** standard pass.
**Bug/Gap:**
1. **Bug:** declared `produces_channels = ("snow_line_factor",)` but conditionally produces `("snow_line_factor", "glacial_delta")` (line 244). Master G2 catalogs this as silent-loss in parallel DAG.
2. **Bug:** `derive_pass_seed` discarded (`_ = ...`) — unused. The carve has no RNG.
3. `total_delta += delta` — additive accumulation across multiple glaciers; should be `np.minimum(total_delta, delta)` (deepest wins) like `carve_cave_volume` does.
4. **Does not call `scatter_moraines`** — the moraine code is orphan (master Section 6).
5. No quality gate (0/40 issue).
6. **`glacial_delta` produced but silently discarded** — master BUG-44 (`pass_integrate_deltas` not registered).
**AAA gap:** Houdini glacial pass produces U-valleys, hanging valleys, cirques, moraines, fluted till — this produces 1 (U-valleys) of 5.
**Severity:** important.
**Upgrade to B+:** wire `scatter_moraines`; fix `produces_channels` to always include `glacial_delta`; merge via min not sum; register integrator (cross-file).

## `get_ice_formation_specs` (line 261) — Grade: B
**Prior grade:** not in CSV.
**What it does:** Samples high snow-coverage cells, calls `generate_ice_formation` (terrain_features.py:1764), returns mesh_spec + world_pos.
**Reference:** standard sampler.
**Bug/Gap:**
1. Calls `generate_ice_formation` which per master BUG-3 ("Ice kt scope — all stalactites uniformly blue") is a known-buggy generator.
2. Coordinate convention `wx = world_origin_x + c * cell_size` — cell-corner. CONFLICT-03 with `_cell_to_world` which uses cell-center.
3. `factor > 0.7` threshold — fixed; on a low-altitude tile no cells qualify and you get zero formations even though the stack is "snowy".
4. `rng.choice(..., replace=False)` — correct.
5. No proximity check (formations can spawn 1m apart).
6. No alignment (`generate_ice_formation` doesn't know which way is downslope; stalactites should hang vertically not at random rotation).
**AAA gap:** Megascans ice kit + Houdini ice scatter handle proximity, downslope alignment, light scattering material slots.
**Severity:** important.
**Upgrade to B+:** Poisson disk subsample for proximity; pass downslope direction to `generate_ice_formation`; fix coord convention.

---

# terrain_cliffs.py (12 functions + 2 dataclasses, 699 lines)

## `class TalusField` (line 44) — Grade: B+
**Prior grade:** not in CSV.
**What it does:** Dataclass holding mask, angle_of_repose_radians (default 34°), average_particle_size_m (default 0.4).
**Reference:** geological angle-of-repose for angular rock debris.
**Bug/Gap:** 34° is correct for angular rock; 30-35° range is real. Particle size 0.4m is a reasonable median for talus. Spec is honest.
**AAA gap:** missing `material_kit_id`, `wetness_factor` (wet talus has lower repose angle). No size distribution (talus has bimodal distribution: small flakes + large boulders).
**Severity:** polish.
**Upgrade to A-:** size distribution (bimodal lognormal), wetness coupling.

## `class CliffStructure` (line 58) — Grade: B
**Prior grade:** not in CSV.
**What it does:** Dataclass — cliff_id, lip_polyline, face_mask, ledges, talus_mask, world_bounds, tier, max_height_m, min_height_m, cell_count.
**Reference:** Houdini cliff anatomy.
**Bug/Gap:**
1. `lip_polyline: np.ndarray` is documented as "(N, 2) int32: (row, col) cells along upper edge" — but per master **BUG-25 it's a point cloud, not an ordered path** (`_extract_lip_polyline` returns lexsort-sorted points, not contour-walked).
2. No `overhang_mask`, no `stratification_bands` (sedimentary horizontal layers), no `fracture_lines`.
**AAA gap:** Houdini cliff anatomy includes overhang_mask, joint_lines, strata_bands, alcove_mask. Megascans cliff scans show all of these.
**Severity:** important.
**Upgrade to B+:** add overhang_mask + stratification_bands + fracture_lines; rename `lip_polyline` to `lip_points` to be honest about what it is.

## `build_cliff_candidate_mask` (line 85) — Grade: B
**Prior grade:** not in CSV.
**What it does:** Boolean mask = slope > threshold, & saliency, OR (ridge AND slope > 0.8×threshold), AND NOT hero_exclusion, with min cluster size filter.
**Reference:** Houdini cliff_candidate detection.
**Bug/Gap:**
1. Slope threshold 55° is sensible (real cliffs: 50-90°). Houdini default is 50°.
2. Calls `_label_connected_components` for cluster-size filter — Python BFS, **50-200× slow** vs `scipy.ndimage.label` (master D.3 #3).
3. `np.unique(labels)` with `return_counts=True` — correct.
4. `np.isin(labels, small)` to mask out small clusters — correct vectorized op.
5. **Bug:** ridge bias (line 122-127) ORs in ridge cells with slope > 80% threshold; but `ridge` channel may have been overwritten by erosion (master CONFLICT-04 / BUG-43: "pass_erosion writes ridge silently"). Ridge bias may be using post-erosion data.
6. No height-difference check — a 60° slope at 1m height is not a cliff. Should require `local_height_range > 5m` over a 5×5 window.
**AAA gap:** Houdini cliff detection uses slope + height_range + curvature. This uses slope + ridge + saliency.
**Severity:** important.
**Upgrade to B+:** scipy.ndimage.label; add height_range gate; document ridge channel provenance dependency.

## `_label_connected_components` (line 147) — Grade: C+
**Prior grade:** Master Appendix A flags as **1000× speedup target**; D.3 ranks #3 (50-200× via scipy.ndimage.label).
**What it does:** 8-connected CC labeling via Python BFS (list-pop = LIFO so it's actually DFS).
**Reference:** `scipy.ndimage.label(mask, structure=np.ones((3,3)))` returns identical output in compiled C.
**Bug/Gap:**
1. **Pure Python BFS over a 2D grid** — fundamentally wrong technique when scipy.ndimage.label exists. Even without scipy, `numpy.ndimage` substitutes (cumulative scan + propagation) would be 10× faster.
2. `next_id` is incremented BEFORE the BFS confirms cells (line 167) — no bug because the m[r0,c0] check is first, but it means `next_id` could over-count if a label has zero cells (it won't here, but the pattern is fragile).
3. Variable named `stack_bfs` but it's actually DFS (uses `.pop()` not `.popleft()`). Either is fine for labeling; misleading name.
4. Missing border handling check is fine — `if r < 0 or r >= rows` guard catches it.
5. No connectivity parameter (always 8-connected); scipy lets you choose.
**AAA gap:** every AAA pipeline uses scipy.ndimage.label or ITK CC; nobody ships hand-rolled BFS for terrain.
**Severity:** important.
**Upgrade to A-:** `try: from scipy.ndimage import label; labels, _ = label(m, structure=np.ones((3,3)))` with Python BFS as documented fallback.

## `carve_cliff_system` (line 188) — Grade: C
**Prior grade:** not in CSV. Master Appendix B.4 grades the file at B+ overall but flags BUG-21 (insert_hero_cliff_meshes is F-stub) and BUG-25 (lip polyline is point cloud).
**What it does:** Per-component, build face_mask, lip_polyline, world_bounds, max/min height. Returns sorted-by-size list of CliffStructure.
**Reference:** Houdini cliff_anatomy SOP.
**Bug/Gap:**
1. **Returns 2D heightmap face_mask only** — no overhang carve, no stratification, no fault offset, no joint planes. Cliffs are flat-projected slopes, not 3D structures. Per the rubric prompt "Cliffs without overhangs/stratification = C". This is exactly that.
2. Inherits `_label_connected_components` slowness (Python BFS).
3. `face_heights = height[face_mask]` then `face_heights.max() / .min()` — correct, but `min_height_m` is the lowest height of any face cell, which for a cliff with talus apron is ~ground level, not the actual base of the cliff face. Use percentiles instead.
4. world_bounds via `cc.min() * cell_size` — cell-corner convention (CONFLICT-03).
5. No noise modulation, no fracture pattern, no overhanging cells — just flat slope cells projected to a mask.
**AAA gap:** Houdini cliff_anatomy emits overhang_mask + jointing + horizontal_strata + alcove + cornice. Elden Ring cliffs have all of these. RDR2 cliffs have fault offsets.
**Severity:** **critical for AAA claim.**
**Upgrade to B:** add overhang detection (find cells where slope > 80° AND height(r-1, c) > height(r, c) + 2m); stratification bands at every 2-5m (sedimentary); fracture pattern from voronoi tessellation.

## `_region_to_slice` (line 260) — Grade: A
**Prior grade:** not in CSV.
**What it does:** Trivial pass-through to `BBox.to_cell_slice`.
**Reference:** standard.
**Bug/Gap:** none. Duplicate of `terrain_caves._region_to_slice` (master CONFLICT-14: "_cell_to_world — 2D vs 3D" + similar pattern for region_to_slice).

## `_extract_lip_polyline` (line 272) — Grade: C+ (DISPUTE downward)
**Prior grade:** master BUG-25: "Lip polyline is point cloud not path" — confirmed.
**What it does:** Per documentation returns "ordered (N, 2) int32 array of (row, col) lip cells". Per **master BUG-25** and verified at line 312 (`order = np.lexsort((pts[:, 1], pts[:, 0]))` — sort by row then col), it actually returns a **point cloud sorted by raster order**, not a contour walk.
**Reference:** Houdini cliff lip extraction = boundary-tracing contour walk (Moore-Neighbor or square-tracing).
**Bug/Gap:**
1. **Lexsort != contour walk.** A real lip polyline traverses the cliff edge in topological order; this returns lip cells in raster order. Downstream "polyline" consumers iterating cell[i] to cell[i+1] will jump across the cliff face, not walk along the lip.
2. Lip condition (`m & (~neighbor_mask) & (neighbor_h >= h - 1e-9)`) — correct definition of "I am face cell, neighbor is not face cell, neighbor is at or above me".
3. Fallback (line 304-308) for "no lip" — uses top row of face_mask. OK.
4. Does NOT split disconnected lip segments — if a single CliffStructure has 2 disjoint lip segments, they're merged in raster order.
**AAA gap:** Houdini's `crease()` SOP returns proper polylines; UE Landscape uses 2D contour walks for cliff edges.
**Severity:** important.
**Upgrade to B+:** Moore-neighbor contour tracing; return list of polyline arrays (one per disconnected lip segment).

## `add_cliff_ledges` (line 321) — Grade: B
**Prior grade:** not in CSV.
**What it does:** Adds 0-3 horizontal ledges per cliff based on height span; each ledge is a band of face cells at a target z ± band_half.
**Reference:** Houdini cliff ledge generator.
**Bug/Gap:**
1. Ledge count brackets (10/20/30m) are reasonable.
2. **Bug:** "Fallback for near-vertical cliffs" (lines 377-382) creates a 1-row ledge at `target_row` — but the cliff face_mask spans rows from `row_min` to `row_max` and `target_row` is just `row_min + frac × (row_max - row_min)`. For a perfectly vertical cliff (1 cell wide, many cells tall) `row_min == row_max` and `target_row == row_min`; ledge is at the top, not at proportional height. Single-row ledges from a single-row face are pathological.
3. `band_half = max(0.75, span / (count*4))` — for span=15m, count=1: band_half=3.75m → ledge spans 7.5m vertically. For real geology, cliff ledges are 0.3-2m tall ("benches"). 7.5m is more like a "shelf" not a "ledge".
4. Ledges are stored as masks not as polylines — downstream consumers can't easily traverse ledge edges.
5. No noise modulation; ledges are perfectly horizontal — real strata-eroded ledges undulate.
**AAA gap:** Houdini cliff_ledge has noise + tilt + per-band material slot. Elden Ring cliffs have undulating ledges with vegetation.
**Severity:** important.
**Upgrade to B+:** real ledge thickness (0.3-2m); noise undulation; ledge polyline output; per-ledge material slot.

## `build_talus_field` (line 395) — Grade: B
**Prior grade:** not in CSV.
**What it does:** Dilates face_mask by `apron_cells`, intersects with non-face cells whose height ≤ min_face_height + 1m, returns TalusField.
**Reference:** geological angle-of-repose talus formation.
**Bug/Gap:**
1. `min_face_h + 1.0` — fixed 1m tolerance regardless of cliff height. A 100m cliff dumps talus 50-200m DOWN from base; a 5m cliff has talus at 1-5m down. Tolerance should scale with height.
2. Dilation is **manual unrolled neighbor union** (lines 422-432) — works but `scipy.ndimage.binary_dilation(face, iterations=apron_cells)` is the canonical AAA call. Master D.3 #1 lists this exact replacement (100-500× speedup for the basin-detect case).
3. **Talus is just a mask** — no actual scree geometry, no rock instances, no slope-projected pile. The TalusField has angle_of_repose but it's never used to compute the actual surface.
4. No talus chute — real cliff talus collects in fans below cracks/gullies, not uniformly along the base.
5. `apron_cells=3` → for cell_size=4m that's 12m apron; for cell_size=1m it's 3m. Should be a world-meter parameter.
**AAA gap:** Houdini talus_pile uses angle-of-repose simulation (settles particles down a slope); this is a flat 2D dilation.
**Severity:** important.
**Upgrade to B+:** scipy.ndimage.binary_dilation; world-meter apron parameter; per-chute talus fan generation; actual height delta for talus pile.

## `insert_hero_cliff_meshes` (line 454) — Grade: F (CONFIRMED)
**Prior grade:** master BUG-21: **"insert_hero_cliff_meshes is F-grade stub"** — **AGREE F**.
**What it does:** Returns side_effect strings without creating any geometry. Docstring openly admits "Real bmesh geometry generation ships in a later Bundle B extension."
**Reference:** the rubric's F definition.
**Bug/Gap:** F by self-admission. No mesh creation. Just string append.
**AAA gap:** UE5 PCG cliff insertion + Houdini cliff_hero_geo + Megascans cliff scan placement all ship working geometry. This is a string formatter.
**Severity:** **critical** for "ship hero cliff meshes" claim.
**Upgrade to B+:** generate procmesh geometry from CliffStructure.face_mask + lip polyline + ledges + strata bands.

## `validate_cliff_readability` (line 483) — Grade: A-
**Prior grade:** not in CSV.
**What it does:** Returns ValidationIssue list for tiny face, missing lip, optional missing ledges, talus/face overlap.
**Reference:** Houdini constraint check.
**Bug/Gap:**
1. **Uses correct ValidationIssue kwargs** (`code=`, `severity=`, `affected_feature=`, `message=`) — UNLIKE the master BLOCKER 1 functions in `terrain_validation.py` which use undefined `category=` / `hard=`. This validator is correctly typed.
2. Missing checks: no overhang validation, no stratification validation, no minimum-height validation (a 1-cell-wide cliff with 100 cells passes face_cells check but is a needle, not a cliff).
3. `min_face_cells=20` default — for cell_size=4m that's 320m². Reasonable floor.
**Severity:** polish.
**Upgrade to A:** add aspect-ratio check (reject 1-cell-wide needles); add height check (≥3m for "cliff", ≥10m for "hero"); add silhouette-readability check (master Section 10).

## `pass_cliffs` (line 552) — Grade: B
**Prior grade:** not in CSV.
**What it does:** Build candidate → region scope → protected zones → carve cliff system → ledges + talus per cliff → insert hero meshes (F-stub) → side_effects → validate.
**Reference:** standard pass.
**Bug/Gap:**
1. **DECL DRIFT:** `consumed_channels=("slope", "saliency_macro")` (line 628) but body reads `slope`, `saliency_macro`, `ridge`, `hero_exclusion` (build_cliff_candidate_mask reads all four). `register_bundle_b_passes` declares `requires_channels=("slope",)` — even narrower. Master G1 catalogues this exact pattern.
2. `derive_pass_seed` derived (line 571) but only consumed for `metrics["seed_used"]` reporting — no actual RNG in the pass. Cosmetic seed.
3. Calls `insert_hero_cliff_meshes` which is the F-stub (BUG-21). Pass reports no error.
4. **No quality gate** (0/40 issue).
5. `cliff_count` and `total_ledges` reported in metrics — useful telemetry.
6. Status `"warning"` if any hard issue — correct.
**AAA gap:** Houdini cliff pass produces cliff_anatomy AND geometry; this produces cliff_anatomy and a string log.
**Severity:** important.
**Upgrade to B+:** fix DECL DRIFT (declare ridge, saliency_macro, hero_exclusion); add quality gate (cliff_count ≥ 1 when slope > 55° present); replace F-stub.

## `_protected_mask_for_cliffs` (line 644) — Grade: B+
**Prior grade:** not in CSV.
**What it does:** Same as `_protected_mask_for_caves` — meshgrid + per-zone OR.
**Reference:** standard.
**Bug/Gap:** **Duplicate of `terrain_caves._protected_mask_for_caves`** (master CONFLICT pattern). Same meshgrid recompute. Should live in `terrain_semantics`.
**Severity:** polish.
**Upgrade to A-:** consolidate to a shared utility.

## `register_bundle_b_passes` (line 670) — Grade: B (DISPUTE downward)
**Prior grade:** not in CSV.
**What it does:** Registers `pass_cliffs` with `requires_channels=("slope",)`, `produces_channels=("cliff_candidate",)`.
**Reference:** standard.
**Bug/Gap:** **DECL DRIFT** — body reads `slope`, `saliency_macro`, `ridge`, `hero_exclusion`. Declaration is too narrow. Same pattern as `register_bundle_f_passes`. Master G1 hazard.
**Severity:** important.
**Upgrade to A-:** `requires_channels=("slope", "saliency_macro", "ridge")` (hero_exclusion is optional and should be marked as such).

---

# Cross-cutting findings (4 files)

## Coordinate-convention drift (CONFLICT-03)
- `terrain_caves._world_to_cell` (line 194-195): `int(round(...))`
- `terrain_caves._cell_to_world` (line 205-206): cell-center (+0.5)
- `terrain_caves.get_cave_entrance_specs` (line 938-939): cell-corner (no +0.5)
- `terrain_karst.detect_karst_candidates` (line 104-105): cell-corner inline
- `terrain_glacial._path_to_cells` (line 40-41): `int(round(...))`
- `terrain_cliffs.carve_cliff_system` (line 237-240): cell-corner

**Net effect:** half-cell to 2-meter drift between cave carve, cave entrance mesh, and cliff face_mask in the same tile. Already in master Section 7 CONFLICT-03 — still present on HEAD.

## Decl-drift (master G2)
- `register_bundle_f_passes`: declares `("height",)` but body reads slope/basin/wetness/concavity
- `register_bundle_b_passes`: declares `("slope",)` but body reads slope/saliency_macro/ridge/hero_exclusion
- `pass_karst`: produces `karst_delta` conditionally; not in produces_channels
- `pass_glacial`: produces `glacial_delta` conditionally; not in produces_channels

All silently lose channels in `PassDAG.execute_parallel`. (Master BLOCKER cross-confirmed by A1+G1+G2.)

## Silently-discarded deltas (master BUG-44)
- `cave_height_delta` (caves)
- `karst_delta` (karst)
- `glacial_delta` (glacial)

All produced; `pass_integrate_deltas` not registered → all DROPPED. Caves don't carve, karst doesn't depress, glacial U-valleys don't carve. The carving exists only in mask-stack memory and is never applied to the heightmap.

## Python loops where vectorization is mandatory (master Section 9 / D.3)
- `terrain_cliffs._label_connected_components` (1000× target via scipy.ndimage.label)
- `terrain_cliffs.build_talus_field` dilation (100-500× via scipy.ndimage.binary_dilation)
- `terrain_glacial.carve_u_valley` (100× via scipy.ndimage.distance_transform_edt)
- `terrain_karst.carve_karst_features` (100× via meshgrid + np.where)

## Geometry stubs (rubric-defined F)
- `terrain_caves._build_chamber_mesh` — 6-face hidden box (rubric: "Hidden 6-face chamber boxes = F")
- `terrain_cliffs.insert_hero_cliff_meshes` — string formatter, no geometry (master BUG-21)
- `terrain_caves.handle_generate_cave` chamber output — wraps the F-stub

## NumPy 2.0 BREAKING (master BUG-36)
- `terrain_karst.py:100` — `h.ptp()` removed; will hard-crash on modern NumPy. **Single highest-severity bug in this module group.**

---

# Recommended fix order (highest leverage)

1. **`terrain_karst.py:100`** — replace `h.ptp()` with `np.ptp(h)` or `h.max() - h.min()`. **One-line fix; unblocks all karst on NumPy ≥2.0.**
2. **Register `pass_integrate_deltas`** in `register_default_passes` (cross-file). **One-line fix; unblocks ALL carving (caves, karst, coast, wind, glacial).**
3. **Fix DECL DRIFT** in `register_bundle_b_passes` and `register_bundle_f_passes` — declare all read channels. **Two-line fix; closes G1 hazard.**
4. **Replace `_label_connected_components`** with scipy.ndimage.label (with Python fallback). **5-line fix; 50-200× speedup.**
5. **Vectorize `carve_u_valley`** via scipy.ndimage.distance_transform_edt. **15-line fix; 100× speedup.**
6. **Replace `_build_chamber_mesh`** with real chamber geometry (or wire into procmesh cave kit). **F→B fix.**
7. **Wire `scatter_moraines`** into `pass_glacial`. **3-line fix; one less orphan.**
8. **Implement `_find_entrance_candidates` fallback** when scene_read is empty. **20-line fix; un-deadens caves auto-discovery.**
9. **Replace `insert_hero_cliff_meshes`** with real cliff mesh generation. **F→B fix.**
10. **Consolidate coordinate conventions** to `terrain_coords.world_to_cell` (cross-file utility). **30-line refactor; closes CONFLICT-03.**

---

## Disputed grades (summary)

| Function | Prior | Mine | Direction |
|---|---|---|---|
| `_world_to_cell` (caves) | A- | B | DOWN (CONFLICT-03) |
| `carve_cave_volume` | B+ | B | DOWN (2D heightmap-only, double-write) |
| `_build_chamber_mesh` | A- | F | DOWN (rubric-defined F: hidden 6-face box) |
| `register_bundle_f_passes` | A | B | DOWN (DECL DRIFT) |
| `_find_entrance_candidates` | B | B- | DOWN (documented fallback unimplemented) |
| `handle_generate_cave` | B | B- | DOWN (wraps F chamber) |
| `register_bundle_b_passes` | not in CSV | B | down vs implicit A (DECL DRIFT) |
| `_extract_lip_polyline` | (master BUG-25) | C+ | confirms downgrade (point cloud not polyline) |
| `generate_damp_mask` | B+ | A- | UP (genuinely vectorized) |
| `compute_snow_line` | not in CSV | A- | up vs implicit B (genuinely vectorized) |

10 disputes. Direction: 9 down, 1 up.

---

## Final tier

| Tier | Count | Functions |
|---|---|---|
| A / A- | 4 | `make_archetype_spec`, `generate_damp_mask`, `compute_snow_line`, `_path_to_cells` (also `class CaveArchetype` A, `_region_to_slice` A in both files, `_cell_to_world` A-, `validate_cave_entrance` A-, `validate_cliff_readability` A-, `KarstFeature` A-) |
| B+ | 5 | `CaveArchetypeSpec`, `_protected_mask_for_caves`, `_sample`, `generate_cave_path`, `scatter_collapse_debris`, `_protected_mask_for_cliffs`, `pass_caves`, `get_cave_entrance_specs`, `_build_synthetic_state`, `TalusField` |
| B | 9 | `CaveStructure`, `_world_to_cell`, `carve_cave_volume`, `register_bundle_f_passes`, `CliffStructure`, `build_cliff_candidate_mask`, `add_cliff_ledges`, `build_talus_field`, `pass_cliffs`, `register_bundle_b_passes`, `pass_glacial`, `scatter_moraines`, `get_ice_formation_specs` |
| B- | 7 | `pick_cave_archetype`, `_find_entrance_candidates`, `handle_generate_cave`, `pass_karst`, `get_sinkhole_specs` |
| C+/C | 6 | `_label_connected_components` C+, `_extract_lip_polyline` C+, `detect_karst_candidates` C+, `carve_karst_features` C+, `carve_cliff_system` C, `carve_u_valley` C |
| D | 1 | (none cleanly D, but `carve_u_valley` is borderline C/D for the quad-loop) |
| F | 2 | `_build_chamber_mesh`, `insert_hero_cliff_meshes` |

(The exact bucket counts above don't sum to exactly 35 because some dataclass __post_init__ are folded into the parent class grade. Distribution stated at the top is canonical.)

---

*Audited by Opus 4.7 ultrathink in a single 1M-context session, 2026-04-16. Cross-referenced against `docs/aaa-audit/GRADES.csv` (224 graded functions), `docs/TERRAIN_UPGRADE_MASTER_AUDIT.md` Sections 4/5/7/8/9 + Appendices A/B.4/C/D, prior-round Codex/Gemini/Opus consensus, NumPy 2.0 breaking-changes, scipy.ndimage performance benchmarks, Houdini Heightfield/Voxel SOP reference, UE5 Voxel Plugin reference, RDR2 cave authoring (GDC 2019), and Megascans cliff-scan visual baseline.*
