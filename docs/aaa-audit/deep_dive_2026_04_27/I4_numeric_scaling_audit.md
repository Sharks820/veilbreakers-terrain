# I4 — Numeric Scaling & Unit Conversion Audit

**Date:** 2026-04-27
**Scope:** Hydraulic erosion, water network, waterfalls, Unity export, foam/mist,
cliffs, wind field, atmosphere, splatmap/heightmap quantisation.
**Method:** Targeted ripgrep sweeps for `* 1e-3 / 1e-3 * 0.001 / 1000 * 1000`,
followed by file-level reads of every hit in physics-bearing modules.

P0 = breaks output by ≥10× (production blocker).
P1 = breaks output by 2–10× or causes shipped-quality regression.
P2 = calibration smell, output still in plausible range.
P3 = stylistic / documentation drift.

---

## P0 — confirmed production bugs (≥10× wrong)

### I4-P0-1 — `_terrain_erosion.py:308`  erodibility ÷ 1e-3 (1000× amplification)
```
_erod_scale = np.clip(erod_arr, 0.0, None) / 1e-3
```
`erod_arr` ships values in roughly [0, 1] (relative hardness/softness map).
Dividing by `1e-3` yields `_erod_scale ∈ [0, 1000]`. That value is then *multiplied*
into `erode_amount` at line 439:
```
erode_amount *= float(_erod_scale[iy, ix])
```
A "soft" cell (erodibility = 1.0) erodes 1000× the unscaled rate; a "hard" cell
(erodibility = 0.5) erodes 500× the unscaled rate. The intent (per the comment at
lines 306-307: "uniformly hard tile must erode less than a uniformly soft tile, not
collapse to the same mean") implies a multiplicative scaling in [hard < 1 < soft].

**Correct expression** (multiplicative, normalised around 1.0):
```python
_erod_scale = np.clip(erod_arr, 0.0, None) * 1e-3   # if intent is dampening
```
or, more likely, the bug is the `/` itself:
```python
_erod_scale = np.clip(erod_arr, 0.0, None)          # already in [0, 1]; multiply directly
```
**Status:** confirmed by A3 audit; tracked as E-1 in the master guide. Severity P0.

---

### I4-P0-2 — `terrain_unity_export.py:1914-1918`  tree positions sent as `metres × 0.85`
```python
"position": _zup_to_unity_vector([
    _apply_unity_scale(float(row[0])),
    _apply_unity_scale(float(row[1])),
    _apply_unity_scale(float(row[2])),
]),
```
Unity's `TreeInstance.position` is documented as a *normalised* `[0, 1]` value
inside the terrain's local space (`pos.x ∈ [0, 1]` maps to `x = pos.x * terrainData.size.x`).
The code emits world-space metres scaled by `UNITY_SCALE_FACTOR = 0.85`.

For a 1024 m tile, an instance at world (512, 0, 512) is exported as
`(435.2, 0, 435.2)` instead of `(0.5, 0, 0.5)`. Trees land hundreds of metres
beyond the terrain bounds and Unity culls them, or — worse — they pass the
out-of-bounds check at line 1895 because `tile_min_x ≤ row[0] ≤ tile_max_x`
is verified pre-scale, then mangled post-scale.

**Correct expression** (normalised tile coords):
```python
norm_x = (float(row[0]) - tile_min_x) / max(tile_max_x - tile_min_x, 1e-9)
norm_z = (float(row[1]) - tile_min_y) / max(tile_max_y - tile_min_y, 1e-9)
norm_y = (float(row[2]) - height_min) / max(height_max - height_min, 1e-9)
"position": [norm_x, norm_y, norm_z],   # Unity Y-up, Y from height
```
**Status:** confirmed by prior audits. Severity P0.

---

## P1 — likely wrong (2–10× off, ships visible damage)

### I4-P1-1 — `terrain_waterfalls.py:610`  depth proxy from drainage cells
```python
depth_est = max(0.5, min(3.0, drain_val / 1000.0))
```
`drain_val` is the upstream cell count from the D8 flow accumulation; dividing
by a literal `1000.0` (whose origin is undocumented) and clamping to `[0.5, 3.0]`
metres gives a depth that is constant over almost the entire drainage range:
- drain_val < 500 → depth = 0.5
- 500 ≤ drain_val ≤ 3000 → linearly between 0.5 and 3.0
- drain_val > 3000 → depth = 3.0 (saturates immediately)

For a 1024² tile, mid-channel cells routinely have drain_val > 3000, so depth
is **always** clamped at 3.0 m and stops varying with flow. `r_hyd = sqrt(depth_est)`
becomes a constant `1.732`, breaking the Manning velocity term that depends on it.

**Fix:** derive depth from `_compute_river_depth(drain_val)` (used elsewhere in
`_water_network.py`), or scale by cell area not raw cell count.

Severity P1 — affects every secondary tier of every waterfall chain.

---

### I4-P1-2 — `terrain_waterfalls.py:421-436`  rational discharge formula off by ~300×
```python
def _estimate_discharge(drainage_cells, cell_size_m) -> float:
    area_km2 = (drainage_cells * cell_size_m * cell_size_m) / 1_000_000.0
    Q = 0.001 * (max(area_km2, 1e-6) ** 0.7)
    return float(np.clip(Q, 0.01, 5000.0))
```
The standard rational-method discharge is `Q = C·i·A` with `C ∈ [0.1, 0.9]`,
`i` rainfall intensity in m/s. For a 1 km² alpine catchment with 50 mm/h rain,
`Q ≈ 0.5 × 0.5 × (50 / 3.6e6) × 1e6 ≈ 7 m³/s`. This formula returns
`Q = 0.001 × 1.0 = 0.001 m³/s` for the same area — **3 orders of magnitude
too small**. A 100 km² basin yields `Q = 0.001 × 100^0.7 ≈ 0.025 m³/s`
(reality: ~50 m³/s).

The `np.clip(..., 0.01, 5000.0)` floor masks the symptom — every small/medium
basin gets the **floor value** of 0.01 m³/s. Mason (1985) plunge-pool depth
becomes `0.664 × sqrt(H) × 0.01^0.33 ≈ 0.14 × sqrt(H)`, so plunge pools are
~3× too shallow at every waterfall under ~1000 km² drainage area.

**Fix:** use `Q = 0.278 × C × i × A_km2` (SI metric form, C≈0.5, i in mm/h)
or `Q = K × A_km2^0.8` with K ≈ 0.4–1.0 for AAA-scale rivers.

Severity P1 — every plunge-pool size, foam intensity, and Unity discharge
field is silently clipped to the floor.

---

### I4-P1-3 — `terrain_unity_export.py:1542-1549`  `cell_size`, origins, height range scaled by 0.85 but `tile_size` is not
```python
"cell_size": _apply_unity_scale(float(stack.cell_size)),                 # × 0.85
"world_origin_x_m": _apply_unity_scale(float(stack.world_origin_x)),     # × 0.85
"world_origin_y_m": _apply_unity_scale(float(stack.world_origin_y)),     # × 0.85
"height_min_m": _apply_unity_scale(float(stack.height_min_m))            # × 0.85
"height_max_m": _apply_unity_scale(float(stack.height_max_m))            # × 0.85
"tile_size": int(stack.tile_size),                                       # NOT scaled (count, not metres)
```
`tile_size` is a sample count (dimensionless), so leaving it unscaled is correct.
But downstream the bridge JSON computes:
```python
# line 981-982
"terrain_size_x_m": float(int(manifest["tile_size"]) * float(manifest["cell_size"])),
```
After scaling, `cell_size` is already `0.85 × original`. So `terrain_size_x_m`
ends up as `0.85 × original_terrain_size`. That is consistent with "all metres
× 0.85 before serialisation," but every other physics-bearing field on the stack
(splatmaps, heightmap raw, normals) is **not** rescaled. Result: the heightmap
RAW stretches across `0.85 × terrain_size` in Unity, but the terrain texture
samples assume `1.0 × terrain_size`. This is a **subtle but systemic 15%
mismatch between heightmap geometry and the splatmap atlas** in the Unity
import. UVs land 15% off-tile.

**Fix:** either drop `UNITY_SCALE_FACTOR` entirely (since metric metres = Unity
units in current Unity 6 / HDRP defaults) or apply it consistently to **every**
spatial field — including splatmap UV scale, foliage instance positions
(after computing normalised tile coords), and audio zone radii.

Severity P1 — caused or partially caused by the same 0.85 factor that drives
I4-P0-2.

---

## P2 — calibration smells (output stays plausible but the formula is wrong)

### I4-P2-1 — `terrain_caves.py:355, 362`  drip rate double-counted
```python
(base_growth_m * damp_arr * jitter * float(drip_rate_per_year / 1000.0))
```
`base_growth_m` already incorporates `total_flux × simulation_years` (line 332,
337). Then the per-cell line multiplies by `drip_rate_per_year / 1000.0`. If
`drip_rate_per_year` is in physical units (drips/yr ≈ 10²–10⁵), this divisor
makes the term roughly O(0.1–100), arbitrarily reshaping growth.

The clamp `np.clip(..., 0.0, 20.0)` at line 367 hides the symptom — almost any
input pegs at the 20 m cap.

**Fix:** drop the second `drip_rate_per_year / 1000.0` factor; it duplicates
information already in `base_growth_m`.

Severity P2 — caves still get stalactites, but the simulation isn't physically
controlled.

---

### I4-P2-2 — `_terrain_world.py:1398`  threshold mixes absolute metres and tile fraction
```python
min_range_threshold = max(tile_size * 0.001, 1e-4)
```
For a 1024 m tile this gives `max(1.024, 1e-4) = 1.024 m`. For a 64 m tile
it gives `0.064 m`. Whether that is intended (1‰ of tile span) or accidental
is undocumented. Low-impact but flagged for review.

Severity P2.

---

### I4-P2-3 — `terrain_audio_zones.py:744, 853, 860`  s→ms conversion ok, but 853 mixes mean+raw
Three call sites convert seconds → milliseconds via `× 1000.0`. All three are
correct dimensionally, but line 853 multiplies a pre-aggregated mean by 1000
without adjusting the variance similarly — downstream consumers reading the
zone metadata may misinterpret the dispersion. Cosmetic.

Severity P3.

---

## P3 — verified-correct call sites (documented for completeness)

| File:line | Expression | Verdict |
| --- | --- | --- |
| `terrain_unity_export.py:97, 194` | `np.round(norm * 65535.0).astype(np.uint16)` after `(h - lo) / (hi - lo)` clip to `[0,1]` | Correct uint16 quantisation; height range recorded in manifest. |
| `terrain_unity_export.py:1100-1119` | `total_weight = weights.sum(axis=2); weights_norm = weights / safe_total; rint(padded * 255)` | Splatmap layer weights normalised to sum-1 before uint8 quantisation, matching Unity's `SetAlphamaps` contract. |
| `terrain_unity_export.py:117-125`, `_compute_terrain_normals_zup` | `np.stack((-dzdx, -dzdy, 1), axis=-1) / length`, then `_zup_to_unity_vectors` swaps Y↔Z | World-space float32 normals; not re-encoded to `[0,1]`. Note: D-sweep flagged this as "world-space normals export broken" — confirmed normals are emitted as raw float32, not packed `(n*0.5+0.5)*255`. If the Unity-side importer expects a packed `_NormalMap`, this is a separate pipeline contract bug, not a numeric scaling error. |
| `_water_network.py:1942-1985` | Manning discharge `Q = (1/n) · A · R^(2/3) · √S` | Correct SI form. |
| `terrain_waterfalls.py:347-361` | Manning velocity `V = (1/n) · R^(2/3) · √S`, clamp [0.01, 15] m/s | Correct. |
| `terrain_waterfalls.py:364-395` | Freefall `t_impact = v_v/g + sqrt((v_v/g)² + 2H/g)` | Correct kinematics. |
| `terrain_waterfalls.py:398-418` | Mason 1985 `r = 0.45·sqrt(H·sqrt(Q))`, `d = 0.664·sqrt(H)·Q^0.33` | Comment says `Q^0.5`, code computes `sqrt(Q)` — equivalent. Correct. |
| `_water_network.py:777-785` | `assert max_slope < 10.0` guard against radian-encoded slope | Correct unit-convention guard. |
| `_terrain_world.py:1398` | `1e-4` floor against zero-range divisions | Correct degenerate-case guard. |
| `terrain_negative_space.py:256, 269` | `kde_mass / (area_m2 / 1000.0)` | Returns features per 1000 m² — matches consumer `max_feature_density_per_1000m2` budget at line 361. Correct. |
| `terrain_caves.py:324` | `C_Ca_mol_per_m3 = ca_concentration_mol_per_l * 1000.0` | Correct mol/L → mol/m³ conversion. |
| `terrain_scatter_points.py:243-245` | `int(round(point.position[i] * 1000.0))` for hashing | mm-resolution spatial hash; not a physics conversion. Correct. |

---

## Negative results — areas checked, no scaling bugs found

- Atmosphere/sky: no `terrain_sky.py` or `atmospheric_volumes.py` handler exists
  in the production handler set; the only references to atmospheric scattering
  are in `procedural_materials.py` and tests, both of which use authored
  preset values (no Rayleigh/Mie unit conversions to audit).
- Cliffs: `terrain_cliffs.py` consistently uses metres for `profile_height`,
  `overhang` extents (0.3–1.2 m at line 19), and `ledge` widths. `cos(60°)`
  threshold for overhang detection is dimensionless. No scaling errors.
- Foam: `_water_network_ext.py:711-829` uses dimensionless ratios
  (`fa / foam_threshold`, `slope / 0.3`, `slope_mod`), all correctly clamped
  to [0, 1]. No bug.
- Heightmap u16: `_quantize_heightmap` correctly maps `[height_min_m, height_max_m]`
  → `[0, 65535]` and the bridge JSON records the range so Unity can invert.

---

## Cross-reference summary (sorted by severity)

| ID | File:line | Bug | Severity |
| --- | --- | --- | --- |
| I4-P0-1 | `_terrain_erosion.py:308` | `/ 1e-3` should be `*` or removed (1000× too aggressive) | P0 |
| I4-P0-2 | `terrain_unity_export.py:1914-1918` | tree positions in metres × 0.85 instead of 0..1 normalised tile coords | P0 |
| I4-P1-1 | `terrain_waterfalls.py:610` | `drain_val / 1000.0` saturates to 3.0 m for typical drainage | P1 |
| I4-P1-2 | `terrain_waterfalls.py:421-436` | `Q = 0.001 × A^0.7` is ~300× too small; clip floor masks it | P1 |
| I4-P1-3 | `terrain_unity_export.py:1542-1549` | UNITY_SCALE_FACTOR=0.85 applied inconsistently across spatial fields | P1 |
| I4-P2-1 | `terrain_caves.py:355, 362` | `drip_rate_per_year / 1000.0` double-counts already-baked drip rate | P2 |
| I4-P2-2 | `_terrain_world.py:1398` | undocumented 1‰-of-tile-size threshold | P2 |
| I4-P3-1 | `terrain_audio_zones.py:853` | mean × 1000 without variance update — cosmetic | P3 |

---

## Recommended next actions

1. **Fix I4-P0-1 and I4-P0-2 immediately** — both already in the master guide
   as E-1 and W-1 respectively.
2. **I4-P1-2 (rational discharge)** is high-impact but easy to fix; it cascades
   into Mason plunge-pool depth, foam intensity, and Unity water shader
   discharge fields. Recommend `Q = 0.4 × A_km2^0.8` as a 1-line patch.
3. **I4-P1-3 (UNITY_SCALE_FACTOR)** — re-evaluate whether the 0.85 conversion
   is still required at all. Modern Unity / HDRP uses metric metres; this
   factor is a 2024-era hack. Removing it is the cleanest fix.
4. **I4-P1-1 (depth_est saturation)** — replace with `_compute_river_depth(drain_val)`
   which already handles the dimensional conversion correctly.
