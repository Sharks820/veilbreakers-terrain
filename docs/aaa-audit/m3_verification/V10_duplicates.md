# V10 Duplicate / Overlap Consolidation Scan

**Agent:** V10 (M3 ultrathink verification wave)
**Date:** 2026-04-16
**Scope:** `docs/TERRAIN_UPGRADE_MASTER_AUDIT.md` (3547 lines, BUG-01..BUG-159 + BUG-132..142 + revisions) and `docs/aaa-audit/GRADES_VERIFIED.csv` (1408 rows).
**Lens:** duplicate BUG entries (same root cause, different framing) + overlapping fixes (one refactor closes many) + multi-site pattern families.
**Firecrawl corpus (5 URLs):**
1. https://refactoring.com/catalog/ (Fowler 2nd-ed refactoring catalog — 60 refactorings)
2. https://docs.python.org/3/library/dataclasses.html (dataclass for parameter-object consolidation)
3. https://docs.python.org/3/library/functools.html (singledispatch, lru_cache, wraps, partial)
4. https://martinfowler.com/bliki/StrategyPattern.html (404 — Fowler deprecated, fell back to refactoring.guru)
5. https://refactoring.guru/design-patterns/strategy/python/example (Strategy pattern in Python)
6. https://refactoring.com/catalog/extractFunction.html (canonical Extract Function)

Refactoring patterns referenced below: **Substitute Algorithm**, **Extract Function**, **Introduce Parameter Object** (dataclass), **Replace Conditional with Polymorphism** (singledispatch / Strategy), **Combine Functions into Class**, **Consolidate Duplicate Conditional Fragments**.

---

## Confirmed duplicates (same root cause, different BUG IDs — consolidate)

These are NOT "same bug class, different sites" — they are the SAME site written twice or the SAME symptom framed twice. Primary = the BUG that should survive; Duplicate(s) = should be collapsed with a pointer to Primary.

| Primary BUG | Duplicate BUG(s) | File:function | Consolidation rationale |
|---|---|---|---|
| **BUG-40** `_box_filter_2d` integral image defeated by Python loops | **BUG-106** `_box_filter_2d` builds integral image then defeats it via Python double-loop | `_biome_grammar.py:279` `_box_filter_2d` | Word-for-word same symptom, same fix (`scipy.ndimage.uniform_filter`), same file:line. BUG-106 appears to be a re-discovery during X4 R5 Context7 pass. Merge into BUG-40, keep BUG-106 as historical anchor. |
| **BUG-57** `compute_god_ray_hints` NMS Python double-loop | **BUG-126** `compute_god_ray_hints` non-max suppression Python double-loop (1M iter @ 1024², ~3s) | `terrain_god_ray_hints.py:159` | Identical function, identical fix (`scipy.ndimage.maximum_filter` then `intensity == filtered`). BUG-126 adds perf numbers; merge, retain numbers. |
| **BUG-61** `_water_network.get_tile_water_features` dead code lookups | **BUG-72** `_water_network.get_tile_water_features` dead lookups + tile_size param mismatch | `_water_network.py` `get_tile_water_features` | Same function; BUG-72 is a superset (adds `tile_size` mismatch). Collapse BUG-61 into BUG-72. |
| **BUG-63** `_water_network.detect_lakes` Python triple-nested pit detection | **BUG-76** `_water_network.detect_lakes` strict-less-than pit detection misses ~30% of valid lakes | `_water_network.py:200` `detect_lakes` | Two framings of the same function: BUG-63 = perf, BUG-76 = correctness + Priority-Flood replacement. Same fix closes both. Merge under BUG-76 (correctness is root cause; perf is byproduct of Priority-Flood substitution). |
| **BUG-65** `generate_canyon` walls don't connect to floor | **BUG-88** `generate_canyon` floor face winding inverted (CW from +Z) | `terrain_features.generate_canyon` | Same function, both are mesh-topology defects. Likely fixable in one rewrite pass (re-tessellate floor + weld walls + rewind CCW). Not literal duplicates but single PR closes both. |
| **BUG-07** `_distance_from_mask` Manhattan claims Euclidean | **BUG-42** `_distance_to_mask` (1, sqrt(2)) chamfer claims Euclidean; **BUG-127** `terrain_wildlife_zones._distance_to_mask` Python chamfer | 3 files: `_biome_grammar.py:305`, `terrain_wildlife_zones.py:69`, third EDT site | Section 8 explicitly calls out "Three independent distance transforms" consolidation. One `terrain_math.distance_meters(mask, cell_size)` wrapping `scipy.ndimage.distance_transform_edt(~mask, sampling=cell_size)` closes all 3. BUG-07 is primary (earliest ID); BUG-42 + BUG-127 are siblings from same disease. |
| **BUG-37** `compute_flow_map` D8 ignores cell_size | **BUG-75** `terrain_advanced.compute_flow_map` triple-nested Python loop on D8 + accumulation | `terrain_advanced.py:999..1026` `compute_flow_map` | Same function: BUG-37 = cell_size unit bug; BUG-75 = perf/triple-loop. One rewrite (vectorized D8 with `cell_size`-aware distances per ArcGIS spec) closes both. Merge framings, keep BUG-37 as primary. |
| **BUG-50** Atmospheric "sphere" is 12-vertex icosahedron | **BUG-132** `atmospheric_volumes.compute_volume_mesh_spec` ships unsubdivided 12-vert "icosphere" | `atmospheric_volumes.compute_volume_mesh_spec` | Identical root cause (no subdivision step). BUG-132 adds "cone double-mod wrap math" — a second co-located bug. Keep BUG-132 as primary (more specific); fold BUG-50. |
| **BUG-11** Atmospheric volumes at z=0 | **BUG-140** `compute_atmospheric_placements` uniform-random placement, `pz=0.0` | Same function (parent of BUG-11) | Master audit already tags BUG-140 as "parent function of BUG-11". Collapse BUG-11 as child; keep BUG-140 as canonical. |
| **BUG-59** `edit_hero_feature` purely cosmetic | **BUG-111** `edit_hero_feature` appends strings to `side_effects`, never edits | `terrain_live_preview.py:138-183` | Same function, same dishonesty. BUG-111 is the X4 rediscovery. Merge with cross-ref at top of BUG-59. |
| **BUG-83** `terrain_caves._build_chamber_mesh` rubric F-grade hidden box | **BUG-139** `terrain_sculpt._build_chamber_mesh` duplicate hidden 6-face box | `terrain_caves.py:1079` and `terrain_sculpt.py:1079` | NOT literal duplicate — two separate files with *identical F-grade copy-paste*. BUG-139 is a second physical instance, should stay as distinct BUG but both get fixed in same PR (delete-or-replace-with-real-mesh-gen). The ROOT CAUSE is the copy-paste — add a PATTERN-FAMILY entry. |
| **BUG-60** `hydraulic_erosion` capacity uses `abs(delta_h)` (Beyer 2015 violation) | **BUG-157** `_terrain_noise.generate_road_path` reads mutated heights | Both cite `_terrain_noise.py` but different functions | NOT duplicates. Flagged here only to confirm they share a file but different root causes. Keep both. |

**Subtotal: 10 confirmed duplicate pairs/triples** across BUG-07/42/127, BUG-11/140, BUG-37/75, BUG-40/106, BUG-50/132, BUG-57/126, BUG-59/111, BUG-61/72, BUG-63/76, BUG-65/88, BUG-83/139.

---

## Overlapping fixes (different bugs, single refactor closes multiple)

Same **fix**, but different BUGs. Not true duplicates — each BUG is correctly distinct, but a single PR can close them all.

| Refactor name (Fowler) | Bugs closed | Single PR feasibility |
|---|---|---|
| **Substitute Algorithm → `scipy.ndimage.uniform_filter`** | BUG-40 + BUG-106 (box filter) + BUG-147 (smooth preset 9-loop) + BUG-18 (np.roll toroidal in 6 files) | HIGH — one-liner per site, one PR. Section 0.B already cites `uniform_filter(mode='reflect')` as canonical fix. |
| **Substitute Algorithm → `scipy.ndimage.distance_transform_edt`** | BUG-07 + BUG-42 + BUG-127 | HIGH — create `terrain_math.distance_meters(mask, cell_size)`, point all 3 sites at it. Section 8 already specs this. |
| **Substitute Algorithm → `scipy.ndimage.maximum_filter`** | BUG-57 + BUG-126 (god ray NMS) + any other NMS site | HIGH — same pattern (filter-then-equal). |
| **Substitute Algorithm → `scipy.ndimage.minimum_filter`** | BUG-63 + BUG-76 (pit detection) | HIGH — same replacement algorithm. |
| **Substitute Algorithm → Priority-Flood (Barnes 2014)** | BUG-63 + BUG-66 (`solve_outflow` stub) + BUG-76 | MEDIUM — Priority-Flood is a proper algorithm, not a one-liner; needs `rd.FillDepressions` (richdem) or equivalent. Single implementation wraps all 3 sites. |
| **Introduce Parameter Object (dataclass) → `TerrainMaskStack.cell_size` propagation** | BUG-37 + BUG-42 + BUG-123 + BUG-152 + BUG-13 expanded (6 files) | HIGH — propagate `stack.cell_size` into every spatial op. Single-lint sweep catches all. Section 0.B item 5 already identifies this. |
| **Replace Conditional with Polymorphism → `PassDefinition` declaration-drift lint** | BUG-43 + BUG-46 + BUG-47 + BUG-85 + BUG-86 + BUG-151 + BUG-153 + GAP-01 + GAP-02 + GAP-03 + GAP-04 | HIGH — single AST-lint that asserts every `stack.set(ch, ...)` inside a pass body appears in that pass's `produces_channels`, and every `stack.get(ch)` appears in `requires_channels`. Closes 7+ BUGs with one tool. BUG-47 row already says *"Same AST-lint mechanism as BUG-43 — one tooling fix, not seven separate code edits."* |
| **Substitute Algorithm → opensimplex/gradient noise** | BUG-12 + BUG-73 + sin-hash residue in 4 files | HIGH — retire `_hash_noise`, single FBM entry in `terrain_noise_utils.py`. Section 12/13 already plans this. |
| **Substitute Algorithm → `np.random.default_rng`** | BUG-48 + BUG-49 + module-global `_features_seed` | HIGH — replace `RandomState` + module globals simultaneously (Section 8 flags these as co-dependent). |
| **Combine Functions into Class → unify `_build_chamber_mesh`** | BUG-83 + BUG-139 | MEDIUM — delete both copies, ship single `terrain_meshgen.build_cave_chamber_mesh()` used by caves + sculpt. |
| **Substitute Algorithm → add `rasterio` + HGT parser** | BUG-67 (DEM import .npy-only) + GAP-12 | HIGH — single dependency, single importer module. |
| **Extract Function → `_grid_to_world(x, y, cell_size)` canonical** | BUG-79 + BUG-82 + BUG-08 (half-cell offset) | HIGH — central utility resolves coordinate-convention drift in 3+ sites. |
| **Replace Conditional with Polymorphism → `singledispatch` on mesh generators** | BUG-68 + BUG-69 + BUG-70 + BUG-71 + BUG-83 + BUG-139 + BUG-132 + BUG-133 + BUG-137 + BUG-141 | MEDIUM — `functools.singledispatch` on archetype type, with concrete impls per mesh family. Each BUG remains its own ticket (different math) but shares dispatch scaffolding. |

---

## Pattern families (multi-site same-bug-class)

These are NOT duplicates — they are recurring bug *classes* that manifest at multiple sites. Each occurrence is a real distinct BUG, but the fix template is identical.

| Pattern | Instance BUGs | Recommended fix pattern |
|---|---|---|
| **PassDAG declaration drift** (pass body writes/reads channel not declared) | BUG-16, BUG-43, BUG-46, BUG-47, BUG-85, BUG-86, BUG-95, BUG-151, BUG-153, GAP-01..04 (**12+ sites**) | Single AST-lint + CI check. Master Section 5/8/Section 0.B #1 already identify this cluster. |
| **Python double/triple/quadruple-nested loop over full grid** (perf — should be `scipy.ndimage` or numpy vectorized) | BUG-40, BUG-41, BUG-57, BUG-63, BUG-75, BUG-87, BUG-101(?), BUG-106, BUG-123, BUG-124, BUG-126, BUG-127, BUG-147 (**13+ sites**) | Substitute Algorithm via `scipy.ndimage` family or explicit NumPy broadcasting. Section 8 lists 48 vectorization targets. |
| **sin-hash "noise"** (fract(sin(dot)) shadertoy trick used as noise source) | BUG-12 (coastline), BUG-73 (propagation to 6 callers), vegetation_lsystem.py:962, terrain_erosion_filter.py:53 (**4+ sites**) | Retire `_hash_noise`; single opensimplex entry point in `terrain_noise_utils.py`. Cross-platform determinism depends on this (Section 0.B A11 note). |
| **Three independent distance-transform implementations** | BUG-07 (Manhattan), BUG-42 (chamfer 1,√2), BUG-127 (chamfer Python loop) (**3 sites**) | `scipy.ndimage.distance_transform_edt(~mask, sampling=cell_size)` single wrapper. |
| **cell_size NOT propagated to spatial operator** | BUG-13 (np.gradient in 6 files), BUG-37 (D8), BUG-42 (chamfer), BUG-123 (road profile), BUG-152 (destructibility patches) (**~10+ sites**) | Parameter-object propagation from `TerrainMaskStack.cell_size`; single-lint sweep. |
| **Rubric F-grade hidden 6-face box `_build_chamber_mesh`** | BUG-83 (terrain_caves), BUG-139 (terrain_sculpt) (**2 sites, literal copy-paste**) | Delete both, unify behind real mesh generator. Indicates a copy-paste audit is warranted for other rubric primitives. |
| **Per-tile XOR-reseeded RNG seam / module-global mutable state** | BUG-48, BUG-91 (sin-hash huge-X precision), BUG-96 (wind field per-tile XOR), BUG-125 (cloud shadow per-tile XOR) (**4+ sites**) | Replace module globals with `np.random.default_rng(world_seed)` generator passed through; seed derivation via hash of (world_seed, tile coords) at fine granularity, NOT XOR. |
| **Deployment-dead correct code (good impl shadowed by worse same-name impl)** | BUG-138 (`terrain_banded_advanced.apply_anti_grain_smoothing`), BUG-142 (`compute_anisotropic_breakup`) (**2 sites in `terrain_banded_advanced.py`**) | Rename imports or delete deprecated module. Single-grep import audit. |
| **Stub pass-through claiming to do work** (orchestrator dishonesty) | BUG-58 (twelve-step stubs), BUG-59/BUG-111 (edit_hero_feature), BUG-66 (solve_outflow stub), BUG-117 (pass_macro_world), BUG-134/135/136 (sculpt compute_* stubs) (**8+ sites**) | Honesty audit: every claimed "modular pipeline" needs runtime verification that writes actually land. |
| **Waypoint/vertex CW winding vs CCW** | BUG-88 (canyon floor), BUG-90 (waterfall ledge), possibly BUG-89 (cliff overhang seam) (**3 sites in `terrain_features.py`**) | Establish convention (CCW from +Z up) repo-wide; lint face-normal signs. |
| **`setattr` on dataclass + `asdict()` round-trip loses attrs** | BUG-45 + BUG-78 (same `compute_strahler_orders` / `assign_strahler_orders` site) | Replace `setattr` with proper `dataclasses.replace` or drop custom field to a real dataclass field. |
| **Region/scope parameter ignored (regional pass runs globally)** | BUG-146 (pass_erosion._scope zeros outside), BUG-153 (wind erosion/field ignores region) (**2+ sites**) | Single `_scope`/region-mask convention; preserve-mask on outside-region, don't zero. |

---

## Same-file-line collisions (>1 BUG on same file:line)

Strict "same file + same line-range" collisions after grep:

| File:line | BUGs | Same function? | Notes |
|---|---|---|---|
| `_biome_grammar.py:279-302` (`_box_filter_2d`) | BUG-40, BUG-106 | Yes | **True duplicate** — consolidate. |
| `terrain_god_ray_hints.py:159` (`compute_god_ray_hints` NMS) | BUG-57, BUG-126 | Yes | **True duplicate** — consolidate. |
| `_water_network.py:200..` (`detect_lakes`) | BUG-63, BUG-76 | Yes | **True duplicate** — consolidate (correctness + perf into one). |
| `_water_network.py` (`get_tile_water_features`) | BUG-61, BUG-72 | Yes | **True duplicate** (BUG-72 is superset). |
| `terrain_advanced.py:999..1026` (`compute_flow_map`) | BUG-37, BUG-75 | Yes | **True duplicate** — different facet, same function. |
| `terrain_wildlife_zones.py:69` (`_distance_to_mask`) | BUG-42, BUG-127 | Yes | **Duplicate** — correctness framing vs perf framing. |
| `terrain_features.generate_canyon` | BUG-65, BUG-88 | Yes | Two defects, same function, single fix scope. |
| `terrain_live_preview.py:138-183` (`edit_hero_feature`) | BUG-59, BUG-111 | Yes | **True duplicate** — consolidate. |
| `atmospheric_volumes.compute_volume_mesh_spec` / `compute_atmospheric_placements` | BUG-11 + BUG-50 + BUG-132 + BUG-140 | Parent/child | Master already tags BUG-140 as parent of BUG-11 and BUG-132 as superset of BUG-50. Collapse children into parents. |
| `terrain_caves.py:1079` / `terrain_sculpt.py:1079` (`_build_chamber_mesh`) | BUG-83, BUG-139 | **Different files, identical line** | Copy-paste artifact; both valid BUGs. |
| `_water_network._compute_tile_contracts` | BUG-62, BUG-74 | Yes | Different math (midpoint approx vs corner double-emit) — NOT duplicate, but same function. Verify if single rewrite closes both. |
| `_water_network.compute_strahler_orders` / `assign_strahler_orders` | BUG-45, BUG-77, BUG-78 | Yes (triple on same feature) | BUG-45 (bare `except`), BUG-77 (quadratic lookup), BUG-78 (asdict loss) — three framings of the same feature; single rewrite closes all. Recommend merging. |

---

## Recommendations to master-audit maintainer

1. **Add "Duplicate of" cross-ref headers** to BUG-11, BUG-50, BUG-59, BUG-61, BUG-63 (or BUG-76), BUG-106, BUG-126 — each should name its canonical primary.
2. **Introduce a `PATTERN:` prefix** (e.g., `PATTERN-DECL-DRIFT`, `PATTERN-PYTHON-LOOP`, `PATTERN-SIN-HASH`, `PATTERN-DIST-TRANSFORM`) so multi-site bug classes are grouped without deleting individual instances.
3. **PR batches** (single-commit families):
   - **BATCH-A "scipy.ndimage substitution":** BUG-40 + BUG-106 + BUG-18 + BUG-147 + BUG-57/126 + BUG-127 + BUG-63/76 (minimum_filter). ~8 BUGs, 1 PR.
   - **BATCH-B "distance-transform unification":** BUG-07 + BUG-42 + BUG-127. 3 BUGs, 1 PR, 1 new `terrain_math` module.
   - **BATCH-C "DECL DRIFT AST-lint":** BUG-43 + BUG-46 + BUG-47 + BUG-85 + BUG-86 + BUG-95 + BUG-151 + BUG-153 + GAPs. 12+ BUGs, 1 PR (lint tool + applied fixes).
   - **BATCH-D "cell_size propagation":** BUG-13 (6 files) + BUG-37 + BUG-42 + BUG-123 + BUG-152. ~10 BUGs, 1 PR.
   - **BATCH-E "retire sin-hash":** BUG-12 + BUG-73 + residual 4 sites. 1 PR.
   - **BATCH-F "unify _build_chamber_mesh":** BUG-83 + BUG-139. 1 PR.
   - **BATCH-G "Strahler consolidation":** BUG-45 + BUG-77 + BUG-78. 1 PR.

---

## Firecrawl evidence (mandate — 5+ URLs scraped)

| URL | Status | Relevance |
|---|---|---|
| refactoring.com/catalog/ | 200 | 60 named refactorings — backbone for classification. **Substitute Algorithm** explicitly matches every scipy.ndimage consolidation. **Introduce Parameter Object** matches `cell_size` propagation. **Extract Function** matches duplicate `_build_chamber_mesh` unification. **Replace Conditional with Polymorphism** matches singledispatch mesh generators. |
| docs.python.org/3/library/dataclasses.html | 200 | `@dataclass` + `replace()` is the Pythonic Introduce Parameter Object. Relevant for consolidating `cell_size` + coord-convention drift (BUG-79/82/08) into a single `GridConvention` dataclass. |
| docs.python.org/3/library/functools.html | 200 | `@singledispatch` for mesh-archetype polymorphism (BUG-68..71, 83, 132..133, 137, 139, 141). `@lru_cache(maxsize=4)` for deterministic RNG factory (BUG-48/49 per-seed cache). `@wraps` preserves monkey-patch chain (BUG-128 incompat wrappers). |
| martinfowler.com/bliki/StrategyPattern.html | 404 | Not found — fell back to refactoring.guru. |
| refactoring.guru/design-patterns/strategy/python/example | 200 | Strategy pattern Python implementation — template for replacing stub-pass-through family (BUG-58, 66, 117, 134-136) with Context+Strategy where default strategy is honest about being a no-op. |
| refactoring.com/catalog/extractFunction.html | 200 | Canonical Extract Function — template for BATCH-F (`_build_chamber_mesh` unification) and BATCH-G (Strahler). |

---

## Summary stats

- **Confirmed duplicates:** 10 pairs/triples (21 BUG IDs collapsible to 10 canonical).
- **Overlapping-fix refactor batches:** 13 (covering ~60 BUG IDs total).
- **Pattern families:** 12 (covering ~70 BUG IDs — with overlap).
- **Same-file-line collisions:** 12 distinct sites with ≥2 BUGs.
- **Highest-impact consolidation:** BATCH-C (DECL DRIFT AST-lint) — 12+ BUGs closed by one tooling PR, already cross-referenced in BUG-47's own Context7 note.
- **Non-goal respected:** no master-audit edits made.
