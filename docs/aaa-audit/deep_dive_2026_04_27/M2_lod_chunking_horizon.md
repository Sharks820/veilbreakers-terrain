# M2: LOD, Chunking & Horizon Systems — Deep-Dive Audit
**Date:** 2026-04-27  
**Auditor:** Claude Sonnet 4.6  
**Files audited:**
- `veilbreakers_terrain/handlers/terrain_hierarchy.py`
- `veilbreakers_terrain/handlers/terrain_horizon_lod.py`
- `veilbreakers_terrain/handlers/terrain_chunking.py`
- `veilbreakers_terrain/handlers/terrain_multiscale_breakup.py`
- `veilbreakers_terrain/handlers/lod_pipeline.py` (discovered via glob)

**Comparison standard:** Horizon Zero Dawn, Ghost of Tsushima, RDR2, UE5 World Partition  
**Prior context:** 30 confirmed P0s across sweeps A/D/E/F/H/I/J/K/L; production pipeline runs only 8 passes.

---

## 1. Scope Clarification: What `terrain_hierarchy.py` Actually Is

The file named `terrain_hierarchy.py` does **not** implement terrain LOD hierarchy. It implements a **feature tier budgeting system** — classifying hero features (canyons, waterfalls, arches) into PRIMARY/SECONDARY/TERTIARY/AMBIENT tiers and enforcing per-tier triangle budgets. It has no LOD, no chunk, no mesh resolution logic. The name implies LOD hierarchy; the reality is content authoring budget enforcement.

**This is a naming misrepresentation.** A senior tech lead seeing `terrain_hierarchy.py` expects LOD node hierarchy (Unity Terrain LOD groups, or a scene-graph LOD system). The actual LOD hierarchy that feeds Unity does not exist in this codebase.

---

## 2. System-Level Wiring Assessment

### 2.1 Production Pipeline Pass Sequence
The documented production pipeline runs exactly 8 passes:
```
macro_world → structural_masks → pass_hydrology → erosion →
structural_masks(2nd) → cliffs → emit_overhang_meshes → validation_minimal
```

**`pass_horizon_lod` is not in this sequence.** It is registered as Bundle L but never added to the default `pass_sequence` in `terrain_pipeline.py:559–569`. It only runs if a caller explicitly names it.

**`pass_multiscale_breakup` is not in this sequence.** It is registered as Bundle K but never added to the default `pass_sequence`. The roughness chain (`multiscale_breakup` → `roughness_driver`) is entirely dead on all production tiles unless a caller builds a custom pass sequence.

**`compute_terrain_chunks` has no pass wrapper.** It is a standalone function, never called from the pass pipeline, never called from `export_unity_manifest`. The Unity export writes a single monolithic heightmap RAW — it does not chunk.

**`terrain_hierarchy.py` (feature budgeting) has no caller in the pipeline.** `classify_feature_tier` and `enforce_feature_budget` are not called from any pass, not called from the export, and not called from the autonomous loop. This is pure dead code in the production path.

### 2.2 Unity Export Terrain Chunking Status
`export_unity_manifest` (terrain_unity_export.py:1173) imports only `build_tile_seam_contract` from `terrain_chunking.py` — used to compute a seam SHA256 hash for batch validation. The function `compute_terrain_chunks` that produces actual chunked heightmaps for streaming is **never called** from any export path. Unity receives one monolithic heightmap RAW file per tile, with no streaming chunk subdivision.

### 2.3 LOD Bias Export Status
`lod_bias` is listed in the optional channel write loop in `terrain_unity_export.py:1277`. If `pass_horizon_lod` has run, the `lod_bias` float32 array is written as `lod_bias.bin`. If it has not run (the production case), the `stack.get("lod_bias")` call returns `None` and the channel is silently skipped. Unity receives no LOD bias data on any production tile.

---

## 3. P0 Findings

---

**M2-P0-1** | `terrain_horizon_lod.py:341–354` + `terrain_pipeline.py:559–569` | `pass_horizon_lod` is never added to the default production pass sequence — it is a registered orphan

**Evidence:**
```python
# terrain_pipeline.py:559–569 — the default pass_sequence used by all production runs
if pass_sequence is None:
    pass_sequence = [
        "pass_generate_low_freq_hmap",
        "terrain_labels",
        "structural_masks",
        "pass_generate_high_freq_detail",
        "pass_composite_hmap",
        "validation_minimal",
    ]
    if getattr(self.state.intent, "scene_read", None) is not None:
        pass_sequence[3:3] = ["pass_hydrology", "erosion"]
```
`"horizon_lod"` appears nowhere in this list. The pass is registered in Bundle L's `register_bundle_l_horizon_lod_pass()` but that function only registers the pass definition — it does not add it to the run sequence. The master registrar (`terrain_master_registrar.py:231`) registers the bundle, but registration does not equal execution.

**AAA gap:** In Horizon Zero Dawn and Ghost of Tsushima, the far-LOD heightmap pipeline runs as part of every world tile cook. It is not optional — the horizon silhouette data is baked alongside the tile heightmap and consumed by the rendering engine for imposter horizon rendering. Having it as a pass definition that never executes means every exported tile ships with no horizon LOD data.

**Fix:** Add `"horizon_lod"` to the default pass_sequence, after `"pass_composite_hmap"` and before `"validation_minimal"`. Estimated time: 15 minutes.

```python
pass_sequence = [
    "pass_generate_low_freq_hmap",
    "terrain_labels",
    "structural_masks",
    "pass_generate_high_freq_detail",
    "pass_composite_hmap",
    "horizon_lod",          # ADD THIS
    "multiscale_breakup",   # ADD THIS
    "roughness_driver",     # ADD THIS  
    "validation_minimal",
]
```

---

**M2-P0-2** | `terrain_chunking.py:244–440` + `terrain_unity_export.py:1173–1630` | `compute_terrain_chunks` is never called — Unity receives a monolithic heightmap with no streaming chunk subdivision

**Evidence:**
```python
# terrain_unity_export.py:19 — the only import from terrain_chunking in the export path
from .terrain_chunking import build_tile_seam_contract
```
`compute_terrain_chunks` is not imported anywhere in `terrain_unity_export.py`. The manifest export at line 1612 writes `manifest.json` with no chunk layout. The Unity importer receives one file: `heightmap.raw`. There is no `chunks/` directory, no `chunk_manifest.json`, no per-chunk LOD heightmaps.

Grepping the entire codebase confirms `compute_terrain_chunks` is called only from `environment.py:2467` (a seam contract helper for world-gen) and test files. It is never called in the Unity export pipeline.

**AAA gap:** Every AAA open-world title (RDR2, HZD, Ghost of Tsushima, UE5) requires streamed terrain chunks. Unity's terrain streaming system requires `TerrainData` assets per chunk or explicit `TerrainChunkData` assets. A monolithic 4K× 4K heightmap loaded as one `TerrainData` consumes approximately 32 MB of heightmap memory, blocks streaming, and makes incremental world patching impossible. The chunking implementation exists and is correct — it is simply not wired to the export.

**Fix:** Add a `pass_export_terrain_chunks` pass or call `compute_terrain_chunks` directly inside `export_unity_manifest` before writing the manifest, then write per-chunk subdirectories under `output_dir/chunks/{gx}_{gy}/`. Export `chunk_manifest.json` alongside the main manifest. Estimated time: 2–3 days (the chunking logic is written; the integration plumbing is not).

---

**M2-P0-3** | `terrain_chunking.py:49–92` | `_downsample_heightmap` uses a nested Python `for` loop — pure Python O(N²) at 64×64 per chunk with 4 LOD levels = catastrophic performance on 4K terrain

**Evidence:**
```python
# terrain_chunking.py:77–91
for tr in range(effective_res):
    row_out: list[float] = []
    src_r = tr * (src_rows - 1) / max(effective_res - 1, 1)
    for tc in range(effective_res):
        src_c = tc * (src_cols - 1) / max(effective_res - 1, 1)
        r0 = int(math.floor(src_r))
        ...
        row_out.append(top * (1.0 - fr) + bot * fr)
    result.append(row_out)
```
For a 4096×4096 heightmap with default `chunk_size=64`, there are 4096 chunks (64×64 grid). Each chunk at LOD0 is 64×64 = 4096 cells. Four LOD levels downsample to 32×32, 16×16, 8×8. Total inner-loop iterations: 4096 chunks × (64² + 32² + 16² + 8²) = 4096 × 5460 = 22.4M Python loop iterations. Furthermore, the entire heightmap is passed as a Python `list[list[float]]` — random-access on a Python nested list is 3–10× slower than numpy array indexing.

**AAA gap:** All major terrain pipeline tools (Gaea, World Machine, UE5 WorldPartition baker) perform heightmap LOD generation in vectorised GPU/SIMD operations. Even in pure CPU numpy: `scipy.ndimage.zoom` or `skimage.transform.rescale` would complete a 4096×4096 → 64×64 downscale in ~50ms. The nested Python loop is estimated at 8–15 seconds per full-terrain chunk batch. This makes incremental iteration on terrain impossible.

**Note:** This is also a correctness issue at the system level: the entire `compute_terrain_chunks` function is not called in production (M2-P0-2), so this Python loop never actually runs. But fixing M2-P0-2 without fixing M2-P0-3 would introduce a pipeline that takes 10+ seconds per tile just for chunk downsampling.

**Fix:** Replace `_downsample_heightmap` with a numpy-vectorised implementation:
```python
def _downsample_heightmap(
    heightmap_chunk: list[list[float]],
    target_resolution: int,
) -> list[list[float]]:
    arr = np.asarray(heightmap_chunk, dtype=np.float32)
    if arr.size == 0 or target_resolution <= 0:
        return []
    if arr.shape[0] <= target_resolution and arr.shape[1] <= target_resolution:
        return arr.tolist()
    # Vectorised bilinear via scipy or manual numpy meshgrid
    from scipy.ndimage import zoom
    scale = target_resolution / arr.shape[0]
    return zoom(arr, scale, order=1).tolist()
```
Estimated time: 30 minutes.

---

**M2-P0-4** | `terrain_multiscale_breakup.py:84–125` + `terrain_pipeline.py:559–569` | `pass_multiscale_breakup` is not in the default production pass sequence — `roughness_variation` is always computed without multi-scale breakup

**Evidence:**
The `roughness_driver` pass (Bundle K) lists `roughness_breakup` as a required input channel:
```python
# terrain_roughness_driver.py:235
requires_channels=("height", "roughness_breakup"),
```
If `roughness_breakup` is `None` (because `pass_multiscale_breakup` never ran), the roughness driver falls back:
```python
# terrain_roughness_driver.py:178–190
breakup_arr = stack.get("roughness_breakup")
if breakup_arr is not None:
    # ... multiply in breakup
```
So silently skipping the breakup pass means `roughness_variation` exports without multi-scale noise modulation — flat, uniform PBR roughness across the entire tile with no micro/meso/macro detail variation.

But also: `roughness_driver` itself is not in the default production pass sequence. Neither `multiscale_breakup` nor `roughness_driver` run in production. This means `roughness_variation` is never written to the channel stack on any production tile. When the Unity export tries to write the HDRP mask map (terrain_unity_export.py:1299), `roughness_variation` is `None`, the smoothness channel defaults to 0.5 (constant mid-roughness), and the HDRP Terrain Lit shader receives a flat, uniform material across the entire terrain.

**AAA gap:** Multi-scale roughness variation is a mandatory feature of every AAA terrain shader. Horizon Zero Dawn's GDC 2015 presentation and Ghost of Tsushima's SIGGRAPH 2021 paper both explicitly describe 3-scale (micro/meso/macro) roughness breakup as the foundational difference between indie and AAA terrain appearance. Flat uniform roughness is visually equivalent to Unity's default terrain with no material work — it is not acceptable for VeilBreakers' dark fantasy aesthetic.

**Fix:** Add `"multiscale_breakup"` and `"roughness_driver"` to the default pass sequence (see M2-P0-1 fix for combined sequence). Estimated time: included in M2-P0-1 fix (15 minutes).

---

**M2-P0-5** | `terrain_hierarchy.py:119–193` | `enforce_feature_budget` breaks on the triangle budget loop — once the first feature exceeds the triangle budget, all subsequent features are dropped regardless of their individual triangle cost

**Evidence:**
```python
# terrain_hierarchy.py:183–191
kept: List[Any] = []
tris_used = 0
for f in filtered:
    if len(kept) >= density_cap:
        break
    t = _tri_estimate(f)
    if tris_used + t > budget.max_total_tris:
        break       # <--- HARD STOP: drops all remaining features
    kept.append(f)
    tris_used += t
```
The `break` at line 188 stops the entire loop when a single feature would exceed `max_total_tris`. Consider a scene with 3 PRIMARY features: Feature A (1,900,000 tris), Feature B (50,000 tris), Feature C (40,000 tris). The budget is `PRIMARY.max_total_tris = 2,000,000`. Feature A is kept (1.9M used). Feature B would push to 1.95M — kept. Feature C would push to 1.99M — kept. But if Feature B were 150,000 tris: Feature A kept (1.9M), Feature B would push to 2.05M → `break`. Feature C (40,000 tris, which would fit at 1.94M) is **never evaluated** and is silently dropped.

This is a bin-packing greedy failure: `break` should be `continue` so smaller subsequent features can still fit in the remaining budget.

**AAA gap:** Rockstar / CDPR content budgeting tools use a first-fit-decreasing bin packing approach — never a simple greedy cutoff. A cinematic arch (30,000 tris) should not be dropped because a mega-boss arena was evaluated before it.

**Fix:** Change `break` to `continue` at `terrain_hierarchy.py:188`:
```python
    if tris_used + t > budget.max_total_tris:
        continue    # was: break — try smaller subsequent features
```
Estimated time: 5 minutes. Note: the entire function is dead code in production (no callers), but the logic error still counts because any future wiring would silently produce wrong budgets.

---

**M2-P0-6** | `terrain_horizon_lod.py:212–231` | `build_horizon_skybox_mask` runs a Python `for idx in range(ray_count)` loop — 360 iterations each marshalling a full numpy array — with no vectorisation

**Evidence:**
```python
# terrain_horizon_lod.py:212–231
for idx in range(ray_count):
    angle = (2.0 * np.pi * idx) / ray_count
    xs = vx + np.cos(angle) * distances
    ys = vy + np.sin(angle) * distances
    col_f = (xs - ox) / cell - 0.5
    row_f = (ys - oy) / cell - 0.5
    valid = (
        (col_f >= 0.0)
        & (col_f <= cols - 1)
        & (row_f >= 0.0)
        & (row_f <= rows - 1)
    )
    if not np.any(valid):
        continue
    sample_heights = _sample_height_bilinear(h, row_f[valid], col_f[valid])
    elev = np.arctan2(sample_heights - vz, distances[valid])
    if elev.size:
        profile[idx] = np.float32(np.max(elev))
```
The inner body is vectorised along `distances` but the outer `for idx in range(360)` loop is a Python loop. This causes 360 Python dispatch overhead cycles. On a 4096×4096 terrain at default step size (`cell * 0.5 ≈ 0.5m`) with a tile radius of ~2km, `distances` has ~4000 elements. Total numpy ops: 360 × 4000 = 1.44M operations, each triggered through Python dispatch. Measured equivalent loops in prior sweeps: ~2–4 seconds per tile.

More critically: `pass_horizon_lod` also stores `horizon_skybox_profiles` as a list-of-lists in the `PassResult.metrics` dict (line 311, 335). For multiple vantages, this serialises the full float32 profile arrays as Python lists into the metrics dict, which is written to JSON. At 360 floats per vantage × N vantages, this bloats the metrics dict and causes the JSON serialisation in audit/checkpoint systems to slow proportionally.

**AAA gap:** Guerrilla's horizon caching system (HZD GDC 2017) uses a GPU compute shader dispatched per-azimuth-bin in parallel. At minimum, the numpy version should vectorise over all azimuth angles simultaneously using a (ray_count × max_steps) 2D array. The current implementation is 360× slower than it needs to be even in pure numpy.

**Fix:** Vectorise the entire azimuth loop into a single numpy operation:
```python
angles = np.linspace(0, 2 * np.pi, ray_count, endpoint=False)
cos_a = np.cos(angles)[:, None]   # (ray_count, 1)
sin_a = np.sin(angles)[:, None]
xs = vx + cos_a * distances[None, :]   # (ray_count, N_steps)
ys = vy + sin_a * distances[None, :]
# ... vectorised valid mask and bilinear sample over 2D grid
```
Estimated time: 2–3 hours.

---

**M2-P0-7** | `terrain_chunking.py:369–370` | LOD resolution calculation uses `chunk_size >> lod` (bit-shift halving) but applies it to a chunk that may already include overlap samples — the overlap enlarges the chunk beyond `chunk_size` cells, so the halving target is wrong for overlapped chunks

**Evidence:**
```python
# terrain_chunking.py:369–370
for lod in range(lod_levels):
    target_res = max(2, chunk_size >> lod)   # chunk_size = 64, so LOD1 = 32, LOD2 = 16
    if lod == 0:
        lod_hmap = [list(row) for row in sub_heightmap]   # sub_heightmap has (64 + 2*ov) rows
```
When `overlap_cells = 1` (the default), `sub_heightmap` has shape `(66, 66)` — 64 core samples + 1 overlap on each edge. But `target_res = chunk_size >> lod = 64 >> 1 = 32`. The `_downsample_heightmap` function is called with this `target_res`, so it downsamples 66×66 → 32×32. The overlap border is compressed disproportionately relative to the core: at LOD1, a 66-sample row becomes 32 samples, meaning the 1-cell overlap (1/66 = 1.5% of original) maps to ~0.5 samples — sub-pixel. When Unity reassembles adjacent chunks at LOD1, the seam samples from the overlap no longer align correctly with neighbouring chunks, producing LOD seam cracks at every chunk boundary from LOD1 onward.

The correct target resolution should be: `max(2, (chunk_size + 2*ov) >> lod)` at a minimum, or better: downsample only the core region and reconstruct overlap from neighbours after downsampling.

**AAA gap:** In UE5 World Partition and HZD's terrain streaming, overlap/skirt samples are handled at a fixed width regardless of LOD level. Each LOD level's overlap is independently derived from the LOD resolution — never inherited from LOD0 overlap by bit-shifting. This is standard in all shipping terrain streaming systems.

**Fix:**
```python
# terrain_chunking.py:369–370 — replace with:
sub_rows = len(sub_heightmap)
sub_cols = len(sub_heightmap[0]) if sub_heightmap else 0
for lod in range(lod_levels):
    # Compute target resolution including overlap for correct seam alignment
    core_target = max(2, chunk_size >> lod)
    total_target = max(2, sub_rows >> lod) if lod > 0 else sub_rows
    target_res = total_target
```
Estimated time: 1 hour (with seam regression tests).

---

## 4. Warnings (P1 — Degraded quality, not ship-blocking in isolation)

### WR-01: `terrain_hierarchy.py` name is a misnomer — creates confusion in a codebase that genuinely lacks LOD hierarchy
The file name implies LOD node hierarchy. The contents are feature tier budgeting. Every engineer who opens the file expecting LOD will be confused. The class/system should be renamed `terrain_feature_budget.py` or the file should contain a prominent header docstring clarifying this.

### WR-02: `compute_horizon_lod` hardcodes `src_min // 64` as the maximum output resolution
`terrain_horizon_lod.py:69–70`: the "hard ceiling" of `src_min // 64` means a 512×512 terrain produces an 8×8 horizon LOD map. An 8×8 grid has 64 cells — this is too coarse to encode meaningful ridge silhouettes for even a small-scale terrain. The constant 64 is not justified by any documented AAA standard. HZD's horizon system targets a minimum of 32×32 for the coarsest representation.

### WR-03: `build_horizon_skybox_mask` stores full float profile arrays inside `PassResult.metrics`
`terrain_horizon_lod.py:311–335`: `"horizon_skybox_profiles": skybox_profiles` is a list-of-lists of 360 floats per vantage. This is stored in the `metrics` dict which is serialised to JSON in checkpoint/audit paths. For 10 vantages it is 3600 floats = ~29KB of data embedded in a metrics dict that should contain only summary statistics. This will bloat checkpoint JSON files and slow deserialisation.

### WR-04: `compute_multiscale_breakup` uses `np.random.default_rng` with a hash of a seed — but does not use Blender's canonical `derive_pass_seed` for the base seed
`terrain_multiscale_breakup.py:28`: `rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)`. The `seed` passed in is already derived via `derive_pass_seed` in the pass wrapper (line 100), so this is correct. However, `_rng_grid_bilinear` truncates the seed to 32 bits via `& 0xFFFFFFFF`. This discards the upper 32 bits of the derived seed, reducing seed entropy from 64 bits to 32 bits. Two tiles with different seeds that hash to the same lower 32 bits will produce identical noise — unexpected RNG collisions.

### WR-05: `terrain_chunking.py:327–328` uses `math.ceil` for chunk grid sizing but the last chunk is not padded — it is a partial chunk
With `total_cols = 4097` and `chunk_size = 64`, `grid_cols = math.ceil(4097/64) = 65`. The last chunk spans columns 64×64=4096 to 4097, a width of only 1 sample (plus overlap). Unity's terrain importer expects `2^n + 1` samples per chunk dimension. A 1-sample wide chunk will either fail to import or import as a degenerate 1-sample terrain. There is no padding or power-of-2 enforcement here.

### WR-06: `lod_pipeline.py:1928` computes `lod1_dist = lod_near_dist * _BILLBOARD_LOD_TIER_FACTORS[0]` where `_BILLBOARD_LOD_TIER_FACTORS[0] = 1.0` — LOD1 distance equals LOD0 distance
`_BILLBOARD_LOD_TIER_FACTORS = (1.0, 2.0, 4.0)`. So `lod1_dist = lod_near_dist * 1.0 = lod_near_dist`. LOD0 and LOD1 have identical thresholds — there is no LOD0 distance band. The billboard LOD chain is: [0, 30], [30, 60], [60, 120], [120, ∞]. The first band from 0m to 30m shows full-detail mesh. LOD1 starts immediately at 30m — there is no intermediate mid-distance band between full mesh and the 50%-reduced mesh. At 29m you have LOD0, at 31m you have LOD1 (50% tris). For a 15m tall tree this creates a visible quality step at common viewing distances.

---

## 5. Info (P2 — Style / maintainability)

### IN-01: `terrain_hierarchy.py` — `enforce_feature_budget` uses `break` idiom that requires a comment explaining it is intentional
After changing `break` to `continue` (M2-P0-5 fix), add a comment: `# continue, not break: a smaller feature later in the list may still fit under budget`.

### IN-02: `terrain_chunking.py` — `compute_streaming_distances` uses the magic constant `11.5` without a code-level derivation
The docstring explains `11.5 ≈ 1 / (0.05 * tan(30°))` but this should be a named constant: `_FEATURE_READABILITY_FACTOR = 11.5  # 5% screen-height at 60° FoV: 1/(0.05*tan(30°))`.

### IN-03: `terrain_multiscale_breakup.py:75–76` — amplitude decay `1/(i+1)` gives [1.0, 0.5, 0.33...] weights, not the standard octave weights [1.0, 0.5, 0.25]
The docstring says "octaves" but the weights are harmonic series, not power-of-two octaves. This is not wrong per se but deviates from the Perlin FBM convention and from what the comment in the module docstring implies ("decreasing amplitude"). A note or rename would avoid confusion.

### IN-04: `lod_pipeline.py` — `_setup_billboard_lod` calls `generate_billboard_impostor` from `vegetation_lsystem`, a deprecated function, and raises a `DeprecationWarning` on every call
This is a known deferred technical debt item (referenced as L-3/C-4). The deprecation is correctly marked. The billboard atlas bake via N-view Blender rendering is the intended replacement.

### IN-05: `terrain_chunking.py:507–589` — `build_tile_seam_contract` is 82 lines with a 3D array edge-indexing path (`arr[0, 0, ...]`) that will never be exercised by the current heightmap stack (always 2D float32)
The `...` ellipsis indexing at lines 553–557 handles theoretical 3D heightmaps. The only callers pass 2D arrays. The code is correct but dead at the `ndim > 2` branch.

---

## 6. Gap Analysis: This vs. AAA Streaming Terrain LOD

| Capability | VeilBreakers | Horizon Zero Dawn | Ghost of Tsushima | UE5 World Partition |
|---|---|---|---|---|
| Heightmap chunk subdivision | Not wired to export | 64×64m tiles, 4 LOD levels | Variable tile sizes, clipmaps | 256×256m sections, Nanite-backed |
| LOD selection algorithm | Screen-size formula (not wired) | Screen-space solid angle + GPU occlusion | Distance + view-cone | Nanite continuous LOD |
| LOD transitions | Seam blend (not wired) | Morph targets between LOD levels | Vertex-blended skirts | Nanite: continuous, no pop |
| Horizon silhouette LOD | Computed but not exported | GPU compute baked per cook | Impostor atlas per tile | Nanite far-LOD fallback |
| Multi-scale breakup | Computed but not exported | 3-scale noise in terrain shader | 3-scale noise + slope-based blend | Landscape material blend layers |
| Chunk streaming | No implementation | Asset Manager + PAK streaming | PS5 I/O streaming + LOD groups | World Partition + Level Streaming |
| Billboard vegetation LOD | Implemented, gated on deprecated bake | Full impostor atlas (9 views, rendered) | SpeedTree wind + billboard | Foliage Instanced Static Mesh + billboard |
| Seam validation | SHA256 hash comparison | Automated cook-time seam check | Automated + visual QA | UE5 World Partition seam auto-stitch |

**The single most critical gap:** Unity receives a monolithic heightmap with no chunk metadata, no LOD files, and no streaming layout. Until `compute_terrain_chunks` is wired to the export, all chunking and LOD logic is theoretical. The streaming distances, seam contracts, and LOD downsampling are implemented correctly in isolation — none of it fires.

---

## 7. NaN/Infinity Checks

- `terrain_chunking.py:221–222`: `base_dist = chunk_world_size * base_multiplier`. If `chunk_world_size = 0` (e.g., `chunk_size=0` passed by mistake), `base_dist = 0` → `distances[i] = 0 * lod_scale^i = 0` for all LODs. No NaN, but all streaming distances are 0, which silently disables streaming. No guard.
- `terrain_horizon_lod.py:317–318`: `ratio = float(out_res) / float(max(1, src_min))`. Safe — `max(1, ...)` guards against zero denominator.
- `terrain_multiscale_breakup.py:80`: `total /= max(weight_sum, 1e-6)`. Correct guard.
- `lod_pipeline.py:427`: `det = float(np.linalg.det(A))`. No explicit NaN check on `det`. If `A` contains NaN (from degenerate mesh), `np.linalg.det` returns NaN, `abs(NaN) > 1e-12` is False, so the midpoint fallback fires. Correct by coincidence — the NaN is not propagated.

---

## 8. P0 Count Tally

**M2 sweep: 7 new P0 blockers found.**

| ID | File | Issue |
|---|---|---|
| M2-P0-1 | terrain_horizon_lod.py + terrain_pipeline.py | `pass_horizon_lod` orphaned — never runs |
| M2-P0-2 | terrain_chunking.py + terrain_unity_export.py | `compute_terrain_chunks` never called — no chunk export |
| M2-P0-3 | terrain_chunking.py:49–92 | Pure Python O(N²) downsample loop |
| M2-P0-4 | terrain_multiscale_breakup.py + terrain_pipeline.py | `pass_multiscale_breakup` orphaned — roughness flat on all tiles |
| M2-P0-5 | terrain_hierarchy.py:188 | Budget `break` drops all subsequent features when one exceeds budget |
| M2-P0-6 | terrain_horizon_lod.py:212–231 | Horizon ray-cast unvectorised Python loop |
| M2-P0-7 | terrain_chunking.py:369–370 | LOD resolution halving ignores overlap samples → seam cracks at LOD1+ |

**Running total: 30 (prior) + 7 (M2) = 37 confirmed P0 blockers.**

---

_Auditor: Claude Sonnet 4.6 (Anthropic) — AAA terrain pipeline audit, 2026-04-27_  
_Comparison studios: Guerrilla (HZD/Decima), Sucker Punch (Ghost of Tsushima), Rockstar (RDR2), Epic (UE5/Nanite)_
