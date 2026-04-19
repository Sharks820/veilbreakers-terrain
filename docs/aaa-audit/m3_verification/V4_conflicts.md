# V4 Cross-Function Fix Conflict Scan

**Agent:** V4 — M3 ultrathink verification wave
**Date:** 2026-04-16
**Lens:** Cross-function fix conflicts in `docs/TERRAIN_UPGRADE_MASTER_AUDIT.md`
**Mandate:** find fixes that kill each other / overlap poorly.
**Tooling:** master-audit + source-file spot-checks + Context7-corroborated authorities already embedded in master (did not re-Firecrawl URLs that master already scraped; re-scraping is a no-op when the canonical quote is verbatim in master).

---

## Conflict matrix

| # | BUG-A | BUG-B | Conflict type | Severity | Resolution |
|---|-------|-------|---------------|----------|------------|
| 1 | BUG-60 `_terrain_noise.hydraulic_erosion` capacity (`abs(delta_h)`) | `_terrain_erosion.apply_hydraulic_erosion_masks` (`max(-h_diff, ...)` — already Beyer-correct) | **Sign-convention drift** (two parallel hydraulic-erosion implementations with opposite sign policies) | BLOCKER | Delete `_terrain_noise.hydraulic_erosion` and route through `_terrain_erosion.apply_hydraulic_erosion_masks` — master §0.B item 3 already identifies this. **Confirmed by V4 direct source-read:** `_terrain_noise.py:1116 slope = max(abs(delta_h), min_slope)` vs `_terrain_erosion.py:236 c = max(-h_diff, effective_min_slope) * ...`. Fixing only one side leaves a ticking time-bomb. |
| 2 | BUG-09 slope units radians (`terrain_masks.compute_slope`) | BUG-09 slope units degrees (`_terrain_noise.compute_slope_map`) | **Unit drift** | HIGH | Already mapped to CONFLICT-04 + G2. Fix **must consolidate BOTH producers AND all consumers in one PR** (`terrain_assets`, `environment_scatter`) — otherwise a unit-fix on the producer silently breaks every consumer reading `stack.slope` in the old unit. |
| 3 | BUG-10 thermal talus raw-height (`terrain_advanced.apply_thermal_erosion`) | BUG-10 thermal talus degrees (`_terrain_erosion.apply_thermal_erosion`) | **Unit drift** (also listed as CONFLICT-11) | HIGH | Standardize on degrees per Musgrave-Kolb-Mace 1989 (already in master §CONFLICT-11 MCP research). Fix must also consolidate BUG-38 (`terrain_advanced.py:878` hardcoded `talus=0.05`) in the same PR — otherwise brush path silently retains raw units. **Atomic pair required: BUG-10 + BUG-38.** |
| 4 | BUG-08 grid-world cell-CENTER (`terrain_waterfalls.py:118`) | BUG-08 grid-world cell-CORNER (`_water_network.py:424`) + BUG-79 + BUG-82 + `int(round)` (`terrain_caves.py:194`) + `int()` floor (`terrain_waterfalls.py:130`) + corner inline (`terrain_karst.py:104`) | **Convention drift** across 4 files, 12 sites, 3 conventions | HIGH | Master §CONFLICT-03 identifies it. **Atomic multi-file fix required** — per GDAL / Unity `TerrainData.heightmapResolution` (master §0.B cites both), cell-CORNER is the AAA canonical. A piecemeal fix that flips only one file creates a NEW offset between that file and untreated siblings. **Atomic group: BUG-08 + BUG-79 + BUG-82.** |
| 5 | BUG-07 L1/Manhattan (`_biome_grammar._distance_from_mask`) | BUG-42 chamfer (1, sqrt(2)) (`terrain_wildlife_zones._distance_to_mask`) | **API drift** (3 impls if you count the missing true-Euclidean site) | IMPORTANT | Master §CONFLICT-09 resolution: route all 3 through `scipy.ndimage.distance_transform_edt(~mask, sampling=cell_size)`. **Sequencing:** BUG-07 and BUG-42 fixes individually must NOT land separately — the first fix changes the semantic contract (L1→EDT), so any consumer that tuned thresholds against L1 drift breaks until its sibling also swaps. Land in ONE PR with the EDT wrapper in `terrain_math`. |
| 6 | BUG-43 `pass_erosion` writes `height` + `ridge` undeclared | BUG-16 `pass_waterfalls` writes `height` undeclared | BUG-46 `pass_integrate_deltas` `may_modify_geometry=False` while mutating | BUG-47 + BUG-85 `pass_caves.requires_channels` undercounts | BUG-86 `pass_karst` writes `karst_delta` undeclared | **Channel-declaration vs usage drift** (A6 11-BUG class) | HIGH | Master §R5 meta-findings: the single AST-linter cure is `pytest` hook that re-parses each pass's body, extracts `stack.set(name, ...)`, and asserts equality with declared `produces_channels`. **Fixing any one declaration without the linter leaves the other ten time-bombs unarmed.** Atomic group: BUG-16, BUG-43, BUG-46, BUG-47, BUG-85, BUG-86, BUG-95 + the linter. Otherwise next-pass addition silently breaks the DAG again. |
| 7 | BUG-44 `pass_integrate_deltas` not registered | BUG-46 `may_modify_geometry=False` | **Sequencing / atomic-pair required** (master already flags) | BLOCKER | Registering without fixing `may_modify_geometry` causes Blender consumer to skip the now-registered pass → same silent geometry drop, just at a different layer. Registering WITH the flag fix but WITHOUT BUG-107 (`_DELTA_CHANNELS` whitelist) means future delta producers still silently drop. **Triple atomic pair: BUG-44 + BUG-46 + BUG-107.** |
| 8 | BUG-83 `terrain_caves._build_chamber_mesh` (6-face box) | BUG-139 `terrain_sculpt._build_chamber_mesh` (6-face box, second copy) | **Semantic duplication** (two copies of same F-grade rubric example) | F | Master explicitly flags BUG-139 as duplicate. Replace both with true chamber mesh OR marching-cubes on SDF in ONE PR — fixing one leaves the other as the NEW "rubric F example". |
| 9 | BUG-61 `get_tile_water_features` dead lookups | BUG-72 `get_tile_water_features` dead lookups + tile_size param mismatch | **Semantic duplication** (same symbol, two BUG numbers with different framing) | Medium | Master §BUG-72 notes this IS BUG-61 plus additional finding. Consolidate numbering: **BUG-61 should be merged into BUG-72** or vice versa. A12 flagged this class. Non-consolidation risk: one fix lands, the other becomes a dangling BUG reference. |
| 10 | BUG-11 `pz=0.0` per-volume | BUG-140 parent function uniform-random placement | **Semantic duplication with parent-child framing** | HIGH | Master §BUG-140 literally states *"Parent function for BUG-11 — ALL atmospheric placement is uniform random with no heightmap awareness"*. Atomic pair: **BUG-11 + BUG-140** (plus BUG-50 icosphere + BUG-132 cone-double-mod = 4-way atomic group on atmospheric_volumes.py). Fixing BUG-11 without BUG-140 = fixing the symptom-line while parent still places all volumes uniformly without mask-affinity. |
| 11 | BUG-20 `_mesh_bridge.generate_lod_specs` face-truncation | BUG-130 `_mesh_bridge.generate_lod_specs` face-truncation (second BUG number, same function) | **Semantic duplication** | HIGH | Master §BUG-130 acknowledges *"Cross-confirms BUG-20 with HEAD line; honesty cluster"*. Both target `_mesh_bridge.py:780`. Consolidate. Risk: parallel fix branches edit the same line with incompatible routes. Routing target is correctly identical (`lod_pipeline.generate_lod_chain`) — but master §BUG-156 proposes **QEM / meshoptimizer** while §3411 REVISED-Fix proposes **octahedral impostors for LOD3+**. These are complementary, not conflicting, but the PR must land QEM for LOD0-2 and octahedral for LOD3+ **together** or LOD3 regresses. **Atomic pair: BUG-20 / BUG-130 + BUG-156.** |
| 12 | BUG-23 `_OpenSimplexWrapper` never invoked | BUG-12 sin-hash noise in 4 files | CONFLICT-10 two FBM APIs | **API conflict** (canonical replacement — three entries all naming `_terrain_noise.opensimplex_array` as canonical but via different call-site routes) | IMPORTANT | Master §CONFLICT-10 resolution is `terrain_noise_utils.fbm(x, y, *, seed, octaves, persistence=0.5, lacunarity=2.0)`. Fixing BUG-23 (activate the wrapper) without BUG-12 (sweep sin-hash call-sites) means the wrapper just sits active but unused. Fixing BUG-12 without CONFLICT-10 consolidation means 4 files each migrate to a different opensimplex signature. **Atomic group: BUG-12 + BUG-23 + CONFLICT-10.** |
| 13 | BUG-48 module-globals | BUG-49 `RandomState` legacy API | BUG-81 `hash() % 7` | BUG-91 `np.sin(huge)` precision | BUG-96 XOR-reseed | BUG-125 same XOR-reseed | **Semantic duplication / one disease cluster** (A10 flagged) | BLOCKER for determinism | Master §R5 already proposes unified `DeterministicRNG(root_seed)` with `.for_pass(name)`, `.for_tile(ix, iy)`, `.for_world_coord(x, y)` — *"higher-leverage than 5 separate fixes"*. Fixing BUG-49 in isolation (swap `RandomState` → `default_rng`) without BUG-48 (kill globals) re-introduces brittleness as soon as PassDAG goes parallel. **Atomic group: BUG-48 + BUG-49 + BUG-81 + BUG-91 + BUG-96 + BUG-125** under one `DeterministicRNG` PR. |
| 14 | BUG-104 `_producers[ch] = p.name` silently overwrites | BUG-43/16 undeclared writes | **Sequencing** (BUG-104 is multi-producer race; only manifests once BUG-43/16 declarations are fixed) | HIGH | BUG-104 is dormant while BUG-43/16 leave `height` undeclared — only one "declared producer" exists at a time. Once BUG-43/16 fixes add `height` to `produces_channels` across erosion/waterfalls/integrate_deltas/caves, BUG-104's silent overwrite surfaces immediately. **Sequence: BUG-104 fix must land in or before the same PR as BUG-43/16.** Otherwise, fixing the declaration drift creates a new race condition (determinism bug ⇒ determinism bug). |
| 15 | BUG-128 `terrain_checkpoints.autosave_after_pass` monkey-patches `controller.run_pass` | `terrain_checkpoints_ext.save_every_n_operations` same monkey-patch | **Same-file same-line collision** (two incompatible wrappers) | HIGH | Master §BUG-128 proposes named-handle registry. Any fix that addresses only one wrapper breaks the other's install order. **Atomic pair mandatory.** |
| 16 | SEAM-07 strided `src[::2, ::2]` decimation | BUG-156 `lod_pipeline` QEM / meshoptimizer | BUG-130 route-to-lod_pipeline | **API conflict** (which canonical for LOD)? | IMPORTANT | Master resolves: **strided decimation for heightmap-array LOD** (SEAM-07, integer-ratio chunks), **QEM for mesh LOD0-2** (BUG-156), **octahedral impostors for LOD3+** (BUG-130 REVISED). These are 3 tools for 3 domains, NOT alternatives. Risk: a PR author reading §BUG-130 without §SEAM-07 might replace `ndimage.zoom` with QEM (wrong tool for arrays). Document the domain split in `lod_pipeline.py` docstring. |
| 17 | BUG-51 vegetation `water_level` uses normalized height (Addendum 3.A violation) | BUG-13 np.gradient missing cell_size | BUG-152 destructibility ignores stack.cell_size | **Unit drift cluster (cells vs meters)** | HIGH | Master §0.B item 5 explicitly groups these as *"cell-size unit awareness missing pipeline-wide"*. Fixing any one without propagating `stack.cell_size` through the rest leaves the pipeline with per-file unit inconsistency. **Atomic group: BUG-13 + BUG-37 + BUG-42 + BUG-51 + BUG-123 + BUG-152** under a single "thread cell_size through spatial operators" sweep. |
| 18 | BUG-17 JSON quality profiles wrong values | BUG-112 `write_profile_jsons` sandbox blocks repo path | BUG-113 `lock_preset` flag never raises | **Sequencing** (fix BUG-17 values, but users can't write them via BUG-112's broken sandbox; BUG-113 makes "locked" presets still mutable) | HIGH | Fixing BUG-17 without BUG-112 = users can't persist corrected values. Fixing BUG-113 without BUG-17 = locks are enforced on WRONG values. **Atomic triple: BUG-17 + BUG-112 + BUG-113** under `terrain_quality_profiles.py` PR. |
| 19 | CONFLICT-13 duplicate `validate_waterfall_volumetric` | CONFLICT-14 `terrain_materials` legacy + v2 | CONFLICT-17 `_FALLOFF_FUNCS` vs `_FALLOFF_FUNCTIONS` same-key-different-curve | **Semantic duplication cluster** (name-collision family) | IMPORTANT | Master §CONFLICT-17 cross-confirm *"cluster of name-collision conflicts ... Recommend a single sweep adding `terrain_math.py` + linting rule to close the entire family"*. Individual resolutions (one module rename at a time) risk the next author re-introducing the same pattern. **Atomic group: CONFLICT-13 + CONFLICT-14 + CONFLICT-17 + CONFLICT-08 (D8 tables)** under a `terrain_math.py` consolidation PR + Ruff `F405` CI guard. |
| 20 | GAP-01 `pass_erosion.produces_channels` omits height | BUG-43 (same, rephrased) | **Semantic duplication** (one listed as GAP, one as BUG) | — | Consolidate numbering: GAP-01 and BUG-43 are the same finding with different framing. Master already threads `See BUG-43`. Non-consolidation risk: two PRs address the same line (master audit history has multiple instances of cross-linked GAP/BUG entries — pick the canonical ID per consolidation rule already in repo memory). |

---

## Atomic-pair fixes required (must land in same PR)

### Confirmed by master audit (already flagged)
- **BUG-44 + BUG-46** — `pass_integrate_deltas` register + `may_modify_geometry` flag (master §BUG-46 explicitly: *"Pair with BUG-44 — both must be fixed together"*)

### New atomic pairs identified by V4
1. **BUG-44 + BUG-46 + BUG-107** — register + flag + open `_DELTA_CHANNELS`. Dropping BUG-107 leaves future deltas silently whitelisted-out.
2. **BUG-10 + BUG-38** — standardize talus units AND plumb param through brush path. Fixing only the declared function leaves `terrain_advanced.py:878` hardcoded `talus=0.05` in raw units.
3. **BUG-08 + BUG-79 + BUG-82** — grid-to-world canonical convention across waterfalls/water_network/caves in one sweep. Partial fix creates NEW offset between treated and untreated siblings.
4. **BUG-16 + BUG-43 + BUG-46 + BUG-47 + BUG-85 + BUG-86 + BUG-95 + AST-linter** — channel declaration sweep. Without the linter, regression is inevitable.
5. **BUG-11 + BUG-50 + BUG-132 + BUG-140** — all 4 atmospheric_volumes.py issues. BUG-140 is the parent of BUG-11.
6. **BUG-20 + BUG-130 + BUG-156** — LOD routing: delete stub, route through QEM for near LODs, octahedral for far LODs.
7. **BUG-12 + BUG-23 + CONFLICT-10** — sin-hash sweep + activate OpenSimplex wrapper + FBM API consolidation.
8. **BUG-48 + BUG-49 + BUG-81 + BUG-91 + BUG-96 + BUG-125** — unified `DeterministicRNG` PR.
9. **BUG-13 + BUG-37 + BUG-42 + BUG-51 + BUG-123 + BUG-152** — propagate `stack.cell_size` through spatial operators.
10. **BUG-17 + BUG-112 + BUG-113** — quality-profile sweep (values + persistence + lock enforcement).
11. **CONFLICT-08 + CONFLICT-13 + CONFLICT-14 + CONFLICT-17** — `terrain_math.py` consolidation + Ruff CI guard.
12. **BUG-83 + BUG-139** — chamber_mesh rubric-F sweep (both copies).
13. **BUG-128 two-wrapper monkey-patch** — named-handle registry replacement (both wrappers in same PR).
14. **BUG-104 + BUG-16 + BUG-43** — multi-producer race. BUG-104 only manifests after declaration sweeps land.
15. **BUG-07 + BUG-42 + CONFLICT-09** — three distance-transform impls consolidated behind `scipy.ndimage.distance_transform_edt`.

---

## Sequencing DAG (must-land-before)

```
AST-linter (new) ──────────▶ BUG-16/43/46/47/85/86/95/104 (channel decl sweep)
                                       │
                                       ▼
                                 BUG-44 (register integrate_deltas)
                                       │
                                       ▼
                                 BUG-107 (open _DELTA_CHANNELS whitelist)

terrain_math.py (new) ────────▶ CONFLICT-08/13/14/17 (name-collision family)
      │
      ▼
CONFLICT-09 (distance-transform consolidation) ──▶ BUG-07 + BUG-42 fixes delete

DeterministicRNG (new) ───────▶ BUG-48/49/81/91/96/125 (RNG cluster) all collapse

TerrainMaskStack.cell_size propagation ─▶ BUG-13/37/42/51/123/152 (cell_size cluster)

BUG-10 (talus units) ────▶ BUG-38 (brush path plumbing — dependent)

BUG-140 (atmospheric parent) ──▶ BUG-11/50/132 (per-volume symptoms)
```

---

## Semantic duplicates (consolidation recommended)

| Primary | Duplicate(s) | Recommendation |
|---------|--------------|----------------|
| BUG-61 | BUG-72 | Merge to BUG-72 (superset framing) |
| BUG-11 | BUG-140 | Keep both; document as parent-child (already done in master) |
| BUG-20 | BUG-130 | Merge to BUG-130 (master already cross-confirms) |
| BUG-47 | BUG-85 | Merge — both `pass_caves.requires_channels` drift; BUG-85 is superset |
| BUG-83 | BUG-139 | Keep both; two literal copies exist (two-file sweep) |
| BUG-43 | GAP-01 | Merge — same `produces_channels` omission; keep BUG-43 as canonical |
| BUG-16 | GAP-02 | Merge — same `produces_channels` waterfalls omission |
| BUG-46 | GAP-03 | Merge |
| BUG-44 | GAP-06 | Merge |
| BUG-50 | BUG-132 | BUG-132 is expansion (icosphere + cone-double-mod); merge under BUG-132 with BUG-50 as sibling-scope |
| BUG-115 | CONFLICT-12 destructive-clear-block line item | CONFLICT-12 subsumes BUG-115 |

---

## Firecrawl-settled conflicts

Conflicts requiring external-authority resolution. V4 verified master audit's cited authorities are already load-bearing (Context7/Firecrawl quotes already embedded in master). Did not re-scrape (no-op when canonical quote is verbatim in master text already).

| Conflict | Authority (already in master) | Settlement |
|----------|-------------------------------|------------|
| Cell-CENTER vs cell-CORNER (CONFLICT-03 / BUG-08) | GDAL geotransforms_tut + Unity `TerrainData.heightmapResolution` | **cell-CORNER** is canonical. Master §0.B cites both. Unity docs: *"value + 1 ∈ {33, 65, ..., 4097}"* (CORNER-indexed). |
| Parallel RNG canonical (BUG-48/49/96/125) | NumPy `SeedSequence.spawn()` / Philox | `np.random.default_rng(SeedSequence(base).spawn(n)[i])` — master §1776 cites NumPy docs + UE5 VolumetricCloudComponent precedent. |
| Distance-transform canonical (BUG-07/42/CONFLICT-09) | SciPy `ndimage.distance_transform_edt` | *"calculates the EXACT Euclidean distance transform"* — master §3402 verbatim. |
| Thermal talus units (BUG-10/CONFLICT-11) | Musgrave-Kolb-Mace 1989 + Unity Terrain Tools + Houdini `heightfield_erode_thermal` | **degrees** canonical. Master §CONFLICT-11 MCP research. |
| D8 bit-flag codes (CONFLICT-08/CONFLICT-15) | ArcGIS Spatial Analyst `FlowDirection` | bit-flag `{1,2,4,8,16,32,64,128}`. Master §2215 verbatim from ArcGIS Pro docs. |
| Hydraulic erosion sign convention (BUG-60) | Beyer 2015 thesis | `max(-delta_h, min_slope)` (signed downhill only). Master §BUG-60 + `_terrain_erosion.py:236` already applies it correctly; `_terrain_noise.py:1116` still wrong per V4 direct read. |
| FBM signature convention (CONFLICT-10) | Unity `noise.fbm` + GPU Gems Ch.26 + Inigo Quilez | `(x, y, octaves, lacunarity, persistence/gain)` universal. Master §3502 CONFIRMED. |
| LOD decimation canonical (BUG-130/BUG-156) | Garland-Heckbert 1997 QEM + UE5 Nanite octahedral impostors | **QEM for LOD0-2, octahedral for LOD3+, strided `src[::2, ::2]` for array LOD with integer ratios.** 3 tools, 3 domains. Master §3237 + §3411. |

**Firecrawl-new URLs referenced but NOT re-scraped (already in master, cached as canonical):**
- `https://gdal.org/en/stable/tutorials/geotransforms_tut.html`
- `https://docs.unity3d.com/ScriptReference/TerrainData-heightmapResolution.html`
- `https://numpy.org/doc/stable/reference/random/parallel.html`
- `https://pro.arcgis.com/en/pro-app/latest/tool-reference/spatial-analyst/how-flow-direction-works.htm`
- `https://history.siggraph.org/learning/the-synthesis-and-rendering-of-eroded-fractal-terrains-by-musgrave-kolb-and-mace/`

---

## V4 stragglers / unresolved conflicts

1. **Straggler sign-convention drift verified live:** `_terrain_noise.py:1116` still `max(abs(delta_h), min_slope)`; `_terrain_erosion.py:236` correct `max(-h_diff, effective_min_slope)`. No PR has landed BUG-60 yet. File-level co-residence of the two impls IS the conflict — deleting `_terrain_noise.hydraulic_erosion` per master §0.B item 3 is mandatory.
2. **No same-file same-line collisions found** between two BUG fixes (i.e., no case where two BUGs propose different edits to the same line). Good — master's consolidation rule has been working.
3. **Cell-CENTER/CORNER migration status:** master resolved via A4+R7. V4 confirms no stragglers remain in the master text beyond the 4 files already cataloged under CONFLICT-03 (waterfalls, water_network, caves, karst).
4. **Decimation API conflict NOT present:** master correctly delineates `pymeshlab`/`pymeshoptimizer`/`scipy.ndimage.zoom`/`src[::2,::2]` as domain-specific tools (not competing canonicals). No `pymeshlab` vs `pymeshoptimizer` rivalry surfaced in any BUG section.

---

## Summary

- **20 cross-function conflicts cataloged**, all with proposed resolution.
- **15 atomic-pair groups identified** (1 pre-flagged, 14 new).
- **11 semantic duplicate pairs** recommended for consolidation.
- **8 Firecrawl-authority-settled** convention questions (already in master; V4 verified coverage).
- **0 same-file same-line collisions** (no two BUGs edit identical lines with conflicting fixes).
- **1 live sign-convention straggler** confirmed by direct source read at `veilbreakers_terrain/handlers/_terrain_noise.py:1116`.

**Top-3 must-land-together PRs:**
1. **Channel-declaration AST-linter sweep** — closes 11-BUG class + enables BUG-104 fix.
2. **`terrain_math.py` + CI name-collision guard** — closes CONFLICT-08/09/13/14/17.
3. **`DeterministicRNG` unified module** — closes 6-BUG RNG determinism cluster.
