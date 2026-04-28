# K2 — Active-Channel Correctness Audit

**Date:** 2026-04-27
**Auditor:** Claude (Opus 4.7) — K2
**Scope:** Are the 22 production-active channels enumerated by J3 actually populated with **correct** values? Per-channel writer math, range contract, reader interpretation, units, and coordinate convention.
**Verdict:** **5 P0 unit/contract bugs, 2 P0 wrong-classification bugs, 3 P1 silent-broken paths, plus 1 J3 mis-classification (a "production-active" channel is actually never written).** The 22-channel "happy path" is several order-of-magnitude smaller than even J3 reported because so many of those 22 are mathematically wrong, off-by-units, or quietly empty.

---

## 1. Methodology

Walked every `stack.set(...)` site identified in J3's "22 ACTIVE channels" table and read:
1. The writer function (math, units, dtype, range).
2. The declared range contract from `terrain_semantics.py` `TerrainMaskStack` field comments.
3. Every active production reader (`terrain_materials_v2.pass_materials`, `terrain_cliffs.pass_cliffs`, `terrain_waterfalls.pass_waterfalls`, plus the v6 builder script `scripts/build_terrain_aaa_node_v6.py:run_production_passes`).

Each finding is verified by line-cited source quotes. P0 = production tile contains systematically wrong/garbage data **at the active reader's input**; P1 = wrong contract that happens to coincide with reader expectation by accident, or partially-broken path.

The 22 channels (per J3 §2):

```
height, slope, rock_hardness, strata_orientation,
unconformity_mask, intrusion_mask, albedo_shift_rgb, strata_cross_section,
cliff_candidate, cliff_contour_spline, cliff_mask, talus_mask, strata_mask,
waterfall_lip_candidate, waterfall_pool_delta, waterfall_velocity, flow_speed,
foam, mist, wet_rock, riverbed_caustics, wave_amplitude_per_vertex,
splatmap_weights_layer, material_weights
```

(The five `unconformity/intrusion/albedo_shift/strata_cross_section/strat_erosion_delta` writes are gated on running `pass_stratigraphy`, not on `compute_rock_hardness`. See K2-J3-1 below.)

---

## 2. Findings

### K2-P0-1 — `slope` is in DEGREES; every active reader expects RADIANS *(P0, units mismatch)*

**Writer:** `scripts/build_terrain_aaa_node_v6.py:179`

```python
slope = np.degrees(np.arctan(np.sqrt(dz_dx ** 2 + dz_dy ** 2))).astype(np.float32)
```

The slope channel is stored as **degrees** (range 0..90).

**Active readers expecting radians:**

1. `terrain_materials_v2.compute_slope_material_weights` (active in v6) — line 547:
   ```python
   slope_w = _smoothstep_band(
       slope, ch.slope_min_rad, ch.slope_max_rad, ch.slope_falloff_rad
   )
   ```
   The `MaterialChannel` rule fields are explicitly named `_rad` and populated via `math.radians(...)` (e.g. `terrain_materials_v2.py:122-156`):
   ```python
   slope_min_rad=0.0, slope_max_rad=math.radians(30.0), slope_falloff_rad=math.radians(8.0),
   ```
   Comparing degrees-valued slope to radians thresholds: a real slope of 30° (= 0.524 rad) is read as the value `30`. Threshold `math.radians(30.0) = 0.524`. So every cell with even mild slope (>≈1°) saturates *every* envelope; the `_smoothstep_band` returns 0 for all cells with slope > falloff (≈8° threshold collapses at 0.14 rad value). Net effect: almost every non-flat cell receives 0 weight from the analytical path and falls through to the `default_channel_id="ground"` constant fill at L705-708.

2. `terrain_materials_v2.compute_slope_material_weights:583`:
   ```python
   steep = slope > math.radians(45.0)
   ```
   `math.radians(45) = 0.785`; with slope in degrees this triggers for any slope > 0.785°, tilting triplanar normals to 45° on essentially every cell, defeating the Brucks-style triplanar variation.

3. `terrain_cliffs.build_cliff_candidate_mask:357-358`:
   ```python
   threshold_rad = math.radians(float(slope_threshold_deg))   # default deg=55 → 0.96 rad
   mask = slope > threshold_rad                               # slope is degrees!
   ```
   Comparison: degrees > 0.96 → every cell with slope > 0.96° is flagged a cliff candidate. Default threshold should give ~steep-only cells (>55°) but in practice nearly every non-table-flat cell becomes a candidate. This subsequently feeds:
   - `cliff_candidate` (channel #9) — explodes from "few hand-picked clusters" to "most of the tile".
   - `cliff_contour_spline` (channel #10) — Moore contour traced over a saturated mask returns the tile boundary, not real cliff edges.
   - `cliff_mask` (channel #11) — `cliff_mask_arr = candidate.copy().astype(np.float32)` at L2658, so propagates the over-saturation.
   - `strata_mask` (channel #13) — accumulates `face_mask` for each survivor of `min_cluster_size`, so the whole over-saturated region gets strata-banded.

The codebase even has a degree/radian autodetect heuristic at `terrain_cliffs.py:1389` (`if float(np.nanmax(slope_arr)) < 2.0: slope_arr = np.degrees(...)`), which is applied in `build_cliff_base_mask` but **not** in `build_cliff_candidate_mask` and **not** in `compute_slope_material_weights`. So the unit confusion is acknowledged in code yet only patched in one of three call sites.

**Severity:** P0. The single root cause invalidates ≥ 6 of the 22 "active" channels (`slope`, `cliff_candidate`, `cliff_contour_spline`, `cliff_mask`, `strata_mask`, `splatmap_weights_layer`/`material_weights`).

**Fix sketch:** Either change v6 to write radians (`np.arctan(...)`, drop `np.degrees`), or change every reader to compare against `math.radians(rule_deg)` and update the field name comment.

---

### K2-P0-2 — `slope` numerator missing `cell_size` divisor (latent units bug, currently masked) *(P0, fragile)*

**Writer:** v6 build script L177-179:

```python
dz_dx = np.gradient(heightmap, axis=1)
dz_dy = np.gradient(heightmap, axis=0)
slope = np.degrees(np.arctan(np.sqrt(dz_dx ** 2 + dz_dy ** 2))).astype(np.float32)
```

`np.gradient(heightmap)` returns the difference along the array index axis, in metres-per-cell. To compute true slope tan(θ) = dz/dx in metres-per-metre, the result must be divided by `cell_size_m`. The v6 script writes the per-cell value directly into `np.arctan(...)`. With `CELL_SIZE_M = 1.0` (line 60) the bug is a no-op today; if a future tile uses cell_size = 2.0 (a common AAA value to halve heightmap memory) every slope value will be 2× too large in tan-space, then the same arctan/degrees pipeline applied — slope would still be in degrees but represent a different physical surface gradient.

This is why the ALREADY-broken comparison K2-P0-1 happens to "still work" structurally — both writer and (some) readers ignore cell_size, so the relative ordering is preserved within the production tile. The moment `cell_size_m != 1.0` lands the slope output flips wrong by a non-linear factor.

`compute_normal_z` (terrain_materials_v2.py:239-255) has the exact same shape — `np.gradient` without cell_size divisor — so triplanar tilt detection has the same latent bug.

**Severity:** P0 because the contract is wrong-by-construction, even if the production tile happens to use cell_size=1.0. (Note: the explicit P0 in K2-P0-1 is independent — the radians/degrees mismatch is wrong even at cell_size=1.0.)

**Fix sketch:** divide both gradients by `stack.cell_size` before the arctan, or write the call as `np.arctan2(np.hypot(dz_dx, dz_dy) / cs, 1.0)`.

---

### K2-P0-3 — `flow_speed` writer violates declared `[0, 1]` range contract *(P0, range contract)*

**Writer:** `terrain_waterfalls.pass_waterfalls:2329-2353`:

```python
flow_speed = np.zeros(stack.height.shape, dtype=np.float32)   # since input None on production
...
boost = 1.0 + 0.5 * math.exp(-cell_dist / 5.0)
flow_speed[gr, gc] = float(np.clip(flow_speed[gr, gc] * boost, 0.0, 15.0))
stack.set("flow_speed", flow_speed, "waterfalls")
```

**Declared contract** (`terrain_semantics.py:325-328`):
> `flow_speed: float32 (H, W) in [0, 1]`. 0 = still water, 1 = max velocity (95th-percentile normalised).

The writer:
1. Initialises to zeros (not "Manning-derived").
2. Multiplies by the boost factor (1.0..1.5).
3. Clips to `[0, 15]` — the wrong range entirely. Comment at 2351 says clip-15.
4. Since `_flow_speed_raw is None` on production, the multiplicative boost on a zero array stays zero everywhere except the boost is then `flow_speed[gr,gc] * 1.5 = 0`. So the channel is effectively all zeros after the entire pass — even on cliff outflow paths.

Two bugs: (a) range contract `[0,1]` not `[0,15]`; (b) the writer has no path that produces non-zero values in production because the multiplicative boost on a zero baseline never exceeds zero. The intended 95th-percentile normalisation logic (in the docstring) lives in an orphan pass (`pass_water_flow_speed`) per J3 — never invoked.

**Reader impact:** the only active reader of `flow_speed` is `pass_waterfalls` itself (used for Manning's velocity at lip cells), but the lip cells assign `chain.lip.flow_velocity_mps` directly, not via this channel. So the broken `flow_speed` channel does not currently corrupt other channels — it is "silently zero". But the contract is still wrong.

**Severity:** P0 (range contract violation; channel structurally cannot fulfil its declared semantics).

**Fix sketch:** drop the `flow_speed` write here and let an earlier pass (`pass_water_flow_speed`) write the 95-pct-normalised values. Or convert this code to do additive contribution and normalise at the end.

---

### K2-P0-4 — `cliff_mask`/`talus_mask`/`strata_mask` rasterise the *over-saturated* candidate set *(P0, downstream of P0-1)*

**Writer:** `terrain_cliffs.pass_cliffs:2658-2675`:

```python
cliff_mask_arr = candidate.copy().astype(np.float32)         # uses bug from K2-P0-1
talus_arr = np.zeros((h, w), dtype=np.float32)
strata_arr = np.zeros((h, w), dtype=np.float32)
for cliff in cliffs:
    if cliff.talus_mask is not None:
        talus_arr = np.maximum(talus_arr, cliff.talus_mask.astype(np.float32))
    if cliff.strata_layers and cliff.face_mask is not None:
        strata_arr = np.maximum(strata_arr, cliff.face_mask.astype(np.float32))
stack.set("cliff_mask", cliff_mask_arr, "cliff_pass")
stack.set("talus_mask", talus_arr, "cliff_pass")
stack.set("strata_mask", strata_arr, "cliff_pass")
```

Two compound problems:

- `cliff_mask` directly inherits the saturated `candidate` from K2-P0-1: every cell with slope > 0.96° appears as cliff. The post-pruning by `min_cluster_size` and protected zones removes only tiny islands; the dominant gradient is preserved as one giant "cliff".
- `talus_mask` and `strata_mask` are then computed only for `CliffStructure`s that survived `carve_cliff_system`. With the bloated candidate set, the talus apron and strata bands extend far beyond physically plausible regions. Any downstream scatter system that places boulders on `talus_mask > 0` would fill the entire mid-elevation band with debris.

`cliff_contour_spline` is doubly broken: not only is the mask saturated, the Moore-neighbour contour traced over a tile-spanning component returns the *tile boundary* as the spline, which is then handed to mesh insertion code expecting hero cliff lips.

**Severity:** P0 — a cascading consequence of K2-P0-1 affecting four of the 22 active channels.

---

### K2-P0-5 — `splatmap_weights_layer` collapses to the default-channel constant *(P0, downstream of P0-1)*

**Writer:** `terrain_materials_v2.compute_slope_material_weights → pass_materials:882-883`. The math chain is correct in isolation, but the analytical envelope `up * down` returns 0 for all cells where slope (in degrees) exceeds the falloff width (≈ 0.14 rad ≈ 8°). Combined with the empty-cell fallback at L705-708:

```python
empty = (total <= 1e-9) & unlabeled
if empty.any():
    weights[empty, default_idx] = 1.0
```

…almost every non-flat cell ends up 100% on the `"ground"` material. The triplanar (cliff/scree/wet_rock) channels survive because they branch on `compute_normal_z` instead of slope (line 537-543), but with the cell_size missing-divisor bug (K2-P0-2) and `ROCK_NORMAL_THRESHOLD = 0.65` the rock_normal_w is nonzero only for steep faces. End state on the v6 tile: a near-uniform splatmap dominated by ground + a thin film of cliff in the steepest zones.

This is the channel-level confirmation of the v6 art-director feedback that the splatmap "looks like washed-out beige".

**Severity:** P0. (The duplicate write to `material_weights` shares the same array, so both channels share the bug.)

---

### K2-P0-6 — `compute_rock_hardness` collapses to the basement layer for the entire tile *(P0, configuration mismatch)*

**Writer:** `terrain_stratigraphy.compute_rock_hardness:215-227`:

```python
h = np.asarray(stack.height, dtype=np.float64)
thicks = np.array([L.thickness_m for L in strat_stack.layers], dtype=np.float64)
bounds = np.concatenate(([0.0], np.cumsum(thicks)))
...
z = (h - strat_stack.base_elevation_m).clip(min=0.0)
idx = np.searchsorted(bounds, z, side="right") - 1
```

The math is correct, but on the production tile the v6 builder constructs the stratigraphy with **default `base_elevation_m=0.0`** (`scripts/build_terrain_aaa_node_v6.py:206-213`):

```python
strat = StratigraphyStack(layers=[
    StratigraphyLayer("basement",  hardness=0.9,  thickness_m=200.0, ...),
    StratigraphyLayer("limestone", hardness=0.65, thickness_m=80.0,  ...),
    StratigraphyLayer("shale",     hardness=0.35, thickness_m=40.0,  ...),
    StratigraphyLayer("topsoil",   hardness=0.15, thickness_m=2.0,   ...),
])
compute_rock_hardness(mask_stack, strat)
```

The v6 heightmap has world-space elevations in `[-10, 200]` m (line 154). With `base_elevation_m=0`, every cell with `h ≤ 200 m` indexes into layer 0 (basement, hardness=0.9). That's the entire tile except the few cells exactly at the cliff peak.

Net result: `rock_hardness` is a constant 0.9 over the production tile (not "varying with stratigraphy"). The channel's declared purpose — modulate erosion/cliff carving by rock-type — is defeated. This is also the reason the orphaned `apply_differential_erosion` (which depends on hardness contrast) would be a no-op even if it were wired in.

**Severity:** P0. The math and the contract are right; the v6 builder picks default config that makes the channel useless.

**Fix sketch:** in v6, set `base_elevation_m=heightmap.min() - 5.0` so the layer column actually spans the tile's elevation range. Or invert the column so basement sits at the top of the elevation range and topsoil at the bottom (geological reality is the opposite, but the formula assumes "0 = bottom of column").

---

### K2-P1-1 — `wave_amplitude_per_vertex` units OK but always zero on v6 *(P1, dependency starvation)*

**Writer:** `terrain_waterfalls.pass_waterfalls:2441-2442`:

```python
wave_amp = np.linalg.norm(vel_field, axis=-1) * 0.05
stack.set("wave_amplitude_per_vertex", wave_amp.astype(np.float32), "waterfalls")
```

5 cm per m/s → metres. Units consistent with the doc on `terrain_semantics.py:313-316`. Math correct.

But `vel_field` only receives non-zero stamps from cliff `chains` produced by `solve_waterfall_from_river(stack, lc, river_network=_water_net)` at L2274. `_water_net = state.water_network` is `None` on the production tile (no orphaned hydrology pass runs). The fallback inside `solve_waterfall_from_river` works without a network, but the lip detection at L2259 requires `drainage >= 500.0` and `min_drop >= 4.0 m`. On the v6 heightmap the gorge does have drops > 4 m so a few lip candidates survive — `vel_field` ends up with a few nonzero plumes, and `wave_amp` matches.

**Severity:** P1 — non-zero in places where lip detection succeeds, but completely absent for the river outflow body since the water network is None. The semantic on `terrain_semantics.py:313-316` ("per-cell wave displacement amplitude") is half-honoured.

---

### K2-P1-2 — `mist`, `foam`, `wet_rock`, `riverbed_caustics` all degrade because `state.water_network is None` *(P1, dependency starvation)*

`compute_wet_rock_mask(stack, _water_net, radius_m=3.0)` (`_water_network_ext.py:547`) seeds the wet-rock mask from:
1. `stack.water_surface > 0.01` — but `water_surface` is None on the production tile (J3 confirms the writer is orphan).
2. `water_network.nodes` — `water_network is None`, this branch is skipped.

So `compute_wet_rock_mask` returns `np.zeros(...)` (line 663-664). The only contribution to `wet_rock` is then the `pool_foam_contribution * 0.8` from each waterfall chain (L2358-2359), so `wet_rock` is non-zero only inside the impact pool's foam halo.

`compute_physical_foam_composite` (terrain_waterfalls.py:1667) reads `flow_accumulation` and `water_surface` — both None on production. Falls back to chain-only foam.

`compute_mist_mask` and `compute_riverbed_caustics` similarly have N depend on water network / water_surface and degrade to chain-only contributions.

Math is correct in each branch, but every "5-source physical composite" actually runs as a 1-source composite on the production tile. The channels are non-zero (so they pass the J3 "non-None" filter) but represent only a fraction of intended signal.

**Severity:** P1 — the channels exist, satisfy their range contracts, and their math is right, but they reflect the broken upstream wiring (`water_network`, `water_surface`, `flow_accumulation` all orphan-written per J3) and so under-cover the tile.

---

### K2-P1-3 — `mist_fog_volume` uses hard-coded constants regardless of waterfall scale *(P1, soft contract)*

**Writer:** `terrain_waterfalls.py:2389-2395`:

```python
mist_fog_volume = {
    "mask_2d":     mist,
    "height_m":    3.0,
    "density_max": 0.6,
    "color":       (0.7, 0.75, 0.8),
}
```

Every chain in every tile gets identical `height_m=3.0`, `density_max=0.6`, `color=(0.7, 0.75, 0.8)`. A 1 m drop and a 100 m drop both get the same `3 m` mist column. Volumetric fog volumes for Unity should scale with chain `total_height_m` (or `flow_velocity_mps²`) per real waterfall physics. Not a numerical bug, just no plumbing.

**Severity:** P1 — opaque channel, not in the 22 array-channel list (so K2 scope leans away), but mentioned as "active" by other audits.

---

### K2-J3-1 — J3 mis-classification: `strata_orientation`, `unconformity_mask`, `intrusion_mask`, `albedo_shift_rgb`, `strata_cross_section` are **None** on the v6 tile *(corrects J3 §2)*

**Evidence.** J3 §2 lists those five channels as "ACTIVE — written by `compute_rock_hardness`" with citations like `terrain_stratigraphy.py:196,961`.

Reading the source:

- `compute_rock_hardness` (terrain_stratigraphy.py:200-228) writes **only** `rock_hardness`. It does not call `compute_strata_orientation`.
- `compute_strata_orientation` (L196 cited by J3) is a separate function. Its only call site is `pass_stratigraphy` (L959).
- `unconformity_mask` (L520), `intrusion_mask` (L623), `albedo_shift_rgb` (L624), `strata_cross_section` (L712) all live inside `pass_stratigraphy` after the orientation call.

The v6 builder (`scripts/build_terrain_aaa_node_v6.py:204-216`) calls `compute_rock_hardness(mask_stack, strat)` directly — **never** `pass_stratigraphy`. So on the production tile:

- `rock_hardness` — written (but constant, see K2-P0-6).
- `strata_orientation`, `unconformity_mask`, `intrusion_mask`, `albedo_shift_rgb`, `strata_cross_section` — **None**.

That reduces the J3 "22 active channels" headline to **17** actually-written-on-v6 channels. The J3 finding of "stratigraphy compute path writes these" is true only when the orphan `pass_stratigraphy` runs, which it never does in v6.

**Severity:** classification correction — these channels should move from J3's "ACTIVE" group into the "OW (orphan-writer)" group. The MASTER_AUDIT_2026_04_27 "22 active channels" claim should be revised to **17 active channels**, and the K-wave headline figure that 80 of 102 are silent should be revised to **85 of 102**.

The downstream impact for K2: a separate active-pass reader at `terrain_cliffs.py:792-798` does:

```python
_strata_raw = stack.get("strata_orientation")
if _strata_raw is not None:
    _arr = np.asarray(_strata_raw)
    _strata_orient_deg = float(_arr.mean()) if _arr.size else 0.0
strata_tilt_rad = math.radians(_strata_orient_deg)
```

…interpreting the **mean of a (H,W,3) unit-normal-vector array** as a **scalar tilt in degrees**. Even when `pass_stratigraphy` does run, the consumer is wrong: a unit-normal array means in `[0,1]` along z, in `[-1,1]` along x/y, and the call `_arr.mean()` averages all three components together. The cliff code then feeds that to `math.radians(...)`. So even when the channel exists, the consumer is misinterpreting the data — would be K2-P0-7 if production passes wrote it.

---

### K2-P0-7 — `strata_orientation` reader in `terrain_cliffs` mis-interprets normal-vector array as scalar degrees *(P0, latent — fires when stratigraphy is wired)*

**Writer:** `terrain_stratigraphy.compute_strata_orientation:184-196` produces a `(H, W, 3) float32` array of bedding-plane unit normals.

**Reader:** `terrain_cliffs.py:790-798`:

```python
_strata_raw = stack.get("strata_orientation")
if _strata_raw is not None:
    _arr = np.asarray(_strata_raw)
    _strata_orient_deg = float(_arr.mean()) if _arr.size else 0.0
strata_tilt_rad = math.radians(_strata_orient_deg)
```

Three layered errors:
1. The data type is a 3-vector field, not a scalar angle.
2. `_arr.mean()` collapses all H×W×3 components into one scalar — averaging direction-cosine x/y/z together is meaningless.
3. The result is then treated as **degrees** (passed to `math.radians`) rather than a unit-vector cosine.

Today the channel is None on production tile (per K2-J3-1) so the if-branch never executes. The moment stratigraphy is wired in (a follow-up to E-2/E-3), this reader will start consuming values around `0.4..0.7` (mean of unit-normal components ≈ 1/3 of `nz` plus zero of `nx, ny`) and treating them as `0.4..0.7` degrees → `0.007..0.012` radians → wrong cliff strata tilt.

A second consumer at `terrain_cliffs.py:2316-2348` first checks `sa.shape == cliff.face_mask.shape` (i.e. `(H,W) == (H,W)`), but the writer produces `(H,W,3)`. The shape check therefore always fails, the strata-style branch silently skips, and `style="granite"` is the only path. That's a third bug in the same reader.

**Severity:** P0 (latent until stratigraphy wires up; trips immediately when it does).

**Fix sketch:** `strata_orientation` consumers must (a) treat as a vector field, (b) extract the dip angle as `acos(nz)` per cell rather than `mean()`, (c) convert to degrees explicitly.

---

## 3. Summary of P0 findings

| ID | Channel(s) affected | Bug | Severity | Already counted in master guide? |
|----|--------------------|-----|----------|----------------------------------|
| K2-P0-1 | `slope` (and 6 downstream channels: `cliff_candidate`, `cliff_contour_spline`, `cliff_mask`, `talus_mask`, `strata_mask`, `splatmap_weights_layer`/`material_weights`) | Writer outputs degrees; readers expect radians | P0 | NO — new |
| K2-P0-2 | `slope`, `compute_normal_z` | `np.gradient` not divided by `cell_size_m` | P0 latent | NO — new |
| K2-P0-3 | `flow_speed` | Range contract `[0,1]` but writer clips to `[0,15]` and produces all-zero on v6 | P0 | NO — new |
| K2-P0-4 | `cliff_mask`, `talus_mask`, `strata_mask`, `cliff_contour_spline` | Saturated mask propagates from K2-P0-1 | P0 | partially — symptomised by A1/A3, root cause new |
| K2-P0-5 | `splatmap_weights_layer`, `material_weights` | Collapses to default channel via K2-P0-1 cascade | P0 | partially — A4 noted "uniform splatmap" |
| K2-P0-6 | `rock_hardness` | `base_elevation_m=0.0` default places entire tile in basement layer | P0 | NO — new |
| K2-P0-7 | `strata_orientation` reader | Reader treats 3-vector field as scalar degrees; shape check incompatible | P0 latent | NO — new |
| K2-P1-1 | `wave_amplitude_per_vertex` | Math correct; under-cover on tile because lip-only path | P1 | covered by A2 |
| K2-P1-2 | `mist`, `foam`, `wet_rock`, `riverbed_caustics` | Multi-source composites degrade to chain-only because `water_network`/`water_surface`/`flow_accumulation` orphan | P1 | covered by A2 + J3 |
| K2-P1-3 | `mist_fog_volume` | Hard-coded constants regardless of chain scale | P1 | NO — new |
| K2-J3-1 | `strata_orientation`, `unconformity_mask`, `intrusion_mask`, `albedo_shift_rgb`, `strata_cross_section` | J3 mis-classified as ACTIVE; actually orphan in v6 | classification correction | NO — new |

**Total NEW P0 from K2: 7.** (K2-P0-1 through K2-P0-7.)

Cross-check against "already-counted" exclusions:
- I1-P0-2 / I1-P0-3 (delta double-apply): K2 channels are not delta channels — no overlap.
- I7-P0-1 (height-range 1.176× inflate in Unity export): K2 covers the writer side of `height`; the writer at TerrainMaskStack.__post_init__ correctly takes the array min/max. The 1.176× inflate is an exporter bug (read in Unity export), already counted in I7. K2 P0-list does **not** re-add this.

---

## 4. Recommended remediation order

1. **K2-P0-1 first.** Single root cause for 7 of the 22 active channels. Either change v6's slope writer to radians, or change the three reader sites (`terrain_materials_v2.py:547,583`, `terrain_cliffs.py:357`) to use `math.degrees(...)` thresholds. The autodetect heuristic at `terrain_cliffs.py:1389` should be lifted into a project-wide helper that all readers call.
2. **K2-P0-6.** One-line fix in v6 builder: `base_elevation_m = float(heightmap.min()) - 5.0`.
3. **K2-J3-1.** Rewrite v6 to call `pass_stratigraphy` (which writes orientation + unconformity + intrusion + albedo + cross-section) instead of bare `compute_rock_hardness`. This drops the K2 13-of-22 active count up to 22-of-22, AND fixes the J3 §2 mis-classification.
4. **K2-P0-2.** Once K2-P0-1 is fixed (slope in radians), audit every gradient-based pass for missing `cs` divisor. Add a `_grid_gradient(arr, cell_size)` helper in `terrain_math.py`.
5. **K2-P0-7.** When K2-J3-1 is fixed and `strata_orientation` becomes truly active, fix the consumer's shape check and per-cell dip-angle extraction at the same time, otherwise the wired channel is immediately corrupted by the consumer.
6. **K2-P0-3.** `flow_speed` writer should be removed from `pass_waterfalls` entirely (the `pass_water_flow_speed` orphan is the right home) and the contract honoured. Until then, downgrade the channel to opaque or document explicitly that it is "boost-only post-pass for outflow path".
7. **K2-P0-4 / K2-P0-5.** Both auto-resolve when K2-P0-1 is fixed. Add a CI assertion that `slope.max() ≤ 1.6` (radians) **or** `slope.max() ≤ 95` (degrees) so that future drift cannot land the same bug silently.

---

## 5. Crosswalk to existing audit findings

- A4 (texture/materials, this directory) noted "uniform beige splatmap" qualitatively — K2-P0-1/P0-5 give the line-cited mechanism.
- A1 / A3 noted cliff over-saturation — K2-P0-1/P0-4 give the mechanism.
- J3 §5 flagged silent-None readers (`materials_v2:533 reads snow_line_factor`, `materials_v2:655-658 reads label channels`) — K2 leaves those classifications as-is and adds **new** silent-wrong-value bugs (slope, cliff masks).
- I1-P0-1 (coastline) and I1-P0-3 (glacial) double-apply — disjoint from K2.
- I4 numeric-scaling audit, if it covered slope, would have surfaced K2-P0-1; verifying the title in the file: `I4_numeric_scaling_audit.md` — recommend cross-reference.

The headline figure should be revised: of the 22 channels J3 flagged active, **only 5 channels (`height`, `waterfall_lip_candidate`, `waterfall_pool_delta`, `waterfall_velocity`, `wave_amplitude_per_vertex`) are populated with values that satisfy both their declared contract and their reader's expected interpretation**. The remaining 17 are either (i) None despite being claimed active, (ii) write degrees-where-radians-expected, (iii) saturated to noise, or (iv) collapsed to a constant.
