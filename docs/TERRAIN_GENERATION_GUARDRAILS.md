# VeilBreakers Terrain Generation Guardrails

**Status: CANONICAL — LOCKED**
**Authority: Senior Technical Architect**
**Scope: All terrain generation, every agent session, every pass, every export**

This document is the law of the land for VeilBreakers terrain generation. Any code, agent, or session that contradicts this document is wrong. Fix the code, not this document. Consult the architecture team before proposing changes to this specification.

---

## Table of Contents

1. [Core Principle: The Rune Technique](#1-core-principle-the-rune-technique)
2. [The Canonical 12-Step World Generation Order](#2-the-canonical-12-step-world-generation-order)
3. [The PassDAG Contract](#3-the-passdag-contract)
4. [Hard Guardrails — Rules That Cannot Be Violated](#4-hard-guardrails--rules-that-cannot-be-violated)
5. [The Channel Dependency Chain](#5-the-channel-dependency-chain)
6. [AAA Quality Standards Per Step](#6-aaa-quality-standards-per-step)
7. [Per-Pass Quality Gates](#7-per-pass-quality-gates)
8. [The Full Channel Registry](#8-the-full-channel-registry)
9. [Unity Export Contract](#9-unity-export-contract)
10. [File and Function Reference](#10-file-and-function-reference)

---

## 1. Core Principle: The Rune Technique

Rune Skovbo Johansen's key insight, which this entire pipeline is built around:

> **Erosion must run on LOW-FREQUENCY terrain only. High-frequency detail is added AFTER erosion.**

Why: Erosion algorithms (hydraulic, thermal, analytical filter) are physically meaningful only when operating on macro landforms — ridgelines, valleys, drainage basins. Adding high-frequency noise before erosion produces noise-carved gibberish, not natural erosion patterns. Adding it after produces eroded landforms with natural surface texture on top.

The implementation consequence: `generate_world_heightmap` generates low-frequency terrain only. `erode_world_heightmap` runs on that. Detail noise is added per-tile after tile extraction. **This order is non-negotiable.**

---

## 2. The Canonical 12-Step World Generation Order

Entry point: `run_twelve_step_world_terrain()` in `veilbreakers_terrain/handlers/terrain_twelve_step.py`

Every terrain generation session MUST execute these steps in this exact order. The `sequence` list in the return value is the audit trail — it must contain all 12 step names.

### Step 1: Parse Params and Validate Intent

**Function:** Inline in `run_twelve_step_world_terrain`
**Input:** `TerrainIntentState`, `tile_grid_x`, `tile_grid_y`
**Output:** Validated scalar parameters (`tile_size`, `cell_size`, `seed`)

**Mandatory validations:**
- `tile_grid_x >= 1` and `tile_grid_y >= 1` — raise `ValueError` otherwise
- `tile_size > 0` — raise `ValueError` otherwise
- `seed` must be an explicit integer — never use Python's default `random.seed()` (PYTHONHASHSEED-randomized)

**Sequence tag:** `"1_parse_params"`

---

### Step 2: Compute World Region Bounds

**Function:** Inline in `run_twelve_step_world_terrain`
**Input:** `tile_grid_x`, `tile_grid_y`, `tile_size`, `intent.region_bounds`
**Output:** `total_samples_x`, `total_samples_y`, `world_origin_x`, `world_origin_y`

**Rule:** World heightmap dimensions are `(tile_grid_y * tile_size + 1, tile_grid_x * tile_size + 1)`. The `+1` implements the shared-edge vertex contract — adjacent tiles share their border column/row exactly, producing zero-delta seams. A world of 2x2 tiles at tile_size=128 requires a 257x257 heightmap, not 256x256.

**Sequence tag:** `"2_compute_world_region"`

---

### Step 3: Generate World Heightmap (Low-Frequency Only)

**Function:** `generate_world_heightmap()` in `veilbreakers_terrain/handlers/_terrain_world.py`
**Delegates to:** `generate_heightmap()` in `veilbreakers_terrain/handlers/_terrain_noise.py`
**Input:** World dimensions, `cell_size`, `seed`, `terrain_type="mountains"`
**Output:** `world_hmap` — `np.ndarray` of dtype `float64`, shape `(total_samples_y, total_samples_x)`, `normalize=False` (world-unit heights, not [0,1])

**AAA requirement:** Use OpenSimplex2S (not Perlin) for base noise. Multi-octave with domain warping. `terrain_type="mountains"` activates the dark-fantasy landform profile. `normalize=False` preserves world-unit heights so path-solvers (road A*, river carve) operate in real-world metric space.

**What this step MUST NOT do:** Add high-frequency detail noise. This step generates macro landform only — ridgelines, valleys, mountain mass. See Step 7 for detail.

**Sequence tag:** `"3_generate_world_heightmap"`

---

### Step 4: Apply Flatten Zones

**Function:** `_apply_flatten_zones_stub()` in `terrain_twelve_step.py`
**Delegates to:** `flatten_multiple_zones()` in `terrain_advanced.py`
**Input:** `world_hmap`, `intent.composition_hints["flatten_zones"]`
**Output:** Modified `world_hmap` with settlement/dungeon-entrance zones flattened

**Rule:** Flatten zones are applied to the raw low-frequency heightmap, before erosion. This ensures erosion integrates with the edited terrain — flattened zones develop natural drainage. Zones declared in `intent.composition_hints["flatten_zones"]` as a list of dicts with keys `center_x`, `center_y`, `radius`, optional `target_height` and `blend_width`.

**World-unit preservation:** `_apply_flatten_zones_stub` normalizes to [0,1] before calling `flatten_multiple_zones`, then denormalizes back. This is the correct call pattern — do not call `flatten_multiple_zones` directly with world-unit values.

**Sequence tag:** `"4_apply_flatten_zones"`

---

### Step 5: Apply Canyon/River Carves

**Function:** `_apply_canyon_river_carves_stub()` in `terrain_twelve_step.py`
**Delegates to:** `carve_river_path()` in `_terrain_noise.py`
**Input:** `world_hmap`, `intent.composition_hints["river_carves"]`
**Output:** Modified `world_hmap` with river/canyon channels cut

**Rule:** River carves use A* pathfinding to find downhill routes between source and destination cells. The carve happens on the LOW-FREQUENCY terrain before erosion, so that hydraulic erosion then deepens the carved channels naturally. Carve depth is specified as a fraction of normalized height range (e.g., `depth=0.05`).

**World-unit preservation:** Same normalize/denormalize wrapper as Step 4.

**Sequence tag:** `"5_apply_canyon_river_carves"`

---

### Step 6: Erode World Heightmap

**Function:** `erode_world_heightmap()` in `_terrain_world.py`
**Delegates to:** `apply_hydraulic_erosion()`, `apply_thermal_erosion()`, `apply_analytical_erosion()` from erosion backends
**Input:** `world_hmap` (post-flatten, post-carve), `erosion_params` from `compute_erosion_params_for_world_range()`
**Output:** `world_eroded` — eroded heightmap, `erosion_result` dict with `flow_map`

**Rule:** Erosion iteration counts are computed from `compute_erosion_params_for_world_range(world_hmap.max() - world_hmap.min())`. Never hardcode `hydraulic_iterations=50`. The world height range drives appropriate iteration depth.

**What erosion produces (besides the eroded heightmap):**
- `flow_map` dict with keys: `flow_direction`, `flow_accumulation`, `drainage_basins`, `num_basins`, `max_accumulation`, `resolution`
- The flow map is extracted and used in Step 7

**This is the LAST step that modifies the macro heightmap** before tile extraction. Steps after this add detail or carve features — they do not reconstruct the macro shape.

**Sequence tag:** `"6_erode_world_heightmap"`

---

### Step 7: Compute Flow Map on Eroded World

**Function:** Either extracted from `erosion_result["flow_map"]` (preferred) or `compute_flow_map(world_eroded)` from `terrain_advanced.py`
**Input:** `world_eroded`
**Output:** `world_flow` dict with `flow_direction`, `flow_accumulation`, `drainage_basins`

**Rule:** Prefer the flow map returned by `erode_world_heightmap` — it was computed on the eroded terrain during the erosion pass, not after. Only fall back to a separate `compute_flow_map` call if `erosion_result` lacks one.

**Why this matters:** Flow accumulation drives: (a) water body detection in Step 11, (b) waterfall lip detection in Step 8, (c) the `drainage` channel written per-tile, (d) drainage streaks in splatmap material weights.

**Sequence tag:** `"7_compute_flow_map"`

---

### Step 8: Detect Hero Candidates

**Functions:**
- `_detect_cliff_edges_stub(world_eroded)` — slope-threshold + connected-component labeling, returns `List[Tuple[int, int]]`
- `_detect_cave_candidates_stub(world_eroded)` — Laplacian curvature + local minima, returns `List[Tuple[int, int]]`
- `_detect_waterfall_lips_stub(world_eroded, ..., flow_accumulation=_world_flow_acc)` — delegates to `detect_waterfall_lip_candidates()` in `terrain_waterfalls.py`

**Input:** `world_eroded`, `world_flow["flow_accumulation"]`
**Output:** `cliff_candidates`, `cave_candidates`, `waterfall_lip_candidates`

**Rule:** Hero candidate detection runs on the ERODED heightmap, after road carves have been applied in Step 9. Wait — **correction**: hero detection currently runs at Step 8, BEFORE road carving at Step 9. This is the correct order: detect natural hero features on the eroded natural terrain first, then let road carving modify the heightmap without invalidating the natural hero detections. Road-adjacent cliffs found during road carving are a separate concern.

**Cliff threshold:** `slope_threshold_deg=55.0`, `min_component_size=20`, `max_components=50`.
**Cave threshold:** Laplacian mean - 1.5 * std, plus strict local-minimum cells below median.
**Waterfall lip:** `min_drainage` and `min_drop_m` configured per scene.

**Sequence tag:** `"8_detect_hero_candidates"`

---

### Step 9: Apply Road Carve to World Heightmap

**Function:** `_generate_road_mesh_specs()` in `terrain_twelve_step.py`
**Delegates to:** `generate_road_path()` in `_terrain_noise.py`
**Input:** `world_eroded`, `intent.road_waypoints`, `tile_grid_x/y`, `cell_size`, `seed`
**Output:** `road_specs` list, `world_eroded` replaced with the carved version

**This step MUST run BEFORE Step 10 (tile extraction).** Road carving grades the heightmap along the road corridor. If tile extraction happens before road carving, half the tiles will have un-graded terrain and seams will be broken at road entry/exit points. This ordering is enforced by the implementation — do not reorder.

**Road carving specification:**
- Width: `max(3, int(3.0 / cell_size))` cells
- Grade strength: `0.8`
- The `generate_road_path` A* solver uses squared slope cost `(6 * slope)^2` with 16-directional movement (AAA standard per research notes). Road carving writes `road_mask` and SDF-per-cell for scatter exclusion.

**Skip condition:** If `intent.road_waypoints` has fewer than 2 points, road carve is silently skipped and `world_eroded` is returned unchanged. This is normal — many tiles have no roads.

**Sequence tag:** `"9_apply_road_carve"`

---

### Step 10: Per-Tile Extraction

**Function:** `extract_tile()` in `_terrain_world.py`
**Input:** `world_eroded` (fully carved, detailed, eroded), `tile_grid_x/y`, `tile_size`
**Output:** `tile_stacks: Dict[Tuple[int, int], TerrainMaskStack]`, `tile_transforms: Dict[Tuple[int, int], TileTransform]`, `extracted_heights`

**Tile shape contract:** Each tile is `(tile_size + 1, tile_size + 1)`. This is the shared-edge vertex contract from Addendum 2.A.1. Adjacent tiles share their border row/column. `extract_tile` uses `row_start:row_end` and `col_start:col_end` slices that overlap by exactly one row/column between neighbors.

**TerrainMaskStack initialization:** Each tile stack is initialized with `height=tile_height`, `tile_size`, `cell_size`, `world_origin_x/y`, `tile_x/y`. The `height` channel is auto-tracked as `populated_by_pass["height"] = "__init__"`.

**High-frequency detail addition:** This is where per-tile high-frequency domain-warped detail noise is added on top of the extracted eroded low-frequency tile. This step is the correct place for it because:
1. Erosion has already shaped the macro landform
2. Each tile's detail can be computed in parallel
3. Detail noise is seeded per-tile using `derive_pass_seed(seed, "detail", tile_x, tile_y, None)` for determinism

**Sequence tag:** `"10_per_tile_extract"`

---

### Step 11: Generate Water Bodies

**Function:** `_generate_water_body_specs()` in `terrain_twelve_step.py`
**Input:** `world_eroded`, `world_flow`, `intent`, `cell_size`
**Output:** `water_specs` list of dicts describing flat water surfaces

**Algorithm:** Cells where `flow_accumulation >= 0.7 * max_accumulation` are water candidates. Surface height is the mean of water-candidate cell heights. Each water body becomes a flat mesh spec for Unity's water shader.

**Sequence tag:** `"11_generate_water_bodies"`

---

### Step 12: Validate Tile Seams (Hard Gate)

**Function:** `validate_tile_seams()` in `_terrain_world.py`
**Input:** `extracted_heights: Dict[Tuple[int, int], np.ndarray]`
**Output:** `seam_report` dict with keys `seam_ok`, `max_edge_delta`, `issues`, `tile_count`, `channel_count`

**This is a hard gate.** If `seam_report["seam_ok"]` is False, the pipeline has produced broken terrain and Unity will display visible cracks between tiles. The calling code must check this and refuse to export.

**Tolerance:** `atol=1e-6` (shared-edge vertices from the same world array must be float-identical within float64 precision).

**Sequence tag:** `"12_validate_tile_seams"`

---

### Return Value Contract

`run_twelve_step_world_terrain` returns:

```python
{
    "tile_stacks":                Dict[Tuple[int, int], TerrainMaskStack],
    "tile_transforms":            Dict[Tuple[int, int], TileTransform],
    "world_heightmap":            np.ndarray,   # world_eroded (post-road-carve)
    "world_flow_map":             dict,          # flow_direction, flow_accumulation, etc.
    "cliff_candidates":           List[Tuple[int, int]],
    "cave_candidates":            List[Tuple[int, int]],
    "waterfall_lip_candidates":   List[LipCandidate],
    "road_specs":                 List[dict],
    "water_specs":                List[dict],
    "seam_report":                dict,
    "sequence":                   List[str],     # audit trail of 12 step names
    "metadata":                   dict,          # timing, tile_grid, etc.
}
```

---

## 3. The PassDAG Contract

The PassDAG (`veilbreakers_terrain/handlers/terrain_pass_dag.py`) governs how registered passes are ordered and executed in parallel waves.

### 3.1 Registering a New Pass

Every pass that wants to participate in the DAG must be registered via:

```python
TerrainPassController.register_pass(PassDefinition(
    name="my_pass",
    func=my_pass_function,
    requires_channels=("height", "slope"),    # channels this pass READS
    produces_channels=("my_channel",),         # channels this pass WRITES
    seed_namespace="my_pass",                  # for deterministic per-pass seed
    may_modify_geometry=False,
    requires_scene_read=False,
))
```

### 3.2 Channel Declaration Rules

| Rule | Enforcement |
|------|-------------|
| Every channel a pass reads MUST be in `requires_channels` | `PassContractError` at run time if channel is unpopulated and declared |
| Every channel a pass writes MUST be in `produces_channels` | Warning logged at run time; future versions will error |
| A pass that modifies `height` MUST declare `"height"` in BOTH `requires_channels` AND `produces_channels` | Manual audit — no runtime check currently |
| No pass may write a channel not in `TerrainMaskStack._ARRAY_CHANNELS` | Silent drop on `.to_npz()` / `.from_npz()` round-trip |

### 3.3 The Canonical Pass Ordering

The topological sort of height-modifying passes MUST always produce this order:

```
macro_world → erosion → framing → stratigraphy (if present) → waterfalls (if present)
```

Any pass that produces `height` without appearing in this chain is a bug. The DAG enforces this through channel dependencies: `erosion` requires `height` (from `macro_world`), so it cannot execute before `macro_world`.

### 3.4 Currently Registered Default Passes

Registered by `register_default_passes()` in `terrain_pipeline.py`:

| Pass Name | Requires | Produces |
|-----------|----------|----------|
| `macro_world` | _(none)_ | `height` |
| `structural_masks` | `height` | `slope`, `curvature`, `concavity`, `convexity`, `ridge`, `basin`, `saliency_macro` |
| `erosion` | `height` | `height`, `erosion_amount`, `deposition_amount`, `wetness`, `drainage`, `bank_instability`, `talus`, `ridge` |
| `validation_minimal` | `height`, `slope` | _(none — read-only validator)_ |
| `delta_integrator` | _(registered via `register_integrator_pass`)_ | Various delta channels |

### 3.5 PassDAG Wave Assignment

The DAG groups passes into waves where every pass in a wave can run concurrently:

```python
# Wave 0: passes with no dependencies
macro_world

# Wave 1: passes that only depend on Wave 0 outputs
structural_masks, erosion

# Wave 2: passes that depend on Wave 1 outputs
validation_minimal  # requires height (wave 0) + slope (wave 1)
```

Within a wave, workers receive a `deepcopy` of the pipeline state, execute their pass, and the DAG merges declared `produces_channels` back in deterministic name order. This means parallel passes must not share output channels — a channel may have exactly one producer per wave.

### 3.6 Adding a New Channel

1. Add the field to `TerrainMaskStack` as `Optional[np.ndarray] = None`
2. Add the channel name to `TerrainMaskStack._ARRAY_CHANNELS` tuple
3. Create or update a `PassDefinition` with that channel in `produces_channels`
4. Register the pass
5. If Unity needs this channel, add it to `TerrainMaskStack.UNITY_EXPORT_CHANNELS`

**Do all five steps atomically.** A channel that exists on the stack but has no producer pass cannot be populated by the pipeline. A channel in `UNITY_EXPORT_CHANNELS` that is not in `_ARRAY_CHANNELS` will be silently skipped in `.to_npz()` / `.from_npz()`.

### 3.7 PassDefinition Behavioral Flags

| Flag | Default | Meaning |
|------|---------|---------|
| `may_modify_geometry` | `False` | Pass emits Blender geometry mutations |
| `may_add_geometry` | `False` | Pass creates new geometry objects |
| `respects_protected_zones` | `True` | Pass is blocked from protected zones |
| `supports_region_scope` | `True` | Pass can operate on a sub-region BBox |
| `requires_scene_read` | `False` | `TerrainSceneRead` must exist on intent |
| `idempotent` | `True` | Re-running produces same result |
| `deterministic` | `True` | Seed-controlled, reproducible |

`structural_masks` sets `supports_region_scope=False` because slope, curvature, and basin are global tile properties. You cannot compute them for a sub-region and get meaningful results — the entire tile must be processed.

---

## 4. Hard Guardrails — Rules That Cannot Be Violated

These are unconditional. No argument about performance, convenience, or "it's just a test" overrides them.

### GUARDRAIL-01: No Scatter/Vegetation Before Structural Masks and Slope

```
FORBIDDEN: Run scatter/vegetation pass before structural_masks pass
REASON: Scatter placement uses slope for exclusion, ridge for placement priority,
        and saliency_macro for density modulation. None of these exist before
        structural_masks runs.
DETECTION: Check populated_by_pass — scatter pass must not appear before
           structural_masks pass in pass_history.
```

### GUARDRAIL-02: No Road Carving After Tile Extraction

```
FORBIDDEN: Modify world heightmap after extract_tile() has been called
REASON: Tile extraction copies regions of world_eroded. Any modification after
        extraction produces tiles that disagree with the world heightmap.
        Seam validation (Step 12) will fail or pass incorrectly.
ENFORCEMENT: In run_twelve_step_world_terrain, road carve is Step 9,
             extract_tile is Step 10. Maintain this sequence.
```

### GUARDRAIL-03: No Splatmap Computation Before Erosion

```
FORBIDDEN: Compute splatmap_weights_layer before erosion pass has run
REASON: Erosion produces ridge (refined), wetness, drainage, and talus.
        AAA splatmaps require:
          - ridge channel for material streaks (rock veining down slopes)
          - wetness channel for water saturation blending
          - drainage channel for bank-material classification
          - talus channel for scree/gravel at slope bases
        Without these, splatmap is structurally blind.
DETECTION: populated_by_pass["splatmap_weights_layer"] timestamp must
           be after populated_by_pass["erosion_amount"].
```

### GUARDRAIL-04: No Unity Export Until All Required Channels Populated

```
FORBIDDEN: Call unity_export_manifest() or write .raw/.npz if any
           UNITY_EXPORT_CHANNELS member that was requested is None
REQUIRED CHANNELS for export:
  - height                  (always required)
  - heightmap_raw_u16       (required for Unity terrain import)
  - terrain_normals         (required for Unity lighting)
  - splatmap_weights_layer  (required for MicroSplat)
  - navmesh_area_id         (required for Unity NavMesh bake)
OPTIONAL CHANNELS (export proceeds without them, with warnings):
  - wind_field, cloud_shadow, traversability, gameplay_zone,
    audio_reverb_class, foam, mist, wet_rock, tidal,
    ambient_occlusion_bake, lod_bias, tree_instance_points
ENFORCEMENT: Assert all required channels are non-None before
             calling unity_export_manifest().
```

### GUARDRAIL-05: No Terrain Generation Without Seeded RNG

```
FORBIDDEN: Any random operation that uses Python built-in random()
           without explicit seed, or numpy RNG without seed
REASON: Determinism. Given the same TerrainIntentState.seed, every
        generation of the same tile must produce bit-identical output.
        This is required for: checkpoint/rollback, multi-tile seam
        guarantee, reproducible artist iteration.
ENFORCEMENT: Always derive pass-local seed via:
    derive_pass_seed(intent.seed, seed_namespace, tile_x, tile_y, region)
    in terrain_pipeline.py. This function uses SHA-256 — not Python's
    PYTHONHASHSEED-randomized hash().
```

### GUARDRAIL-06: Priority-Flood Before Flow Direction Routing

```
FORBIDDEN: Compute flow_direction or flow_accumulation on a heightmap
           that has not had depression-filling applied
REASON: The D8 flow-direction algorithm routes flow downhill. Flat regions
        and enclosed depressions cause flow to terminate (infinite sinks).
        Priority-Flood (or an equivalent depression-filling algorithm)
        guarantees every cell has a downhill path to the domain boundary,
        making flow_accumulation globally consistent.
IMPLEMENTATION: erode_world_heightmap calls compute_flow_map (terrain_advanced.py)
                after erosion; that function is responsible for ensuring
                depressions are resolved before D8 routing.
```

### GUARDRAIL-07: Erosion on Low-Frequency Terrain Only (The Rune Technique)

```
FORBIDDEN: Add high-frequency domain-warped detail noise before calling
           erode_world_heightmap()
FORBIDDEN: Add high-frequency noise to generate_world_heightmap output
           before Step 6 (erosion)
CORRECT ORDER:
  Step 3: generate low-frequency world heightmap
  Steps 4-5: structural edits (flatten, carve) — still low-frequency
  Step 6: erode the low-frequency terrain
  Step 10: extract tiles, THEN add per-tile high-frequency detail
ENFORCEMENT: generate_world_heightmap uses terrain_type="mountains" which
             produces multi-octave low-frequency OpenSimplex2S. High-frequency
             detail is a separate noise pass applied after extraction.
```

### GUARDRAIL-08: Seam Validation Is a Hard Gate on Export

```
FORBIDDEN: Export any tile data if seam_report["seam_ok"] is False
REASON: Unity will display visible Z-fighting cracks at tile boundaries.
        This is not a soft warning — it is a rendering defect.
ENFORCEMENT: seam_report is returned by run_twelve_step_world_terrain.
             Callers must check seam_ok before proceeding to any Unity export.
             atol=1e-6 is the tolerance; float64 arithmetic from the same
             source array guarantees this is achievable.
```

### GUARDRAIL-09: Height Channel Must Be C-Contiguous After Each Height-Modifying Pass

```
FORBIDDEN: A height-modifying pass that returns a Fortran-order or non-contiguous
           numpy array in the height channel
REASON: Unity .raw import requires row-major byte order. scipy/numpy operations
        (gradients, erosion kernels) assume C-contiguous arrays. Mismatched
        memory layout causes silent corruption.
ENFORCEMENT: TerrainMaskStack.set() calls np.ascontiguousarray() on all channel
             values. Direct setattr bypasses this — never set channels via direct
             attribute assignment on a live stack.
```

### GUARDRAIL-10: No Pass May Write Channels Not in _ARRAY_CHANNELS

```
FORBIDDEN: Writing a channel via stack.set() where the channel name is
           not a field on TerrainMaskStack
REASON: Unknown channels are silently dropped on .to_npz() and .from_npz()
        round-trips. The channel data is lost on checkpoint/reload without error.
DETECTION: TerrainMaskStack.set() raises AttributeError for unknown channels.
RULE: Before a pass is merged, terrain_pass_dag._merge_pass_outputs logs a
      WARNING for any channel written but not declared in produces_channels.
      Treat this warning as an error.
```

---

## 5. The Channel Dependency Chain

```
                    TerrainIntentState.seed
                            │
                            ▼
                    ┌───────────────┐
                    │  macro_world  │  Step 3 — generate_world_heightmap()
                    │               │  OpenSimplex2S, low-freq only
                    └──────┬────────┘
                           │ height (raw low-freq)
                           │
                    ┌──────┴────────┐
                    │  flatten +    │  Steps 4-5 — structural edits
                    │  river carve  │  still low-frequency
                    └──────┬────────┘
                           │ height (edited low-freq)
                           │
                    ┌──────┴────────┐
                    │    erosion    │  Step 6 — erode_world_heightmap()
                    └──┬───┬───┬───┘
                       │   │   │
              ┌────────┘   │   └─────────────────┐
              │            │                     │
              ▼            ▼                     ▼
           height       wetness               drainage
        (eroded)      (saturation)          (accumulation)
              │            │                     │
              │    ┌───────┴───┐         ┌───────┴────────┐
              │    │  material │         │ flow_direction  │
              │    │  streaks  │         │ routing         │
              │    └───────────┘         └───────┬─────────┘
              │                                  │
              ▼                                  ▼
    ┌──────────────────┐              ┌───────────────────┐
    │  structural_masks│              │  water_surface     │
    │  (full-tile)     │              │  foam, mist, tidal │
    └──┬───┬───┬───────┘              └───────────────────┘
       │   │   │
  slope│   │   │ridge (refined by erosion)
       │   │   │
       │   │   └──────────────────────┐
       │   │                          │
       ▼   ▼                          ▼
  scatter  curvature/         splatmap_weights_layer
  exclusion concavity/           (MicroSplat input)
  (slope    convexity              Brucks height-blend
   gate)                           ridge drainage streaks
                                   snow normal.z factor
       │
       ▼
  road_mask ──────────────────► scatter_exclusion (SDF)
  (Step 9, pre-extraction)

       │
       ▼
  detail_density ──────────────► vegetation_placement
  (per-tile, post-extraction)     (large-to-small priority)
```

### Channel Producers Summary

| Channel | Producer Pass | Step |
|---------|---------------|------|
| `height` (initial) | `macro_world` | 3 |
| `height` (eroded) | `erosion` | 6 |
| `slope` | `structural_masks` | post-extraction |
| `curvature` | `structural_masks` | post-extraction |
| `concavity` | `structural_masks` | post-extraction |
| `convexity` | `structural_masks` | post-extraction |
| `ridge` | `structural_masks` + `erosion` (overwrite) | post-extraction |
| `basin` | `structural_masks` | post-extraction |
| `saliency_macro` | `structural_masks` | post-extraction |
| `erosion_amount` | `erosion` | post-extraction |
| `deposition_amount` | `erosion` | post-extraction |
| `wetness` | `erosion` | post-extraction |
| `drainage` | `erosion` | post-extraction |
| `bank_instability` | `erosion` | post-extraction |
| `talus` | `erosion` | post-extraction |
| `flow_direction` | water routing pass | post-extraction |
| `flow_accumulation` | water routing pass | post-extraction |
| `water_surface` | water body pass | post-extraction |
| `foam`, `mist`, `wet_rock`, `tidal` | water detail pass | post-extraction |
| `splatmap_weights_layer` | material/splatmap pass | after erosion + structural_masks |
| `heightmap_raw_u16` | Unity export pass | final |
| `terrain_normals` | Unity export pass | final |
| `navmesh_area_id` | navmesh pass | post-extraction |
| `wind_field` | ecosystem pass | post-extraction |
| `traversability` | navmesh/ecosystem pass | post-extraction |

---

## 6. AAA Quality Standards Per Step

These are not suggestions. Outputs that do not meet these standards are not AAA quality.

### 6.1 World Heightmap (Step 3)

| Requirement | Standard |
|-------------|----------|
| Noise algorithm | OpenSimplex2S — NOT Perlin, NOT value noise |
| Octave structure | Minimum 4 octaves: macro (low lacunarity), mid-freq, fine, micro-detail |
| Domain warping | Applied to macro octaves only (high-freq domain warping produces mud) |
| Coordinate space | World-space meters (`normalize=False`), `scale=100.0` default |
| Terrain character | `terrain_type="mountains"` for VeilBreakers dark fantasy profile |
| Output type | `np.float64` (required for erosion numerical stability) |
| Determinism | SHA-256 seed derivation, not Python `hash()` |

### 6.2 Erosion (Step 6)

| Requirement | Standard |
|-------------|----------|
| Algorithm | Hydraulic erosion (particle or grid), plus analytical erosion filter (`apply_analytical_erosion` from `terrain_erosion_filter.py`) |
| Iteration count | Computed from world height range via `compute_erosion_params_for_world_range()` — never hardcoded |
| Input | Low-frequency heightmap ONLY — see GUARDRAIL-07 |
| Outputs | `height` (modified), `wetness`, `drainage`, `erosion_amount`, `deposition_amount`, `talus`, `bank_instability`, `ridge` (overwrite), plus `flow_map` dict |
| AAA signature | Ridgelines should show differential erosion (softer below ridge, sharper at ridge). Valleys should have fluvial V-profiles, not circular bowls |

### 6.3 Structural Masks (post-extraction)

| Channel | AAA Standard |
|---------|-------------|
| `slope` | Gradient magnitude in radians. Zero at flat terrain, pi/2 at vertical cliff |
| `curvature` | Mean curvature (Laplacian of height). Negative = concave (valleys). Positive = convex (ridges) |
| `concavity` | Profile curvature (curvature along steepest descent) — drives erosion concentration |
| `convexity` | Plan curvature (curvature across contour) — drives lateral dispersion |
| `ridge` | Topographic wetness index / ridge detection. Overwritten by erosion pass with physics-derived ridge |
| `basin` | Drainage basin membership from Priority-Flood |
| `saliency_macro` | Visual saliency — high at hero features (cliffs, peaks), low at flat ground |

### 6.4 Splatmap (post-erosion + structural_masks)

The splatmap drives MicroSplat's per-vertex layer blending in Unity. It must be generator-label-driven (structural reasoning), not analytical threshold classification.

| Requirement | Standard |
|-------------|----------|
| Layer assignment method | Generator-label driven: each cell's primary label comes from structural analysis, not slope > threshold |
| Height blending | Brucks height-blend algorithm: blend layers weighted by (height_channel_i + blend_noise) rather than linear interpolation |
| Ridge drainage streaks | `ridge` channel drives vertical material streaks — dark rock veining, mineral deposits — down slopes |
| Wetness integration | `wetness` channel modifies saturation: wet cells blend toward wet-rock, moss, dark gravel |
| Snow factor | `snow_line_factor` modulated by `terrain_normals.z` — north-facing cells (low normal.z in Z-up space) accumulate snow above snow line |
| No single-material dominance | No material layer may dominate > 80% of a tile (enforced by QualityGate) |
| Output shape | `(H, W, L)` where L = number of MicroSplat layers |

### 6.5 Roads (Step 9)

| Requirement | Standard |
|-------------|----------|
| Pathfinding | A* with squared slope cost: `cost(edge) = 1 + (6 * slope)^2` |
| Movement directions | 16-directional (8 cardinal + 8 diagonal at 22.5° increments) |
| Carving zones | 3-zone: inner lane (full grade), shoulder/slope zone (partial grade), splat zone (material override to road material) |
| SDF storage | Signed distance field stored per cell for scatter exclusion — scatter queries SDF, not road_mask name-string |
| Grade smoothing | Spline smoothing of A* path before heightmap carving |
| Output channels | `road_mask` (binary), road SDF (float, negative inside road, positive outside) |

### 6.6 Scatter/Vegetation

| Requirement | Standard |
|-------------|----------|
| Placement driver | `detail_density` channel (per-type float maps) — NOT hardcoded density rules by biome name |
| Placement order | Large objects first (trees, boulders), then medium (shrubs, rocks), then small (grass, debris) — prevents small objects spawning under large ones |
| Exclusion method | SDF query against road SDF and hero_exclusion channel — NOT name-string comparison ("is this near a road object?") |
| Wind awareness | `wind_field` channel drives wind-bend vertex shader weight (stored as tree_instance_points attribute) |
| Slope gating | Uses `slope` channel — no scatter on cells where `slope > max_scatter_slope` |
| Cliff exclusion | Uses `cliff_candidate` channel — no scatter on cliff cells |

### 6.7 LOD

| Requirement | Standard |
|-------------|----------|
| Chunk resolution | Variable — `lod_bias` channel per cell drives Unity LOD group selection |
| Seam hiding | Skirt meshes at tile edges with 1-cell overlap — not visible gaps |
| Streaming | `lod_bias` channel written to `TerrainMaskStack` for Unity Addressables streaming priority |

---

## 7. Per-Pass Quality Gates

Quality gates are defined on `PassDefinition.quality_gate` as `QualityGate` instances. A `QualityGate.check(result, mask_stack)` callable runs after every successful pass. Hard issues downgrade the pass to `"failed"`. Soft issues downgrade to `"warning"`.

### Required Quality Gates (Must Exist — Write Them If Missing)

| Pass | Gate | Hard Failure Condition |
|------|------|----------------------|
| `erosion` | `erosion_wetness_coverage` | `wetness` channel populated in < 5% of cells |
| `erosion` | `erosion_drainage_nonzero` | `drainage` channel is all-zero |
| `structural_masks` | `slope_range_valid` | `slope.max() < 0.01` (flat tile with no slope data) |
| `structural_masks` | `ridge_nondegenerate` | `ridge` is None or all-zero |
| `splatmap` | `no_single_layer_dominance` | Any single MicroSplat layer covers > 80% of tile |
| `splatmap` | `all_layers_present` | `splatmap_weights_layer` has fewer layers than the declared MicroSplat layer count |
| `tile_extraction` | `seam_validity` | `seam_report["seam_ok"]` is False |
| Any height-modifying pass | `no_nan_inf` | `np.any(np.isnan(height))` or `np.any(np.isinf(height))` |
| Any height-modifying pass | `height_contiguous` | `not height.flags["C_CONTIGUOUS"]` |

### Gate Execution Rules

1. Gates run after pass function returns, before checkpoint is written
2. If gate function itself raises an exception, it emits a hard `ValidationIssue` with code `GATE_{NAME}_CRASHED` — gate crashes are never silently swallowed
3. `QualityGate(blocking=False)` converts all hard issues to warnings — use only for informational gates
4. Gates declared on `validation_minimal` pass are read-only: they may not write channels

### Topological Sort Determinism

The DAG's `topological_order()` uses depth-first search starting from `sorted(self._passes.keys())`. The sort is alphabetical, which is stable. Any two runs with the same set of registered passes produce the same topological order. This is a hard requirement — if you see non-deterministic pass ordering, it means you have a cycle or are registering passes in side-effect-dependent order.

---

## 8. The Full Channel Registry

All channels that exist in `TerrainMaskStack._ARRAY_CHANNELS` as of the current codebase. Every channel name listed here is valid for `stack.set()`, `stack.get()`, and `.to_npz()`. Channels not in this list will raise `AttributeError` in `stack.set()`.

### Height and Structure

| Channel | Type | Shape | Producer Pass |
|---------|------|-------|---------------|
| `height` | `float64` | `(H, W)` | `macro_world`, `erosion` |
| `slope` | `float64` | `(H, W)` | `structural_masks` |
| `curvature` | `float64` | `(H, W)` | `structural_masks` |
| `concavity` | `float64` | `(H, W)` | `structural_masks` |
| `convexity` | `float64` | `(H, W)` | `structural_masks` |
| `ridge` | `float64` | `(H, W)` | `structural_masks`, `erosion` (overwrite) |
| `basin` | `float64` or `int32` | `(H, W)` | `structural_masks` |
| `saliency_macro` | `float64` | `(H, W)` | `structural_masks` |

### Hero Candidates

| Channel | Type | Shape | Producer Pass |
|---------|------|-------|---------------|
| `cliff_candidate` | `bool` | `(H, W)` | hero detection |
| `cave_candidate` | `bool` | `(H, W)` | hero detection |
| `cave_height_delta` | `float64` | `(H, W)` | cave generation |
| `waterfall_lip_candidate` | `bool` | `(H, W)` | waterfall detection |
| `waterfall_pool_delta` | `float64` | `(H, W)` | waterfall generation |
| `hero_exclusion` | `float64` | `(H, W)` | hero placement |

### Erosion-Derived

| Channel | Type | Shape | Producer Pass |
|---------|------|-------|---------------|
| `erosion_amount` | `float64` | `(H, W)` | `erosion` |
| `deposition_amount` | `float64` | `(H, W)` | `erosion` |
| `wetness` | `float64` | `(H, W)` | `erosion` |
| `talus` | `float64` | `(H, W)` | `erosion` |
| `drainage` | `float64` | `(H, W)` | `erosion` |
| `bank_instability` | `float64` | `(H, W)` | `erosion` |
| `sediment_accumulation_at_base` | `float64` | `(H, W)` | erosion supplement |
| `pool_deepening_delta` | `float64` | `(H, W)` | erosion supplement |

### Water and Hydrology

| Channel | Type | Shape | Producer Pass |
|---------|------|-------|---------------|
| `flow_direction` | `int32` | `(H, W)` | water routing |
| `flow_accumulation` | `float64` | `(H, W)` | water routing |
| `water_surface` | `float64` | `(H, W)` | water body |
| `foam` | `float64` | `(H, W)` | water detail |
| `mist` | `float64` | `(H, W)` | water detail |
| `wet_rock` | `float64` | `(H, W)` | water detail |
| `tidal` | `float64` | `(H, W)` | water detail |

### Materials and Ecosystem

| Channel | Type | Shape | Producer Pass |
|---------|------|-------|---------------|
| `biome_id` | `int32` | `(H, W)` | biome assignment |
| `material_weights` | `float64` | `(H, W, M)` | material pass |
| `roughness_variation` | `float64` | `(H, W)` | material pass |
| `macro_color` | `float64` | `(H, W, 3)` | material pass |
| `audio_reverb_class` | `int32` | `(H, W)` | ecosystem pass |
| `gameplay_zone` | `int32` | `(H, W)` | gameplay pass |
| `wind_field` | `float64` | `(H, W, 2)` | ecosystem pass |
| `cloud_shadow` | `float64` | `(H, W)` | sky pass |
| `traversability` | `float64` | `(H, W)` | navmesh pass |

### Geology (Bundle I)

| Channel | Type | Shape | Producer Pass |
|---------|------|-------|---------------|
| `strata_orientation` | `float64` | `(H, W)` | geology pass |
| `rock_hardness` | `float64` | `(H, W)` | geology pass |
| `snow_line_factor` | `float64` | `(H, W)` | climate pass |

### Delta Integrator (Phase 51–52)

| Channel | Type | Shape | Producer Pass |
|---------|------|-------|---------------|
| `strat_erosion_delta` | `float64` | `(H, W)` | delta integrator |
| `sediment_height` | `float64` | `(H, W)` | delta integrator |
| `bedrock_height` | `float64` | `(H, W)` | delta integrator |
| `coastline_delta` | `float64` | `(H, W)` | coastline pass |
| `karst_delta` | `float64` | `(H, W)` | karst pass |
| `wind_erosion_delta` | `float64` | `(H, W)` | wind erosion pass |
| `glacial_delta` | `float64` | `(H, W)` | glacial pass |

### Unity-Ready

| Channel | Type | Shape | Producer Pass |
|---------|------|-------|---------------|
| `splatmap_weights_layer` | `float32` | `(H, W, L)` | splatmap pass |
| `heightmap_raw_u16` | `uint16` | `(H, W)` | Unity export pass |
| `terrain_normals` | `float32` | `(H, W, 3)` Y-up | Unity export pass |
| `navmesh_area_id` | `int32` | `(H, W)` | navmesh pass |
| `physics_collider_mask` | `int32` | `(H, W)` | physics pass |
| `lightmap_uv_chart_id` | `int32` | `(H, W)` | lightmap pass |
| `lod_bias` | `float32` | `(H, W)` | LOD pass |
| `tree_instance_points` | `float32` | `(N, 5)` | scatter pass |
| `ambient_occlusion_bake` | `float32` | `(H, W)` | AO pass |

### Dict Channels (not in _ARRAY_CHANNELS, but on TerrainMaskStack)

These are not scalar ndarrays — they are `Dict[str, np.ndarray]` and require special handling in `.to_npz()`:

| Channel | Type | Producer Pass |
|---------|------|---------------|
| `wildlife_affinity` | `Dict[str, (H,W) float32]` | ecosystem pass |
| `decal_density` | `Dict[str, (H,W) float32]` | decal pass |
| `detail_density` | `Dict[str, (H,W) float32]` | scatter pass |

---

## 9. Unity Export Contract

### 9.1 UNITY_EXPORT_CHANNELS

The following channels are included in `unity_export_manifest()` when populated:

```python
UNITY_EXPORT_CHANNELS = (
    "height",
    "splatmap_weights_layer",
    "heightmap_raw_u16",
    "terrain_normals",
    "navmesh_area_id",
    "physics_collider_mask",
    "lightmap_uv_chart_id",
    "lod_bias",
    "tree_instance_points",
    "ambient_occlusion_bake",
    "wind_field",
    "cloud_shadow",
    "traversability",
    "gameplay_zone",
    "audio_reverb_class",
    "foam",
    "mist",
    "wet_rock",
    "tidal",
)
```

Adding a channel to this tuple is a Unity-side contract change. The Unity-side importer must also be updated.

### 9.2 Height Range Metadata

Unity terrain import requires `height_min_m` and `height_max_m` to compute the 16-bit quantization scale. These are set automatically at `TerrainMaskStack` construction time from the initial height array. If erosion or any other pass changes the height range significantly, the pass must update `height_min_m` and `height_max_m` on the stack.

Formula for `heightmap_raw_u16`:
```python
normalized = (height - height_min_m) / (height_max_m - height_min_m)
heightmap_raw_u16 = (normalized * 65535).astype(np.uint16)
```

### 9.3 Coordinate System

`TerrainMaskStack.coordinate_system = "z-up"` is the pipeline convention end-to-end. Unity is Y-up. The conversion happens at Unity-side import, not in the Python pipeline. `terrain_normals` is written as Y-up vectors (as declared in the field docstring) — this is the one exception where the Python side writes Unity-space data.

### 9.4 Tile Size Contract

Unity terrain requires power-of-2+1 heightmap dimensions: 129, 257, 513, 1025, 2049. The tile extraction produces `(tile_size + 1, tile_size + 1)` shape, so `tile_size` must be a power of 2 (128, 256, 512, 1024, 2048). This is not enforced in code today — it is an authoring responsibility. `TerrainIntentState.tile_size` should always be power-of-2.

---

## 10. File and Function Reference

### Core Modules

| Module | Purpose |
|--------|---------|
| `terrain_semantics.py` | All data contracts: `TerrainMaskStack`, `PassDefinition`, `TerrainIntentState`, `TerrainPipelineState`, `PassResult`, `QualityGate`, all exceptions |
| `terrain_pipeline.py` | `TerrainPassController`, `derive_pass_seed`, `register_default_passes` |
| `terrain_pass_dag.py` | `PassDAG`, parallel wave scheduler, `_merge_pass_outputs` |
| `terrain_twelve_step.py` | `run_twelve_step_world_terrain` — canonical 12-step orchestration |
| `_terrain_world.py` | `generate_world_heightmap`, `extract_tile`, `validate_tile_seams`, `erode_world_heightmap`, `world_region_dimensions`, Bundle A pass functions |
| `_terrain_noise.py` | `generate_heightmap` (OpenSimplex2S), `carve_river_path`, `generate_road_path` |
| `_terrain_erosion.py` | `apply_hydraulic_erosion`, `apply_thermal_erosion`, `ErosionConfig` |
| `terrain_erosion_filter.py` | `apply_analytical_erosion` (Rune's analytical erosion filter) |
| `terrain_advanced.py` | `compute_flow_map`, `flatten_multiple_zones` |
| `terrain_world_math.py` | `TileTransform`, `compute_erosion_params_for_world_range` |
| `terrain_waterfalls.py` | `detect_waterfall_lip_candidates` |
| `road_network.py` | `compute_mst_edges`, road routing, bridge detection, `handle_compute_road_network` |
| `__init__.py` | `COMMAND_HANDLERS` dispatch table, `register_all()` |
| `terrain_master_registrar.py` | `register_all_terrain_passes()` — full pass registration for runtime |

### Key Functions

| Function | File | Purpose |
|----------|------|---------|
| `run_twelve_step_world_terrain(intent, tx, ty)` | `terrain_twelve_step.py` | The ONE entry point for world terrain generation |
| `derive_pass_seed(intent_seed, namespace, tx, ty, region)` | `terrain_pipeline.py` | SHA-256 seed derivation — always use this |
| `TerrainPassController.register_pass(PassDefinition)` | `terrain_pipeline.py` | Register a new pass |
| `TerrainPassController.run_pass(name, region)` | `terrain_pipeline.py` | Run single pass with all enforcement |
| `PassDAG.execute_parallel(controller)` | `terrain_pass_dag.py` | Run full DAG in parallel waves |
| `TerrainMaskStack.set(channel, value, pass_name)` | `terrain_semantics.py` | Write channel with provenance — always use this, never direct setattr |
| `TerrainMaskStack.assert_channels_present(channels)` | `terrain_semantics.py` | Assert channels populated before export |
| `validate_tile_seams(tiles, atol=1e-6)` | `_terrain_world.py` | Step 12 seam gate |
| `extract_tile(world_hmap, tx, ty, tile_size)` | `_terrain_world.py` | Step 10 tile extraction — shared-edge vertex contract |
| `erode_world_heightmap(hmap, ...)` | `_terrain_world.py` | Step 6 erosion with integrated flow computation |

### Exception Types

| Exception | Raised When |
|-----------|-------------|
| `SceneReadRequired` | Mutating pass runs without `TerrainSceneRead` on intent |
| `ProtectedZoneViolation` | Pass attempts to fully overwrite a protected zone |
| `PassContractError` | Pass declared channel not populated after run; pass returned non-`PassResult` |
| `UnknownPassError` | `get_pass()` called with unregistered pass name |
| `PassDAGError` | Cycle detected in dependency graph; unknown pass in DAG construction |

---

## Appendix A: Common Anti-Patterns

These patterns appear repeatedly in buggy agent sessions. Do not implement them.

### Anti-Pattern 1: Erosion After Detail Addition

```python
# WRONG
hmap = generate_world_heightmap(...)
hmap = add_detail_noise(hmap)    # <-- adds high-freq
hmap = erode_world_heightmap(hmap)  # <-- now eroding noise, not landform
```

```python
# CORRECT (Rune Technique)
hmap = generate_world_heightmap(...)
hmap = erode_world_heightmap(hmap)  # erode low-freq only
# per-tile: tile_hmap += generate_detail_noise(tile_x, tile_y, seed)
```

### Anti-Pattern 2: Scatter Before Structural Masks

```python
# WRONG — slope is None, scatter falls through to all cells
result = controller.run_pass("scatter")  # GUARDRAIL-01 violation
```

```python
# CORRECT
controller.run_pass("structural_masks")  # slope, ridge, basin populated
controller.run_pass("scatter")           # now slope is available
```

### Anti-Pattern 3: Road Carve After Tile Extraction

```python
# WRONG — tiles already extracted from un-carved terrain
tiles = extract_tiles(world_eroded, ...)
world_eroded = carve_roads(world_eroded, ...)  # tiles are stale
```

```python
# CORRECT (enforced by Step 9 → Step 10 ordering)
world_eroded = carve_roads(world_eroded, ...)  # Step 9
tiles = extract_tiles(world_eroded, ...)        # Step 10
```

### Anti-Pattern 4: Direct Channel Setattr

```python
# WRONG — bypasses np.ascontiguousarray, bypasses provenance tracking
stack.height = my_array

# CORRECT — uses TerrainMaskStack.set() with provenance
stack.set("height", my_array, pass_name="my_pass")
```

### Anti-Pattern 5: Unity Export Without Seam Check

```python
# WRONG
export_to_unity(tile_stacks)

# CORRECT
seam_report = validate_tile_seams(extracted_heights, atol=1e-6)
if not seam_report["seam_ok"]:
    raise RuntimeError(f"Seam validation failed: {seam_report['issues']}")
export_to_unity(tile_stacks)
```

### Anti-Pattern 6: Hardcoded Erosion Iterations

```python
# WRONG — hardcoded 50 iterations regardless of terrain height range
erode_world_heightmap(hmap, hydraulic_iterations=50)

# CORRECT — computed from height range
params = compute_erosion_params_for_world_range(hmap.max() - hmap.min())
erode_world_heightmap(hmap, hydraulic_iterations=params["hydraulic_iterations"])
```

### Anti-Pattern 7: Undeclared Channel Writes

```python
# WRONG — writes my_channel but PassDefinition doesn't list it
# PassDAG logs WARNING, channel is not merged back in parallel execution
PassDefinition(
    name="my_pass",
    produces_channels=("slope",),  # forgot my_channel
)
# pass_function writes stack.set("my_channel", ...)

# CORRECT — declare every channel the pass writes
PassDefinition(
    name="my_pass",
    produces_channels=("slope", "my_channel"),  # both declared
)
```

---

*End of VeilBreakers Terrain Generation Guardrails. Version: initial canonical. Date: 2026-04-18.*
