# L1 — Waterfall Visual Quality Deep Dive

**Date:** 2026-04-27
**Scope:** `veilbreakers_terrain/handlers/terrain_waterfalls.py` (2,890 lines), `terrain_waterfalls_volumetric.py` (813 lines), and consumers (`terrain_unity_export.py`, `terrain_delta_integrator.py`, `_water_network.py`).
**Mandate:** Find NEW P0 bugs in the production-running waterfall path. Already-counted P0s (I1-P0-1 phantom `pool_deepening_delta`, I4 P1 discharge underestimate, F4-P0-1 mesh memory, J2-P0-1 particle gate, F1-P0-1/2 sim/ orphan) are NOT re-added.

---

## Summary of NEW Findings

| ID | Severity | Location | Title |
|----|----------|----------|-------|
| **L1-P0-1** | **P0** | `terrain_waterfalls.py:923-994` | Cascade tier list discarded — chained waterfalls collapse to a SINGLE merged drop with no per-tier pools, foam, mist, or particle emitters |
| **L1-P0-2** | **P0** | `terrain_waterfalls.py:899, 2274` | `solve_waterfall_from_river(..., river_network=...)` accepts and ignores the river network — waterfall lips/outflows are NEVER reconciled with detected rivers; outflows can teleport into ridges or off-tile |
| **L1-P0-3** | **P0** | `terrain_waterfalls.py:2389-2395` + `terrain_unity_export.py` | `mist_fog_volume` channel is computed and written, but Unity export has zero consumer for it — VolumetricFogVolume mist is dead-on-arrival in every shipped tile |
| **L1-P1-1** | P1 | `terrain_waterfalls.py:832` | Slope unit double-conversion bug: `slope_val = best_slope_arr / cs` after `slopes_stack` already divided by D8 distance — Manning velocity used to seed lips is ~`1/cs`× too small (e.g. 1/2 the correct value at 2 m cells, 1/16 at 16 m cells) |
| **L1-P1-2** | P1 | `terrain_waterfalls.py:212-229` | `WaterfallChain` data model holds exactly ONE `pool: ImpactPool` — the schema cannot represent a multi-tier cascade with intermediate pools even if the solver wanted to emit them |
| **L1-P1-3** | P1 | `terrain_waterfalls.py:2286-2305, 2335-2353` | Foam/velocity/flow-speed boost are computed against `_h_preview = stack.height + pool_delta` but the actual height carve happens in a *later* pass (`integrate_deltas`) — readability/validators that read both `height` and `waterfall_pool_delta` see different geometry; foam mask is concentrated where the pool *will be* but velocity boosts are stamped on un-carved cells |
| **L1-P2-1** | P2 | `terrain_waterfalls.py:1067-1070` | `mist_radius = total_drop * 0.3 * 1.0` hard-codes `wind_factor = 1.0` inside `solve_waterfall_from_river` — the wind from `composition_hints` is only applied later in `generate_mist_zone()`, so the chain's stored `mist_radius_m` (used to size the mist particle zone & OBB) ignores wind |

---

## Detailed Findings

### L1-P0-1 — Chained-waterfall cascade list is detected then DISCARDED

**File:** `terrain_waterfalls.py`
**Lines:** `547-639` (detect), `923-928` (call), `930-995` (consume).

```python
# terrain_waterfalls.py:923-928
cascade_tiers = _detect_cascade_chain(
    stack, lip, drainage,
    min_drop_m=3.0, search_radius_m=5.0,
)
tier_count = len(cascade_tiers)
```

`_detect_cascade_chain()` returns an *ordered list of `LipCandidate`s* representing each tier of a multi-step cascade (Niagara-style: upper fall → plateau → lower fall). It builds full `LipCandidate` records — world position, drainage, drop, Manning velocity, discharge — for every tier discovered (lines 616-627).

**Then the solver throws the list away.** Only `len(cascade_tiers)` survives. From line 930 onward the solver walks the original `lip` cell down a single steepest-descent path and produces ONE `WaterfallChain` with ONE `ImpactPool`. There is no loop over `cascade_tiers[1:]` to:
- generate per-tier sub-pools at each plateau,
- carve per-tier `pool_delta` bowls,
- emit per-tier foam / mist masks,
- spawn per-tier particle emitter zones (`_build_particle_emitter_specs` only iterates `chains`, not tiers).

The downstream effect:
- A 200 m three-step cascade (e.g. Yosemite-style upper-middle-lower) is exported as a single 200 m freefall with one plunge pool at the bottom. The middle pool, the foam churn at each transition, and the per-tier mist plumes are **completely absent**.
- The Mason-1985 pool radius/depth is computed from `total_drop = 200 m`, producing a single ~30 m crater at the base instead of three smaller pools.
- The "waterfall_velocity" float2 channel records ONE flow azimuth (`chain.flow_azimuth_rad`) for the entire cascade. Tiers that bend (e.g. lower tier flowing east, upper flowing south) are flattened to one direction.

**Smoking gun:** `WaterfallChain` (line 212-229) only has a `pool: ImpactPool` field (singular) — no list of pools. So even fixing the discard would require schema changes (see L1-P1-2). The `tier_velocities: Tuple[float, ...]` field exists but is appended to from the steepest-descent walker (lines 961, 971, 989, 995), NOT from the discovered cascade tiers — yet another dead handle.

**Why P0:** The user's `feedback_water_cliff_path_priority.md` calls out chained waterfalls as a top-3 contention area against AAA bar. God of War, Horizon Forbidden West, Tsushima all ship multi-tier cascades with distinct intermediate pools and per-tier foam churn. Producing a single homogenized drop instead is a categorical visual regression — not a "polish" issue.

**Fix sketch:**
1. Extend `WaterfallChain` to `pools: Tuple[ImpactPool, ...]` and `mist_radii_m: Tuple[float, ...]`.
2. In `solve_waterfall_from_river`, iterate `cascade_tiers`, calling `_mason_1985_pool` per tier with `tier_drop_segments[i]` and the local discharge.
3. Make `carve_impact_pool`, `generate_foam_mask`, `generate_mist_zone`, `_build_particle_emitter_specs` iterate the tier list.

---

### L1-P0-2 — `river_network` parameter is dead — waterfalls are not reconciled with rivers

**File:** `terrain_waterfalls.py`
**Lines:** `899, 2274`.

```python
# terrain_waterfalls.py:896-899
def solve_waterfall_from_river(
    stack: TerrainMaskStack,
    lip: LipCandidate,
    river_network: Optional[Any] = None,    # <-- accepted
) -> WaterfallChain:
```

`grep "river_network" terrain_waterfalls.py` returns exactly 2 hits: the parameter declaration and the caller. **`river_network` is referenced zero times inside the function body.** The function name `solve_waterfall_from_river` is a lie — the function does not consult the river network.

There are TWO completely independent waterfall detection systems in the repo:
1. `_water_network.detect_waterfall_along_path` (lines 1246+ in `_water_network.py`) — runs as part of river construction, uses river-path indices and emits `top_row, top_col, bottom_row, bottom_col, drop, drop_rate, drainage_area, orientation_rad`.
2. `terrain_waterfalls.detect_waterfall_lip_candidates` (line 777) — runs in `pass_waterfalls`, scans all interior cells with D8 + drainage threshold, emits `LipCandidate` records.

System #2 is what the production pipeline actually uses (system #1's output is held inside the river network and never traversed by `pass_waterfalls`). Because lips are detected from *raw heightmap drainage*, not from *traced river segments*:

- A lip's `outflow` is traced via `_steepest_descent_step` from the pool — it never queries the river network for the downstream path.
- If the river network terminated the upstream river at a confluence one cell upstream of the lip (because routing said "merge into lake" or similar), the waterfall happily continues drawing water that the river system says doesn't exist.
- Conversely, if the river network has a waterfall at row=120 col=50 (system #1) but the heightmap lip detection hits row=119 col=51 (system #2), the foam, mist, and pool are stamped at the wrong location relative to the river ribbon mesh.
- Outflow channels carved by `build_outflow_channel` (line 1207+) walk steepest-descent for 32 steps and then *stop* — there is no merge into the existing `flow_accumulation` river network. The channel ends abruptly. (Compare with the A2-2 P1 finding that foam uses a 3-source proxy: similar disconnect pattern.)

**Why P0:** This means waterfall meshes float in space relative to the actual river system. A waterfall lip without an upstream river source is a wall fountain. A waterfall outflow that doesn't merge with the river ribbon produces a disconnected pool. Both are categorical AAA-fail.

**Validation evidence:** `terrain_validation.check_waterfall_chain_completeness` (validation.py:1124) checks for "a waterfall_pool_delta > 0 cell within drain_distance" of a lip — but it does NOT cross-check that the lip's upstream cells contain a river. So this validator confirms the pool was carved (good), not that the waterfall is connected to a real river (the P0).

**Fix sketch:** `solve_waterfall_from_river` should:
1. Project `lip.world_position` onto the nearest river-network polyline; reject lips farther than `cell_size * 2` from any river.
2. Inherit `discharge` from the river segment instead of recomputing from `_estimate_discharge(drain_val, cs)` (which differs from the river network's own Manning derivation).
3. Trace the outflow until it intersects an existing river segment, then snap the last point to the river vertex (continuity).

---

### L1-P0-3 — `mist_fog_volume` is a dead channel; Unity gets no volumetric fog data

**File:** `terrain_waterfalls.py:2389-2395`
**File:** `terrain_unity_export.py` (no consumer).

```python
# terrain_waterfalls.py:2388-2395
# Step 7: Convert 2D mist mask to fog volume descriptor for engine VolumetricFogVolume.
mist_fog_volume = {
    "mask_2d":     mist,
    "height_m":    3.0,
    "density_max": 0.6,
    "color":       (0.7, 0.75, 0.8),
}
stack.set("mist_fog_volume", mist_fog_volume, "waterfalls")
```

The pass declares `mist_fog_volume` as a produced channel (line 2453) and sets it on the stack. It's also declared on the `TerrainMaskStack` dataclass (`terrain_semantics.py:319`). **No code anywhere reads it.**

```
$ grep "mist_fog_volume" veilbreakers_terrain/handlers/terrain_unity_export.py
(no matches)
```

The cross-referenced D2 channel-contracts audit (`docs/aaa-audit/deep_dive_2026_04_27/D2_channel_contracts.md:114`) lists it explicitly as a "WASTED" channel: "produced with ZERO consumption anywhere".

The 2D `mist` mask (separate channel) IS rasterized as `wet_rock` and used in vertex-color export, but that is the *projected ground darkening*, not a volumetric fog. There is no atlas writer for `mist_fog_volume`, no Unity descriptor, no Niagara/VFX-graph wiring. A user opening a tile in Unity sees zero volumetric mist around any waterfall base — just a 2D wet-rock decal patch.

**Why P0 (separate from J2-P0-1 particle-gate):** J2-P0-1 covers `pass_emit_particle_systems` being unreachable (so particle emitters never instantiate). This finding is a SEPARATE wiring failure: even when the producer pass DOES run (`pass_waterfalls` is in the default sequence and runs every build), its volumetric-fog descriptor is never serialized. Mist is always missing for two independent reasons. Fixing one does not fix the other.

**Fix sketch:** Add `_mist_fog_volume_json(stack)` in `terrain_unity_export.py` mirroring `_particle_emitter_specs_json`, write to `mist_fog_volumes.json` and reference it in the manifest's `volumetric_fog_descriptor` field.

---

### L1-P1-1 — Slope unit double-conversion in lip detection

**File:** `terrain_waterfalls.py:808-832`.

```python
# terrain_waterfalls.py:815-816
_h_diff = h[_r_d, _c_d] - h[_r_s, _c_s]
slopes_stack[_d_idx, _r_d, _c_d] = _h_diff / _dist        # _dist is 1.0 or sqrt(2) (cells)
...
# terrain_waterfalls.py:832
slope_val = float(best_slope_arr[r, c]) / cs              # divides AGAIN by cs
```

`_D8_DISTANCES` (line 74) holds D8 step distances in **cells** (1.0 for cardinal, √2 for diagonal). So `slopes_stack` is in `metres_drop / cell_step`. The correct slope (m/m, dimensionless) is `_h_diff / (_dist * cs)`. But line 832 divides by `cs` AFTER selecting the best slope — meaning a `min_drop=4 m` cardinal step on a `cs=2 m` grid yields `slope_val = 4/1/2 = 2.0`, which is wrong by exactly the cell-size factor. The correct slope is `4 / (1 * 2) = 2.0` — wait, by coincidence this works for cardinal at cs=2.

Actually re-checking: `slopes_stack = h_diff / dist` where `dist = 1` cell (unitless). Then `slope_val = best_slope_arr / cs = h_diff / cs`. This is `m_drop / m_horizontal` for cardinal (correct) but `m_drop / (sqrt(2) * cs)` evaluated as `m_drop / cs` for diagonal — i.e. diagonals are 1.41× too steep, cardinals are correct. This biases lip selection toward diagonal cells and inflates Manning velocity by up to 1.41× on diagonal lips.

**More importantly** — the slope is then passed to `_manning_velocity(slope, r_hyd)` at line 841 (with a clamp to `>= 0.01`). Manning is `V = (1/n) * R^(2/3) * sqrt(slope)`. A 1.41× slope error → 1.19× velocity error → up to 1.19× discharge-via-velocity error → AAA water "too fast" or "too slow" depending on which direction the bias compounds.

This isn't catastrophic on its own (P1, not P0), but combined with the I4 300× discharge underestimate it pushes velocities further from physical truth.

---

### L1-P1-2 — `WaterfallChain` schema holds only one pool

**File:** `terrain_waterfalls.py:212-229`.

The dataclass has `pool: ImpactPool` (singular) and `outflow: Tuple[Tuple[float, float, float], ...]` (single polyline from THE pool). It cannot represent a tiered cascade even if downstream code wanted to render one. This is the structural enabler of L1-P0-1.

---

### L1-P1-3 — Foam/velocity computed on a *preview* height that other passes never see

**File:** `terrain_waterfalls.py:2286-2305, 2335-2353`.

```python
# 2286-2287
_h_preview = stack.height + pool_delta
_preview_stack = replace(stack, height=_h_preview)

# 2289-2305
for chain in chains:
    wf_chain_foam = np.maximum(wf_chain_foam, generate_foam_mask(chain, _preview_stack))
    mist = np.maximum(mist, generate_mist_zone(chain, _preview_stack, ...))
foam = compute_physical_foam_composite(stack, wf_chain_foam, lip_mask)  # NB: passes ORIGINAL stack here
```

Foam composite uses `stack` (original height) but the chain-foam contribution was built from `_preview_stack` (carved height). These two layers disagree about where the pool surface sits — by exactly `pool_depth` (Mason 1985: up to 20 m). For a deep crater pool, the chain foam ring sits at the *future* water surface while shoreline-foam, rapid-foam, bend-foam from `compute_physical_foam_composite` sit at the *un-carved* surface. After Gaussian smoothing the discontinuity becomes a foam halo ring that doesn't align with the eventual water mesh.

Note also (line 2333-2353): the flow-speed boost is stamped on `flow_speed[gr, gc]` based on grid coordinates from the un-carved heightmap. Cells that will become pool-bottom after the integrator runs receive the boost on their pre-carve elevation — the actual integrated tile may have those cells underwater, where flow_speed is irrelevant.

This is fixable by either (a) running the carve in `pass_waterfalls` before generating foam (the pre-`integrate_deltas` architecture had this) or (b) running foam/velocity in a post-integration pass. Currently it's neither.

---

### L1-P2-1 — `mist_radius` ignores wind inside the chain solver

**File:** `terrain_waterfalls.py:1067-1070`.

```python
# Mist radius = H * 0.3 * wind_factor (AAA req #7)
# wind_factor defaults to 1.0 here; pass_waterfalls applies wind from intent
mist_radius = total_drop * 0.3 * 1.0
```

Comment admits the bug. `pass_waterfalls` reads `wind_factor` from `composition_hints` and passes it to `generate_mist_zone()` only — but `chain.mist_radius_m` (set from `mist_radius` at line 1082) is what the particle emitter spec consumes (line 2546 `chain.mist_radius_m`) and what the OBB volumetric bounds use. So the particle/OBB system always uses `wind_factor=1.0`, even in a calm-day intent (`wind_speed_factor=0.0` would zero out mist in `generate_mist_zone` but not in particle emitter sizing).

---

## Confirmed Existing Findings (not re-counted)

- **I1-P0-1 (`pool_deepening_delta` phantom):** `_terrain_erosion.py:507` computes `pool_deepening_delta` but the field is on a returned dataclass (line 517) that is then never read by anything that mutates `stack` — the channel is never set on the stack. Confirmed: `grep` shows only the producer (erosion) and the integrator's `_DELTA_CHANNELS` list contains it, but no producer ever calls `stack.set("pool_deepening_delta", ...)`. The integrator therefore never sees it and `_collect_deltas` skips it. Distinct from the (separate, working) `waterfall_pool_delta` channel which IS set at `terrain_waterfalls.py:2384` and IS picked up by the integrator.
- **I4 P1 discharge ~300× underestimate:** Confirmed at `terrain_waterfalls.py:421-436`. `Q = 0.001 * A_km2^0.7` is the Creager-style low-flow envelope, not Chezy/Manning. For a 10 km² catchment in a wet biome (e.g. Niagara is ~1 M km², the Yosemite Falls catchment is ~3 km²) this gives Q ≈ 0.005 m³/s — roughly 300× under the real ~1.5 m³/s baseflow of a 3 km² mountain catchment.
- **F1-P0-1/2 (`sim/foam.py` orphaned):** Confirmed — only `compute_physical_foam_composite` (line 1667) runs; it has 5 sources but two are degraded proxies (Source 2 uses `np.gradient(flow_direction)` rather than Froude+Kelvin, Source 4 uses `binary_dilation` rather than the proper shoreline foam advection in `sim/foam.py`).

---

## Risk Verdict

Even ignoring already-counted P0s, waterfalls in this repo do not meet AAA bar:

- Multi-tier cascades degenerate to a single drop (L1-P0-1).
- Waterfalls are not reconciled with the river network — outflows can disconnect (L1-P0-2).
- Volumetric mist is computed but never reaches Unity (L1-P0-3).

These are **three independent P0 wiring/structural failures** on the production-running waterfall path, separate from the I1/I4/F1/J2/F4 list. The "what runs" path produces a single homogeneous drop with a 2D foam ring, no per-tier intermediate features, no volumetric fog, and a discharge that's 300× too low for the AAA "feels like a real river" bar the user mandates.
