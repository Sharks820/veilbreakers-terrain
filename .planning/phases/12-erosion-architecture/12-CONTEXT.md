# Phase 12: Erosion Architecture Upgrades — Context

**Gathered:** 2026-04-18
**Status:** Ready for planning
**Source:** Master Audit BUG-S10-003/020/021, Rune low/high-freq split, Cordonnier 2016

<domain>
## Phase Boundary

Rearchitect erosion: erode only low-frequency heightmap (base shape), then add high-frequency detail after erosion. Add Stream-Power Law O(n) implicit solver (Cordonnier 2016). Add variable erodibility from rock hardness. This is ARCHITECTURAL — Fix 12.1 must update PassDAG declarations before 12.2/12.3 run.

</domain>

<decisions>
## Implementation Decisions

### Low/High-Freq Split (Fix 12.1 / BUG-S10-020 — ARCHITECTURAL)
- File: `veilbreakers_terrain/handlers/terrain_pipeline.py` + relevant noise/erosion passes
- New PassDAG structure:
  1. `pass_generate_low_freq_hmap`: generates base heightmap with low octaves only (max 3–4 octaves)
  2. `pass_erosion`: runs on `_hmap_low_freq` (not full resolution hmap)
  3. `pass_generate_high_freq_detail`: generates detail noise (high octaves, 2× scale range)
  4. `pass_composite_hmap`: `final_hmap = _hmap_low_freq + _hmap_high_freq * detail_scale`
- `detail_scale` = 0.15–0.25 (detail adds 15–25% height variation on top of eroded base)
- Both channels declared in `_ARRAY_CHANNELS`: `"hmap_low_freq"`, `"hmap_high_freq"`
- All downstream passes that read `height` continue to read the composited `height` channel

### PassDAG Updates for 12.1
- `pass_generate_low_freq_hmap.produces_channels = ["height", "hmap_low_freq"]`
- `pass_generate_high_freq_detail.produces_channels = ["hmap_high_freq"]`
- `pass_erosion.depends_on = ["hmap_low_freq"]`; reads `stack.get("hmap_low_freq")`
- `pass_composite_hmap.produces_channels = ["height"]` (overwrites height with final composite)
- `pass_composite_hmap.depends_on = ["hmap_low_freq", "hmap_high_freq"]`

### Stream-Power Law (Fix 12.2 / BUG-S10-021)
- File: `veilbreakers_terrain/handlers/_terrain_erosion.py`
- Cordonnier 2016 ε-topological-order solver (implicit parallel):
  ```
  uplift term: dH/dt = U - K * A^m * S^n
  where: U = uplift_rate, K = erodibility, A = drainage_area, S = slope, m=0.5, n=1
  ```
- Solver: priority-queue topological order (ε-variant handles flats stably)
- Input: `dem` (eroded low-freq hmap), `uplift_rate` map, `erodibility` map
- Output: steady-state dem after stream-power erosion
- `drainage_area` computed from `flow_accumulation` channel (requires Phase 7 Priority-Flood)
- New function: `compute_stream_power_erosion(dem, uplift_rate, erodibility, K_scalar, m, n, dt, steps)`

### Variable Erodibility (Fix 12.3 / BUG-S10-021 companion)
- File: `veilbreakers_terrain/handlers/_terrain_erosion.py`
- Erodibility map: `K_map = K_base + rock_hardness * K_strata_scale`
  - `K_base` = 0.001 (default for soft sediment)
  - `rock_hardness` from `stack.get("rock_hardness")` channel (already in `_ARRAY_CHANNELS`)
  - `K_strata_scale` = -0.0008 (hard rock reduces erodibility)
- Higher K → more erodible (soft soil); lower K → resistant (granite)
- Wire into `compute_stream_power_erosion` and existing `apply_hydraulic_erosion_masks`

### Claude's Discretion
- If `rock_hardness` channel is not populated, use uniform K_base
- `detail_scale` is an exposed parameter (not hardcoded) for quality profile control
- Low-freq octave count: expose as `low_freq_octaves` parameter (default: 3)

</decisions>

<canonical_refs>
## Canonical References

- `docs/TERRAIN_UPGRADE_MASTER_AUDIT.md` — Phase 12 FIXPLAN items 12.1–12.3, BUG-S10-020/021
- `veilbreakers_terrain/handlers/terrain_pipeline.py` — pass registration and DAG
- `veilbreakers_terrain/handlers/_terrain_erosion.py` — erosion algorithms
- `veilbreakers_terrain/handlers/terrain_semantics.py` — _ARRAY_CHANNELS
- `veilbreakers_terrain/handlers/_terrain_noise.py` — noise generation (low/high freq split)

</canonical_refs>

<specifics>
## Specific Values

### Stream-Power Law parameters (default)
```python
K = 0.001  # erodibility
m = 0.5    # drainage area exponent
n = 1.0    # slope exponent
uplift_rate = 0.001  # mm/year normalized
dt = 1000.0  # years per step
steps = 50   # typical convergence
```

### Low-freq octave split
```python
LOW_FREQ_OCTAVES = 3   # octaves 0–2 → large-scale shape
HIGH_FREQ_OCTAVES = 5  # octaves 3–7 → micro-detail
DETAIL_SCALE = 0.2     # high-freq adds 20% amplitude
```

</specifics>

<deferred>
## Deferred Ideas

- GPT-style uplift pattern simulation → future research
- Tectonic simulation → future
- Multi-layer stratigraphy coupled to erodibility → future

</deferred>

---
*Phase: 12-erosion-architecture*
*Context gathered: 2026-04-18 from master audit sessions 9–10*
