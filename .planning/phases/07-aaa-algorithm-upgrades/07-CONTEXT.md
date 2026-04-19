# Phase 7: AAA Algorithm Upgrades — Context

**Gathered:** 2026-04-18
**Status:** Ready for planning
**Source:** Master Audit sessions 1–10 (docs/TERRAIN_UPGRADE_MASTER_AUDIT.md)

<domain>
## Phase Boundary

Fix broken/missing channel contracts, consolidate thermal erosion, vectorize remaining hot-path loops, fix _pow_inv formula, add Priority-Flood hydrology. These are foundational correctness fixes that unblock all downstream phases (texturing, scatter, roads all read channels that are currently missing or wrong).

</domain>

<decisions>
## Implementation Decisions

### Channel Contracts (CRITICAL — must fix first)
- `flow_direction` has zero producers → add Priority-Flood (Barnes 2014) as producer in `pass_erosion` or new `pass_hydrology`; write via `stack.set("flow_direction", fd)`
- `roughness_variation` has 3 conflicting writers in `terrain_waterfalls.py`, `terrain_erosion_filter.py`, `vegetation_system.py` → pick canonical writer (`terrain_erosion_filter.py` since it computes actual micro-roughness from erosion), stub others with `pass`

### Priority-Flood (Fix 7.3)
- File: `veilbreakers_terrain/handlers/_water_network.py`
- Algorithm: Barnes 2014 Priority-Flood — priority queue (min-heap) starting from boundary cells; fills depressions to spill level
- Replace naive `scipy.ndimage.minimum_filter` pit detection at `:200-212`
- Output: `flow_direction` array (D8 or D-infinity encoding), `flow_accumulation` array
- Both written to `TerrainMaskStack` via `stack.set()`

### _pow_inv Formula Fix (Fix 7.19 / BUG-S10-001)
- File: `veilbreakers_terrain/handlers/_terrain_noise.py`
- Correct formula: `1 - (1-p)**e` (Rune's formula: `1-(1-0.5)^2 = 0.75`)
- Wrong formula currently likely uses: `1/(1-p)` or `p**(1/e)` 
- Must add unit test: `assert abs(_pow_inv(0.5, 2.0) - 0.75) < 1e-6`

### Thermal Erosion Consolidation (Fix 7.6 / Fix 7.20 CONFLICT-11)
- Files: `terrain_advanced.py`, `_terrain_erosion.py`, `terrain_waterfalls.py`, `_terrain_noise.py`
- 4 separate implementations → 1 canonical in `_terrain_erosion.py`
- Canonical uses: `rest_angle` parameter, vectorized `np.where(slope > rest_angle, ...)`
- All callers import from `_terrain_erosion.canonical_thermal_erosion`

### Vectorization (Fix 4.8 ext)
- `_terrain_depth.detect_cliff_edges` — replace `scipy.ndimage.label` loop with `scipy.ndimage.binary_erosion` + `np.logical_xor`
- `_water_network` pit detection `:200-212` — replace Python loop with `scipy.ndimage.minimum_filter` already available

### Convention Conflicts (Fix 7.20)
- CONFLICT-01: Slope in degrees vs. radians → canonical = radians everywhere; convert at display only
- CONFLICT-02: `_noise_scale` vs `noise_scale` parameter naming → canonical = `noise_scale`
- CONFLICT-03: Thermal erosion `rest_angle` vs `talus_angle` → canonical = `rest_angle`
- CONFLICT-04: `height_delta` vs `delta_h` → canonical = `delta_h`
- CONFLICT-05: `erosion_rate` vs `erosion_strength` → canonical = `erosion_rate`
- CONFLICT-06: Redundant thermal erosion across 4 modules (atomic with Fix 7.6)

### LOD / QEM (Fix 7.13 / Fix 7.14 / BUG-174/175)
- File: `veilbreakers_terrain/handlers/lod_pipeline.py`
- Real Garland-Heckbert: `Q = sum(outer(n,n))` per vertex; `v^T Q v` error quadric; heap rebalance after each collapse
- Fix stale priority queue: recompute Q_w + update incident edges after each collapse
- Fix discarded `generate_lod_chain()` return value at `:1113`

### Triplanar Projection (BUG-116 / Fix 7.16)
- File: `veilbreakers_terrain/handlers/terrain_materials_v2.py` (or `_biome_grammar.py`)
- `w = pow(abs(normal), 4); w /= sum(w); blend = w.x*noise(yz) + w.y*noise(xz) + w.z*noise(xy)`
- Replaces `compute_biome_transition` Z-only noise input

### Claude's Discretion
- Test approach: parametric unit tests for _pow_inv; regression snapshots for thermal erosion
- Exact file line numbers may drift — always read current file before editing

</decisions>

<canonical_refs>
## Canonical References

- `docs/TERRAIN_UPGRADE_MASTER_AUDIT.md` — Phase 7 FIXPLAN items 7.3–7.20, BUG-S9-005, BUG-S9-012, BUG-S10-001, CONFLICT-01–06
- `veilbreakers_terrain/handlers/_water_network.py` — Priority-Flood target
- `veilbreakers_terrain/handlers/_terrain_noise.py` — _pow_inv, thermal erosion
- `veilbreakers_terrain/handlers/_terrain_erosion.py` — canonical thermal erosion target
- `veilbreakers_terrain/handlers/terrain_semantics.py` — _ARRAY_CHANNELS declarations
- `veilbreakers_terrain/handlers/lod_pipeline.py` — QEM LOD target
- `veilbreakers_terrain/handlers/terrain_materials_v2.py` — triplanar projection target

</canonical_refs>

<specifics>
## Specific Implementation Details

### Priority-Flood Barnes 2014
```python
import heapq
def priority_flood(dem):
    H, W = dem.shape
    visited = np.zeros((H, W), bool)
    pit = []  # min-heap (elevation, r, c)
    # seed from all boundary cells
    for r in range(H):
        for c in [0, W-1]:
            heapq.heappush(pit, (dem[r,c], r, c))
            visited[r,c] = True
    for c in range(W):
        for r in [0, H-1]:
            if not visited[r,c]:
                heapq.heappush(pit, (dem[r,c], r, c))
                visited[r,c] = True
    flow_dir = np.zeros((H, W), np.int8)
    while pit:
        elev, r, c = heapq.heappop(pit)
        for nr, nc, d in neighbors8(r, c, H, W):
            if not visited[nr,nc]:
                visited[nr,nc] = True
                new_elev = max(dem[nr,nc], elev)
                flow_dir[nr,nc] = d
                heapq.heappush(pit, (new_elev, nr, nc))
    return flow_dir
```

### Brucks Height-Blend (Fix 7.11)
```glsl
// ma = max of weighted heights minus contrast
ma = max(h0 + (1-alpha), h1 + alpha) - contrast
b0 = max(h0 + (1-alpha) - ma, 0)
b1 = max(h1 + alpha - ma, 0)
result = (c0*b0 + c1*b1) / (b0 + b1)
```

### Heitz-Neyret Histogram-Preserving Blend (Fix 7.12)
- Triangle-grid partition + 3-patch barycentric blend + variance-preserving formula
- File: `build_uv_offset_noise_mask` or new `heitz_neyret_blend` function

</specifics>

<deferred>
## Deferred Ideas

- Full O(n) stream-power catchment area → moved to Phase 12.2
- IQ erosion fBm → Phase 11 (Fix 11.2)
- Water adjacency (rivers to sea) → Phase 10 / water adjacency work
- Hero cliff mesh (Fix 5.11/7.15) — complex procmesh; defer to Phase 7 last wave if time permits

## Explicitly Deferred Convention Conflicts (requires dedicated rename sweep)

- **CONFLICT-02** (`_noise_scale` vs `noise_scale`): Private-vs-public underscore naming; cross-cutting 8+ handler files. Renaming in Phase 7 would add ~40 touch-points to an already large wave-3 plan. Deferred to post-Phase-13 cleanup sweep. REQ-P7-007 is fulfilled for CONFLICT-01/04/06 (slope naming, triplanar); CONFLICT-02 deferred.
- **CONFLICT-05** (`erosion_rate` vs `erosion_strength`): Two callers use different names for the same erosion intensity parameter. CONFLICT-06 (thermal consolidation) in plan 07-04 already rationalises the canonical implementation; a parameter rename sweep is post-Phase-13 work. Deferred with same justification.
- **CONFLICT-03** (cell origin convention): Cross-cutting 12+ files, architectural. Already documented as deferred in original context.

</deferred>

---
*Phase: 07-aaa-algorithm-upgrades*
*Context gathered: 2026-04-18 from master audit sessions 1–10*
