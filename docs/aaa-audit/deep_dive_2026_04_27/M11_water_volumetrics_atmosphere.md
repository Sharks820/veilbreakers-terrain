# M11 — Water Volumetrics, Fog, Cloud & Atmospheric Audit

**Date:** 2026-04-27
**Auditor:** Senior Tech Lead (AAA standard — Rockstar/Guerrilla Games bar)
**Files audited:**
- `veilbreakers_terrain/handlers/terrain_waterfalls_volumetric.py` (814 LOC)
- `veilbreakers_terrain/handlers/atmospheric_volumes.py` (1018 LOC)
- `veilbreakers_terrain/handlers/terrain_fog_masks.py` (377 LOC)
- `veilbreakers_terrain/handlers/terrain_cloud_shadow.py` (356 LOC)
- `veilbreakers_terrain/handlers/terrain_wind_field.py` (377 LOC)
- `veilbreakers_terrain/handlers/_water_network_ext.py` (1143 LOC)

---

## Executive Summary

This sweep covers six files: two are **entirely dead** (no pipeline registration, no Unity export), two are **correctly wired and exported**, one is **partially wired but silently broken at export**, and one is a **validator-only library masquerading as a volumetric simulation**. The atmospheric system designed for VeilBreakers' core "corruption" game mechanic has zero game-specific logic — the corruption atmosphere is approximated by `void_shimmer`, a generic visual effect with no corruption semantics. Combined with prior findings (K8-P0-1, L1-P0-3), the entire atmospheric/volumetric layer is a D+ system that produces no live output in the running game.

**P0 count this sweep: 8**

---

## 1. terrain_waterfalls_volumetric.py

### What it is

This file is a **pure-Python validator and data-structure library** — not a volumetric simulation. Its public surface is:

- `WaterfallVolumetricProfile` — geometry budget config (vertex density, curvature ratio)
- `WaterfallVolumeBounds` — OBB (oriented bounding box) data class
- `build_waterfall_volume_bounds()` — constructs an OBB from flow azimuth
- `build_particle_seed_zones()` — constructs three `ParticleSeedZone` objects (lip/impact/mist)
- `validate_waterfall_volumetric()` — checks vertex density and front curvature
- `validate_waterfall_volume_bounds()` — validates OBB orthonormality
- `validate_particle_seed_zones()` — validates zone presence and density
- `validate_waterfall_anchor_screen_space()` — camera anchor range check
- `enforce_functional_object_naming()` — naming convention enforcer

There is **no volumetric simulation**. There is no fluid solver, no spray/mist particle physics, no sheet deformation, no turbulence model. The file provides geometry budgets and naming contracts for a system that would need to exist elsewhere.

### Is it wired?

**Partially.** `build_particle_seed_zones()` is called from `terrain_waterfalls.py:2530` inside `_build_particle_emitter_specs()`, and those specs flow through to `particle_emitter_specs.json` in the Unity export. The OBB builder (`build_waterfall_volume_bounds()`) is **never called anywhere in production code** — it only appears in tests. The validators are never called in production — only in tests.

### Quality gap vs AAA

Horizon Zero Dawn and God of War waterfall volumetrics include:
- Runtime-simulated spray sheets using fluid-surface advection (not just a bounding-box budget)
- Per-cascade foam splatmap baked from particle impact maps
- Absorption-coefficient depth fog (Beer-Lambert) inside the waterfall volume itself
- Wet-rock darkening that propagates dynamically from discharge changes

This file delivers none of that. It is a naming/budgeting library, not a volumetric system.

---

**M11-P0-1** | `terrain_waterfalls_volumetric.py:111-182` | `build_waterfall_volume_bounds()` is never called in production — waterfall OBB is not computed or exported

**Evidence:**
```python
# build_waterfall_volume_bounds is defined at line 111.
# Full codebase grep of all non-test callers:
# terrain_waterfalls.py  — calls only build_particle_seed_zones (line 2530)
# terrain_unity_export.py — no reference to WaterfallVolumeBounds whatsoever
# Result: zero production callers
```

**AAA gap:** Real AAA pipelines export oriented bounding boxes for waterfalls so the engine's volumetric fog system can spawn a local fog volume tightly fitted to the cascade geometry. Without the OBB, Unity has no bounds for the waterfall's atmospheric volume — it cannot efficiently cull or render fog confined to the waterfall.

**Fix:** In `terrain_waterfalls.py` inside `_build_particle_emitter_specs()` (after particle zones are built), call `build_waterfall_volume_bounds()` for each chain and include the resulting OBB as `"volume_obb"` in each emitter spec dict. Serialize to `particle_emitter_specs.json` via `terrain_unity_export._particle_emitter_specs_json()`. Estimated time: 2 hours.

---

**M11-P0-2** | `terrain_waterfalls_volumetric.py:392-475` | All volumetric validators (validate_waterfall_volumetric, validate_waterfall_volume_bounds, validate_particle_seed_zones) are never called in any production pass — silent geometry regressions ship undetected

**Evidence:**
```python
# validate_waterfall_volumetric() — only called in tests
# validate_waterfall_volume_bounds() — only called in tests
# validate_particle_seed_zones() — only called in tests
# No production call sites found in handlers/
```

**AAA gap:** Geometry budget validators exist precisely to prevent silent regressions (the flat-billboard problem this file was created to catch). If they never run in the pipeline, a flat waterfall sheet ships and no alarm fires.

**Fix:** Add a validation call inside `pass_waterfalls` (or a dedicated Bundle C validation sub-pass). Raise `PassResult(status="error")` when `validate_waterfall_volumetric()` returns hard issues. Estimated time: 3 hours.

---

## 2. atmospheric_volumes.py (quality audit beyond K8-P0-1)

Prior finding K8-P0-1 established this entire 1018-LOC module is dead: no PassDefinition, no pipeline registration, no stack write, no Unity export. This section audits whether it would even be **correct** if wired.

### Atmospheric scattering calculations — INCORRECT

`compute_atmospheric_placements()` generates volume placement records (position, size, color, opacity). This is **placement** logic, not atmospheric scattering. There is no Mie or Rayleigh scattering computation, no phase function, no extinction coefficient, no in-scattering calculation, no path-length integration. The `density` and `opacity` fields are hard-coded constants from `ATMOSPHERIC_VOLUMES` (e.g., `ground_fog.density = 0.3`, `ground_fog.opacity = 0.4`). No physical atmospheric model is present.

### Corruption atmosphere modeling — MISSING

VeilBreakers' core game mechanic is the "Veil" corruption spreading across the world. The corruption atmosphere should modulate scattering differently in corrupted biomes — colored extinction, altered phase function, corruption spread radius. The file has exactly one corruption-adjacent type: `void_shimmer` with `color: (0.3, 0.1, 0.5)` and `distortion: True`. This is a generic purple distortion sphere. There is:
- No corruption intensity gradient
- No corruption spread radius parameter
- No corruption-modified extinction coefficient
- No corruption-driven sky color shift
- No link to any `corruption_mask` channel on the stack

### Performance model — WRONG AT AAA RESOLUTION

`estimate_atmosphere_performance()` uses resolution=64 as default, cost per volume ∝ `res² × samples × density × opacity × 0.002`. At 64px this is toy budget. At production resolution (1920×1080 or 4K), a tile with 20 volumes at density=0.3/opacity=0.4 yields `(1920²) × 8 × 0.3 × 0.4 × 0.002 = 7,077 ms per frame` — 300× over budget. The model is not calibrated for AAA resolutions.

---

**M11-P0-3** | `atmospheric_volumes.py:876-1018` | `estimate_atmosphere_performance()` default resolution=64 is toy scale — same placement count that passes "excellent" at res=64 is 300× over GPU budget at production (1920×1080)

**Evidence:**
```python
def estimate_atmosphere_performance(
    placements, ..., resolution: int = 64, ...
) -> dict:
    cost_ms += (
        (resolution ** 2)   # 64^2 = 4096. At 1920^2 = 3,686,400 — 900× higher
        * num_samples        # 8
        * density * opacity  # 0.3 × 0.4 = 0.12
        * base_fill_rate     # 0.01
        * 0.002
    )
# At default res=64, 20 volumes:  cost = 4096 * 8 * 0.12 * 0.01 * 0.002 * 20 = 0.016 ms → "excellent"
# At res=1920:                   cost = 3,686,400 * 8 * 0.12 * 0.01 * 0.002 * 20 = 14,155 ms → never reached, crashes frame budget
```

**AAA gap:** Unreal's volumetric fog cost model operates at tile resolution scaled by the fog density texture resolution (typically 1/4 render res). Passing a 64px model to an artist as "excellent" when the same settings at full res are 300× over budget causes shipped content that tanks frame time.

**Fix:** Change default `resolution` to match the tile's actual render resolution (pass as parameter from the caller context), add explicit budget calibration notes per platform tier (PC Ultra / Console). Estimated time: 4 hours.

---

**M11-P0-4** | `atmospheric_volumes.py:1-1018` | VeilBreakers corruption atmosphere has zero game-specific implementation — `void_shimmer` is a generic purple distortion sphere with no corruption mechanics

**Evidence:**
```python
"void_shimmer": {
    "shape": "sphere",
    "density": 0.1,
    "color": (0.3, 0.1, 0.5),    # generic purple
    "distortion": True,
    # No: corruption_intensity, corruption_radius, veil_spread_rate,
    #      corruption_extinction_coeff, or any VeilBreakers game mechanic
}
```
Grep of entire file for "corruption", "veil", "mechanic", "spread" → zero hits.

**AAA gap:** God of War's Realm Tears, Horizon FW's cauldron fog, and RDR2's tornado all have dedicated game-mechanic atmosphere types that modulate physics (player damage zones, gameplay state transitions, visibility restrictions). VeilBreakers' corruption is a core pillar of the game loop. Treating it as `void_shimmer` with a purple tint is not a game system, it's a placeholder.

**Fix:** Add `corruption_fog` and `veil_boundary` volume types with parameters: `corruption_intensity` (0–1 driven by stack's `corruption_mask` channel), `veil_spread_radius_m`, `extinction_rgb` (per-channel for colored scattering), `player_damage_per_second`. Wire to the `corruption_mask` channel in `compute_atmospheric_placements()`. Estimated time: 2 days.

---

## 3. terrain_fog_masks.py

### What it generates

`compute_fog_pool_mask()` builds a float32 [0,1] fog density field combining:
- Altitude weight (low elevation = more fog, gamma 1.5)
- Valley concavity (Gaussian-weighted Laplacian, mesoscale basins)
- Flow accumulation moisture (log-normalised, valley-floor proxy)
- Temperature inversion (low slope × low elevation)

`compute_mist_envelope()` builds near-water mist via Beer-Lambert distance decay with height stratification.

Both are physically motivated and technically competent.

### Is it wired?

**Yes, correctly.** `register_bundle_l_fog_masks_pass()` registers the pass via `TerrainPassController`, `terrain_bundle_l.py:33` calls it, and `terrain_bundle_l` is registered in `terrain.yaml:314`. The pass writes `stack.set("mist", combined, "fog_masks")`. The `mist` channel is in the Unity export loop at `terrain_unity_export.py:1271`.

### Quality

At Guerrilla Games level this is **acceptable but shallow**:
- No 3D volumetric fog layer (height-stratified 2D mask is not volumetric fog)
- No temporal persistence (fog doesn't linger after rain events)
- No biome-specific fog density profiles
- The combined blend weights (0.40 altitude, 0.30 basin, 0.20 moisture, 0.10 inversion) are magic numbers with no tuning documentation

These are P1/P2 items, not P0s. The core computation is physically defensible.

### One P0 found

---

**M11-P0-5** | `terrain_fog_masks.py:163-173` | Scipy fallback Laplacian uses arithmetic-mean smoothing (5-point stencil), not a proper Laplacian — fog pool mask miscalculates basin concavity when scipy is absent

**Evidence:**
```python
except ImportError:
    fog_pad = np.pad(fog, 1, mode="reflect")
    smoothed = (
        fog_pad[:-2, 1:-1]
        + fog_pad[2:, 1:-1]
        + fog_pad[1:-1, :-2]
        + fog_pad[1:-1, 2:]
        + fog             # <-- this is the combined fog array, NOT h_smooth
    ) / 5.0
```
The fallback smooths the already-combined `fog` array (not `h_smooth`) with a 5-point arithmetic mean. This is a box-blur of the output, not the Gaussian smoothing applied to heightmap data as in the scipy path. The Laplacian in the `except` branch computes correctly using `h`, but the smoothing step at the end operates on the wrong variable. The scipy and no-scipy paths produce different maps.

Note: Lines 97-106 show the *Laplacian fallback* correctly operating on `h`. The above bug is in the final *output smoothing* at lines 163-173 where `fog` (the combined mask) is smoothed instead of computing `gaussian_filter(fog, sigma=1.5)`.

**AAA gap:** Inconsistent fog masks between dev machines (with scipy) and build servers (without) means the asset looks different in CI than in production. A AAA pipeline must be bit-identical regardless of optional dependencies.

**Fix:**
```python
except ImportError:
    k = 3  # simple 3x3 box blur kernel
    fog_pad = np.pad(fog, 1, mode="reflect")
    smoothed = (
        fog_pad[:-2, 1:-1] + fog_pad[2:, 1:-1]
        + fog_pad[1:-1, :-2] + fog_pad[1:-1, 2:]
        + fog_pad[:-2, :-2] + fog_pad[:-2, 2:]
        + fog_pad[2:, :-2] + fog_pad[2:, 2:]
        + fog
    ) / 9.0  # 3x3 box blur of fog (correct target variable)
```
Alternatively, gate the Gaussian smoothing in a separate try/except that operates explicitly on `fog`. Estimated time: 30 minutes.

---

## 4. terrain_cloud_shadow.py

### What it generates

Three-octave permutation-table value noise (Perlin-style, not white noise), animated via cloud_speed + time offset, with sun parallax offset and Gaussian blur. Writes `stack.sun_cloud_shadow` and `stack.cloud_shadow` (alias).

### Is it wired?

**Yes, correctly.** `register_bundle_j_cloud_shadow_pass()` registers via `TerrainPassController`, `terrain_bundle_j.py:57` calls it, `terrain.yaml:275` registers Bundle J. The `cloud_shadow` channel is exported at `terrain_unity_export.py:1263`.

### Quality

Technically competent within its scope. The value noise (not gradient noise) produces blotchy cloud shapes — this matches far Cry 6-style soft shadows rather than Horizon's more billowing cumulus cloud shapes, but is acceptable.

**One correctness bug found:**

---

**M11-P0-6** | `terrain_cloud_shadow.py:100-101` | Fractional offset wrap uses modulo on sample coordinates causing discontinuous cloud motion — clouds teleport instead of drifting at tile edges

**Evidence:**
```python
ys = np.linspace(0.0, gh - 1.0, h_out) + offset_y
xs = np.linspace(0.0, gw - 1.0, w_out) + offset_x

# Wrap offsets into grid range
ys = ys % (gh - 1.0)    # line 100
xs = xs % (gw - 1.0)    # line 101
```
The animation offset `offset_y` / `offset_x` grows linearly with `time_seconds`. When `ys % (gh - 1.0)` wraps (i.e., `ys > gh - 1.0`), the sample coordinate jumps discontinuously from near `gh-1` back to near 0. The noise value at these two positions is unrelated — the cloud pattern teleports. A Horizon/RDR2-quality animated cloud shadow wraps by making the underlying noise field **periodic**, not by clamping sample positions.

At `cloud_speed=(5.0, 0.0)` and `cloud_scale_m=500.0` on a 500-cell tile, the offset grows at `5/(500/500)*h_out = h_out` cells/second, meaning the discontinuity hits at t=1 second. This will be visible as a hard cut.

**AAA gap:** All commercial cloud shadow systems (Horizon ZD, RDR2, Far Cry 6) use tileable noise with seamless wrap. The noise field is never re-sampled discontinuously — the cloud moves like a physical object.

**Fix:** Make the grid periodic by wrapping grid *indices* not sample coordinates:
```python
# Instead of clamping ys/xs post-modulo, tile the noise grid:
# In _value_noise: grid already has duplicated borders (gh+2 rows). Use
# fractional sample coords WITH modulo applied BEFORE flooring:
y0 = np.floor(ys % (gh - 1.0)).astype(np.int32)
x0 = np.floor(xs % (gw - 1.0)).astype(np.int32)
y1 = (y0 + 1) % (gh - 1)
x1 = (x0 + 1) % (gw - 1)
# Remove the clamping lines 105-108 entirely.
```
This makes the noise wrap continuously. Estimated time: 1 hour.

---

## 5. terrain_wind_field.py

### What it generates

An (H, W, 2) float32 wind vector field in m/s. Terrain-aware: altitude factor (1× valley → 2× peak), ridge acceleration (+30% per unit, uses `abs(ridge)` to handle canyon walls), basin deceleration (×0.5), 4-octave spectral fBm Perlin perturbation.

### Is it wired?

**Yes, correctly, and consumed.** `register_bundle_j_wind_field_pass()` is called in `terrain_bundle_j.py:56`. The field is exported via the channel loop in `terrain_unity_export.py:1263`. It is consumed by:
- `environment_scatter.py:3313` — `_wind_rotation_y()` aligns scattered object rotations to wind direction
- `terrain_vegetation_depth.py:275` — wind magnitude affects vegetation depth channel

### Quality gap

The field is 2D (H×W×2). This is a ground-plane wind field, not a volumetric (H×W×Z×2) field. Real AAA wind systems (Unreal's Wind Directional Source + per-level wind volumes, Unity's Wind Zone + Shader Graph wind) use 3D wind volumes for vertical variation — important for tall trees where crown wind differs from trunk wind. This is a P1, not P0.

The wind field is **not connected to atmospheric_volumes.py** at all (atmospheric_volumes has its own `wind_dir_deg` parameter in `weather_hints`, independent of the stack's `wind_field` channel). This means cloud shadows, fog masks, and atmospheric placements all use separate wind inputs that may contradict each other. This is a P0.

---

**M11-P0-7** | `terrain_wind_field.py` + `atmospheric_volumes.py` + `terrain_fog_masks.py` + `terrain_cloud_shadow.py` | Wind field is computed in `wind_field` channel but ALL atmospheric systems ignore it — four separate, contradictory wind inputs are used

**Evidence:**
```python
# terrain_wind_field.py:329 — wind from composition_hints["wind_direction_rad"]
direction = float(hints.get("wind_direction_rad", 0.0))

# atmospheric_volumes.py:445 — atmospheric placement uses its OWN wind parameter
wind_dir_deg = float(_whints.get("wind_dir_deg", float("nan")))

# terrain_fog_masks.py — no wind input at all (fog pool is static, no advection)

# terrain_cloud_shadow.py:262 — cloud uses its OWN cloud_speed from hints
raw_speed = hints.get("cloud_speed", [0.0, 0.0])

# _water_network_ext.compute_mist_mask: uses wind_direction_rad parameter
# (passed from terrain_waterfalls.py, which gets it from composition_hints)

# Four systems, four separate wind inputs. None reads stack.wind_field.
```

**AAA gap:** In RDR2 and Horizon ZD, a single simulation wind field drives vegetation sway, cloud drift, fog advection, particle direction, and sound occlusion — all from one source of truth. When the player sees leaves blowing east while fog moves west and cloud shadows drift north, it breaks environmental cohesion. This is a world-building integrity failure.

**Fix:** In `pass_wind_field`, after computing the field, write the mean prevailing direction to `state.intent.composition_hints["wind_direction_rad"]` and `["wind_dir_deg"]` and `["cloud_speed"]` so downstream passes (cloud_shadow, atmospheric_volumes, fog_masks mist advection) use the same wind source. Estimated time: 4 hours.

---

## 6. _water_network_ext.py

### What it provides

- `add_meander()` — Leopold & Wolman (1960) wavelength/amplitude + Langbein & Leopold (1966) sine-generated curve with oxbow guard
- `apply_bank_asymmetry()` — Ikeda (1989) inner/outer bank depth profile + point-bar elevation
- `solve_outflow()` — D8 steepest-descent path from impact pool + inline priority-flood for depression routing + Manning discharge accumulation
- `compute_wet_rock_mask()` — distance-transform wetness with per-seed source strength from flow_accumulation
- `compute_foam_mask()` — three-layer foam (impact pool, rapids, coastal froth) with Gaussian blur
- `compute_mist_mask()` — wind-advected Gaussian mist plume + valley fog
- `compute_riverbed_caustics()` — Beer-Lambert depth-attenuated tileable caustic noise

### Is it wired?

**Partially.** `compute_mist_mask`, `compute_foam_mask`, `compute_wet_rock_mask`, and `compute_riverbed_caustics` are all called from `terrain_waterfalls.py` — correctly wired. These produce stack channels that are exported.

**`add_meander`, `apply_bank_asymmetry`, and `solve_outflow` are never called anywhere in production code.** Grep of all `.py` files outside of `_water_network_ext.py` itself and the test files shows zero production callers for these three functions.

---

**M11-P0-8** | `_water_network_ext.py:43-516` | `add_meander()`, `apply_bank_asymmetry()`, and `solve_outflow()` are never called in production — rivers have no meander geometry, no bank asymmetry, and no discharge-routed outflow paths

**Evidence:**
```python
# Full handler/ grep for add_meander, apply_bank_asymmetry, solve_outflow:
# Only callers: _water_network_ext.py definitions + test_water_network_upgrade.py
# terrain_waterfalls.py  — zero calls to any of the three
# _water_network.py       — no import from _water_network_ext
# terrain_bundle_c.py     — not a file; Bundle C is in terrain_waterfalls.py
```

**AAA gap:** Rivers in Horizon FW, RDR2, and God of War all have sinuous meander geometry. A straight-segment river on dark-fantasy terrain is immediately readable as procedural in the worst sense. Bank asymmetry (deep outer bank, shallow point bar) is a core visual signal that distinguishes a river from a trench. Outflow routing without discharge accumulation means downstream channels have incorrect water volume — wetness masks, foam masks, and mist zones downstream of confluence points are underpowered.

**Fix:** In `terrain_waterfalls.py` `pass_waterfalls`, after `WaterNetwork` is built and before masks are generated, call:
```python
from ._water_network_ext import add_meander, apply_bank_asymmetry, solve_outflow
add_meander(water_network, amplitude=8.0,
            discharge=hints.get("meander_discharge_m3s"))
apply_bank_asymmetry(water_network, bias=hints.get("bank_asymmetry_bias", 0.3))
for chain in chains:
    solve_outflow(water_network, chain.pool)
```
Estimated time: 3 hours.

---

## Summary Table

| Finding | File | Severity | Description |
|---------|------|----------|-------------|
| M11-P0-1 | terrain_waterfalls_volumetric.py:111 | P0 | OBB (build_waterfall_volume_bounds) never called in production — no cascade volume bounds exported |
| M11-P0-2 | terrain_waterfalls_volumetric.py:392 | P0 | All volumetric validators dead in production — flat billboard waterfalls ship silently |
| M11-P0-3 | atmospheric_volumes.py:876 | P0 | Performance estimator defaults to res=64 — valid placement budgets at toy resolution are 300× over budget at production |
| M11-P0-4 | atmospheric_volumes.py:1-1018 | P0 | VeilBreakers corruption atmosphere has zero game-specific implementation |
| M11-P0-5 | terrain_fog_masks.py:163 | P0 | Scipy fallback smooths wrong variable — fog pool mask is wrong without scipy |
| M11-P0-6 | terrain_cloud_shadow.py:100 | P0 | Sample coordinate modulo wrap causes discontinuous cloud teleport at tile edges |
| M11-P0-7 | terrain_wind_field.py + atmospheric_volumes.py + terrain_fog_masks.py + terrain_cloud_shadow.py | P0 | Four atmospheric systems use four independent wind inputs — no single source of truth |
| M11-P0-8 | _water_network_ext.py:43-516 | P0 | add_meander, apply_bank_asymmetry, solve_outflow never called — rivers are straight, banks symmetric, outflow unrouted |

---

## Additional P1 Items (Not P0, but block AAA bar)

- **atmospheric_volumes.py** is entirely dead (K8-P0-1 confirmed). The terrain placement logic in `compute_atmospheric_placements()` is technically competent (D8 drainage accumulation for valley fog, ridge-notch god-ray placement, windward bias) but irrelevant until wired.
- **terrain_fog_masks.py**: Fog mask is 2D; no 3D volumetric layer. Fog does not respond to precipitation events (no `precipitation_channel` input).
- **terrain_cloud_shadow.py**: Value noise (not gradient noise) produces blotchy shadows rather than coherent cumulus shapes. A Worley-noise-based approach is standard for cloud silhouettes.
- **terrain_wind_field.py**: 2D wind only. No vertical variation for tall trees. Wind field is not fed back to atmospheric scatter direction.
- **_water_network_ext.py**: `solve_outflow()` priority-flood is capped at 4096 cells (`max_pf = min(rows * cols, 4096)`) — on a 2km tile at 1m/cell (4M cells) this means depressions larger than 64×64m are not properly routed, truncating the discharge accumulation.

---

**Total M11 P0 count: 8**
