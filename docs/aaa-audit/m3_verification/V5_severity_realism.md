# V5 Severity Realism vs Real AAA Output

**Agent:** V5 (M3 ultrathink verification wave — severity-realism lens)
**Date:** 2026-04-16
**Scope read:** `docs/TERRAIN_UPGRADE_MASTER_AUDIT.md` (BUG-01..BUG-159, BUG-132..BUG-142), `docs/aaa-audit/GRADES_VERIFIED.csv` (rows 1-50 sample + targeted rows via Grep), `docs/aaa-audit/CHART.md` context.
**Firecrawl mandate:** fulfilled — 10 unique URLs scraped, 6 of them the exact URLs named in the brief + 4 supplemental AAA references.
**Non-goal:** no edits to master audit or GRADES_VERIFIED.csv.

---

## 0. Executive severity-realism verdict

The audit's severity vocabulary is **broadly disciplined** but has a **consistent bias toward underselling player-visible failures as "POLISH" / "IMPORTANT"** and a matching tendency to **overclaim AAA-Equivalent parentage** (Gaea / Houdini / Horizon) for 50-line pure-Python loops that ship placeholder output. Conversely, some mesh-topology bugs (CW winding, welding cracks) and one dead-code pattern are over-severed relative to their actual ship-impact on an AAA target.

Concrete pattern counts (from the master doc + CSV sample):

- **Under-severed (should escalate):** 8 bugs where the severity tag is ≥1 step below what AAA studios treat as ship-blocking. Most egregious: BUG-11 / BUG-140 "atmospheric placement at z=0 uniform-random" is **not polish — it is shipping a broken-fog bug**.
- **Over-severed (should downgrade):** 3 bugs where the CRITICAL / BLOCKER tag reflects engineering hygiene, not player-visible failure. Most egregious: BUG-45 "setattr with bare except" marked CRITICAL in CSV; it is latent landmine POLISH until `WaterSegment` is frozen.
- **AAA-Equivalent inflation:** 11 documented inflations. The `_biome_grammar.py` family repeatedly claims "Gaea", "Houdini Mountain SOP", "Horizon Forbidden West coral-reef authoring" for Python loops that are 50-100 lines long with no multi-scale composition, no GPU acceleration, and no artist-facing tooling. Real Gaea is a node graph with thousands of hours of R&D and C++/GPU acceleration.
- **AAA-Equivalent deflation:** 2 items where a correct, canonical implementation is graded below its AAA floor because the module is shadowed by a worse sibling (BUG-138 / BUG-142 `terrain_banded_advanced`).

---

## 1. Under-severed (should escalate)

Severity should move UP. AAA studios would fail QA on each of these.

| BUG | Current severity | Proposed severity | AAA product that ships this correctly | Firecrawl ref |
|---|---|---|---|---|
| BUG-11 `atmospheric_volumes` pz=0.0 | "important" (CSV col Severity row #44), doc body calls it CRITICAL — **tag in the master-doc table is IMPORTANT** | **CRITICAL / BLOCKER** | Horizon Zero Dawn Nubis volumetric cloudscapes (Schneider 2015 SIGGRAPH) place volumetric fog as 3D density LUTs in world space, not billboards at z=0. HDRP Local Volumetric Fog *requires* OBB placement at ground level. Fog 2000 m underground on a mountain is a shipping bug. | https://www.guerrilla-games.com/read/the-real-time-volumetric-cloudscapes-of-horizon-zero-dawn ; https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@17.0/manual/create-a-local-fog-effect.html |
| BUG-140 parent of BUG-11 (uniform-random placement, no feature affinity) | "important" | **CRITICAL** (R7 line already proposes this upgrade, but the bolded **Severity:** field in the doc still reads IMPORTANT — propagate to the top-level severity tag) | Nubis / Decima authoring uses feature-driven importance sampling on cloud/affinity masks. Fireflies over open ocean, god-rays in flat grass meadow, fog pools on mountain ridges are player-visible QA fails in Guerrilla / Rockstar / Naughty Dog titles. | https://www.guerrilla-games.com/read/the-real-time-volumetric-cloudscapes-of-horizon-zero-dawn |
| BUG-12 / BUG-73 sin-hash noise ("fract(sin) * 43758.5453") | "important" | **HIGH** (already partly upgraded to F in R7 line but master bolded **Severity:** is IMPORTANT / CRITICAL-in-cluster) | Gaea and World Machine use C++ OpenSimplex / Perlin with explicit gradient tables. Sin-hash is ShaderToy-era demoscene; no AAA terrain ships with it as the SOLE noise source. R7 confirms cross-platform bit-instability silently breaks deterministic replay. | https://docs.quadspinner.com/Reference/Erosion/Erosion.html ; https://help.world-machine.com/topic/device-thermalerosion/ |
| BUG-50 / BUG-132 12-vert "icosphere" | IMPORTANT | **HIGH** | Unity HDRP / UE5 Local Fog Volume and even Unity ProBuilder sample icosphere start at subdiv=2 (162 verts); AAA floor per user rubric is subdiv=3 (642 verts). A 12-vert polyhedron is visually nothing like a sphere — the silhouette is visible on every fog / firefly / godray volume at any camera distance. | https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@17.0/manual/create-a-local-fog-effect.html |
| BUG-67 `terrain_dem_import` can't read GeoTIFF or SRTM | IMPORTANT | **CRITICAL** for a "terrain" addon claiming DEM import. AAA terrain tools (Gaea, World Machine, Houdini HeightField Import, UE5 Landscape Import) all consume GeoTIFF + SRTM `.hgt` natively; a DEM-import module that does neither is a function-name lie. | https://help.world-machine.com/topic/device-thermalerosion/ (World Machine ships SRTM import out-of-box) |
| BUG-83 / BUG-139 `_build_chamber_mesh` 6-face invisible box (TWO copies) | CRITICAL (BUG-83) / BLOCKER (BUG-139) — **adequate**, but the **R5 severity field in the BUG-83 row uses "F" (rubric grade)** which is not a valid severity in the audit's taxonomy — inconsistent. Normalize to **BLOCKER**. | BLOCKER | UE5 voxel plugin / Houdini SDF+VDB / scikit-image marching_cubes. Naughty Dog / Guerrilla / Santa Monica Studio all ship hand-authored or SDF-carved caves, not invisible-marker boxes. An invisible "mesh" cave that relies on a heightfield delta (which itself isn't wired per BUG-44) is a ship-stop. | https://scikit-image.org/docs/stable/auto_examples/edges/plot_marching_cubes.html (via R7 references) |
| BUG-137 octahedral impostor stub returning `next_steps` JSON | BLOCKER — **adequate**. But callout: the **BUG-141 consumer is tagged IMPORTANT**, which understates the cascade: no billboard = LOD3+ pops visibly at 100-200m, the single most-noticed open-world LOD artifact. | Escalate BUG-141 to **HIGH / BLOCKER** in lockstep | Fortnite Battle Royale ships 12×12=144 sub-frame octahedral atlases (2048² RGBA + 1024² Normal+Depth). SpeedTree ships impostor baker out-of-box. Horizon Forbidden West vegetation keeps impostor LODs ≥LOD3. | https://store.speedtree.com/ ; https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-overview |
| BUG-110 `terrain_hot_reload` 100% no-op | CRITICAL — **adequate**. But the CSV severity for several of the individual reload functions is lower ("important" / "polish"). Normalize to CRITICAL because *the entire feature does not function*. | CRITICAL (harmonize) | UE5 Live Coding and Unity Hot-Reload both actually reload. A hot-reload module that claims the feature and no-ops is in the user's explicit honesty cluster. | https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-overview (UE5 live-iteration reference) |

### Additional under-sever call-out (not in table above but worth escalation)

- **BUG-134 / BUG-135 / BUG-136 `terrain_sculpt.compute_{raise,lower,flatten}_displacements`** are tagged CRITICAL in CSV which is correct. But the **AAA-Equivalent is missing entirely from the doc** — user expects comparison to ZBrush / Mudbox / Nomad / Unity Terrain Brush / UE5 Landscape Sculpt. These are the canonical ship targets. Add them (see §3).

---

## 2. Over-severed (should downgrade)

Severity should move DOWN. Marking these CRITICAL dilutes the word for the real CRITICALs.

| BUG | Current severity | Proposed severity | Why downgrade | Firecrawl ref |
|---|---|---|---|---|
| BUG-45 `compute_strahler_orders` `setattr` + bare `except: pass` | CSV Severity = **critical** | **POLISH / IMPORTANT** | The bug only manifests if `WaterSegment` becomes frozen (it isn't). Currently: dataclass mutated silently but visibly. The fix is a one-line field declaration. Real shipping AAA code has worse `try/except: pass` patterns; this is lint-grade hygiene. The master doc's own severity says "POLISH (latent landmine)" — the CSV severity column (`critical`) is the outlier. | n/a (internal Python idiom) |
| BUG-01 stamp falloff dead parameter | Upgraded during review; effectively HIGH / BLOCKER in some reviewers | **IMPORTANT** | `blend = edge_falloff * (1-falloff) + edge_falloff * falloff` simplifies to `edge_falloff`. Parameter is dead. One-line algebraic fix. Player-visible? Only if a designer ever moved the slider and expected it to do something. Real shipping bug? No — terrain still stamps, just with one redundant knob. Downgrade to IMPORTANT. | n/a |
| BUG-109 `terrain_legacy_bug_fixes` static-grep "audit" module | IMPORTANT (honesty cluster) | **POLISH (deletion)** + honesty cluster remediation tag | The module is dead/decorative, not wrong. The correct move is deletion, not "fix". Marking as IMPORTANT implies there's something to fix in place; there isn't. Separate tag: HONESTY-CLUSTER-REMOVAL. | n/a |
| BUG-39 `pass_integrate_deltas` `max_delta` metric is min | POLISH — **correct**. Mentioned here only because reviewers have flirted with escalating to IMPORTANT on naming-hygiene grounds. | Keep POLISH | Pure telemetry/metric-naming issue. Not player-visible. Real AAA telemetry dashboards rename metrics all the time. | n/a |

---

## 3. AAA-Equivalent claim audit

This is the single biggest issue in the audit. The `AAA Equivalent` column is frequently **aspirational, not descriptive**. Descriptive column = "what does this code MATCH today"; Aspirational = "what are we shooting at." The user requested severity realism, so these MUST be corrected.

### 3.A Inflated AAA-Equivalent claims (current impl does NOT match the AAA target)

| BUG / CSV row | Current "AAA Equivalent" claim | Actual AAA impl of that claim | Correct label for current code |
|---|---|---|---|
| CSV Row #4 `apply_desert_pavement` → **"Gaea Desert/Arid node"** | Gaea Desert/Arid is a GPU-accelerated multi-scale erosion stack with slope+altitude bias + selective processing, tuned by the QuadSpinner team over 10+ years. | A 10-line Python slope+elev mask + `_box_filter_2d` (which itself is a D-grade Python double-loop per BUG-40/106). | **"Slope-elev pavement mask (hand-rolled)"** or **"Sub-Gaea placeholder"**. No Gaea equivalence. |
| CSV Row #5 `apply_geological_folds` → **"Gaea Stratify + Tilt nodes combined"** | Gaea Stratify + Tilt is a calibrated geological sim with plunge/strain/amplitude variation along strike, GPU-accelerated. | Sinusoidal/triangular wave added linearly, uniform amplitude, no strain scaling, no plunge. | **"Procedural fold band (placeholder)"** |
| CSV Row #6 `apply_hot_spring_features` → **"Yellowstone travertine terraces reference (Hell Let Loose / Horizon)"** | Real travertine pools in Horizon FW are hand-sculpted heightfields + custom shader + photo-sourced decals. | Perfectly circular concentric rings at uniform spacing. | **"Concentric-ring placeholder"** |
| CSV Row #9 `apply_reef_platform` → **"Horizon Forbidden West coral-reef authoring"** | HFW coral reefs are Decima's landscape material + hand-authored feature meshes + Megascans scans. | A uniform reef band computed from `_distance_from_mask` (which is broken per BUG-07, L1-Manhattan not Euclidean). | **"Shore-band placeholder"** |
| CSV Row #12 `generate_world_map_spec` → **"UE5 PCG World Partition biome graph / Witcher 3 region splitter"** | UE5 PCG is a full DAG with HLOD + World Partition streaming + instanced spawners; Witcher 3 region system is a CD Projekt in-house authoring tool + 100s of hand-authored biome rules. | Voronoi biome distribution + fBm corruption + circular flatten zones. | **"Voronoi biome sketch"** |
| CSV Row #14 `detect_cliff_edges` → **"Houdini Edge Detection / Gaea Slope mask with clustering"** | Houdini uses vectorized C++ + PCA-fit oriented bounding boxes. | Python flood-fill + single-cell gradient at cluster center (no PCA). ~3-5s on 1024². | **"Slope-flood-fill cliff detector"** |
| CSV Row #18 `generate_waterfall_mesh` → **"Horizon Forbidden West waterfall / RDR2 volumetric cascade"** | HFW / RDR2 waterfalls are hand-sculpted meshes + Niagara/Decima particle curtains + real-time mist volumes + multi-material shaders. | Single-sided 2-row flat strip + 16-segment fan pool disk — exactly the flat-plane failure mode flagged in `feedback_waterfall_must_have_volume.md`. | **"Stepped cascade placeholder (violates volume rule)"** |
| CSV Row #20 `generate_world_heightmap` → **"Gaea canvas sampler at world window"** | Gaea canvas is a node-graph output with multi-scale composition (Mountains + Hills + Rocks node stack). | Thin wrapper around `generate_heightmap`; single-scale noise. | **"Single-scale noise wrapper"** |
| CSV Row #21 `pass_erosion` → **"Gaea Erosion2 / Houdini Erosion node"** | Gaea Erosion2 is GPU-accelerated with 10k+ droplet iterations, `Rock Softness`, `Downcutting`, `Inhibition`, `Base Level`, `Feature Scale` params. Houdini Erosion is Mei 2007 pipe-model. | Layered analytical + droplet + thermal, default 200-600 iterations. **Reasonable architecture, but iteration count is 20-50x below Gaea AAA target** per R7 note. | Keep "Gaea Erosion2" but **add asterisk: "at 1/20 Gaea iteration count"**. |
| BUG-72 `get_tile_water_features` → doc claims Strahler-ordered tile contracts | Strahler-ordered river tile contracts are Gaea Rivers / SideFX Heightfield convention. | Contains dead-code lookups (R5 notes) + tile_size param mismatch. | **"Tile-contracts sketch (has dead code)"** |
| CSV Row #44 `compute_atmospheric_placements` → **"UE5 volumetric fog / Horizon Forbidden West localized fog sheets"** | HFW localized fog is a Decima feature-driven placement engine with affinity masks + VDB density fields. | `pz = 0.0` uniform-random scatter. | **"Uniform-random placement stub"** |

### 3.B Deflated AAA-Equivalent claims (correct code graded below its AAA floor)

| BUG / CSV row | Current label | Actual AAA floor | Correct label |
|---|---|---|---|
| BUG-138 `terrain_banded_advanced.apply_anti_grain_smoothing` | BLOCKER + implementation "correct but deployment-dead" | Separable Gaussian = Marr 1980 / Lindeberg 1994 scale-space canonical op. Matches SciPy `gaussian_filter` and Photoshop Gaussian Blur. | **"Correct canonical Gaussian smoother (needs wiring)"** — the code itself is AAA-grade; the deployment is the bug, not the algorithm. |
| BUG-142 `terrain_banded_advanced.compute_anisotropic_breakup` | BLOCKER | Two-frequency Lissajous with coprime ratios is the standard procedural-detail pattern in Gaea, Substance Designer, Houdini COP. | **"Correct Lissajous detail overlay (dead module)"** — wiring fix, not algorithm fix. |

### 3.C Missing AAA-Equivalent claims (should exist, don't)

These bugs' `AAA Equivalent` column is empty or weak. User wants the bar named.

| BUG | Missing AAA-Equivalent reference |
|---|---|
| BUG-134 `compute_raise_displacements` | **ZBrush Move/Clay brush, Mudbox Sculpt, Blender Sculpt Add, Unity Terrain Raise, UE5 Landscape Sculpt**. Explicit target: stroke-accumulation buffer + per-dab falloff + pressure + max-height clamp + normal-aligned direction. |
| BUG-135 `compute_lower_displacements` | **ZBrush ZSub, Mudbox Dig, UE5 Landscape Lower**. |
| BUG-136 `compute_flatten_displacements` | **ZBrush Flatten, UE5 Landscape Flatten, Unity Terrain Flatten**. Plane-fit via least-squares; target-pick via eye-dropper; trim mode. |
| BUG-67 `terrain_dem_import` | **Gaea DEM Import, World Machine File Input, Houdini HeightField Import, UE5 Landscape Import**. Formats: GeoTIFF (via GDAL), SRTM `.hgt` (big-endian int16), Copernicus DEM GeoTIFF. |
| BUG-121 `terrain_audio_zones` | **Wwise Spatial Audio (AkGeometry + AkRoomPortal), FMOD Studio Geometry**. Zero Wwise/FMOD payload is a broken feature. |
| BUG-137 octahedral impostor | **SpeedTree impostor baker, UE5 Octahedral Impostor plugin, Unity Amplify Impostors, Fortnite 12×12 octahedral atlas (Epic Impostor Baker)**. The R7 line surfaces Fortnite; it should be in the AAA-Equivalent column too. |

---

## 4. Firecrawl-grounded AAA-floor tables

For each terrain subsystem, "what a current AAA title ships" vs "what VeilBreakers ships today." Rooted in the Firecrawl scrapes below.

### 4.1 Volumetric fog / god-rays / fireflies

| Capability | AAA floor (Horizon Zero Dawn / Unity HDRP 17) | VeilBreakers today | Gap |
|---|---|---|---|
| Placement z | Sampled from terrain height + archetype vertical offset | `pz = 0.0` (BUG-11) | CRITICAL — fog 2000 m underground on a mountain |
| Placement strategy | Feature-driven importance sampling on affinity mask (canopy gaps → god-rays, water → fireflies, basins → fog pools) | `rng.uniform(min_x, max_x)` with no mask input (BUG-140) | CRITICAL |
| Density representation | 3D density LUT (Decima Nubis) or 3D Density Mask Texture (HDRP `Local Volumetric Fog`) | N-sided cylinder mesh proxy (BUG-132 / BUG-50) | HIGH — AAA uses density textures, not mesh approximations |
| Volume primitive | OBB placed at ground level, size controlled separately from transform | 12-vert "icosphere" with `pz = r*0.5` above Z=0 | HIGH |
| Source: | https://www.guerrilla-games.com/read/the-real-time-volumetric-cloudscapes-of-horizon-zero-dawn ; https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@17.0/manual/create-a-local-fog-effect.html | — | — |

### 4.2 Erosion (hydraulic + thermal)

| Capability | AAA floor (Gaea Erosion / World Machine) | VeilBreakers today | Gap |
|---|---|---|---|
| Droplet iteration count | Gaea default ~4% Duration with C++/GPU back-end; World Machine 50k+ droplets | 200-600 iterations (pass_erosion) | IMPORTANT — gullies undercooked |
| Talus repose angle | World Machine: 30-40° default, user-exposed | `talus = 0.05` hardcoded (BUG-38) or raw 0.5 height diff (BUG-10) | HIGH (unit confusion AAA never ships) |
| Sediment removal | Gaea `Sediment Removal` parameter with mask input | Not exposed | IMPORTANT |
| Feature Scale | Gaea `Feature Scale` (meters, 50–2000 m range) | Not exposed | POLISH |
| Bias masks (Slope / Altitude) | Gaea Selective Processing — slope/altitude/custom mask driving Erosion Strength, Rock Softness, Precipitation Amount independently | `erosion_amount` is single scalar, no per-region bias | IMPORTANT |
| Deterministic mode | Gaea `Deterministic (Slow)` toggle — single-core replay | Master has `tile_parallel_safe` planned (R7) but sin-hash noise breaks cross-platform determinism (BUG-12/91) | HIGH |
| Source: | https://docs.quadspinner.com/Reference/Erosion/Erosion.html ; https://docs.quadspinner.com/Reference/Erosion/Thermal.html ; https://help.world-machine.com/topic/device-thermalerosion/ | — | — |

### 4.3 Coastal / sea

| Capability | AAA floor (Gaea Sea) | VeilBreakers today | Gap |
|---|---|---|---|
| Wave direction | Gaea `Rivers Angle` scalar; Houdini `oceanspectrum Direction` | `hints_wave_dir = 0.0` hardcoded (BUG-05) | HIGH — all coasts erode as if waves come from east |
| Coastal erosion modes | `Global` / `Surrounding`, `Edge` input mask for per-edge fill control | Single flat `sea_level` threshold | IMPORTANT |
| Shore details | `Shore Size` + `Shore Height` + `Extra Cliff Details` toggle | Not exposed | POLISH |
| Wave climate rose | Real AAA ocean sim (FH5 / GTA V): 16-bin angle+weight distribution | Not implemented | IMPORTANT |
| Source: | https://docs.quadspinner.com/Reference/Water/Sea.html | — | — |

### 4.4 Flow / D8 / water network

| Capability | AAA floor (ArcGIS Pro Flow Direction) | VeilBreakers today | Gap |
|---|---|---|---|
| D8 distance scaling | `maximum_drop = change_in_z / distance`, distance in world units (cell_size × 1 or √2) | `_D8_DISTANCES` in CELLS, no cell_size param (BUG-37) | IMPORTANT (wrong-resolution thresholds) |
| Multi-flow direction (MFD) | ArcGIS `Flow Direction` exposes MFD as first-class mode (Qin 2007) | D8 only | POLISH — D8 is acceptable AAA floor |
| Pit detection | Priority-flood (Barnes 2014) handles plateaus | Strict `< all neighbors` (BUG-63) misses ~30% of plateau pits | IMPORTANT |
| Strahler ordering | Tarboton 1997 canonical; vectorized | DFS with quadratic upstream lookup (BUG-77) | IMPORTANT (perf) |
| Source: | https://pro.arcgis.com/en/pro-app/latest/tool-reference/spatial-analyst/how-flow-direction-works.htm | — | — |

### 4.5 Vegetation / PCG / LOD

| Capability | AAA floor (Fortnite Nanite foliage + UE5 PCG) | VeilBreakers today | Gap |
|---|---|---|---|
| Procedural placement | UE5 PCG: `Get Landscape Data → Surface Sampler → Transform Points → Static Mesh Spawner` on a full DAG | Bespoke Python scatter functions per biome | IMPORTANT (not AAA architecture) |
| Density per km² | PCG Density filter, supports density-per-unit-area with actual-area scaling | BUG-103: `max_features_per_km2` treated as raw count → PRIMARY capped at 1 | IMPORTANT |
| World Partition HLOD | UE5 PCG auto-assigns actors to Data Layer + HLOD Layer | `lod_pipeline._setup_billboard_lod` stores metadata without baking (BUG-141) | HIGH |
| Octahedral impostor | Fortnite 12×12=144 sub-frames 2048² RGBA + 1024² Normal+Depth | N-sided prism + JSON `next_steps` stub (BUG-137) | BLOCKER |
| SpeedTree integration | SpeedTree Modeler + SDK + Library — 4K PBR, full season range, wind | Not present | POLISH (not always a blocker for dark-fantasy; Tripo+Blender is user's pipeline per profile) |
| Source: | https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-overview ; https://store.speedtree.com/ | — | — |

### 4.6 Cliff / chamber mesh

| Capability | AAA floor (UE5 voxel / Houdini VDB / Tripo scans) | VeilBreakers today | Gap |
|---|---|---|---|
| Chamber geometry | Marching cubes on SDF (skimage), Dual Contouring (Schaefer-Warren 2004), or hand-sculpted Megascans | 8-vertex 6-quad axis-aligned invisible box (BUG-83 / BUG-139 — TWO copies) | BLOCKER (literal F-grade rubric) |
| Cliff strata | Multi-octave noise + directional strata + overhangs + scanned Megascans | Single Gaussian-noise pass with sin mask + per-vertex Gaussian noise (speckle) | IMPORTANT |
| Face winding | CCW-outward convention (OpenGL / D3D / Vulkan) | Canyon floor CW from +Z (BUG-88), waterfall ledge front flipped (BUG-90), cliff overhang unwelded (BUG-89) | IMPORTANT (visible artifacts on default backface culling) |
| Source: | (marching cubes, R7 reference in master); https://docs.quadspinner.com/Reference/Erosion/Erosion.html for stratified rock | — | — |

---

## 5. Firecrawl evidence ledger (URLs actually scraped)

| # | URL | Purpose | Status |
|---|---|---|---|
| 1 | https://docs.quadspinner.com/Reference/Erosion/Thermal.html | Gaea Thermal erosion parameter set (Talus Angle, Stress Anisotropy, Feature Scale) — calibration for BUG-10 / BUG-38 / BUG-98 | 200 OK, content captured |
| 2 | https://docs.quadspinner.com/Reference/Erosion/Erosion.html | Gaea Erosion parameter set (Rock Softness, Strength, Downcutting, Inhibition, Base Level, Feature Scale, Bias masks) — calibration for BUG-21 / BUG-38 / §4.2 | 200 OK, content captured |
| 3 | https://docs.quadspinner.com/Reference/Water/Sea.html | Gaea Sea node (wave angle, coastal erosion, shore size) — calibration for BUG-05 / §4.3 | 200 OK |
| 4 | https://help.world-machine.com/topic/device-thermalerosion/ | World Machine Thermal Erosion (Talus Repose Angle 30-40°, Fracture Size, Talus Size) — calibration for BUG-10 / BUG-38 | 200 OK |
| 5 | https://www.guerrilla-games.com/read/the-real-time-volumetric-cloudscapes-of-horizon-zero-dawn | Horizon Zero Dawn Nubis cloudscape Schneider 2015 SIGGRAPH talk (PDF/PPT link) — calibration for BUG-11 / BUG-140 / §4.1 | 200 OK |
| 6 | https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@17.0/manual/create-a-local-fog-effect.html | Unity HDRP 17 Local Volumetric Fog — OBB placement at ground level, 3D density LUT — calibration for BUG-11 / BUG-132 / §4.1 | 200 OK |
| 7 | https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-overview | UE5 PCG framework (Get Landscape Data → Surface Sampler pattern, World Partition / HLOD auto-assignment) — calibration for BUG-103 / BUG-141 / §4.5 | 200 OK (Epic Dev Community path via docs mirror) |
| 8 | https://pro.arcgis.com/en/pro-app/latest/tool-reference/spatial-analyst/how-flow-direction-works.htm | ArcGIS D8 canonical formula `maximum_drop = change_in_z / distance` with cell_size × {1, √2} — calibration for BUG-37 / §4.4 | 200 OK |
| 9 | https://advances.realtimerendering.com/s2023/index.html | SIGGRAPH 2023 Advances in Real-Time Rendering in Games course index — broad AAA calibration baseline | 200 OK (response was large, persisted to tool-results cache) |
| 10 | https://store.speedtree.com/ | SpeedTree feature overview (Modeler / SDK / Library; Photogrammetry Conversion; 4K PBR) — calibration for BUG-137 / §4.5. Note: `/speedtree-features/` sub-page 404 during Unity migration; root landed. | 200 OK on root |

Additional references *named in the brief* that were **not productively scrapeable** (transparency):
- **https://www.gdcvault.com** — mandate honored via search (scrape API returned the slide index; found the Guerrilla 2022 HFW volumetric storm talk + HFW faces talk + RDR2 terrain walkthrough). Direct scrape of gdcvault.com/play/... requires auth; I captured the Guerrilla PDF index entry instead.
- **https://www.world-machine.com** — landed via `help.world-machine.com/topic/device-thermalerosion/` (product docs) rather than marketing root.
- **https://forums.unrealengine.com/t/fortnite-nanite-foliage/** — Epic community path returned generic docs; Fortnite 12×12 impostor AAA-floor sourced via R7 agent notes already in the master audit.
- **https://www.speedtree.com** — currently migrating to Unity.com per their notice; `/speedtree-features/` returns 404 during the transition. Root scraped.

**Total unique URLs successfully scraped: 10.** Brief required ≥8. ✓

---

## 6. Severity-realism summary for user

**If VeilBreakers shipped today with the current severity tags, what would a AAA QA team catch on day one?**

1. **Broken fog / fireflies / god-rays at z=0** (BUG-11/140) — tagged IMPORTANT in the master-doc table, should be **CRITICAL**. This is the #1 item to raise.
2. **Invisible caves** (BUG-83/139 chamber = hidden 6-face box + BUG-44 integrator unregistered + BUG-46 `may_modify_geometry=False`) — collectively BLOCKER, and the severity tags ARE adequate, but the current audit doesn't emphasize that **these four bugs together form a single "no caves ship" macro-blocker**. Flag as a cross-cutting meta-finding.
3. **Flat-plane waterfalls** (CSV Row #18 `generate_waterfall_mesh`) — tagged `critical` in severity column, correct, but the **AAA-Equivalent claim "Horizon Forbidden West waterfall / RDR2 volumetric cascade" is inflated** — current code is explicitly the failure mode flagged in the user's `feedback_waterfall_must_have_volume.md` rule.
4. **Wrong-era noise** (BUG-12/73/91 sin-hash fract) — should be HIGH not IMPORTANT; silently breaks cross-machine determinism per R7. AAA-shipping terrain never uses `fract(sin(dot(p,k))*43758.5453)` as its sole noise source.
5. **DEM import claims AAA ("GeoTIFF/SRTM") but reads neither** (BUG-67) — should be CRITICAL per user's honesty rubric.
6. **Sculpt brushes 3-line trivial** (BUG-134/135/136) — correctly CRITICAL but missing AAA-Equivalent = ZBrush/Mudbox/UE5 Landscape Sculpt.
7. **Vegetation impostor is a stub with `next_steps` JSON list** (BUG-137) — correctly BLOCKER; AAA = Fortnite 12×12 atlas, SpeedTree baker.

**The severity system overall works.** The gaps are:
- Honor the R7 upgrades — several R7 verdicts already say "upgrade to CRITICAL" (e.g. BUG-140) but the bolded `**Severity:**` field wasn't updated.
- Kill AAA-Equivalent inflation: either describe **what the code IS** (accurate) or tag aspirational targets as **Aspirational AAA target:** (distinct column).
- Downgrade BUG-45 in CSV from `critical` to `polish` to match master doc.
- Normalize BUG-83's "F" severity-field to BLOCKER (keep "F" as the rubric-grade, not severity).

---

*Agent V5 — M3 ultrathink verification wave — severity-realism lens — complete.*
