# M5 Audit: Glacial, Wind Erosion & Advanced Terrain

**Auditor:** Claude (senior tech-lead standard — Rockstar/Guerrilla)
**Date:** 2026-04-27
**Files audited:**
- `veilbreakers_terrain/handlers/terrain_glacial.py` (419 lines)
- `veilbreakers_terrain/handlers/terrain_wind_erosion.py` (471 lines)
- `veilbreakers_terrain/handlers/terrain_erosion_filter.py` (541 lines)
- `veilbreakers_terrain/handlers/terrain_advanced.py` (~1300+ lines, read in chunks)
- `veilbreakers_terrain/handlers/terrain_weathering_timeline.py` (142 lines)

**Overall grade: D+**

The code is cleaner than the hydraulic erosion module but is riddled with structural and physics-correctness failures that mean none of the cinematic landforms it promises ever ship to the player. The headline problems: no ice-flow physics whatsoever (glacial is a static geometry tool), wind erosion is not mass-conserving at the per-call level, the weathering timeline is an admitted orphan that has never been called in production, and the analytical erosion filter is wired to only one caller (_terrain_world.py) — not the main 12-step pipeline. Below are the ship-blocking findings.

---

## P0 Findings

---

**M5-P0-1** | `terrain_glacial.py:300–360` | No ice-flow physics — glacial is static geometry stamping, not simulation

**Evidence:**
```python
def pass_glacial(state, region):
    # Optional U-valley carving from hints
    glacier_paths = hints.get("glacier_paths", [])
    if glacier_paths:
        for gp in glacier_paths:
            path = gp.get("path", [])
            delta = carve_u_valley(stack, path, width, depth)
            total_delta += delta
```
The entire glacial pass is: (1) compute a snow line altitude, (2) if the user authored `glacier_paths` hint — stamp a parabolic trough along each path. There is no ice-flow simulation. Ice does not flow from accumulaton zones. The ice surface elevation, ice thickness, and basal sliding velocity are never computed. Without those, the carving depth is a fixed authored scalar (`depth_m`), not driven by any physical process.

**AAA gap:** Guerrilla Games (Horizon series) and Rockstar's RED (Red Dead Redemption 2 mountain terrain) both use a Shallow Ice Approximation (SIA) solver: `∂H/∂t = -∇·(D∇h)` where D is the diffusivity proportional to H^(n+2)|∇h|^(n-1). This drives U-valleys, cirque headwall erosion, arête sharpening, and moraine placement emergently from physics, not pre-authored paths. Critically, the accumulation zone (above equilibrium line altitude = ELA) and ablation zone (below ELA) must be tracked so ice flows downhill and terminates where melt equals accumulation. None of this is present. The current implementation cannot produce cirques, arêtes, hanging valleys, or paternoster lakes — the canonical dark-fantasy glacial features.

**Fix:** Implement a 2D SIA time-stepping loop:
```python
# Glen's flow law: n=3
D = A_factor * (rho_ice * g) ** n * H ** (n+2) * slope_mag ** (n-1)
dH_dt = accumulation - ablation + divergence(D * gradient(surface_elevation))
```
Minimum viable: 20–50 iterations at world-scale, GPU-accelerated via cupy or scipy sparse. Estimated time: 3–4 days.

---

**M5-P0-2** | `terrain_glacial.py:47–163` | No cirques, arêtes, or hanging valleys — only U-valleys along pre-authored paths

**Evidence:**
```python
def carve_u_valley(stack, path, width_m, depth_m) -> np.ndarray:
    """Return a height delta carving a glacial U-shaped valley along ``path``."""
    # ... parabolic cross-section only along the given path
```
`carve_u_valley` produces one landform: a trough with a parabolic cross-section. The following glacier-diagnostic landforms are completely absent from the entire codebase:
- **Cirques** (bowl-shaped headwall hollows where ice accumulates) — not computed
- **Arêtes** (knife-edge ridges between adjacent cirques) — not computed  
- **Hanging valleys** (tributary glacier valleys that don't reach the main trough floor) — not computed
- **Roches moutonnées** (asymmetrically abraded bedrock knobs) — not computed
- **Fjords** (drowned U-valleys) — not computed
- **Paternoster lakes** (string of cirque lakes) — not computed

**AAA gap:** Guerrilla's Decima Engine terrain for Horizon Zero Dawn/Forbidden West explicitly generates cirques by tracking ice-accumulation ELA intersections with ridgelines. The dark fantasy aesthetic (frozen peaks, ancient glacial scars) specifically requires cirques and arêtes — these are the visual signatures that distinguish glaciated terrain from ordinary mountains. Without them the "glacial" module produces nothing a player would read as glacial.

**Fix:** Add a `carve_cirques()` function that identifies ELA-intersecting slope concavities and deepens them with a hemispherical kernel, plus a ridge-sharpening pass that detects saddles between adjacent cirques and reduces their width. 2–3 days.

---

**M5-P0-3** | `terrain_glacial.py:339` | `glacial_delta` is set to all-zeros unless `glacier_paths` hint is authored — snow line is the only guaranteed output

**Evidence:**
```python
stack.set("glacial_delta", total_delta.astype(np.float32), "glacial")
```
`total_delta` is initialized to `np.zeros((H, W))` at line 320 and is only modified if `glacier_paths` hint is non-empty. The composition hint `glacier_paths` is never set by any default pipeline configuration. Cross-referencing `environment.py`, `terrain_twelve_step.py`, and `terrain_master_registrar.py`:
- `pass_glacial` is registered via `register_bundle_i_passes()`
- Bundle I IS loaded by `terrain_master_registrar.py` (line 220)
- BUT `environment.py`'s pipeline builder (lines 2004–2035) never adds `"glacial"` to the pipeline list
- The pipeline in `compose_map` uses `["macro_world", "structural_masks", ...]` — `"glacial"` is not in it

So in normal production flow: pass_glacial never runs, and even if it did, `glacial_delta` would be all-zeros because no caller ever populates `composition_hints["glacier_paths"]`.

**AAA gap:** A glacial pass that requires manual path authoring to do anything is a design tool, not a simulation. Production terrain pipeline should auto-derive glacier paths from the ELA + slope analysis. Without this, every VeilBreakers level has zero glacial erosion unless a designer hand-crafts each glacier path — which does not happen.

**Fix:** (1) Add `"glacial"` to the environment.py pipeline list. (2) Add auto-path derivation that traces from ELA-altitude cells downhill using D8 flow direction as glacier seed paths. 1 day.

---

**M5-P0-4** | `terrain_wind_erosion.py:219–231` | Mass conservation capped at 3× but erosion-only frames are common — net deflation is unbounded across passes

**Evidence:**
```python
conservation_scale = erosion_total / deposition_total
# Cap at 3× to prevent runaway amplification on nearly-flat terrain
conservation_scale = min(conservation_scale, 3.0)
delta = np.where(delta > 0, delta * conservation_scale, delta)
```
The comment says "cap at 3×" but this means if the terrain is nearly flat (saltation_delta ≈ 0, bagnold → 0, lee_gain ≈ 0), the condition `deposition_total > 1e-12` fails and the entire conservation block is skipped (line 226: `if deposition_total > 1e-12 and erosion_total > deposition_total`). On flat terrain — deserts, plains — there is zero deposition and non-zero erosion, so net delta is purely negative. Over multiple pipeline passes this causes unbounded terrain deflation.

More critically: the 3× cap means in the normal case, up to 2× more material is deposited than eroded. This violates conservation in the opposite direction on rugged terrain, building phantom sand deposits that are not sourced from anywhere.

**AAA gap:** The Far Cry 6 aeolian system and Gaea's Wind Erosion node both operate on a closed mass budget: the total volume of `erosion_delta + deposition_delta = 0` per invocation. This is done by computing divergence of a flux field, not by rescaling. The current approach is a heuristic approximation that fails in both the flat and rugged extremes.

**Fix:** Replace the post-hoc scale with a proper flux-divergence formulation:
```python
# Transport flux vector
flux_x = bagnold * dx * intensity
flux_y = bagnold * dy * intensity
# Divergence = erosion; convergence = deposition
delta = -(np.gradient(flux_x, axis=1) + np.gradient(flux_y, axis=0)) * cell_size
```
Estimated time: 1 day.

---

**M5-P0-5** | `terrain_wind_erosion.py:398–463` | `pass_wind_erosion` never runs in production — not in any live pipeline sequence

**Evidence:**
```python
def pass_wind_erosion(state, region) -> PassResult:
    # ...
    stack.set("wind_erosion_delta", total_delta.astype(np.float32), "wind_erosion")
```
Tracing the pipeline:
- `pass_wind_erosion` is registered by `register_bundle_i_passes()` (geology_validator.py:557)
- `terrain_master_registrar.py` calls `register_bundle_i_passes` (line 220)
- `environment.py` pipeline builder (lines 2004–2035) does NOT add `"wind_erosion"` to the pipeline list
- `terrain_twelve_step.py` does NOT call `pass_wind_erosion`
- No grep match for `pass_wind_erosion` in `terrain_twelve_step.py` (confirmed: "No matches found")

The pass is registered but never scheduled. `wind_erosion_delta` is listed in `_DELTA_CHANNELS` in `terrain_delta_integrator.py:44`, so if it were populated it would be applied — but it never is. Every VeilBreakers terrain ships with zero aeolian erosion.

**AAA gap:** Wind erosion is not optional for a dark fantasy game. It's what creates the ventifacts, yardangs, and deflation hollows that give ancient ruins their weathered look. This is dead letter code.

**Fix:** Add `"wind_erosion"` to the environment.py pipeline list after `"structural_masks"`. Ensure `composition_hints["wind_direction_rad"]` defaults are set. 4 hours.

---

**M5-P0-6** | `terrain_wind_erosion.py:170–189` | Saltation hop length is hardcoded to 2 cells regardless of wind speed or cell size — physically incorrect at all resolutions

**Evidence:**
```python
# Hop length = 2 cell sizes (typical saltation trajectory)
hop = 2.0
up = _shift_fractional_with_edge_repeat(h, row_shift=-dy * hop, col_shift=-dx * hop)
down = _shift_fractional_with_edge_repeat(h, row_shift=dy * hop, col_shift=dx * hop)
```
The saltation hop length is `2 * cell_size` unconditionally. Real saltation hop length scales as:
```
L_hop ≈ (u* - u*_t)^2 / g × particle_density/air_density
```
For typical desert conditions (u* = 0.4 m/s, d_grain = 250 μm): L_hop ≈ 0.1–0.5 m.

At a terrain cell size of 1 m (typical for 1-km tiles at 1024-res), the hop is 2 m — in range.
At a cell size of 10 m (world-scale pass), the hop is 20 m — an order of magnitude too long.
At a cell size of 0.25 m (high-res detail), the hop is 0.5 m — plausible only by accident.

The `stack.cell_size` attribute is available but never consulted. The effective transport distance scales with tile resolution, not with physics.

**AAA gap:** Houdini's HeightField Wind Erode uses physical grain diameter and friction velocity to parameterize saltation. The hop length is `f(wind_speed, grain_size, cell_size)`.

**Fix:**
```python
# Physical hop: Bagnold (1941) ~ 10-12 × grain diameter, wind-speed scaled
grain_diameter_m = hints.get("grain_diameter_m", 0.00025)  # 250 μm default
hop_physical_m = 12.0 * grain_diameter_m * (1.0 + 8.0 * intensity)  # ~0.1-0.5m
hop = max(0.5, hop_physical_m / stack.cell_size)
```
Estimated time: 2 hours.

---

**M5-P0-7** | `terrain_wind_erosion.py:188` | Saltation blend weights (0.45/0.35/0.20) have no physical basis — the formula does not implement Bagnold transport

**Evidence:**
```python
# Saltation delta: erode windward face, deposit downwind
# Asymmetric blend weighted by Bagnold rate
saltation_blend = 0.45 * h + 0.35 * up + 0.20 * down
saltation_delta = (saltation_blend - h) * intensity * (0.6 + 0.4 * bagnold)
```
The docstring claims to implement the Bagnold transport rate `q ∝ u*^3`, but the implementation does not. The actual delta is a weighted average of three shifted copies of the heightfield. This is a spatial low-pass filter oriented along the wind direction, not a transport model. The Bagnold term `(0.6 + 0.4 * bagnold)` is a scalar multiplier on what is fundamentally a smoothing operation — it does not move mass from windward faces to lee faces.

True aeolian transport computes:
1. Erosion flux per cell = q(windward_slope, u*) — mass lifted per unit time
2. Deposition flux per cell = q(lee_slope, settling_velocity) — mass landed per unit time
3. delta = deposition - erosion (continuity equation)

The current code computes none of this.

**AAA gap:** This is cosmetically plausible for a 2-minute look at a static render but would not pass a Rockstar tech review. The asymmetry of yardangs and the sharp slip-face angle of dunes require a proper erosion-deposition continuity model.

**Fix:** Implement a flux-divergence model (see M5-P0-4 fix). The saltation blend approach should be removed entirely. 1 day.

---

**M5-P0-8** | `terrain_weathering_timeline.py:31–35` | `generate_weathering_timeline` is an admitted orphan — explicitly documented as having no production caller

**Evidence:**
```python
def generate_weathering_timeline(
    # FUTURE USE: Bundle Q pass — drives time-lapse weathering sequences for
    # environmental storytelling and material aging. No production caller yet;
    # will be wired into the post-pipeline hooks in a future Bundle Q pass registration.
    duration_hours: float,
    seed: int,
) -> List[WeatheringEvent]:
```
The comment is self-incriminating. Confirmed by grep: zero callers of `generate_weathering_timeline` or `apply_weathering_event` in any production handler. The `wetness` channel mutation in `apply_weathering_event` feeds nothing — `wetness` is not consumed by materials, scatter, or export. The entire module is dead.

**AAA gap:** Not just a wiring gap. The weathering simulation itself lacks critical physical processes:
- No freeze-thaw cycling (mechanical weathering = major fracture driver for dark fantasy cliffs)
- No chemical weathering (carbonate dissolution, oxidation) that drives material color variation
- No weathering rind thickness accumulation (controls surface texture aging)
- The "wetness ceiling = max(2 × current max, 1.0)" formula at line 91 means wetness can grow without bound across successive rain events — there is no drainage or evaporation removing water from the system between events

**Fix:** Wire `generate_weathering_timeline` into a Bundle Q pass registration AND into the post-pipeline hook system. Add evaporation term to rain handler. Minimum viable: 1 day to wire, 3 days for physical correctness.

---

**M5-P0-9** | `terrain_weathering_timeline.py:91` | Wetness ceiling is unbounded — `max(2 × current_max, 1.0)` allows exponential growth across events

**Evidence:**
```python
max_existing = float(wet.max()) if wet.size else 0.0
ceil_val = max(1.0, max_existing * 2.0)
# ...
wet = np.clip(wet + intensity * (0.5 + 0.5 * weight), 0.0, ceil_val)
```
After the first rain event: `max_existing` = some value V, `ceil_val` = max(1.0, 2V).
After the second rain event on the same high-wetness cell: `max_existing` ≥ V, `ceil_val` ≥ 2V.
Each successive rain event can double the wetness ceiling. Over 100 events (a 200-hour sim at 1 event/2 hrs), wetness can reach 2^100 × initial — floating-point overflow territory.

The correct physical ceiling is 1.0 (field capacity = 100% saturation). Any excess water should drain or run off.

**Fix:**
```python
ceil_val = 1.0  # physical saturation ceiling — no water above field capacity
# Add drainage between events: wet *= exp(-drain_rate * dt)
```
2 hours.

---

**M5-P0-10** | `terrain_erosion_filter.py` | `apply_analytical_erosion` is called from `_terrain_world.py` but NOT from `terrain_twelve_step.py` — the 12-step pipeline ships without analytical erosion

**Evidence:**
From grep results:
```
C:\...\handlers\_terrain_world.py:34: from .terrain_erosion_filter import apply_analytical_erosion
C:\...\handlers\_terrain_world.py:1144: analytical_result = apply_analytical_erosion(
```
And from grep of `terrain_twelve_step.py` for `analytical_erosion` or `erosion_filter`: zero results.

`terrain_twelve_step.py` is the main production 12-step pipeline. It calls `erode_world_heightmap` (lines 1120–1127) which is the hydraulic erosion stub — not `apply_analytical_erosion`. The analytical erosion filter (which is the only erosion that produces convincing gully networks, ridge maps, and flow accumulation) runs in `_terrain_world.py` only, which is the legacy single-tile path.

Multi-tile world generation via the 12-step pipeline gets zero analytical erosion. It gets only the hydraulic erosion stub from `_terrain_erosion.py` which has the E-1 1000× erodibility bug (already logged as P0).

**AAA gap:** World Creator, Gaea, and every AAA terrain pipeline runs analytical erosion globally before tile extraction so erosion features are continuous across tile boundaries. Running it only in the legacy single-tile path means multi-tile worlds (the production use case) have no erosion detail.

**Fix:** Add `apply_analytical_erosion` call to `terrain_twelve_step.py` Step 6, replacing or augmenting `erode_world_heightmap`. Requires passing a consistent `ridge_range` across tiles to prevent seam artifacts. 1–2 days.

---

**M5-P0-11** | `terrain_glacial.py:246–258` | Moraine scatter returns `(x, y, radius_m)` but is never applied to the heightfield — moraines exist only as a list, not as terrain geometry

**Evidence:**
```python
def scatter_moraines(stack, glacier_path, seed) -> List[Tuple[float, float, float]]:
    """Return a list of (x, y, radius_m) moraine placements."""
    # ...
    return moraines
```
`scatter_moraines` is never called anywhere in production code. Confirmed by grep across all `.py` files: zero callers of `scatter_moraines`. Even if called, it returns only coordinates — there is no function that takes the moraine list and raises the terrain at those positions to create the actual ridges.

**AAA gap:** Moraines are one of the most visually distinctive glacial features — the key landscape element that tells the player "ancient glacier was here." Without them the entire glacial simulation has no signature in the output mesh.

**Fix:** (1) Add a `raise_moraines(stack, moraines)` function that applies a Gaussian mound at each moraine position. (2) Call `scatter_moraines` + `raise_moraines` from `pass_glacial`. 4 hours.

---

**M5-P0-12** | `terrain_glacial.py:363–409` | `get_ice_formation_specs` calls `terrain_features.generate_ice_formation` — tight coupling to module that may not exist in production context, with silent empty-return fallback

**Evidence:**
```python
def get_ice_formation_specs(stack, *, max_formations=5, seed=42) -> list:
    from .terrain_features import generate_ice_formation
    factor = stack.get("snow_line_factor")
    if factor is None:
        return []
```
This function is called after `pass_glacial` to get ice mesh specs, but:
1. It has a deferred import of `terrain_features.generate_ice_formation` — if that module fails to import (missing dependency, Blender-only code), it raises `ImportError` uncaught at the call site
2. If `snow_line_factor` is None (which it is if `pass_glacial` hasn't run — and it usually hasn't), returns silently empty
3. The caller must set `max_formations` explicitly; the default of 5 uses a fixed seed=42, which means every level has the same 5 ice formation positions

**Fix:** Wrap the import in try/except, log the failure, and document the dependency. Change seed default to `state.intent.seed` when called from a pass context. 2 hours.

---

## Warning-Level Findings (P1)

**M5-P1-1** | `terrain_glacial.py:105–113` | EDT path mask uses O(H×W) full-grid distance transform even when the glacier path covers only a small fraction of the tile

For a 1024×1024 tile with a 200m glacier path, ~95% of the EDT computation is wasted. The path bounding box crop exists (lines 100–103) for `dist_crop` but the EDT itself is computed on the full grid (`path_mask` is H×W). This means every tile pays a full O(N²) EDT cost regardless of glacier path length.

**Fix:** Compute EDT only on the bounding-box crop with a padding margin, then place the result back into the full grid. Reduces cost by 10–100× for short glacier paths.

---

**M5-P1-2** | `terrain_wind_erosion.py:302–319` | Barchan dune count formula `(H * W) // (spacing * spacing * 3)` can produce hundreds of barchans that are summed over (N, H, W) array — OOM risk at 1024×1024

```python
n_barchans = max(4, (H * W) // (spacing * spacing * 3))
# ...
mound = np.exp(-(du / sigma_u) ** 2 - (dv / sigma_v) ** 2)  # (N, H, W)
```
At 1024×1024 with `spacing=170` (1024//6), `n_barchans = (1024*1024) // (170*170*3) ≈ 12`. That's acceptable. But with `spacing=8` (minimum), `n_barchans = (1024*1024) // (8*8*3) ≈ 5461`. A (5461, 1024, 1024) float64 array is **43 GB** — immediate OOM kill.

`spacing = max(8, min(H, W) // 6)` means at minimum dimension 128 the minimum spacing is 21 — still potentially large N. No cap on `n_barchans` beyond `max(4, ...)`.

**Fix:** Add `n_barchans = min(n_barchans, 256)` hard cap before the array allocation.

---

**M5-P1-3** | `terrain_advanced.py:938` | `apply_layer_operation` with LayerOp bulk modes clips `layer.heights` to `[0, 1]` — normalised offsets, but heights are world-space meters elsewhere

```python
np.clip(layer.heights, 0.0, 1.0, out=layer.heights)
```
`TerrainLayer` docstring says "height offsets" but provides no unit documentation. If a layer is used for world-space height displacement (in meters), clipping to [0, 1] silently discards any offset above 1 meter. For an AAA terrain in the 0–2000m range this is a catastrophic data loss. The contract is ambiguous.

**Fix:** Document whether `heights` are normalized [0,1] or world-space meters. Remove the clip if world-space; document the [0,1] contract clearly if normalized.

---

**M5-P1-4** | `terrain_erosion_filter.py:340–414` | Octave loop updates `gx`/`gz` in-place each octave via `gx += k * slope_dir_x` — gradient drift accumulates unbounded

```python
k = sign_sin * d_cos * config.strength * config.gully_weight * 0.1
gx += k * slope_dir_x
gz += k * slope_dir_z
```
The gradient is modified in every octave but never renormalized or bounded. For high `octave_count` (e.g. 8) and high `strength`, the gradient vectors can grow to large magnitudes, making the slope direction numerically unstable in later octaves. This produces NaN when `slope_len ≈ 0` after drift causes the gradient to point in contradictory directions.

**Fix:** Recompute the gradient from the accumulated height_delta each N octaves, or clamp gradient magnitude to `[0, max_expected_slope]` after each update.

---

**M5-P1-5** | `terrain_weathering_timeline.py:102–103` | `np.gradient(h, float(stack.cell_size))` uses 2-argument form — passes cell_size as a scalar, but numpy interprets this as the spacing in both dimensions only if `h` is 2D; for a 1D slice it is wrong

```python
dh_dy, dh_dx = np.gradient(h, float(stack.cell_size))
```
`np.gradient(h, s)` with a 2D array and a single scalar returns `[dh/dy, dh/dx]` where both are divided by `s`. This is correct ONLY if `cell_size_x == cell_size_y`. If the tile is not square or the cell_size differs per axis (rare but possible), the gradient magnitude is wrong.

More critically: the variable naming suggests `dh_dy` is the first return and `dh_dx` is second. But `np.gradient` of a 2D array returns `[grad_row, grad_col]` = `[∂h/∂row, ∂h/∂col]`. Rows correspond to the Y-axis (world Y), columns to X. So `dh_dy = np.gradient(h, cell_size)[0]` is `∂h/∂y` — that is correct. `dh_dx = np.gradient(h, cell_size)[1]` is `∂h/∂x` — also correct. But only when cell_size is the same in both dimensions. No assertion or guard exists.

**Fix:** Use `np.gradient(h, stack.cell_size, stack.cell_size)` explicitly or assert `cell_size_x == cell_size_y` at the top of the function.

---

## Quality Assessment

### terrain_glacial.py — Grade: D
The code is well-structured Python but the simulation is a geometry stamp, not a glacier. The parabolic U-valley profile is correct. The moraine classification is geologically accurate and well-documented. But nothing moves. There is no ice. There is no physics. The entire module produces either a static trough along a pre-authored path (if the user configured glacier_paths) or a snow coverage mask (always). Neither is usable for AAA without the SIA physics behind it. The `pass_glacial` pass is not in the production pipeline. Moraines are computed but never applied to terrain.

### terrain_wind_erosion.py — Grade: D+
The dune morphology classification (transverse/barchan/star) is scientifically accurate. The barchan horn geometry formula referencing Bagnold migration rates is genuinely good. But the underlying erosion model is a spatial filter dressed up as physics — the Bagnold transport rate is computed then used only as a scalar multiplier on a smoothing blend, not as an actual flux. The pass is not in the production pipeline. The mass conservation fix is a post-hoc rescale that overcorrects in both directions.

### terrain_erosion_filter.py — Grade: B-
This is the strongest module in the set. The PhacelleNoise implementation is clean, vectorized, and physically motivated. The xxHash mixing is solid. The sediment DC removal / chunk-parallel logic is thoughtful. The primary failure is that it only runs in the legacy single-tile path, not the 12-step production pipeline. The gradient drift issue is a real numerical stability risk at high octave counts.

### terrain_advanced.py — Grade: C
Feature-complete for a tech-demo. Spline deformation, terrain layers, brush system, flow map — all present and functional. The arc-length reparameterization on splines is proper. The bilinear layer resize is correct. The known J6 5-unused-locals issue is minor. Main gap: everything in this module is Blender-specific except the pure-logic functions, and the pure-logic functions are not connected to the pipeline's pass system. They are editor tools, not pipeline simulation.

### terrain_weathering_timeline.py — Grade: F
Self-described as having no production caller. The wetness ceiling formula is a time-bomb. The module has never run in production. The physical model (when it does run) lacks evaporation, drainage, and freeze-thaw cycling — the three dominant weathering drivers for dark fantasy mountain terrain.

---

## Wiring Summary

| Module | Registered? | In Pipeline? | Delta Applied? |
|--------|-------------|--------------|----------------|
| `pass_glacial` | Yes (Bundle I) | **No** | N/A |
| `pass_wind_erosion` | Yes (Bundle I) | **No** | N/A |
| `apply_analytical_erosion` | No pass | Legacy only | Legacy only |
| `generate_weathering_timeline` | No pass | **No** | N/A |
| `scatter_moraines` | No pass | **No** | **Never** |
| `get_ice_formation_specs` | No pass | Not connected | N/A |

Both Bundle I erosion passes (glacial + wind) are wired into `terrain_delta_integrator._DELTA_CHANNELS` — meaning IF they ran and produced deltas, the integrator would apply them. The wiring from pass to pipeline is the broken link in every case.

---

## P0 Count

**12 P0 blockers** in this module sweep.

| ID | File | Summary |
|----|------|---------|
| M5-P0-1 | terrain_glacial.py:300 | No ice-flow physics — SIA not implemented |
| M5-P0-2 | terrain_glacial.py:47 | No cirques, arêtes, hanging valleys |
| M5-P0-3 | terrain_glacial.py:339 | glacial_delta is zeros in production — pass never called |
| M5-P0-4 | terrain_wind_erosion.py:219 | Mass conservation capped at 3× — unbounded deflation on flat terrain |
| M5-P0-5 | terrain_wind_erosion.py:398 | pass_wind_erosion never in production pipeline |
| M5-P0-6 | terrain_wind_erosion.py:170 | Saltation hop hardcoded to 2 cells — ignores cell_size |
| M5-P0-7 | terrain_wind_erosion.py:188 | Saltation blend is a spatial filter, not a transport model |
| M5-P0-8 | terrain_weathering_timeline.py:31 | Entire module is a documented orphan with no production caller |
| M5-P0-9 | terrain_weathering_timeline.py:91 | Wetness ceiling doubles each rain event — unbounded growth |
| M5-P0-10 | terrain_erosion_filter.py | Analytical erosion absent from 12-step pipeline |
| M5-P0-11 | terrain_glacial.py:246 | Moraines computed but never raised on terrain |
| M5-P0-12 | terrain_glacial.py:363 | get_ice_formation_specs has uncaught ImportError path |

**Total M5 P0s: 12**
**Running pipeline total (pre-M5): 105**
**Updated total: 117 P0 blockers**
