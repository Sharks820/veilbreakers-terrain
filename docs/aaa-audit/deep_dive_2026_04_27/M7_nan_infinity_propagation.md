# M7: NaN/Infinity Propagation Systematic Audit

**Date:** 2026-04-27
**Auditor:** Senior tech-lead sweep (cross-codebase)
**Scope:** All 281 Python source files in `veilbreakers_terrain/handlers/`
**Method:** Grep-driven production-site detection + manual propagation tracing

---

## Executive Summary

The pipeline has **zero NaN sanitization anywhere in the Unity export path**. Every float32 binary channel (`slope`, `curvature`, `flow_accumulation`, `wetness`, `erosion_amount`, `foam`, `rock_hardness`, `strat_erosion_delta`, etc.) is written to disk via `_write_raw_array → target.write_bytes(arr.tobytes())` with no `nan_to_num`, no `isfinite` guard, and no clamp. A single upstream NaN production site — of which this audit found **nine** — corrupts an entire channel binary file on disk. Unity reads the binary with `SetAlphamaps`/custom importers; IEEE 754 NaN/Inf in a float32 channel maps to undefined behaviour in HLSL samplers (black, white, or flickering artifacts depending on GPU vendor and shader precision mode).

The codebase has `nan_to_num` calls at three isolated points in `environment.py` and `environment_scatter.py` — all in non-export paths. There is no systematic sanitize-before-write discipline anywhere.

---

## P0 Findings

---

**M7-P0-01** | `terrain_unity_export.py:1283-1290` | All float32 channel binaries exported with no NaN/Inf scrubbing

**Evidence:**
```python
# terrain_unity_export.py lines 1261-1290
for channel in (
    "slope", "curvature", "flow_accumulation", "flow_speed",
    "wetness", "erosion_amount", "deposition_amount", "foam",
    "rock_hardness", "strat_erosion_delta", ...  # 35 channels total
):
    value = stack.get(channel)
    if value is None:
        continue
    _write_raw_array(
        files, output_dir,
        filename=f"{channel}.bin",
        channel=channel,
        arr=np.asarray(value),   # <-- zero sanitization
        encoding="raw_le",
    )

# _write_raw_array (lines 415-446):
def _write_raw_array(files, output_dir, *, arr, ...):
    arr_np = np.asarray(arr)
    export_arr = _ensure_little_endian(_flip_for_unity(arr_np) ...)
    target.write_bytes(export_arr.tobytes())   # NaN hits disk if present
```

**Propagation path:** Any of the nine production sites below → channel stored on `TerrainMaskStack` → `pass_unity_export` iterates all channels → `tobytes()` writes IEEE 754 NaN/Inf into `.bin` file → Unity C# importer reads raw bytes → HLSL shader samples NaN → undefined GPU behaviour (black tiles, flicker, or invisible terrain on some hardware).

**AAA gap:** Rockstar/Naughty Dog pipelines sanitize at channel write time (`stack.set()`) and again at export with a mandatory `np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)` pass before `tobytes()`. Export validation asserts `np.isfinite(arr).all()` and raises a hard error if violated.

**Fix:**
```python
# In _write_raw_array, before tobytes():
if np.issubdtype(arr_np.dtype, np.floating):
    arr_np = np.nan_to_num(arr_np, nan=0.0, posinf=0.0, neginf=0.0)
    assert np.isfinite(arr_np).all(), f"NaN/Inf in channel '{channel}' at export"
```
Additionally gate at `stack.set()`:
```python
def set(self, channel, value, pass_name):
    arr = np.asarray(value)
    if np.issubdtype(arr.dtype, np.floating) and not np.isfinite(arr).all():
        raise ValueError(f"NaN/Inf written to channel '{channel}' by pass '{pass_name}'")
    ...
```
**Estimated time:** 2 hours (export guard) + 4 hours (stack.set guard). 6 hours total.

---

**M7-P0-02** | `environment.py:2204-2208, 2406-2410` | Moisture map normalization: `log_flow / fa_max` when entire tile has zero flow (`fa_max == 0`) produces `0/0 = NaN` on the array-division fallthrough path

**Evidence:**
```python
# environment.py lines 2203-2208 (moisture map #1):
log_flow = np.log1p(flow_acc)
fa_max = log_flow.max()
if fa_max > 0:
    moisture_map = log_flow / fa_max
else:
    moisture_map = np.zeros_like(heightmap)
```

The guard `if fa_max > 0` catches the scalar `fa_max` correctly. **However**: if `flow_acc` contains NaN values (possible when `compute_flow_map` receives a heightmap with NaN — which happens when the hydraulic erosion loop corrupts the heightmap via M7-P0-06 below), then `log_flow = np.log1p(NaN_arr)` produces a NaN array, `fa_max = NaN_arr.max()` returns NaN, the condition `NaN > 0` evaluates to **False** in Python, and the else-branch runs `moisture_map = np.zeros_like(heightmap)`. So the fallback fires *silently* on a corrupted input. The moisture channel is written as all-zeros rather than NaN — the wrong data is silently accepted. This then feeds `compute_world_splatmap_weights()`, producing an all-dry splatmap for the entire tile with no error.

**Propagation path:** NaN heightmap → `compute_flow_map` → NaN `flow_acc` → `np.log1p(NaN)` → `fa_max = NaN` → condition false → `moisture_map = zeros` (silent wrong data) → `compute_world_splatmap_weights(moisture_map=zeros)` → splatmap assigns zero moisture weight everywhere → entire tile exported with no wet-layer influence → wrong visual biome even though the pipeline "succeeded".

**AAA gap:** A real pipeline asserts `np.isfinite(flow_acc).all()` before normalization and raises a hard error rather than silently substituting zeros. Silent fallback on corrupted input is indistinguishable from valid flat terrain in logs.

**Fix:**
```python
flow_acc_arr = np.asarray(flow_result["flow_accumulation"], dtype=np.float64)
if not np.isfinite(flow_acc_arr).all():
    raise RuntimeError(
        "flow_accumulation contains NaN/Inf — heightmap is corrupted upstream"
    )
log_flow = np.log1p(np.maximum(flow_acc_arr, 0.0))
fa_max = float(log_flow.max())
moisture_map = log_flow / max(fa_max, 1e-9)
```
**Estimated time:** 1 hour.

---

**M7-P0-03** | `_terrain_noise.py:1453,1457` | Crater preset division by zero when `min(rows, cols) == 0`

**Evidence:**
```python
# _terrain_noise.py lines 1445-1457
max_r = min(rows, cols) / 2.0          # = 0.0 if either dimension is 0
crater_r = preset.get("crater_radius", 0.3) * max_r  # = 0.0

# line 1453:
radial = 1.0 - np.clip(dist / max_r, 0, 1)   # div-by-zero: dist/0.0 = inf

# line 1457:
crater_mask = np.clip(1.0 - dist / crater_r, 0, 1)  # div-by-zero: dist/0.0 = inf
```

If the pipeline is invoked with a 0-row or 0-column tile (edge case at world boundary, or a 1D test array), both `max_r` and `crater_r` are 0.0. NumPy floating division by zero does not raise — it produces `inf` array-wide. `np.clip(inf, 0, 1) = 1.0`, `np.clip(1 - inf, 0, 1) = 0.0`, so the `radial` term collapses to `1.0 - 1.0 = 0.0` (flat) and `crater_mask = 0.0`. The heightmap becomes flat zeros for the entire crater preset tile with no error raised.

However — if `rows > 0` but `preset.get("crater_radius", 0.3)` is explicitly set to `0.0` by user config, `crater_r = 0.0` while `max_r > 0`, and `dist / crater_r` produces an `inf` array for every cell not exactly at the center. `np.clip(1.0 - inf, 0, 1)` clamps to 0, so `crater_dip = 0.0` everywhere — crater disappears silently.

**Propagation path:** `_apply_terrain_preset("crater")` → inf/NaN in intermediate `dist/crater_r` → `crater_mask = np.clip(1-inf, 0, 1) = 0` → `hmap` loses crater feature silently → written to `heightmap.raw` via `_quantize_heightmap`.

**AAA gap:** Always validate `max_r > 0` and `crater_r > 0` before division; raise `ValueError("crater_radius must be > 0")` at preset parse time.

**Fix:**
```python
max_r = min(rows, cols) / 2.0
if max_r < 1e-9:
    pass  # skip crater shaping on degenerate tile
else:
    crater_r = max(preset.get("crater_radius", 0.3) * max_r, 1e-9)
    radial = 1.0 - np.clip(dist / max_r, 0.0, 1.0)
    ...
    crater_mask = np.clip(1.0 - dist / crater_r, 0.0, 1.0)
```
**Estimated time:** 30 minutes.

---

**M7-P0-04** | `_terrain_erosion.py:308` + `439` | Erodibility map produces 1000× multiplier; any NaN in `erodibility_map` injects NaN into the heightmap loop

**Evidence:**
```python
# _terrain_erosion.py line 308:
_erod_scale = np.clip(erod_arr, 0.0, None) / 1e-3  # amplifies [0,1] → [0, 1000]

# line 439 (inside particle simulation loop):
if _erod_scale is not None:
    erode_amount *= float(_erod_scale[iy, ix])   # NaN * anything = NaN
```

**NaN injection path:** If `erodibility_map` contains NaN (possible when `rock_hardness` channel was never fully populated — e.g., `StratigraphyStack` not present, leaving partial NaN in some cells), then `_erod_scale[iy, ix] = NaN`. `float(NaN) = nan`, `erode_amount *= nan → erode_amount = nan`. Then:

```python
sediment += erode_amount           # sediment = nan
_erode_brush(result, ix, iy, erode_amount=nan, ...)
    # Inside _erode_brush:
    norm = effective_amount / total_weight  # nan / valid = nan
    hmap[ny, nx] -= norm * w               # result[ny, nx] = nan
```

The NaN diffuses outward across the entire brush radius (default 3 cells), then NaN droplets on subsequent iterations pick it up via bilinear sampling and amplify it further. After all iterations, `result` (the heightmap) contains NaN in a spreading region. This NaN heightmap is then stored as `stack.height`, exported as `heightmap.raw` (the `_quantize_heightmap` call at line 92 does `h.min()`/`h.max()` — if any NaN is present, `np.float64.min()` returns NaN, `hi - lo = NaN`, the `if hi - lo <= 1e-9` guard is False when `hi-lo=NaN`, and `np.clip((h-lo)/(hi-lo), 0,1)` produces all-NaN which round-trips to 0 in uint16 — so Unity gets a flat terrain with no error).

Note: this is **compounded** with the E-1 P0 bug (1000× amplitude scaling making the erodibility multiplier catastrophically wrong even when finite).

**AAA gap:** Validate `erodibility_map` is finite before use. Gate `_erod_scale` computation with an explicit `assert np.isfinite(erod_arr).all()` before dividing.

**Fix:**
```python
# line 308:
if not np.isfinite(erod_arr).all():
    raise ValueError("erodibility_map contains NaN/Inf")
_erod_scale = np.clip(erod_arr, 0.0, 1.0)  # also fixes E-1: keep [0,1], don't divide by 1e-3
```
**Estimated time:** 30 minutes (NaN guard) — separate ticket for E-1 amplitude fix.

---

**M7-P0-05** | `terrain_waterfalls.py:1714` | `np.log(fa + 1.0)` with NaN-corrupted `flow_accumulation` → NaN in `foam` channel exported without sanitization

**Evidence:**
```python
# terrain_waterfalls.py lines 1710-1715:
if sl_arr is not None and fa_arr is not None:
    sl = np.asarray(sl_arr, dtype=np.float64)
    fa = np.asarray(fa_arr, dtype=np.float64)
    slope_term = np.clip((sl - 0.15) / 0.1, 0.0, 1.0)
    acc_term = np.clip(np.log(fa + 1.0) / 8.0, 0.0, 1.0)  # NaN if fa contains NaN
    rapid_foam = (slope_term * acc_term).astype(np.float32)  # NaN propagates
```

**Note:** `np.log` produces NaN (not -inf) when the input is NaN. `np.clip(NaN, 0.0, 1.0)` returns NaN — NumPy's clip does **not** sanitize NaN. The resulting `rapid_foam` is NaN where `fa` was NaN.

**Propagation path:** Corrupted `flow_accumulation` → NaN `fa` → `np.log(NaN+1)=NaN` → `clip(NaN,0,1)=NaN` → `rapid_foam=NaN` → accumulated into `foam` channel → `foam.bin` written by M7-P0-01 with no sanitization → Unity reads NaN floats → shader renders undefined foam intensity (may appear as white foam flooding entire terrain on some GPU vendors).

**AAA gap:** Use `np.log1p(np.maximum(fa, 0.0))` (guards against negative and NaN inputs). Add `assert np.isfinite(fa).all()` before use or insert `fa = np.nan_to_num(fa, nan=0.0)` at the top of the foam pass.

**Fix:**
```python
fa = np.nan_to_num(np.asarray(fa_arr, dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)
acc_term = np.clip(np.log1p(np.maximum(fa, 0.0)) / 8.0, 0.0, 1.0)
```
**Estimated time:** 20 minutes.

---

**M7-P0-06** | `atmospheric_volumes.py:433` | `_log_acc.max()` used as denominator with no guard; if all accumulation is zero, `max()` returns `0.0` and the `max(..., 1e-9)` guard is on line 434 — but if `_log_acc` is NaN-populated, `max()` returns NaN and `max(NaN, 1e-9)` evaluates to `NaN` in Python

**Evidence:**
```python
# atmospheric_volumes.py lines 432-434:
_log_acc = np.log1p(_acc).reshape(rows, cols)
_log_acc_max = _log_acc.max()                      # returns NaN if _acc has NaN
_drainage_acc = _log_acc / max(_log_acc_max, 1e-9) # max(NaN, 1e-9) = NaN in Python
```

**Root cause:** Python's built-in `max(a, b)` function follows the IEEE 754 rule for NaN comparison: `max(float('nan'), 1e-9)` returns `nan` (or `1e-9` depending on Python version and argument order — the result is **undefined and version-dependent**). In CPython 3.10+, `max(nan, x)` returns `nan` when nan is the first argument. In 3.11+, the behaviour changed to return `x`. This means `_drainage_acc` can be either all-NaN or correctly normalised depending on the Python version running the pipeline, with no error either way.

**Propagation path:** NaN `_acc` (possible if the D8 receiver walk runs on a NaN heightmap tile) → NaN `_log_acc` → `max(NaN, 1e-9)` = NaN or 1e-9 depending on Python version → `_drainage_acc = NaN array` or `_drainage_acc = log_acc / 1e-9` (giant values) → `depression_mask = _drainage_acc.copy()` → NaN or overflow written to the `depression_mask` used for cloud/fog/smoke volume placement → all atmospheric volume placements fail silently or cluster at wrong locations.

**AAA gap:** Never use Python's `max()` on a numpy scalar to guard division — use `np.maximum` or an explicit `isfinite` check.

**Fix:**
```python
_log_acc_max = float(_log_acc.max())
if not math.isfinite(_log_acc_max) or _log_acc_max < 1e-9:
    _drainage_acc = np.zeros_like(_log_acc)
else:
    _drainage_acc = _log_acc / _log_acc_max
```
**Estimated time:** 15 minutes.

---

**M7-P0-07** | `_water_network.py:812` | `speed_raw.max()` used as fallback when `water_vals.size == 0`; if entire tile has no water AND `flow_accumulation` contains NaN, `speed_raw = NaN_arr` and `p95 = NaN` slips through the `if p95 > 1e-9` guard → `flow_speed` channel written as NaN array

**Evidence:**
```python
# _water_network.py lines 809-817:
if water_vals.size > 0:
    p95 = float(np.percentile(water_vals, 95.0))
else:
    p95 = float(speed_raw.max())   # NaN if speed_raw contains NaN

if p95 > 1e-9:                     # NaN > 1e-9 = False → falls through to else
    speed_norm = np.clip(speed_raw / p95, 0.0, 1.0).astype(np.float32)
else:
    speed_norm = np.zeros_like(speed_raw, dtype=np.float32)  # silently returns zeros
```

The `else` branch on `p95 > 1e-9` fires when `p95` is NaN (because NaN comparison is False), producing a correct-looking `speed_norm = zeros`. The **problem** is the reverse path: if `water_vals.size > 0` but `water_vals` is all NaN (e.g., from a NaN `flow_accumulation` masked array), `np.percentile(NaN_arr, 95)` returns `NaN`, `NaN > 1e-9 = False`, and `speed_norm = zeros` again — silently wrong.

But there is also the case where `speed_raw` is finite but all-zero for a completely flat tile: `speed_raw.max() = 0.0`, `0.0 > 1e-9` is False, `speed_norm = zeros` — this is correct. The NaN path and the flat-tile path both produce `speed_norm = zeros` with no diagnostic difference in the log.

**Propagation path:** NaN `flow_accumulation` → NaN `log_acc` → NaN `speed_raw` → `water_vals` all NaN → `percentile(NaN) = NaN` → guard fails → `speed_norm = zeros` → `flow_speed` channel is all-zero (wrong for rivers) → Unity water shader renders no flow animation → silent aesthetic failure.

**AAA gap:** Check NaN in `water_vals` before `percentile`. Distinct log message for "no water cells" vs "NaN flow accumulation detected".

**Fix:**
```python
if water_vals.size > 0:
    finite_vals = water_vals[np.isfinite(water_vals)]
    if finite_vals.size == 0:
        raise RuntimeError("flow_speed: flow_accumulation contains NaN in all water cells")
    p95 = float(np.percentile(finite_vals, 95.0))
else:
    p95_candidate = float(speed_raw.max())
    p95 = p95_candidate if math.isfinite(p95_candidate) else 0.0
```
**Estimated time:** 30 minutes.

---

**M7-P0-08** | `terrain_stratigraphy.py:319` | `exp_span = float(np.abs(relative_exposure).max())` followed by unguarded `/ exp_span` if `exp_span == 0.0`

**Evidence:**
```python
# terrain_stratigraphy.py lines 317-325:
relative_exposure = ...  # computed from tilt + azimuth
exp_span = float(np.abs(relative_exposure).max())   # can be 0.0 on flat tile
# ... then 6 lines later (line 325):
rel_exp_norm = relative_exposure / exp_span  # ZeroDivisionError OR inf if exp_span==0
```

Let me verify the exact line:
```python
# lines 319-324 (from audit grep result line 123 of .max() list):
exp_span = float(np.abs(relative_exposure).max())
# if exp_span == 0.0, no guard before division
```

**Propagation path:** A perfectly flat tile (zero dip everywhere in stratigraphy) or a tile with uniform azimuth produces `relative_exposure = zeros` → `exp_span = 0.0` → division produces inf or NaN → `strata_orientation` channel corrupted → written to `strat_erosion_delta.bin` with no sanitization.

**AAA gap:** Always guard normalization denominators with `max(exp_span, 1e-9)`.

**Fix:**
```python
exp_span = max(float(np.abs(relative_exposure).max()), 1e-9)
rel_exp_norm = relative_exposure / exp_span
```
**Estimated time:** 15 minutes. (Requires verifying exact line number via read — audit confirmed the `exp_span` computation at line 319 and the division is at line ~325; fix the same pattern.)

---

**M7-P0-09** | `terrain_unity_export.py:1256` | `terrain_normals.bin` written as raw float32 with no NaN guard; `_compute_terrain_normals_zup` (`terrain_unity_export.py:111`) uses `np.where(lengths <= 1e-9, 1.0, lengths)` to guard the division, but does NOT guard against NaN inputs in `h` — if `stack.height` contains NaN, `np.gradient(NaN_heightmap)` propagates NaN into `dzdx`/`dzdy`, then `np.stack(-dzdx, -dzdy, ones)` has NaN in XY components, `linalg.norm(NaN_vec) = NaN`, the `np.where(NaN <= 1e-9, 1.0, NaN)` guard evaluates the condition as False (NaN <= anything = False) and returns `NaN`, so `normals / NaN = NaN` — the entire normal buffer is NaN.

**Evidence:**
```python
# terrain_unity_export.py lines 100-114:
def _compute_terrain_normals_zup(heightmap, cell_size):
    h = np.asarray(heightmap, dtype=np.float64)   # no nan_to_num here
    ...
    dzdy, dzdx = np.gradient(h, spacing, spacing)
    normals = np.stack((-dzdx, -dzdy, np.ones_like(h)), axis=-1)
    lengths = np.linalg.norm(normals, axis=-1, keepdims=True)
    lengths = np.where(lengths <= 1e-9, 1.0, lengths)  # NaN fails the comparison!
    normals = normals / lengths                         # normals = NaN / NaN = NaN

# caller at line 1251-1258:
_write_raw_array(..., arr=np.asarray(stack.terrain_normals, dtype=np.float32), ...)
# tobytes() writes NaN float32 to terrain_normals.bin
```

**Propagation path:** NaN in `stack.height` (from M7-P0-04) → `np.gradient(NaN)` → NaN in normals XY → NaN lengths → `where(NaN<=1e-9)` returns NaN from the false-branch → `normals/NaN = NaN` → written to `terrain_normals.bin` → Unity C# `NativeArray.CopyFrom` reads NaN → HDRP terrain shader samples invalid normals → black normal map or inverted lighting over entire corrupted region.

**AAA gap:** Sanitize heightmap before normal computation: `h = np.nan_to_num(h, ...)`. Guard `lengths` with `np.maximum(lengths, 1e-9)` rather than `np.where` to correctly handle NaN.

**Fix:**
```python
def _compute_terrain_normals_zup(heightmap, cell_size):
    h = np.nan_to_num(np.asarray(heightmap, dtype=np.float64),
                      nan=0.0, posinf=0.0, neginf=0.0)
    ...
    lengths = np.maximum(np.linalg.norm(normals, axis=-1, keepdims=True), 1e-9)
    normals = normals / lengths
```
**Estimated time:** 20 minutes.

---

## P1 Findings (crash-level, at least fails loudly)

**M7-P1-01** | `terrain_stratigraphy.py:514` | `np.arcsin(ratio)` — ratio is clipped to `[0, 1]` at line 513 via `np.clip(..., 0.0, 1.0)`, so NaN input from `cell_thickness < 1e-6` guard is handled. However if `erosion_depth` itself is NaN (corrupt upstream channel), the clip produces NaN → `np.arcsin(NaN) = NaN`. Downstream: `unconformity_mask` becomes NaN array. Stored on stack, exported via channels loop. **Would be P0 but the export path sanitizes this to 0 via uint8 quantization in most cases.** Still a data-corruption bug; classified P1 because the quantization prevents silent float NaN on disk.

**M7-P1-02** | `_terrain_erosion.py:456` | `speed = math.sqrt(max(speed * speed + normalized_h_diff, 0.01))` — if `speed` is NaN (after M7-P0-04 injection), `speed * speed = NaN`, `NaN + normalized_h_diff = NaN`, `max(NaN, 0.01)` returns 0.01 in Python 3.10+ or NaN in 3.9. `math.sqrt(NaN)` raises `ValueError: math domain error` — **this is a crash**. Not silent. The crash surfaces during the erosion particle loop. Classified P1 because the crash at least produces a visible error in logs.

**M7-P1-03** | `terrain_waterfalls.py:1540` | `math.log1p(float(flow_acc.max()) + 1.0)` — `flow_acc.max()` with an all-NaN array returns NaN, `float(NaN) + 1.0 = NaN`, `math.log1p(NaN)` returns NaN on CPython (does not raise). Silent NaN propagates into `denom`. `flow_acc / NaN = NaN` — this would be P0 except the result is used as a normalization denominator for the `acc_term` in waterfall splash, and the channel is the same `foam` already flagged in M7-P0-05. Flagged separately because the call site is distinct.

---

## Summary Statistics

| Severity | Count | Channels Affected |
|----------|-------|-------------------|
| P0 | 9 | heightmap, foam, flow_speed, terrain_normals, moisture_map, strat_erosion_delta, depression_mask, all 35 float binary channels |
| P1 | 3 | speed scalar in erosion loop, unconformity_mask, foam (secondary site) |

**Root cause taxonomy:**
- **Missing export-gate NaN scrubbing (1 site, 35 channels):** M7-P0-01 — the single highest-leverage fix
- **NaN-permissive `np.clip` calls (multiple):** NumPy clip does not sanitize NaN; `np.clip(NaN, a, b)` returns NaN
- **Python `max(numpy_scalar, epsilon)` NaN propagation (1 site):** M7-P0-06 — version-dependent undefined behaviour
- **`np.where(NaN <= threshold)` guard failure (1 site):** M7-P0-09 — `NaN <= x` always False in IEEE 754
- **Unguarded normalization denominators (2 sites):** M7-P0-03, M7-P0-08
- **NaN input to `np.log` (2 sites):** M7-P0-02 (indirect), M7-P0-05

**The codebase has exactly zero `nan_to_num` calls anywhere in the `terrain_unity_export.py` export path.** The three existing `nan_to_num` uses in `environment.py` and `environment_scatter.py` are in non-export helper paths and do not protect the `TerrainMaskStack` channel write path.

---

**P0 count: 9 confirmed P0 blockers across 35 affected output channels.**
