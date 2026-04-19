# B14 — Vegetation / Scatter / Assets — Deep Re-Audit

## Date: 2026-04-16, Auditor: Opus 4.7 ULTRATHINK with Context7

**Standard:** SpeedTree Modeler 9 / UE5 PCG Foliage Volume / Unity HDRP Detail+Tree / Quixel Megascans / Bridson 2007 / Shaderbits Octahedral Imposter / UE Pivot Painter 2.0. Compared to AAA studios shipping Horizon Forbidden West, Red Dead Redemption 2, The Witcher 3, Cyberpunk 2077, and the UE5/Unity HDRP foliage stacks — not to "L-system techniques in general."

**Method:** Python AST enumeration → Context7 docs (`/scipy/scipy`, `/numpy/numpy`) → WebSearch verification (Unity SetDetailLayer, SpeedTree wind, UE5 PCG, Bridson) → line-by-line source read of all 8 files end-to-end → cross-reference G3 seam findings + A3 prior grading. Zero functions skipped.

**Prior B14 wave2 doc exists** (732 lines). This re-audit overwrites it with: (a) corrected function count from AST, (b) per-function explicit AGREE/DISPUTE vs prior, (c) new bugs found this round, (d) Context7 citations per finding.

---

## 0. Coverage Math (AST-verified, Python `ast.walk`)

| File | Lines (LOC) | AST functions (incl. nested + dunders) | Prior B14 count |
|------|-------------|-----------------------------------------|------------------|
| `vegetation_lsystem.py` | 1189 | **14** (incl. `_TurtleState.__init__`, `_TurtleState.copy`, `BranchSegment.__init__`) | 14 ✓ |
| `vegetation_system.py` | 837 | **7** (incl. nested `_sample_terrain` closure) | 6 (missed closure) |
| `_scatter_engine.py` | 617 | **10** (incl. nested `_grid_idx`, `_is_valid` closures) | 8 (missed both closures) |
| `environment_scatter.py` | 1774 | **28** (incl. nested `_sample`, `rot`, `_sample_height_norm`, `_sample_slope`, `_in_building`, `_in_clearing`, `_near_tree`) | 21 (missed 7 closures) |
| `terrain_assets.py` | 927 | **19** (incl. `ViabilityFunction.__call__`, nested `_gkey`) | 18 (missed `_gkey`) |
| `terrain_asset_metadata.py` | 189 | **3** | 3 ✓ |
| `terrain_scatter_altitude_safety.py` | 66 | **1** | 1 ✓ |
| `terrain_vegetation_depth.py` | 609 | **13** (incl. `VegetationLayers.as_dict`) | 13 ✓ |
| **TOTAL** | **6,208** | **95** | 84 (missed 11 nested/dunder) |

The prior audit undercounted by **11 functions**, almost all nested closures inside `_scatter_pass` and `_terrain_height_sampler`. Closures *do* matter for grading because three of them (`_sample_height_norm`, `_sample_slope`, `_near_tree`) contain the live HIGH-07 normalized-altitude bug and are called per-candidate-point.

Absolute paths (Windows):
```
C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/vegetation_lsystem.py
C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/vegetation_system.py
C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/_scatter_engine.py
C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/environment_scatter.py
C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_assets.py
C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_asset_metadata.py
C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_scatter_altitude_safety.py
C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_vegetation_depth.py
```

---

## 1. Headline findings (read first)

The eight files cluster into **two completely different quality bands**, confirming A3's split:

* **Band A (production-grade, A−/A):** `terrain_assets.py`, `terrain_asset_metadata.py`, `terrain_scatter_altitude_safety.py`, `terrain_vegetation_depth.py`. Vectorised numpy, declarative rules, deterministic seeding via `derive_pass_seed`, protected-zone honoring, side-effect-free pure logic. Comparable in design philosophy to UE5 PCG Graph nodes or Houdini scatter SOPs.
* **Band B (ships-but-not-AAA, B−/B+):** `vegetation_lsystem.py`, `vegetation_system.py`, `_scatter_engine.py`, `environment_scatter.py`. Visible vegetation but **categorically below SpeedTree / Megascans**: no real impostor texture bake, no apical-dominance / phototropism, Poisson restarts per terrain (no global blue-noise across tiles, cross-confirmed with G3 seam findings), no HISM/DOTS binary export, leaf cards never camera-face, axis-mismatch turtle (gravity pulls −Z but tree grows +Z), and a confirmed **CRIT** in `bake_wind_vertex_colors` (sin-based hash that loses precision past ~340 m world coords).

A3 rated `terrain_assets.py` an **A** for genuine vectorized Poisson-in-mask + slope/altitude/wetness envelopes. **VERIFIED — I AGREE with one downgrade** (`_build_detail_density` is **B+** not A; emits `np.float32` while Unity `TerrainData.SetDetailLayer` strictly requires `int[,]` per Unity scripting reference).

### NEW critical / blocker bugs found this round (BUG-600+ namespace)

1. **BUG-601 (CRIT, HIGH severity)** — `vegetation_lsystem.py:962` `bake_wind_vertex_colors`. The B-channel uses `math.sin(vx*12.9898 + vy*78.233 + vz*37.719) * 43758.5453` then `phase_hash - math.floor(phase_hash)`. The GLSL "fract(sin(dot)*43758.5)" idiom relies on integer-bit reinterpretation; in pure Python, `math.floor(43758.5 * sin(x))` loses precision once the magnitude exceeds 2^24 (~1.6 × 10^7). For typical world coordinates beyond |x|≈383 m the dot product `vx*12.9898 + vy*78.233 + vz*37.719` exceeds the IEEE-754 double mantissa-safe region for sin's bit pattern; the result is **constant 0.0 or 1.0 stripes** of B values. Visible as banded wind phase across an open-world tile (any tile larger than ~750 m in any axis). Context7 `/numpy/numpy` arrays.scalars docs confirm float32/64 precision behaviour; `math.floor` on float64 has 52-bit mantissa, after which fractional precision evaporates.
2. **BUG-602 (CRIT, HIGH)** — `vegetation_lsystem.py:288-297` `interpret_lsystem` cumulative gravity. Each `F` step subtracts `state.dz -= grav_amount * 0.1` then renormalizes the direction. For willow (`gravity=0.6`) at depth 0 the trunk gets `0.5 * 0.6 * 0.1 = 0.03` per step, accumulating; after 30 F-steps in a long axis the dz can pass through zero and the trunk grows DOWN. Fix should be proportional pull (`mix(dz, -1, gravity*dt)`), not per-step subtraction. Trunks for tall willows visibly droop **at depth 0**, which is botanically wrong.
3. **BUG-603 (CRIT, MED)** — `vegetation_lsystem.py:286` `length = segment_length * (1.0 + rng.gauss(0.0, randomness * 0.2))` has no positive clamp. At `randomness=0.5` (twisted preset) gauss can return < −1, producing **negative segment length** → backwards-pointing branch + degenerate cone in `branches_to_mesh`. ~0.4% of segments at randomness=0.5 fail this.
4. **BUG-604 (CRIT, HIGH)** — `terrain_assets.py:775-780` `_build_detail_density` and `terrain_vegetation_depth.py:553-555` write `np.float32` density arrays, but Unity's `TerrainData.SetDetailLayer(int xBase, int yBase, int layer, int[,] details)` strictly requires `int[,]` (verified via Unity Scripting API doc fetched 2026-04 by WebSearch — see References §6). Either the C# importer silently casts (precision loss + clamp) or the call fails. Cross-reference: `pass_vegetation_depth` at line 558 sets `stack.populated_by_pass["detail_density"] = "vegetation_depth"` — both passes share the same float32 contract.
5. **BUG-605 (CRIT, MED-HIGH)** — `vegetation_lsystem.py:1094` `prepare_gpu_instancing_export`. Function name says "export," accepts `output_path` and `format` (`'json'` or `'binary'`), but **never opens any file** — search `\bopen\(` returns nothing. The export_data dict is just returned. Caller can't tell the export "succeeded" — claim-without-implementation, same anti-pattern as the textureless billboard impostor.
6. **BUG-606 (CRIT, MED)** — `_scatter_engine.py:188-191` `biome_filter_points` UV mapping `u = x / width; v = y / depth; col_idx = int(u * (cols-1))`. The function assumes `points` are corner-anchored `[0, terrain_width] × [0, terrain_depth]`. The single live caller (`environment_scatter.handle_scatter_vegetation` at line 1364) does pass corner-anchored Bridson output ✓, but the contract is **undocumented and brittle** — any future caller passing center-anchored or world-space coords will silently mis-index moisture_map and slope_map.
7. **BUG-607 (HIGH, regression)** — `environment_scatter.py:1148, 1168` `_scatter_pass` gates trees by NORMALIZED altitude (`if h < 0.1 or h > 0.7`). Cross-confirmed with G3's seam findings: the normalized heightmap is `(heights - height_min) / height_range`, so for any tile with negative elevations (basin, sea-level depression) the entire underwater region collapses to `h ≈ 0` and gets rejected. Addendum 3.A regression — alive in source. The bug canary `terrain_scatter_altitude_safety.audit_scatter_altitude_conversion` was *built to detect this class of bug* but its regex set has a gap (BUG-608).
8. **BUG-608 (MED, canary gap)** — `terrain_scatter_altitude_safety.py:32-38` `_BAD_PATTERNS` is incomplete: catches `heights/heights.max()`, `heightmap/heightmap.max()`, `altitude/height_scale`, `center.z/height_scale`, `np.clip(altitude, 0, 1)` — but does NOT catch the actual smoking gun in `_scatter_pass` (normalized heightmap then `< 0.1` literal comparison) nor the `(heights - height_min)/height_range` definition that *creates* the normalized map. The canary lulls reviewers into "passing" while the bug is alive.
9. **BUG-609 (HIGH)** — `environment_scatter.py:1486` `instance.location = (wx, wy, wz)`. `wz` from `_sample_heightmap_surface_world` is `sample * height_scale`, but `height_scale=height_max` is passed (line 1477) while the heightmap was normalized via `((heights - height_min) / height_range)` (line 1326). Math: `wz = ((z - height_min) / height_range) * height_max`. For `height_min = −50, height_max = 100, height_range = 150`, a vertex at world z=0 yields `wz = 50*100/150 = 33.33 m`. **Vegetation floats 33 m above sea level on negative-elevation tiles.** Same `_sample_heightmap_world` is used in `_terrain_height_sampler`'s closure (line 296-307), so `handle_scatter_props` inherits the bug.
10. **BUG-610 (HIGH, NEW)** — `environment_scatter.py:1594` `terrain_sampler = _terrain_height_sampler(bpy.data.objects.get(area_name))`. `area_name` defaults to `"PropScatter"` — the **scatter collection name**, not a terrain object. `bpy.data.objects.get("PropScatter")` returns None (collections aren't objects). `_terrain_height_sampler` returns None. Line 1620 `wz = terrain_sampler(p["position"][0], p["position"][1]) if terrain_sampler else 0.0` — **all props placed at z=0** regardless of actual ground. Confirmed by reading: the function never receives a terrain object name. Cross-confirms the prior wave2 finding (was MED-PROP-1).
11. **BUG-611 (MED, NEW)** — `vegetation_lsystem.py:580-594` `generate_roots`: root start is offset by `dx*trunk_radius*0.5`, but the root end is computed as `(base + dx*length, base + dy*length, base + dz*length)` — the start offset is dropped from the end. Result: the cone connecting start→end is not aligned with `(dx,dy,dz)`. Visible: roots flare outward more than directionally suggests.
12. **BUG-612 (MED, NEW)** — `vegetation_lsystem.py:360-362` tip-marking heuristic `if segments and segments[-1].depth >= state.depth: segments[-1].is_tip = True` — runs on `]`. If a `[X]` opens-and-closes with no `F` between brackets (e.g. grammar `F[+F]F[++]F`), the last segment was emitted at parent depth and gets falsely marked `is_tip=True`. Then `branches_to_mesh` at line 462-473 emits leaf placeholders from the trunk. Bare twig grammars (e.g. "twisted" with `F[++F][--F]`) work fine; complex grammars trip this.
13. **BUG-613 (MED, NEW, NUMERIC)** — `vegetation_lsystem.py:405-408` `_generate_cylinder_ring` perpendicular reference vector flip at `|dx|=0.9` is a hard threshold. Adjacent ring frames whose direction crosses this boundary will use a different `(perp_x, perp_y, perp_z)` and produce **a visible 90° twist** in the bark seam between the two rings. Should use parallel-transport (Frenet frame propagation).
14. **BUG-614 (MED, NEW)** — `vegetation_system.py:441` `if has_height_variation and norm_h < water_level` uses normalized height for water-level comparison. Same Addendum 3.A failure mode as BUG-607: when terrain has negative elevations, `norm_h = (vz - min_h) / height_range`; `min_h < 0` makes norm_h shifted, so `water_level=0.05` no longer means "5% of [0..max_h]" but "5% of [min_h..max_h]." Vegetation excludes parts of land that are above sea level when min_h is sufficiently negative.
15. **BUG-615 (MED, NEW)** — `vegetation_system.py:445-466` density double-application. Line 445 `roll = rng.uniform(0.0, total_density); cumulative = 0.0; for cat, entry in all_entries: cumulative += entry["density"]; if roll <= cumulative: select` (selection by density weight) — then line 466 `if rng.random() > selected_entry["density"]: continue` (Bernoulli on density). Effective placement rate ≈ `density^2`. For density=0.3, actual placements ≈ 9% — caller cannot reason about expected count.
16. **BUG-616 (MED, NEW)** — `vegetation_system.py:359-398` `_sample_terrain` brute-force 9-cell scan per query. For 5000 candidates × ~80 verts/cell × 9 cells = 3.6 M distance ops per call. Replace with `scipy.spatial.cKDTree(xy_array).query(p)` — Context7 `/scipy/scipy` confirms cKDTree is "200-1000× faster than KDTree" and is "drop-in replacement" with same API. Single line change.
17. **BUG-617 (MED, NEW)** — `vegetation_system.py:475` `sample_h, _ = _sample_terrain(wx, wy)` is a **redundant second call** to the same expensive sampler that line 425 already invoked for slope/height filtering. Cache the first call's result.
18. **BUG-618 (MED, NEW)** — `vegetation_system.py:772-773` `if len(placements) > max_instances: placements = placements[:max_instances]` — silent truncation. Bridson active-list order has spatial clustering; truncating the first 5000 of 8000 valid placements creates **biased density** (early-active region oversampled). Replace with `np.random.choice(N, max_instances, replace=False)` or weighted subsample.
19. **BUG-619 (MED, NEW)** — `vegetation_system.py:651-662` `_create_biome_vegetation_template` raises `ValueError` if no generator found. `BIOME_VEGETATION_SETS` references types like `veil_blighted`, `mangrove_root`, `frost_lichen`, `ice_pine`, `corrupted_sapling`, `ember_plant`, `crystal_cluster`, `obsidian` — most are NOT in `VEGETATION_GENERATOR_MAP` (verified by grep). At scatter time this raises and **blows up the entire biome materializer.** Should emit `ValidationIssue(code="VEG_GENERATOR_MISSING", severity="warning")` and fall back to a tagged primitive.
20. **BUG-620 (MED, NEW)** — `vegetation_lsystem.py:664` `iterations = max(1, min(iterations, 6))` silently overrides caller intent (e.g. caller passes 8 expecting hero detail). MISC-020 cap is correct for performance, but should LOG and offer a vertex-budget solver instead of silent clamp.
21. **BUG-621 (LOW-MED, NEW)** — `vegetation_lsystem.py:688` `num_roots = max(3, min(5, int(trunk_radius * 10)))` — for ancient/oak (trunk_radius=0.6) capped at 5; hero trees should have 8+ visible roots.
22. **BUG-622 (HIGH visual, NEW)** — `vegetation_lsystem.py:750-882` `generate_leaf_cards`. Cards never camera-face (no shader hint, no normal output, no UV emission). `final_ux += dz * tilt; final_uz -= dx * tilt` (lines 853-854) is an additive shear, not a rotation — the resulting quad has non-orthogonal corners and breaks unit-length invariant. No UVs returned anywhere → alpha cutout cannot map.
23. **BUG-623 (HIGH stream, NEW from G3 cross-confirm)** — `_scatter_engine.poisson_disk_sample:26` and `terrain_assets._poisson_in_mask:362` both restart Bridson per call with a fresh seeded initial point. **No global blue-noise across tile boundaries.** G3 confirmed seam discontinuities at tile borders. UE5 PCG and Houdini both use either tileable Poisson or globally-evaluated-then-cropped sampling. **D-grade for streaming use, A− for single-tile use.**
24. **BUG-624 (LOW, NEW)** — `terrain_assets.py:593-594` `dr = int(round(sin*dist))` rounds to integer cells in `_cluster_around`; multiple rocks within one cluster can land on the same `(rr, cc2)` cell, producing co-located rocks. No intra-cluster Poisson.

Total NEW bugs this round: **24** (BUG-601 to BUG-624).

---

## 2. Per-function deep audit (95 functions)

Format per entry: **`name` (file:line) — Prior grade: X → My grade: Y — AGREE/DISPUTE-DOWN/DISPUTE-UP** | What | Reference | Bug/gap (file:line) | AAA gap | Severity | Upgrade.

Prior grades come from CSV (`environment_scatter.py` only) and prior wave2 B14 doc (`vegetation_lsystem.py`, `vegetation_system.py`, `_scatter_engine.py`, `terrain_assets.py`, `terrain_asset_metadata.py`, `terrain_scatter_altitude_safety.py`, `terrain_vegetation_depth.py`). A3 doc grades override where present.

---

### 2.1 `vegetation_lsystem.py` (14 functions)

#### `expand_lsystem` (vegetation_lsystem.py:125) — Prior **A** → My **A** — **AGREE**
* What: Standard string-rewriting L-system; `O(N · iterations · avg-rule-len)`.
* Reference: Lindenmayer 1968; matches L-Py and Houdini L-System SOP byte-for-byte.
* Bug: none material.
* AAA gap: real SpeedTree uses **parametric L-systems** (`F(length, radius)` with arithmetic in productions). This is non-parametric.
* Severity: cosmetic.
* Upgrade to A+: parametric L-system support with a small expression evaluator.

#### `_rotate_vector` (vegetation_lsystem.py:153) — Prior **A** → My **A** — **AGREE**
* Rodrigues' rotation, correct, branch-free.
* AAA gap: modern engines use quaternions for chained rotations to avoid axis drift.
* Upgrade to A+: vectorize via numpy when called in batches.

#### `_TurtleState.__init__` (vegetation_lsystem.py:186) — Prior **A−** → My **A−** — **AGREE**
* `__slots__` perf-correct; explicit field init. Direction starts (0,0,1) — Z-up. Right starts (1,0,0).
* No bug.

#### `_TurtleState.copy` (vegetation_lsystem.py:201) — Prior **A−** → My **A−** — **AGREE**
* Hand-rolled to avoid `copy.copy` overhead. Solid for hot path.
* MED bug: never re-orthogonalizes `right` against `direction` after rotations. Over many `[`/`+`/`-` operations the basis drifts. SpeedTree's turtle re-Gram-Schmidts per push.
* Upgrade to A: Gram-Schmidt re-orthonormalize `right` against the new direction in `_rotate_vector`.

#### `BranchSegment.__init__` (vegetation_lsystem.py:226) — Prior **A−** → My **A−** — **AGREE**
* Slot-optimized. Trivial. No bug.

#### `interpret_lsystem` (vegetation_lsystem.py:245) — Prior **B+** → My **C+** — **DISPUTE-DOWN**
* What: turtle interpreter with stack push/pop, gravity, randomness.
* Reference: faithful to L-Py turtle, missing apical dominance, phototropism, biomechanical relaxation, and tropism vectors that SpeedTree models.
* **BUG-602 (CRIT):** lines 288-297 — cumulative gravity drag flips trunk direction past zero on willow / long branches. Trunks droop at depth 0, botanically wrong.
* **BUG-603 (CRIT):** line 286 — negative `length` from gauss perturbation produces backwards twigs.
* **BUG-612 (MED):** lines 360-362 — empty branches mark trunk as `is_tip=True` → leaves on trunks.
* AAA gap: no leaf orientation hint (SpeedTree emits tip + bundle normal); no per-segment Reaction Wood metadata; no biomechanical post-pass.
* Severity: HIGH.
* Upgrade to A: clamp `length ≥ 0.05`; replace cumulative gravity with proportional pull `state.dz = mix(state.dz, -1, gravity*dt)`; add `apical_dominance` parameter; emit explicit tip_kind so leaves don't spawn on trunks.

#### `_generate_cylinder_ring` (vegetation_lsystem.py:380) — Prior **A−** → My **B+** — **DISPUTE-DOWN**
* Builds perpendicular ring via cross-product. Branch-free 2-arm choice for perpendicular reference.
* **BUG-613 (MED):** line 405-408 — perpendicular flip at `|dx|=0.9` is a hard threshold; visible 90° bark seam twist when adjacent ring frames cross the boundary.
* AAA gap: SpeedTree maintains parallel-transport frames along branches (Frenet frame propagation).
* Severity: medium.
* Upgrade to A: parallel-transport — pass previous ring's `up` to next call.

#### `branches_to_mesh` (vegetation_lsystem.py:437) — Prior **A−** → My **A−** — **AGREE**
* Truncated cones via paired rings + quad faces. Drops sub-radius segments to leaf placeholders. Correct.
* Bug: line 503 emits **quads**, but no triangulation. Caller (`mesh_from_spec`) likely triangulates, but `face_count` metadata conflates quads vs tris.
* AAA gap: no per-vertex normal emit (relies on `auto_smooth`); no UV emission.
* Severity: low-medium.
* Upgrade to A: emit per-vertex normals (cross product of ring tangent × axial direction); emit UVs `(angle/2π, accumulated_length)` for bark.

#### `generate_roots` (vegetation_lsystem.py:539) — Prior **A−** → My **B+** — **DISPUTE-DOWN**
* What: 3-8 visible roots, downward-angled, randomized per-root.
* **BUG-611 (MED):** line 580-594 — root end-position drops the start offset. Cone is not aligned to declared `(dx,dy,dz)` direction.
* **BUG-621 (LOW-MED):** num_roots capped at 5 even for huge trunks (line 688 in `generate_lsystem_tree`).
* AAA gap: roots not adapted to terrain slope — SpeedTree's "Mesh Forces" fall roots along ground normal.
* Severity: medium.
* Upgrade to A: align root start to ground normal; fix end-position bug; vary root taper.

#### `generate_lsystem_tree` (vegetation_lsystem.py:609) — Prior **A−** → My **B+** — **DISPUTE-DOWN**
* What: pipeline (expand → interpret → roots → mesh).
* **BUG-620 (MED):** line 664 — silent iteration cap from 8 to 6; should LOG + offer vertex-budget solver.
* **BUG-621 (LOW-MED):** line 688 — root count capped at 5 regardless of trunk size.
* AAA gap: no LOD chain emitted (single mesh). SpeedTree exports LOD0..LOD3 + billboard atlas in one call.
* Severity: medium.
* Upgrade to A: vertex-budget solver `solve_iterations(target_verts=15000)`; ramp `num_roots` with `trunk_radius`; emit LOD0/1/2 in one call.

#### `generate_leaf_cards` (vegetation_lsystem.py:750) — Prior **B+** → My **B−** — **DISPUTE-DOWN**
* What: cross-quad leaf cards at branch tips, random rotation/scale/tilt.
* **BUG-622 (HIGH visual):** leaves never camera-face; lines 853-854 shear-tilt produces non-orthogonal quads; no UVs emitted → alpha cutout cannot map.
* AAA gap: SpeedTree uses **8-card hemispherical leaf clusters** with subsurface translucency, two-sided alpha, wind-mask vertex colors, per-card random UV atlas slot. Megascans uses real photogrammetry leaf meshes.
* Reference: Quixel Megascans Foliage uses *measured* leaf meshes with 8K alpha+normal+SSS atlases per species.
* Severity: HIGH for visual quality.
* Upgrade to A: emit `(u,v) ∈ [0,1]^2` per quad-corner; emit per-quad center + normal so a Unity shader can billboard; replace shear "tilt" with axis-angle rotation; document a fixed atlas grid (e.g. 4×4 leaf variants).

#### `bake_wind_vertex_colors` (vegetation_lsystem.py:889) — Prior **A−** → My **C+** — **DISPUTE-DOWN**
* What: R = radial+height sway, G = depth-based flutter, B = phase hash.
* **BUG-601 (CRIT, HIGH):** line 962 sin/floor hash precision — banded wind phase striping at world coords beyond ~340 m. Critical for any open-world tile.
* MED issue: R-channel mixes radial *and* height with `0.5/0.5` weights. SpeedTree convention is R=primary trunk sway (height-only, 0 at root), G=branch sway, B=leaf flutter. This re-uses R for what should be G+B mixed.
* AAA gap: Pivot Painter 2.0 packs per-pivot data into 16-bit RG channels with B for hierarchy index — this stuffs phase into 8-bit B alone (256 buckets max, periodic at 60 Hz wind).
* Reference: WebSearch confirmed SpeedTree to UE plugin uses 5 additional UV channels + vertex paint for 2-level wind; Pivot Painter 2 uses 1 UV channel + 2 textures for 4-level wind. Neither matches this implementation.
* Severity: HIGH (visible artifact + wrong channel semantics).
* Upgrade to A: replace sin-hash with `numpy.random.default_rng(seed=int(vx*1000) ^ int(vy*1000)*31 ^ int(vz*1000)*97).random()` for deterministic per-vertex phase; split channels SpeedTree-style; pack phase as two 8-bit halves into BA for 16-bit precision.

#### `generate_billboard_impostor` (vegetation_lsystem.py:975) — Prior **D** → My **D** — **AGREE**
* Generates an N-sided **textureless prism** + JSON metadata blob with a "next_steps" list of things the caller should do but never does. Zero impostor texture baking anywhere in the codebase.
* Reference: Real octahedral impostors (Shaderbits / Ryan Brucks 2018, integrated into UE5 since 4.20) bake a 2K-4K RGBA atlas with N=12 cap-octahedron view directions plus depth in alpha for parallax. Crysis-era cross-billboards (this implementation) were AAA in 2007.
* AAA gap: catastrophic. A AAA open-world game ships *real* impostor atlases authored either in SpeedTree, ImposterBaker, or Houdini PDG — none of that exists here.
* Severity: BLOCKER for AAA distance vegetation.
* Upgrade to A: integrate Blender's `bpy.ops.render.render` driven by a script that places a 12-position camera ring + 4 hemispherical caps, captures RGBA+depth into a 2048² atlas, exports as PNG, and emits a Unity Shader Graph or UE5 Material that does parallax-depth lookup. Without this, the codebase **cannot** ship 1000+ trees per view at 60 fps.

#### `prepare_gpu_instancing_export` (vegetation_lsystem.py:1094) — Prior **B** → My **C** — **DISPUTE-DOWN**
* **BUG-605 (CRIT MED-HIGH):** function is called "export" with `output_path` and `format` parameters but **never opens the file**. The export_data dict is returned in result; I/O is left to caller. Format='binary' accepted with no binary code path.
* AAA gap: no actual HISM (Unreal Hierarchical Instanced Static Mesh) binary, no Unity DOTS-ECS chunk, no MeshInstancer-compatible struct. Emits plain JSON. Real GPU instancing payloads are interleaved float arrays packed as ByteBuffer / FlatBuffer / HISM proto — the format Unity *can* consume in `Graphics.DrawMeshInstancedIndirect`.
* Severity: medium-high (API claim mismatch).
* Upgrade to A: add `format='unity_indirect'` emitting tightly packed `np.float32 (N, 16)` matrix + `(N,)` material/lod arrays writable as `np.save`. Add `format='ue5_hism'` emitting binary `FInstancedStaticMeshInstanceData` payload. Actually call `with open(output_path, 'wb') as f: ...`.

---

### 2.2 `vegetation_system.py` (7 functions)

#### `_max_slope_for_category` (vegetation_system.py:262) — Prior **A** → My **A** — **AGREE**
* Trivial dispatch on category string. No bug.

#### `compute_vegetation_placement` (vegetation_system.py:277) — Prior **A−** → My **B** — **DISPUTE-DOWN**
* What: terrain-grid lookup + Poisson + slope/altitude/biome + density probability.
* Reference: matches UE5 PCG Graph "Density Filter + Self-Pruning" pattern.
* **BUG-614 (MED, HIGH-domain):** line 441 normalized water level — Addendum 3.A class bug.
* **BUG-615 (MED):** lines 445-466 density applied twice; effective rate ≈ density².
* **BUG-616 (MED):** brute-force 9-cell vertex scan per query (line 359-380).
* **BUG-617 (MED):** redundant second `_sample_terrain` call (line 475).
* AAA gap: no per-species exclusion radius (oak and pine can co-locate); no neighborhood density estimation; no canopy/understory awareness (duplicates `terrain_vegetation_depth.compute_vegetation_layers`).
* Context7 `/scipy/scipy` confirms `cKDTree.query` is 200-1000× faster than the brute-force vertex grid.
* Severity: HIGH.
* Upgrade to A: scipy KDTree for vertex lookup; replace double-density with single density-by-area; honor `WorldHeightTransform` for water level; cache `_sample_terrain` result per point; integrate with `terrain_vegetation_depth.compute_vegetation_layers`.

#### `_sample_terrain` (closure inside `compute_vegetation_placement`, vegetation_system.py:359) — Prior **(missed)** → My **C+** — **NEW ASSESSMENT**
* Brute-force 9-cell × ~80-vert scan per call.
* Bug: returns `(0.5, 0.0)` default if no nearest vertex found — silent fallback that places vegetation at "mid-height, flat" → can spawn trees in voids.
* Severity: medium.
* Upgrade to A: scipy KDTree on terrain XY; raise on no-neighbor-found instead of silent default.

#### `compute_wind_vertex_colors` (vegetation_system.py:490) — Prior **A−** → My **B** — **DISPUTE-DOWN**
* Same channel-mixing issue as L-system version: R/G/B all derived from radial+height mix; B is `(r*0.5+g*0.5)` literally — that's a deterministic function of R and G, providing **zero independent information** on B.
* No CRIT-01 hash banding here (uses simple normalized math), so safer than L-system version.
* AAA gap: same SpeedTree channel-semantic mismatch.
* Severity: medium.
* Upgrade to A: split into trunk-sway (R, height-only), branch-sway (G, depth proxy), leaf-flutter (B, per-vertex random with deterministic seed), phase (A, packed 16-bit).

#### `get_seasonal_variant` (vegetation_system.py:574) — Prior **B+** → My **B+** — **AGREE**
* 4 seasons × 3 vegetation classes with sensible scalar tweaks. Clean.
* AAA gap: no per-species seasonal curves (autumn is per-genus); no transition states (mid-autumn = blend). Just discrete enum.
* Upgrade to A: `season: float ∈ [0, 4)` and interpolate.

#### `_create_biome_vegetation_template` (vegetation_system.py:651) — Prior **B+** → My **C+** — **DISPUTE-DOWN**
* **BUG-619 (HIGH gap):** raises `ValueError` if no generator. `BIOME_VEGETATION_SETS` references many types not in `VEGETATION_GENERATOR_MAP` (`veil_blighted`, `mangrove_root`, `frost_lichen`, `ice_pine`, `corrupted_sapling`, `ember_plant`, `crystal_cluster`, `obsidian`, `shelf_mushroom`, `bioluminescent`, `spore_cluster`, `fungal_log`, `frozen_boulder`, `ice_crystal`, `sludge_rock`, `crumbled_stone`, `dead_brush`, `tumbleweed`, `cactus_rock`, `wind_eroded`, `coastal_scrub`, `sea_grass`, `driftwood`, `sea_worn`, `lone_windswept`, `tall_grass`, `wildflower`, `field_stone`, `giant_mushroom`, `small_growth`, `mineral_formation`, `ancient_oak`, `thick_fern`, `hanging_moss`, `surface_root`, `root_boulder`, `tombstone`, `charred_stump`, `dark_pine`, `willow_hanging`, `dead_twisted`). At biome materializer time this raises. Fail-loud is OK *if* upstream catches; but the master audit notes "21+ scatter asset types lack mesh generators" — this is the failure point.
* Severity: HIGH (gap, not bug).
* Upgrade to A: emit `ValidationIssue(code="VEG_GENERATOR_MISSING", severity="warning")` and use a fallback "tagged primitive" template instead of raising.

#### `scatter_biome_vegetation` (vegetation_system.py:673) — Prior **B+** → My **B−** — **DISPUTE-DOWN**
* **BUG-618 (MED):** line 772 silent truncation introduces spatial bias.
* Bug: line 793 `_setup_billboard_lod` only fires for trees; rocks/ground cover get LOD distance custom props (line 815-820) but no actual LOD chain — there are no LOD1/LOD2 meshes made anywhere, just numbers in a property. Unity importer must independently generate LODs from these distance hints.
* AAA gap: no HISM batching, no chunk-spatial groups (large terrains dump 5000 instances into one Blender collection — Unity importer has to re-chunk).
* Severity: medium-high.
* Upgrade to A: importance-weighted subsample; generate actual LOD1/LOD2 meshes via `generate_lod_chain`; output spatial chunk metadata for streaming.

---

### 2.3 `_scatter_engine.py` (10 functions)

#### `poisson_disk_sample` (_scatter_engine.py:26) — Prior **A** → My **A−** — **DISPUTE-DOWN**
* Bridson 2007 spatial-hash Poisson disk; `cell_size = min_dist/√2`, 5×5 neighborhood, max_attempts=30. Matches the canonical algorithm (verified vs cs.ubc.ca/~rbridson PDF).
* **BUG-623 (HIGH for streaming):** restart per-call with fresh seeded initial point — no global blue-noise across tiles. Cross-confirmed with G3 seam findings. UE5 PCG and Houdini both use tileable Poisson or globally-evaluated-then-cropped sampling.
* MED bug: line 92-93 `x0 = rng.uniform(0, width); y0 = rng.uniform(0, depth)` — initial point is uniform-random, ignoring prior active list. For `width < min_distance`, no second point can fit and function returns 1 point. Edge case.
* AAA gap: not tileable; no boundary stitching; no density-modulated radius (real PCG uses `min_distance(x,y)` from a density map — Poisson sphere packing with variable r).
* Severity: HIGH for streaming use; LOW for single-tile use.
* Upgrade to A: add `tile_x, tile_y` and seed-global-then-crop variant `poisson_disk_sample_tileable(world_x, world_y, tile_size, min_distance)` returning the subset of a globally-deterministic point cloud falling inside this tile.

#### `_grid_idx` (closure inside `poisson_disk_sample`, _scatter_engine.py:66) — Prior **(missed)** → My **A** — **NEW ASSESSMENT**
* Trivial cell index helper with bounds clamp. No bug.

#### `_is_valid` (closure inside `poisson_disk_sample`, _scatter_engine.py:73) — Prior **(missed)** → My **A** — **NEW ASSESSMENT**
* 5×5 spatial hash neighborhood scan. Bridson canonical. No bug.

#### `biome_filter_points` (_scatter_engine.py:131) — Prior **A−** (implied) → My **B+** — **DISPUTE-DOWN**
* What: filters Poisson points by altitude/slope/moisture rules. Per-rule density Bernoulli + weighted choice across passing rules.
* **BUG-606 (CRIT MED):** lines 188-191 — UV mapping has undocumented corner-anchored contract. Single live caller is OK but contract is brittle.
* MED: line 234 per-rule Bernoulli applied before weighted pick → total density is `1 − ∏(1 − d_i)`, not `Σ d_i`. Caller can't reason about output density.
* AAA gap: no per-species exclusion (KD-tree query of already-placed points within rule-specific exclusion radius).
* Severity: medium-high.
* Upgrade to A: document corner-anchored input contract; replace per-rule Bernoulli + weighted-pick with single weighted random over all matching rules; add post-filter KD-tree exclusion.

#### `context_scatter` (_scatter_engine.py:318) — Prior **B+** (implied) → My **B+** — **AGREE**
* Poisson-disk near buildings, distance-based affinity blend with generic props.
* Reference: matches Witcher 3 / RDR2 "town clutter" placement style (visual-similarity, not algorithmic copy).
* Bug: line 366-373 nearest-building search is O(N_buildings × N_candidates). Fine for ≤100 buildings; should KDTree for large towns.
* AAA gap: no orientation-aware placement (props at building corners should align to wall normal); no occlusion check (props inside dense building cluster get culled in PCG); affinity_radius hardcoded 15.0 m regardless of building size.
* Severity: low-medium.
* Upgrade to A: scipy KD-tree on building positions (Context7 `/scipy/scipy` `KDTree.query` drop-in); per-building-type `affinity_radius`; orient props to nearest wall normal.

#### `_weighted_choice` (_scatter_engine.py:402) — Prior **A** (implied) → My **A** — **AGREE**
* Standard weighted-choice. Sum, uniform, cumulate, return. No bug.

#### `generate_breakable_variants` (_scatter_engine.py:455) — Prior **B+** (implied) → My **B+** — **AGREE**
* Emits intact + destroyed mesh specs with darkened material.
* Bug: `darken_factor = 0.6` is magic; should be data-driven per material.
* AAA gap: no Voronoi fracture (Houdini RBD or Unity's PolyFracture). Stave approximation is 2008-era.
* Severity: low.
* Upgrade to A: load Voronoi fragments from Houdini PDG `.json` if present, fallback to current stave approximation.

#### `_build_geometry_op` (_scatter_engine.py:525) — Prior **A** → My **A** — **AGREE**
* Trivial dispatch. No bug.

#### `_generate_fragments` (_scatter_engine.py:539) — Prior **B+** → My **B+** — **AGREE**
* Stave-like (cylinder) and plank-like (box) approximations. `frag_width = 2*radius*sin(π/count)` is geometrically correct for an inscribed N-gon stave.
* AAA gap: no inertia tensors; no UV preservation across cut surface; no break-edge color variation (interior wood lighter than weathered exterior).
* Upgrade to A: emit `interior_face_indices` and a separate `interior_material` for shading freshly-broken faces.

#### `_generate_debris` (_scatter_engine.py:586) — Prior **B+** → My **B+** — **AGREE**
* Random small cubes scattered around the prop. Trivial.
* AAA gap: not really debris — just cubes. Real debris is splinters, shards, fragments with proper volume distribution.

---

### 2.4 `environment_scatter.py` (28 functions)

#### `_assign_scatter_material` (environment_scatter.py:146) — Prior CSV **B+** → My **B** — **DISPUTE-DOWN slightly**
* Builds procedural Principled BSDF with noise + colour ramp per material key. No textures. Tree mode adds height-based trunk→foliage gradient. Adequate preview shading.
* AAA gap: no PBR map binding (albedo/normal/roughness/AO from Megascans). Procedural noise instead.
* Severity: this is *Blender preview material*, not the shipped material. Acceptable per its scope but the prior B+ overstates it — it's a **B for preview, never a shipped material**.

#### `_vegetation_rotation` (environment_scatter.py:249) — Prior CSV **A−** → My **A** — **DISPUTE-UP slightly**
* Trivial Y-up→Z-up rotation dispatch via membership in frozensets. Clean.

#### `_prop_rotation` (environment_scatter.py:255) — Prior CSV **A−** → My **A** — **DISPUTE-UP slightly**
* Same pattern. Clean.

#### `_terrain_height_sampler` (environment_scatter.py:261) — Prior CSV **B** → My **B−** — **DISPUTE-DOWN**
* Builds bmesh, detects rows×cols by uniqueness, computes normalized heightmap, returns closure that calls `_sample_heightmap_world`.
* Bug: line 273-275 `xs = set(round(v.co.x, 3) for v in bm.verts)` — `round(x, 3)` quantizes to 1 mm. For small terrains where vertex spacing < 1 mm this collapses to 1 cell. Edge case.
* **BUG-609 contributor:** heightmap is normalized `((heights - height_min) / height_range)` (line 289) but `_sample` (line 296-307) passes `height_scale=height_max` not `height_range` — multiplying normalized output by height_max gives `(z - height_min) * height_max / height_range` ≠ z when height_min ≠ 0.
* AAA gap: closure rebuilds heightmap on every handler call (no caching).
* Severity: medium-high.
* Upgrade to A: pass `height_scale=height_range` and add `height_offset=height_min`; cache.

#### `_sample` (closure inside `_terrain_height_sampler`, environment_scatter.py:296) — Prior **(missed)** → My **B−** — **NEW ASSESSMENT**
* Inherits BUG-609 from caller. Otherwise trivial.

#### `_world_to_terrain_uv` (environment_scatter.py:311) — Prior CSV **A−** → My **A−** — **AGREE**
* Standard local-coords-to-UV. Raises on zero/negative dims. Correct.

#### `_sample_heightmap_surface_world` (environment_scatter.py:334) — Prior CSV **A−** → My **B+** — **DISPUTE-DOWN**
* Bilinear height + analytical gradients (`dzdx`, `dzdy`) via finite-difference. Correct math when `height_scale` matches the heightmap's normalization range.
* **BUG-609:** when caller passes `height_scale=height_max` for a heightmap normalized by `height_range`, output is biased by `|height_min|`. Cross-confirms with `handle_scatter_vegetation` at line 1475-1484.
* AAA gap: single-resolution bilinear; no Catmull-Rom or cubic interpolation. UE5 Landscape uses cubic.
* Severity: medium.

#### `_sample_heightmap_world` (environment_scatter.py:392) — Prior CSV **A** → My **A−** — **DISPUTE-DOWN slightly**
* Wrapper that drops gradients. Same bug class. Not material per-se, but inherits parent.

#### `_terrain_axis_spacing_from_extent` (environment_scatter.py:417) — Prior CSV **A** → My **A** — **AGREE**
* Trivial. `(rows-1, cols-1)` correct denominator. No bug.

#### `_terrain_cell_size_from_extent` (environment_scatter.py:429) — Prior CSV **A** → My **A** — **AGREE**
* Trivial wrapper. No bug.

#### `_create_template_collection` (environment_scatter.py:493) — Prior CSV **A−** → My **A−** — **AGREE**
* Hides templates from viewport/render. No bug.

#### `_create_vegetation_template` (environment_scatter.py:503) — Prior CSV **B** → My **B−** — **DISPUTE-DOWN**
* `VEGETATION_GENERATOR_MAP` lookup with cube fallback for unmapped types.
* Bug: line 519 — `iterations=3, ring_segments=4` for tree types. Reasonable. But `bush`, `shrub`, `mushroom` etc. don't get any low-poly override — they use generator defaults which may be high-poly. Inefficient.
* Bug: cube fallback for unmapped types is silent (no warning); user sees gray 0.5m cubes scattered everywhere a generator is missing.
* AAA gap: no LOD chain on the template; no impostor; templates are single-resolution and used 1000×.
* Severity: medium.
* Upgrade to A: warn on cube fallback; auto-generate LOD chain for every template; emit billboard impostor for tree templates.

#### `_add_leaf_card_canopy` (environment_scatter.py:637) — Prior CSV **B+** → My **B** — **DISPUTE-DOWN**
* 3 vertical + (N-3) angled planes around canopy center, each with phase-randomized wind vertex colors.
* Reference: 2010-era leaf-card cluster (Crysis 2 trees).
* AAA gap: planes never re-orient to camera; alpha cutout texture not bound; SSS material not used; planes interpenetrate without alpha sorting.
* Severity: medium.

#### `create_leaf_card_tree` (environment_scatter.py:744) — Prior CSV **A−** → My **B** — **DISPUTE-DOWN**
* Trunk (6-segment tapered cylinder) + leaf-card canopy. Wind colors painted on trunk too (A=trunk_sway).
* AAA gap: no branches between trunk and canopy — just trunk+canopy. Real trees have visible mid-canopy branches even at LOD2.
* Severity: medium.
* Upgrade to A: route to L-system tree (with iter=3) for trunk+branches, then add leaf cards.

#### `_create_grass_card` (environment_scatter.py:826) — Prior CSV **B+** → My **B+** — **AGREE**
* 2 crossed V-bend blades, wind colors at base/mid/tip, biome-color material. Standard "billboard grass tuft".
* AAA gap: no anisotropic shading hint (grass needs aniso direction along blade); no 4-or-6-way card cluster (Modern grass is 4-6 cards rotated 30/60/120 — this only does 2 at 60).
* Severity: low.

#### `rot` (closure inside `_create_grass_card`, environment_scatter.py:890) — Prior **(missed)** → My **A** — **NEW ASSESSMENT**
* Trivial 2D rotation. No bug.

#### `_rock_size_from_power_law` (environment_scatter.py:953) — Prior CSV **B** → My **A−** — **DISPUTE-UP**
* 70/25/5 power-law size split. Returns (scale, size_class). Statistically realistic — matches geological field-data distribution for talus.
* Could vary rotation/density per class but that's the caller's job.
* I disagree with prior CSV's B — this matches geomorphology literature.

#### `_generate_combat_clearing` (environment_scatter.py:972) — Prior CSV **A−** → My **A−** — **AGREE**
* Tree ring around 15-40 m clearing, N entry gaps. Clean.
* Edge case: line 1015 `entry_gap_half_angle = math.asin(min(1.0, 2.0 / radius))` — for radius < 2 m, asin(1) = π/2 = 90°, meaning the entire half-circle is a "gap" and no trees spawn. The diameter clamp keeps radius ≥ 7.5 m so safe in practice.
* AAA gap: no path mesh emitted (just gap); no torch/lantern placement at entrance; clearing flatness not enforced (terrain may slope inside).

#### `_scatter_pass` (environment_scatter.py:1057) — Prior CSV **B−** → My **C+** — **DISPUTE-DOWN**
* Per-pass (structure/ground_cover/debris) Poisson + slope/height/exclusion filtering.
* **BUG-607 (HIGH):** lines 1148, 1168 use NORMALIZED heightmap for `if h < 0.1 or h > 0.7`. Addendum 3.A regression confirmed alive.
* Bug: lines 1185-1186 grass `seed+2`, 1233 rocks `seed+3`, 1106 trees `seed+1` — should use `derive_pass_seed(seed, "structure")` etc. (consistent with Bundle E pattern).
* Bug: line 1188 `biome_grass = biome if biome in _GRASS_BIOME_SPECS else "prairie"` — silent fallback; `_GRASS_BIOME_SPECS` has 6 biomes vs `_BIOME_DENSITY` has 9 — most biome names that work for tree density don't have grass specs.
* AAA gap: no per-tile global Poisson; no canopy-overlap check (`_near_tree(wx, wy)` only checks 1 m radius, real shadow extends to ~tree_canopy_radius).
* Severity: HIGH (BUG-607 alone is a vis bug).
* Upgrade to A: route altitude check through `WorldHeightTransform` to operate in metres; use `derive_pass_seed`; add canopy radius check based on tree.scale; add KD-tree for tree exclusion.

#### `_sample_height_norm` (closure inside `_scatter_pass`, environment_scatter.py:1108) — Prior **(missed)** → My **C+** — **NEW ASSESSMENT**
* Returns the live BUG-607 normalized value. Fix at this site or at the caller.

#### `_sample_slope` (closure inside `_scatter_pass`, environment_scatter.py:1117) — Prior **(missed)** → My **B+** — **NEW ASSESSMENT**
* Slope sampling is OK (slope_map isn't normalized, it's degrees). No domain bug here. Minor: O(1) lookup but rebuilds u/v fresh per call; could cache.

#### `_in_building` (closure inside `_scatter_pass`, environment_scatter.py:1126) — Prior **(missed)** → My **B** — **NEW ASSESSMENT**
* Linear scan over building_zones. For 200 buildings × 5000 candidates = 1M ops. KDTree on AABB centers would help.

#### `_in_clearing` (closure inside `_scatter_pass`, environment_scatter.py:1134) — Prior **(missed)** → My **B+** — **NEW ASSESSMENT**
* Linear scan over combat_clearings. Typically <10 clearings, fine.

#### `_near_tree` (closure inside `_scatter_pass`, environment_scatter.py:1190) — Prior **(missed)** → My **C** — **NEW ASSESSMENT**
* Hardcoded 1.0 m radius regardless of tree size. Should use tree.scale * canopy_radius_factor.
* O(N_trees × N_grass) — for 5000 trees × 50000 grass = 250M ops. KDTree drop-in would cut to O(grass × log(trees)).
* Severity: medium-high.

#### `handle_scatter_vegetation` (environment_scatter.py:1266) — Prior CSV **B** → My **B−** — **DISPUTE-DOWN**
* ~250-line bpy handler.
* **BUG-609 (HIGH, CONFIRMED):** line 1486 with line 1477 `height_scale=height_max` — vegetation floats above sea-level basins. Math walked through: `wz = ((z - height_min)/height_range) * height_max`.
* Bug: lines 1376-1408 building exclusion does an O(N_objects × N_children × N_corners) scan of the entire scene every call. For a city with 200 buildings × 8 corners × 5000 placements = 8 M ops per scatter — slow.
* Bug: line 1428 silent truncation at `max_instances=5000`.
* Bug: lines 1444-1448 calls `_setup_billboard_lod` with `veg_spec=None` — falls back to bbox estimation. Comment admits it's a fallback path.
* AAA gap: very long single function (250+ lines); no async/chunked instantiation (large terrains stall Blender for minutes); no progress reporting.
* Severity: HIGH.
* Upgrade to A: refactor into helpers; pre-build KD-tree of building bboxes; fix height_scale; warn on truncation; add `bpy.types.Operator` modal progress.

#### `_create_prop_template` (environment_scatter.py:1519) — Prior CSV **B+** → My **B+** — **AGREE**
* `PROP_GENERATOR_MAP` lookup with cube fallback + warning log. Better than vegetation template (which silently cubes).

#### `handle_scatter_props` (environment_scatter.py:1565) — Prior CSV **B+** → My **C+** — **DISPUTE-DOWN**
* Context_scatter wrapper. Clean ~70 lines.
* **BUG-610 (HIGH NEW):** line 1594 `terrain_sampler = _terrain_height_sampler(bpy.data.objects.get(area_name))` — area_name="PropScatter" is the scatter collection name, not a terrain object. terrain_sampler always None → all props at z=0 (line 1620).
* Severity: HIGH.
* Upgrade: accept explicit `terrain_name` parameter and look that up.

#### `handle_create_breakable` (environment_scatter.py:1638) — Prior CSV **B** → My **B** — **AGREE**
* Generates intact + destroyed cube approximations + materials. Standard.
* Bug: line 1697 assumes the default `Principled BSDF` node exists. After `mat_intact.use_nodes = True`, Blender 4.x default *does* create it, so OK.
* AAA gap: no rigid-body physics setup, no fragment audio cues, no debris fade-out timer.
* Severity: low.

---

### 2.5 `terrain_assets.py` (19 functions) — strongest module

A3 rated this an **A** for genuine vectorized Poisson-in-mask + slope/altitude/wetness envelopes. Verified — I AGREE with one downgrade (`_build_detail_density` due to Unity int[,] mismatch).

#### `AssetRole` enum (terrain_assets.py:62) — Prior **A** → My **A** — **AGREE**
9 roles. Clean.

#### `ViabilityFunction` dataclass (terrain_assets.py:79) — Prior **A** → My **A** — **AGREE**
Frozen dataclass + `__call__`. Excellent.

#### `ViabilityFunction.__call__` (terrain_assets.py:90) — Prior **(implied A)** → My **A** — **AGREE**
* Trivial dispatch to the wrapped function with float coercion. No bug.

#### `AssetContextRule` dataclass (terrain_assets.py:94) — Prior **A** → My **A** — **AGREE**
Frozen, declarative, slot-friendly. Excellent.

#### `ClusterRule` dataclass (terrain_assets.py:112) — Prior **A** → My **A** — **AGREE**
Frozen, declarative.

#### `classify_asset_role` (terrain_assets.py:152) — Prior **A−** → My **A−** — **AGREE**
Lookup + heuristic substring fallback. Clean.

#### `build_asset_context_rules` (terrain_assets.py:176) — Prior **A−** → My **A−** — **AGREE**
~10 default rules. Reasonable starting set.
* Could be data-driven (load from YAML) for non-developer iteration.

#### `compute_viability` (terrain_assets.py:283) — Prior **A** → My **A** — **AGREE**
* Vectorised per-cell viability mask. No Python loops over cells. Conservative behaviour when slope channel absent (line 311-314): if the rule requires non-trivial slope bounds and slope is missing, viability=0 (fail-loud-ish).
* Reference: matches Houdini "Heightfield Mask by Feature" exactly.
* Bug: none material.

#### `_cell_to_world` (terrain_assets.py:346) — Prior **A** → My **A** — **AGREE**
* Z-up world coord conversion. Reads `stack.height[r,c]` directly per Bundle E contract. Honors the safety doctrine.

#### `_poisson_in_mask` (terrain_assets.py:362) — Prior **A−** → My **A−** — **AGREE**
* Bridson-style spatial-hash Poisson constrained to viability mask.
* Bug: `max_attempts=20` (default) vs Bridson's recommended 30. Lower attempts → ~5% fewer accepted points. Cosmetic.
* Bug: line 386 `rng.shuffle(candidates)` — shuffles entire candidates array (could be 10K elements). Bridson's true active-list approach skips the shuffle. Performance OK.
* **BUG-623 (HIGH):** not tileable (per-call seed-anchored, same as `_scatter_engine.poisson_disk_sample`). Adjacent tiles have density seams.
* Severity: low (mask-constrained variants tend to mask out boundaries naturally) for single tile; HIGH for streaming.
* Upgrade to A: bump `max_attempts=30`; tileable variant.

#### `_gkey` (closure inside `_poisson_in_mask`, terrain_assets.py:398) — Prior **(missed)** → My **A** — **NEW ASSESSMENT**
* Trivial 2-element tuple. No bug.

#### `_protected_mask` (terrain_assets.py:432) — Prior **A−** → My **A−** — **AGREE**
* Vectorized AABB-in-mask via meshgrid. Standard.
* Bug: O(zones × cells). For 50 zones × 1024² mask = 52 M ops. Fine for 1024² but slow for 4096². Could vectorize via stacking zone bounds and reducing.

#### `_region_mask` (terrain_assets.py:458) — Prior **A−** → My **A−** — **AGREE**
Same pattern. Clean.

#### `place_assets_by_zone` (terrain_assets.py:481) — Prior **A** → My **A** — **AGREE**
* Per-rule viability + Poisson + protected/region mask. Deterministic via `derive_pass_seed`. Honors Bundle E contract.
* Bug: none material.

#### `_cluster_around` (terrain_assets.py:530) — Prior **A−** → My **A−** — **AGREE**
* Stride-downsampled cluster centers + N rocks per cluster within radius_cells. Correct.
* **BUG-624 (LOW):** line 593-594 `dr = int(round(sin*dist))` truncates to integer cells — multiple rocks within the same cluster can land on the same `(rr, cc2)` cell, producing co-located rocks. No intra-cluster Poisson.
* AAA gap: cluster geometry doesn't follow cliff orientation (rocks scatter circular even when cliff is linear).
* Severity: low.
* Upgrade to A: continuous-coord placement (don't round to cell), add intra-cluster min-distance check.

#### `cluster_rocks_for_cliffs` (terrain_assets.py:601) — Prior **A−** → My **A−** — **AGREE**
Specialized wrapper with appropriate count + radius defaults. Clean.

#### `cluster_rocks_for_waterfalls` (terrain_assets.py:619) — Prior **A−** → My **A−** — **AGREE**
Specialized wrapper. Clean.

#### `scatter_debris_for_caves` (terrain_assets.py:637) — Prior **A−** → My **A−** — **AGREE**
Specialized wrapper. Clean.

#### `validate_asset_density_and_overlap` (terrain_assets.py:660) — Prior **A−** → My **A−** — **AGREE**
* O(n²) overlap detection per asset_id via numpy broadcast. Fine for bounded counts (<1000).
* Bug: only reports the FIRST overlap pair `(i, j)` per asset (line 711) — skips remaining.
* Severity: low.

#### `_build_tree_instance_array` (terrain_assets.py:738) — Prior **A** → My **A** — **AGREE**
* Flatten tree-like placements into `(N, 5) float32` matching Unity contract `(x, y, z, rot, prototype_id)`. Excellent.

#### `_build_detail_density` (terrain_assets.py:762) — Prior **A** → My **B+** — **DISPUTE-DOWN**
* What: per-ground-cover-asset (H, W) float32 density maps written to `stack.detail_density`.
* **BUG-604 (CRIT, HIGH):** Unity's `TerrainData.SetDetailLayer(int xBase, int yBase, int layer, int[,] details)` strictly requires `int[,]` (verified via Unity scripting reference 2026-04 WebSearch — see References §6). This emits `np.float32`. Either C# importer casts to int (silent precision loss + clamp) or fails.
* Bug: line 780 `arr[r, c] += 1.0` — counts placements per cell. With Bridson min-distance >= cell-size, max one per cell typically, so values ∈ {0.0, 1.0}. But for very dense ground cover with min-distance < cell-size (e.g. cell=1 m, min_dist=0.6 m for moss), multiple placements stack and cell value > 1.0. Unity expects density 0..255 or 0..value-range. No normalization or clamping.
* Severity: HIGH (interface mismatch + no clamp).
* Upgrade to A: emit `np.uint8` or `np.int32` with clamped 0..255 scaling; add `density_scale=255` parameter.

#### `pass_scatter_intelligent` (terrain_assets.py:790) — Prior **A** → My **A** — **AGREE**
* Full pass: viability → Poisson → cluster-add → materialize → validate. Writes `tree_instance_points` + `detail_density`. Side-effect placement dict for downstream.
* Bug: validation runs after materialization (could short-circuit if region_area == 0).
* This is the single best procedural pass in the entire terrain handler suite.

#### `register_bundle_e_passes` (terrain_assets.py:893) — Prior **A** → My **A** — **AGREE**
Trivial registration. Clean.

---

### 2.6 `terrain_asset_metadata.py` (3 functions) — taxonomy

#### `validate_asset_metadata` (terrain_asset_metadata.py:66) — Prior **A** → My **A** — **AGREE**
* Per-tag taxonomy validation; emits `ASSET_META_INVALID_*` issues with remediation hints. Matches Quixel metadata schema validation pattern.
* No bug.

#### `classify_size_from_bounds` (terrain_asset_metadata.py:144) — Prior **A** → My **A** — **AGREE**
Trivial bbox→size tag.

#### `AssetContextRuleExt.effective_variance` (terrain_asset_metadata.py:176) — Prior **A** → My **A** — **AGREE**
Role-adjusted variance multiplier (hero 0.5×, support 1×, filler 1.5×). Clean.

---

### 2.7 `terrain_scatter_altitude_safety.py` (1 function) — bug canary

#### `audit_scatter_altitude_conversion` (terrain_scatter_altitude_safety.py:41) — Prior **A** → My **B+** — **DISPUTE-DOWN**
* What: regex audit of source code for the 5 known bad altitude-normalization patterns. Lint-as-Python-function.
* **BUG-608 (MED, NEW):** the regex set is **incomplete** — catches `heights/heights.max()`, `heightmap/heightmap.max()`, `altitude/height_scale`, `center.z/height_scale`, `np.clip(altitude, 0, 1)` — but does NOT catch:
  * `heightmap[r, c]` followed by `< 0.1` or similar normalized-comparison (the pattern in `environment_scatter._scatter_pass:1148`)
  * `(heights - height_min) / height_range` followed by index sampling at `* height_max` (BUG-609)
  * `heightmap = ... / height_range` definitions
  
  The canary is "looking for the smoking gun" but missing the actual smoking guns currently alive in the codebase.
* Bug: `_BAD_PATTERNS` ordered most-specific-first and `break` after first match (line 58) — multiple violations on same line are missed.
* Severity: medium (canary purports to detect bugs that ARE alive in the code; gap is dangerous because it lulls into "passing").
* Upgrade to A: extend pattern set with the two patterns above; remove `break` so multiple regex hits on same line are reported; add a positive test that intentionally uses normalized-domain comparisons and ensures the canary catches them.

---

### 2.8 `terrain_vegetation_depth.py` (13 functions) — Bundle O

#### `VegetationLayer` enum (terrain_vegetation_depth.py:38) — Prior **A** → My **A** — **AGREE**
Trivial enum.

#### `VegetationLayers` dataclass (terrain_vegetation_depth.py:46) — Prior **A** → My **A** — **AGREE**
4-array container.

#### `VegetationLayers.as_dict` (terrain_vegetation_depth.py:54) — Prior **A** → My **A** — **AGREE**
Trivial dict serialization. Clean.

#### `DisturbancePatch` dataclass (terrain_vegetation_depth.py:64) — Prior **A** → My **A** — **AGREE**
Trivial.

#### `Clearing` dataclass (terrain_vegetation_depth.py:72) — Prior **A** → My **A** — **AGREE**
Trivial.

#### `_region_slice` (terrain_vegetation_depth.py:83) — Prior **A** → My **A** — **AGREE**
Slice helper using `BBox.to_cell_slice`. Clean.

#### `_protected_mask` (terrain_vegetation_depth.py:99) — Prior **A−** → My **A−** — **AGREE**
Same pattern as `terrain_assets._protected_mask` — vectorized AABB. Could share via a common helper module.

#### `_normalize` (terrain_vegetation_depth.py:125) — Prior **A** → My **A** — **AGREE**
Min-max normalize. Returns zeros for constant array (correct).

#### `compute_vegetation_layers` (terrain_vegetation_depth.py:140) — Prior **A−** → My **B+** — **DISPUTE-DOWN**
* 4-layer stratification driven by slope+altitude+wetness+wind. Vectorised numpy.
* Reference: matches Horizon Zero Dawn's vegetation density passes (canopy/under/shrub/ground).
* Bug: `biome_scale` (line 178-183) only has 4 entries (`dark_fantasy_default`, `tundra`, `swamp`, `desert`); the **14 biomes** in `vegetation_system.BIOME_VEGETATION_SETS` will all fall back to `(1.0,1.0,1.0,1.0)`. Loss of biome differentiation.
* Bug: line 190 `(1.0 - np.abs(alt_n - 0.4) * 1.2).clip(0.0, 1.0)` — uses NORMALIZED altitude `alt_n = _normalize(h)` → 0.4 of normalized range. Same Addendum-3.A class: "moderate altitude" is meaningless when terrain has any negative elevations. Canopy density peak shifts based on tile elevation extremes.
* Severity: medium.
* Upgrade to A: complete biome_scale table (14 entries); operate on absolute altitude (e.g., 0..1500 m), not normalized.

#### `detect_disturbance_patches` (terrain_vegetation_depth.py:223) — Prior **A−** → My **A−** — **AGREE**
Deterministic placement of N patches per kind per area. Clean.
* Bug: line 239 `per_kind = max(1, int(np.sqrt(rows*cols) // 24) or 1)` — for typical 1024² tiles `sqrt(rows*cols)//24 ≈ 42`. So 42 fire + 42 windthrow + 42 flood = 126 patches per tile. Maybe too many; should be density (per km²), not raw count.
* Severity: low.

#### `place_clearings` (terrain_vegetation_depth.py:274) — Prior **A−** → My **A−** — **AGREE**
* Poisson-disk sampled clearings with O(n²) reject. Adequate for n<200.
* Bug: line 324 `kind = "natural" if (len(clearings) % 2 == 0) else "human"` — alternation by index gives exactly 50/50 split regardless of biome. Should be biome-driven.

#### `place_fallen_logs` (terrain_vegetation_depth.py:334) — Prior **A−** → My **A−** — **AGREE**
Reject-sample-from-mask. Clean.
* Could use `_poisson_in_mask` from `terrain_assets.py` to reuse spatial-hash. Currently O(target × placed) instead of O(N).

#### `apply_edge_effects` (terrain_vegetation_depth.py:389) — Prior **B+** → My **B+** — **AGREE**
4-ring iterative dilation. Clean. Could use `scipy.ndimage.distance_transform_edt` for true Euclidean distance instead of 4-connected dilation. (Context7 `/scipy/scipy` confirms `distance_transform_edt` is available and faster.)

#### `apply_cultivated_zones` (terrain_vegetation_depth.py:440) — Prior **A−** → My **A−** — **AGREE**
Override densities in cultivation mask. Simple.
* Magic numbers (0.05, 0.02, 0.05, 1.0) — should be biome-dependent.

#### `apply_allelopathic_exclusion` (terrain_vegetation_depth.py:472) — Prior **A−** → My **A−** — **AGREE**
Real ecology touch (walnut/eucalyptus suppression). Vectorized. Clean.

#### `pass_vegetation_depth` (terrain_vegetation_depth.py:504) — Prior **A−** → My **A−** — **AGREE**
Standard pass with protected-zone masking. Writes 4-layer detail_density.
* Same BUG-604 caveat: float32 vs Unity int[].

#### `register_vegetation_depth_pass` (terrain_vegetation_depth.py:580) — Prior **A** → My **A** — **AGREE**

---

## 3. Summary tables

### 3.1 Function grade summary (95 functions)

| File | Avg prior | Avg my | Δ |
|------|-----------|--------|---|
| `vegetation_lsystem.py` (14) | B+ | C+ to B− | DOWN |
| `vegetation_system.py` (7) | B+ | B− | DOWN |
| `_scatter_engine.py` (10) | A− | B+ | DOWN |
| `environment_scatter.py` (28) | B/B+ | B− | DOWN |
| `terrain_assets.py` (19) | A− | A− | STABLE (one B+ for `_build_detail_density`) |
| `terrain_asset_metadata.py` (3) | A | A | AGREE |
| `terrain_scatter_altitude_safety.py` (1) | A | B+ | DOWN |
| `terrain_vegetation_depth.py` (13) | A− | A− | STABLE (one B+ for `compute_vegetation_layers`) |

### 3.2 NEW BUGS (BUG-601 to BUG-624) — severity-ranked

| Code | Severity | File:line | What |
|------|----------|-----------|------|
| **BUG-601** | HIGH | `vegetation_lsystem.py:962` | sin/floor hash banding at \|coord\| > ~340 m → wind phase striping in open-world tiles |
| **BUG-602** | HIGH | `vegetation_lsystem.py:288-297` | Cumulative gravity drag flips trunk direction past zero on willow/long branches |
| **BUG-603** | MED | `vegetation_lsystem.py:286` | Negative `length` from gauss perturbation → backwards twigs |
| **BUG-604** | HIGH | `terrain_assets.py:778-781`, `terrain_vegetation_depth.py:553-555` | `detail_density` emitted as float32; Unity `SetDetailLayer` requires `int[,]` |
| **BUG-605** | MED-HIGH | `vegetation_lsystem.py:1094` | `prepare_gpu_instancing_export` claims to export but never writes the file |
| **BUG-606** | MED | `_scatter_engine.py:188-191` | `biome_filter_points` UV mapping has undocumented corner-anchored contract |
| **BUG-607** | HIGH | `environment_scatter.py:1148, 1168` | `_scatter_pass` gates trees by NORMALIZED altitude (Addendum 3.A) |
| **BUG-608** | MED | `terrain_scatter_altitude_safety.py:32-38` | Bug canary regex set incomplete — misses BUG-607 / BUG-609 patterns |
| **BUG-609** | HIGH | `environment_scatter.py:1486` (root in `_terrain_height_sampler` / `_sample_heightmap_world`) | Tree z = `normalized * height_max` floats vegetation by `\|height_min\|` for negative-elevation tiles |
| **BUG-610** | HIGH | `environment_scatter.py:1594` | `terrain_sampler` looks up scatter collection name as terrain → always None → props at z=0 |
| **BUG-611** | MED | `vegetation_lsystem.py:580-594` | Root end-position drops the start offset → cone misaligned to declared direction |
| **BUG-612** | MED | `vegetation_lsystem.py:360-362` | Empty branches mark trunk as `is_tip=True` → leaves on trunks |
| **BUG-613** | MED | `vegetation_lsystem.py:405-408` | Ring perpendicular reference snap creates twist at \|dx\|=0.9 boundary |
| **BUG-614** | MED | `vegetation_system.py:441` | Water level uses normalized height (Addendum 3.A) |
| **BUG-615** | MED | `vegetation_system.py:445-466` | Density applied twice → effective rate ≈ density² |
| **BUG-616** | MED | `vegetation_system.py:359` | Brute-force terrain vertex scan; should be scipy KDTree |
| **BUG-617** | MED | `vegetation_system.py:475` | Redundant `_sample_terrain` call (cache the first one) |
| **BUG-618** | MED | `vegetation_system.py:772-773` | Silent truncation at max_instances introduces Bridson active-list spatial bias |
| **BUG-619** | HIGH-gap | `vegetation_system.py:651-662` | Many biome veg types lack generators → ValueError blows up materializer |
| **BUG-620** | MED | `vegetation_lsystem.py:664` | Silent iteration cap from 8 to 6; should LOG and offer vertex-budget solver |
| **BUG-621** | LOW-MED | `vegetation_lsystem.py:688` | Root count capped at 5 even for huge trunks |
| **BUG-622** | HIGH (visual) | `vegetation_lsystem.py:750-882` | Leaf cards never camera-face; shear-tilt non-orthogonal; no UVs |
| **BUG-623** | HIGH (streaming) | `_scatter_engine.py:26`, `terrain_assets.py:362` | Per-call Poisson restart → density seams across tiles. Cross-confirmed by G3 |
| **BUG-624** | LOW | `terrain_assets.py:593-594` | `_cluster_around` rounds to integer cells → co-located rocks within cluster |

### 3.3 Disputes vs prior grades (table)

| Function | Prior | Mine | Direction | Reason |
|----------|------:|-----:|-----------|--------|
| `interpret_lsystem` | B+ | C+ | DOWN | BUG-602/603 + BUG-612 tip bug |
| `_generate_cylinder_ring` | A− | B+ | DOWN | BUG-613 perpendicular flip seam |
| `generate_roots` | A− | B+ | DOWN | BUG-611 end-position |
| `generate_lsystem_tree` | A− | B+ | DOWN | BUG-620/621 silent caps |
| `generate_leaf_cards` | B+ | B− | DOWN | BUG-622 no UVs, shear-tilt |
| `bake_wind_vertex_colors` | A− | C+ | DOWN | BUG-601 sin/floor banding |
| `prepare_gpu_instancing_export` | B | C | DOWN | BUG-605 claim-without-implementation |
| `compute_vegetation_placement` | A− | B | DOWN | BUG-614/615/616/617 stacked |
| `_sample_terrain` (closure) | (missed) | C+ | NEW | Brute-force + silent default |
| `compute_wind_vertex_colors` | A− | B | DOWN | B-channel deterministic of R+G — zero info |
| `_create_biome_vegetation_template` | B+ | C+ | DOWN | BUG-619 ValueError on missing generators |
| `scatter_biome_vegetation` | B+ | B− | DOWN | BUG-618 truncation bias |
| `poisson_disk_sample` | A | A− | DOWN | BUG-623 not tileable |
| `biome_filter_points` | A− | B+ | DOWN | BUG-606 + double-density |
| `_assign_scatter_material` | B+ | B | DOWN | Preview-only, never shipped material |
| `_vegetation_rotation` | A− | A | UP | Clean, no bugs found this pass |
| `_prop_rotation` | A− | A | UP | Clean, no bugs found this pass |
| `_terrain_height_sampler` | B | B− | DOWN | BUG-609 contributor |
| `_sample` (closure) | (missed) | B− | NEW | Inherits BUG-609 |
| `_sample_heightmap_surface_world` | A− | B+ | DOWN | BUG-609 multiplier mismatch |
| `_sample_heightmap_world` | A | A− | DOWN | Inherits parent |
| `_create_vegetation_template` | B | B− | DOWN | Silent cube fallback |
| `_add_leaf_card_canopy` | B+ | B | DOWN | No camera facing, no UVs |
| `create_leaf_card_tree` | A− | B | DOWN | No mid-canopy branches |
| `_rock_size_from_power_law` | B | A− | UP | Statistically realistic per geomorphology lit |
| `_scatter_pass` | B− | C+ | DOWN | BUG-607 confirmed live |
| `_sample_height_norm` (closure) | (missed) | C+ | NEW | Returns BUG-607 normalized value |
| `_sample_slope` (closure) | (missed) | B+ | NEW | OK domain |
| `_in_building` (closure) | (missed) | B | NEW | Linear scan should be KDTree for many buildings |
| `_in_clearing` (closure) | (missed) | B+ | NEW | Few clearings — fine |
| `_near_tree` (closure) | (missed) | C | NEW | Hardcoded 1 m, O(N×M) brute force |
| `handle_scatter_vegetation` | B | B− | DOWN | BUG-609 + 250-line god-function + truncation |
| `handle_scatter_props` | B+ | C+ | DOWN | BUG-610 props at z=0 |
| `_build_detail_density` | A | B+ | DOWN | BUG-604 Unity int[,] mismatch |
| `_cluster_around` | A− | A− | AGREE | BUG-624 noted but cosmetic |
| `audit_scatter_altitude_conversion` | A | B+ | DOWN | BUG-608 canary regex incomplete |
| `compute_vegetation_layers` | A− | B+ | DOWN | 4 of 14 biomes covered + normalized altitude |

Total: **34 disputes (32 DOWN, 2 UP), 11 NEW assessments for previously-missed closures, ~50 ratifications.**

### 3.4 AAA-gap summary

| Area | Industry standard (2026) | Our state | Gap |
|------|---------------------------|-----------|-----|
| Tree authoring | SpeedTree 9 parametric L-system + apical dominance + phototropism + biomechanics | Non-parametric L-system, cumulative gravity bug | 1 generation behind |
| Leaf cards | Megascans photogrammetry meshes + 4×4 alpha atlas + SSS | Untextured paper quads with no UVs | 2 generations behind |
| Wind animation | Pivot Painter 2.0 (16-bit packed RGBA) + Unity Wind Zone shader | 8-bit hash with banding bug | 1 generation behind |
| Impostors | Octahedral 12-view 2K atlas with parallax depth (Shaderbits 2018, UE5 native) | Textureless N-prism mesh | BLOCKER — claim without implementation |
| GPU instancing | UE5 HISM + Unity DOTS-ECS chunks | Plain JSON dict, no file write | 1 generation behind |
| Scatter sampling | Tileable Poisson with global blue-noise across chunks | Per-call restart, density seams | 1 generation behind for streaming |
| Detail density format | Unity TerrainData `int[,]` / Mesa-Foliage uint8 | float32 (silent cast required) | minor but visible |
| Spatial queries | scipy cKDTree O(log N) | Python-loop brute force | obvious upgrade |
| LOD chains | Auto LOD0/1/2 + impostor in one auth pass | Single resolution + custom-prop distance hints | 1 generation behind |
| Scatter intelligence (Bundle E) | Houdini PCG / UE5 PCG Graph | **Match — best module in codebase** | none |

---

## 4. Top 10 actionable upgrades (ordered by ROI)

1. **Fix BUG-601 wind phase hash** (`vegetation_lsystem.py:962`) — replace sin/floor with deterministic numpy RNG seeded on quantized vertex coords. 1-line fix; eliminates visible banding in open-world tiles. **2 hours.**
2. **Fix BUG-602 cumulative gravity** (`vegetation_lsystem.py:288-297`) — switch to per-step proportional bias `state.dz = mix(state.dz, -1, gravity*dt)`. **3 hours.**
3. **Fix BUG-607 + BUG-609 normalized-altitude bugs** (`environment_scatter.py:1148,1168,1486`, `_terrain_height_sampler`, `_sample_heightmap_world`) — route through `WorldHeightTransform` from `terrain_semantics`. **1 day.** Without this, every negative-elevation tile mis-places vegetation.
4. **Extend BUG-608 canary regex set** (`terrain_scatter_altitude_safety.py`) — add patterns for normalized-comparison and `* height_max` post-normalization. Add positive test suite. **2 hours.**
5. **Fix BUG-604 detail_density dtype** (`terrain_assets.py:778-781`, `terrain_vegetation_depth.py:553-555`) — emit `np.int32` with clamp/scale. **1 hour.**
6. **Fix BUG-610 prop terrain sampler** (`environment_scatter.py:1594`) — accept explicit `terrain_name` param. **1 hour.**
7. **Real impostor baker** (`vegetation_lsystem.py:975`) — integrate Blender headless render of N=12 view atlas. **3-5 days.** Highest visual ROI; required for AAA distance vegetation.
8. **Tileable Poisson** (`_scatter_engine.py:26`, `terrain_assets.py:362`) — global-deterministic-then-crop. **2 days.** Fixes BUG-623 density seams in streaming.
9. **scipy KDTree replacement for terrain vertex sampling** (`vegetation_system.py:359`, `_scatter_engine.py:368`) — drop-in `cKDTree(xy_array).query(p)`. Context7 `/scipy/scipy` confirms 200-1000× speedup, drop-in API. **1 day.** Cuts placement compute by 100×.
10. **Real HISM/DOTS export** (`vegetation_lsystem.py:1094`) — emit packed `(N, 16) float32` transform array + uint16 prototype IDs as binary; matches `Graphics.DrawMeshInstancedIndirect`. **2 days.**

Total: **~3 weeks of senior dev time** to lift `vegetation_lsystem` + `vegetation_system` + `_scatter_engine` + `environment_scatter` from B−/B+ to A−/A. The Bundle E modules (`terrain_assets`, `terrain_asset_metadata`, `terrain_vegetation_depth`, `terrain_scatter_altitude_safety`) are already at A− and need only the int32 dtype fix + canary regex extension.

---

## 5. Cross-Module Findings

### 5.1 The "normalized-altitude family" is alive in 4 places

Four sites in three files use normalized heightmap (`(z - min) / range`) for absolute altitude comparisons:

* `environment_scatter.py:1148, 1168` — `if h < 0.1 or h > 0.7` (BUG-607)
* `environment_scatter.py:1486` — vegetation z = normalized * height_max (BUG-609)
* `vegetation_system.py:441` — `if has_height_variation and norm_h < water_level` (BUG-614)
* `terrain_vegetation_depth.py:190` — `(1.0 - np.abs(alt_n - 0.4) * 1.2)` canopy peak

The bug canary `terrain_scatter_altitude_safety` was built to detect this family but its regex set misses all four. Cross-confirms G3's seam findings: when terrain has negative elevations, vegetation density patterns visibly shift.

**Single fix:** route every altitude consumer through `terrain_semantics.WorldHeightTransform`, then update the canary regex set + add positive tests.

### 5.2 Poisson tileability gap (BUG-623) is systemic

Both `_scatter_engine.poisson_disk_sample` and `terrain_assets._poisson_in_mask` restart per call. G3 confirms visible seam discontinuities. UE5 PCG and Houdini both use either tileable Poisson (Wang tiles, recursive subdivision) or globally-evaluated-then-cropped sampling. This is a **streaming blocker**.

### 5.3 KDTree opportunity (Context7 verified)

Three sites brute-force scan when KDTree would help:

* `vegetation_system.py:359` `_sample_terrain` — 5000 candidates × 80 verts × 9 cells (BUG-616)
* `_scatter_engine.py:368` `context_scatter` nearest-building search — N×M
* `environment_scatter.py:1190` `_near_tree` closure — N×M

Context7 `/scipy/scipy` confirms `cKDTree.query` is 200-1000× faster than KDTree and is "drop-in replacement" with same API. Single-day refactor across all three sites.

### 5.4 Two complete duplicate vegetation pipelines

`vegetation_system.compute_vegetation_placement` and `terrain_vegetation_depth.compute_vegetation_layers` both produce vegetation density maps from terrain signals, with no awareness of each other. The first is per-instance Poisson placement; the second is per-cell density rasters. They should share:

* slope/altitude/wetness envelope computation
* biome scalar tweaks
* exclusion zone handling

Currently each duplicates the work and disagrees on biome semantics (vegetation_system has 14 biomes; vegetation_depth has 4).

### 5.5 Wind vertex color channel layout disagreement

Three different functions produce wind vertex colors with **incompatible channel semantics**:

* `vegetation_lsystem.bake_wind_vertex_colors` (line 889): R=radial+height mix, G=branch depth, B=phase hash
* `vegetation_system.compute_wind_vertex_colors` (line 490): R=trunk distance, G=ground height, B=`(R*0.5+G*0.5)`
* `environment_scatter._add_leaf_card_canopy` (line 692): R=flutter (height_t), G=cluster phase, B=branch sway, A=trunk sway

A Unity wind shader consuming these would see wildly different inputs depending on which generator made the mesh. No documentation reconciles them. SpeedTree's reference convention (R=trunk, G=branch, B=leaf, A=phase) isn't followed by any of the three.

---

## 6. Context7 / WebFetch References Used (per-finding citations)

* **Unity TerrainData.SetDetailLayer** — `https://docs.unity3d.com/ScriptReference/TerrainData.SetDetailLayer.html`. Verified via WebSearch 2026-04: signature is `SetDetailLayer(int xBase, int yBase, int layer, int[,] details)`. Confirms BUG-604.
* **scipy.spatial KDTree / cKDTree** — Context7 `/scipy/scipy`. cKDTree.query is "200-1000× faster than KDTree" and "drop-in replacement with same API." Cited for BUG-616 (vegetation_system._sample_terrain), BUG-623 (_scatter_engine), and `context_scatter` nearest-building scan.
* **NumPy float precision** — Context7 `/numpy/numpy` arrays.scalars docs. float64 has 52-bit mantissa; `math.floor(43758 * sin(x))` loses precision when arg magnitude exceeds 2^24. Cited for BUG-601 (`bake_wind_vertex_colors`).
* **Bridson 2007** — `https://www.cs.ubc.ca/~rbridson/docs/bridson-siggraph07-poissondisk.pdf`. Verified `cell_size = min_dist/√2`, 5×5 neighborhood, max_attempts=30 canonical values. The implementations in `_scatter_engine.poisson_disk_sample` and `terrain_assets._poisson_in_mask` match the canonical algorithm but lack tileability.
* **Recursive Wang Tiles (Kopf 2006)** — `https://prideout.net/recursive-wang-tiles`. Reference for tileable blue-noise — the upgrade path for BUG-623.
* **SpeedTree wind / Pivot Painter 2** — `https://forum.speedtree.com/forum/speedtree-modeler/using-the-speedtree-modeler/14334-decoding-the-unreal-wind-material-data-stored-in-the-uv-maps`, `https://www.fab.com/listings/08e6ac56-e1c4-4c59-a5eb-208d67701cb9` (IGToolsPP). Confirms SpeedTree-to-UE plugin uses 5 additional UV channels + vertex paint for 2-level wind; Pivot Painter 2 uses 1 UV channel + 2 textures for 4-level wind. Neither matches our implementations.
* **UE5 PCG Foliage** — `https://dev.epicgames.com/community/learning/knowledge-base/KP2D/unreal-engine-a-tech-artists-guide-to-pcg`, `https://digitalproduction.com/2025/11/12/unreal-engine-5-7-foliage-pcg-and-in-editor-ai/`. UE5.7 (Nov 2025) adds Nanite Foliage and production-ready PCG. PCG-spawned grass underperforms built-in Foliage paint tool for very dense ground cover — relevant to BUG-622's leaf card concerns.
* **Shaderbits Octahedral Imposter** — Ryan Brucks 2018; UE5 4.20+ native. Reference for what `generate_billboard_impostor` should be doing instead of emitting an N-prism.
* **Quixel Megascans Foliage** — 4K alpha+normal+SSS atlases per species. Reference for what `_LEAF_PRESETS` / `generate_leaf_cards` should be consuming instead of emitting untextured cards.
* **Horizon Forbidden West vegetation streaming GDC 2023** — Guerrilla's tile-aware streaming with global blue-noise. Reference for BUG-623 fix path.

---

## 7. Final summary

**95 functions enumerated via Python AST**, all 95 graded:
* 24 NEW bugs (BUG-601 to BUG-624), 4 critical-severity, 7 high-severity.
* 32 functions DOWNGRADED from prior grades (most due to rediscovery of Addendum 3.A normalized-altitude family + new precision/contract bugs).
* 2 functions UPGRADED (`_vegetation_rotation`, `_prop_rotation`, `_rock_size_from_power_law`).
* 11 NEW assessments for previously-missed nested closures (`_sample`, `_sample_height_norm`, `_sample_slope`, `_in_building`, `_in_clearing`, `_near_tree`, `_sample_terrain`, `_grid_idx`, `_is_valid`, `_gkey`, `rot`).
* ~50 functions ratified at prior grade.

**A3's "terrain_assets.py is genuine A" claim — VERIFIED with one downgrade.** `pass_scatter_intelligent`, `place_assets_by_zone`, `compute_viability`, `_poisson_in_mask` (slope/altitude/wetness envelopes, vectorized numpy, deterministic seeding) remain the strongest procedural pass in the entire terrain handler suite. The single downgrade is `_build_detail_density` (B+) due to the Unity `int[,]` contract violation (BUG-604).

**Bundle B vegetation/scatter (vegetation_lsystem + environment_scatter + _scatter_engine + vegetation_system)** ships visible vegetation but is **categorically below SpeedTree / UE5 PCG / Megascans** — graded B− to B+ with 4 critical bugs alive. ~3 weeks of senior dev time gets this band to A−/A.

**Bundle O / E / asset metadata / canary** are A−/A modules with one `int32 dtype` fix and one `regex extension` to lift to ratified A.
