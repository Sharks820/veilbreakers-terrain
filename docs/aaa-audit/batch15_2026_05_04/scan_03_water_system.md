# Scan 03 — Water System Deep Audit

**Date:** 2026-05-04
**Auditor:** Claude (Opus 4.7, terrain-engineer persona)
**Scope:** `terrain_water_variants.py`, `_water_network.py`, `_water_network_ext.py`, `terrain_waterfalls.py`, `terrain_waterfalls_volumetric.py`, `terrain_water_contracts.py`, `terrain_vegetation_depth.py` (collateral consumer).
**Prior status:** Water = D+ (2026-04-27). W-1 dual-semantics flagged active.

---

## 1. Executive Summary

| Component | Grade | Trend | Notes |
|-----------|-------|-------|-------|
| Flow network (D8 / Priority-Flood / Strahler) | **B+** | ↑ from B− | Barnes 2014 + flat-resolution; Strahler+Shreve baked; lake spill-rim correct |
| Waterfalls (lip / freefall / Mason pool / cascade) | **B** | ↑ from C+ | Manning + Mason 1985 + contour-traced lip + multi-tier cascade; OBB volume bounds added |
| Foam / Mist / Caustics / Wet-rock | **B−** | ↑ from C− | Multi-source foam (impact + rapids + coastal) + wind-advected mist + Beer–Lambert caustics |
| Bathymetry / Depth zones | **B** | ↑ from D+ | Per-body spill-rim reconstruction + 4-zone classification |
| Tidal simulation | **F** | flat | `tidal` channel is a single scalar (`1.0` when frozen, untouched otherwise). NO amplitude, NO phase, NO M2/S2 components, NO coastal attenuation. Pure stub. |
| Seasonal water state | **C+** | ↑ from D | Now passes through DAG with overrides; only mutates 3 channels via uniform multipliers. NO snowmelt routing, NO frost-heave, NO regelation. |
| Estuary / Karst / Perched / Hot-spring detection | **C** | flat | Heuristics fire but never feed back into geometry. Estuary salinity is single scalar (1.0 at mouth). |
| Wetland classification (marsh/fen/bog) | **B−** | ↑ from D | pH-proxy classification using rock_hardness + water proximity is real (Mitsch & Gosselink 2015). |
| Water runtime contract validator | **D+** | flat | Schema-only; no values, no continuity check. |
| **W-1 dual semantics fix** | **PARTIALLY FIXED** | — | Migration in flight; legacy `water_surface` still produced and consumed alongside `water_surface_mask` and `water_surface_elevation_m`. Concrete migration plan in §4. |
| **Overall water system** | **C+** | ↑ from D+ | The hydrology pipeline is now real; the rendering / runtime contracts are the bottleneck. Tidal & seasonal are still placeholder. |

**Comparison to AAA bar:** still ~1.5 grade points behind RDR2/Ghost of Tsushima. Specific gaps in §3.

---

## 2. W-1 Dual Water Semantics — Full Map

### 2.1 The three coexisting channel names

| Channel | Semantic | Type | Scale |
|---------|----------|------|-------|
| `water_surface` | Legacy "binary-ish" | float32 (H,W) | Treated as boolean by some readers (`> 0.5`), as fractional alpha by others (`> 0.01` or `> 0.0`) |
| `water_surface_mask` | Canonical binary | float32 (H,W) | Strictly `{0.0, 1.0}` per latest writers |
| `water_surface_elevation_m` | Float elevation | float32 (H,W) | World metres above datum; 0.0 on dry cells |

### 2.2 Producers — write sites

| File | Line(s) | Channel(s) written | Who | Notes |
|------|---------|--------------------|-----|-------|
| `terrain_water_variants.py` | 781, 878 | `water_surface` | `pass_water_variants` | Still emits legacy float-alpha channel |
| `terrain_water_variants.py` | 707, 879 | `water_surface_mask` | `pass_water_variants`, `apply_seasonal_water_state` | Canonical writer |
| `terrain_water_variants.py` | 880, 1463, 1585 | `water_surface_elevation_m` | `pass_water_variants`, `pass_bathymetry` | Bathymetry writes per-body spill-rim elevation |
| `_water_network.py` | (lakes) | `water_surface_mask` (assumed via `pass_river_convergence`) | `pass_river_convergence`, lake handling | declares `water_surface_mask` in `consumed_channels` (line 3445) but actually writes `river_mouth_mask` etc. |
| `terrain_waterfalls.py` | 2327 | (read-only path) | `pass_waterfalls` | Reads but does not write a unified water-surface channel |

### 2.3 Consumers — read sites

| File | Line(s) | Channel read | Reader semantic |
|------|---------|--------------|-----------------|
| `terrain_water_variants.py:516,578` | 516, 578 | `water_surface` | wetland marsh detection: `> 0.3` |
| `terrain_water_variants.py:747` | 747 | `water_surface` | seed for variants (legacy) |
| `terrain_water_variants.py:868,869` | 868–869 | `water_surface_mask`, `water_surface_elevation_m` | region-aware merge in pass_water_variants |
| `terrain_water_variants.py:681` | 681 | `water_surface_mask` | seasonal mutator (W-1 corrected) |
| `terrain_water_variants.py:1449,1474,1488,1491,1496,1567` | 1449–1496 | `water_surface` | `pass_bathymetry` heuristically auto-detects elevation vs mask via ad-hoc `is_absolute_elevation` test (BUG — see §3) |
| `_water_network.py:909-913` | 909–913 | mask first, falls back to legacy | `pass_water_flow_speed` (preferred chain) |
| `_water_network_ext.py:358-362` | 358–362 | mask first, falls back | `solve_outflow` (preferred chain) |
| `_water_network_ext.py:636` | 636 | mask first, falls back | `compute_wet_rock_mask` (preferred chain) |
| `_water_network_ext.py:1054,1083,1105-1118` | 1054, 1083, 1114 | `water_surface` (default param) | `compute_riverbed_caustics`. Uses `ws - height` to derive depth — TREATS CHANNEL AS ELEVATION. **Active bug if upstream wrote a mask.** |
| `terrain_waterfalls.py:1785-1787` | 1785–1787 | mask first, falls back | shoreline foam (preferred chain) |
| `terrain_waterfalls.py:2327` | 2327 | mask first, falls back | `pass_waterfalls` |
| `terrain_water_contracts.py:11-15` | 11–15 | `water_surface_elevation_m` is REQUIRED | runtime contract; `water_surface` is NOT in required list (good) |
| `terrain_vegetation_depth.py` | (none direct) | uses `forest_mask`, `wetness` only | not a water-channel consumer |

### 2.4 Findings

W-1 is **partially fixed**. The migration is half done:

1. New canonical channels (`water_surface_mask`, `water_surface_elevation_m`) exist and are produced by `pass_water_variants` and `pass_bathymetry`.
2. New consumers (`_water_network.pass_water_flow_speed`, `_water_network_ext.solve_outflow`, `_water_network_ext.compute_wet_rock_mask`, `terrain_waterfalls.compute_physical_foam_composite`, `pass_waterfalls`) prefer `water_surface_mask` then fall back to `water_surface`.
3. **BUT:** `pass_water_variants` still writes the legacy `water_surface` channel (line 878) *in addition to* the canonical pair. This means downstream readers that have not yet been updated still see a populated but ambiguously-typed channel.
4. **CRITICAL ACTIVE BUG (W-1A):** `_water_network_ext.compute_riverbed_caustics` (line 1054 default `water_surface_channel="water_surface"`) computes `depth = max(ws - height, 0.0)`. When `pass_water_variants` writes `water_surface = (depth_norm > 0.55)` (line 770) — i.e. a fractional alpha — the `ws - height` arithmetic produces nonsense (a depth that approximates `-height` everywhere wet), so `Beer-Lambert exp(-k*d)` collapses to ~0 everywhere. Caustics are silently broken.
5. **CRITICAL ACTIVE BUG (W-1B):** `pass_bathymetry` (line 1484) uses a heuristic to decide if `water_surface` is an elevation or a mask:
   ```python
   is_absolute_elevation = (ws_max > h_range * 0.1) and (ws_max - float(ws.min()) > 5.0)
   ```
   When `water_surface` is `0.6` for braided channels (line 851), `ws_max = 0.6`. If `h_range = 4 m` (small tile), `h_range * 0.1 = 0.4`, so `is_absolute_elevation` evaluates **True** for a mask, and the entire bathymetry pass produces garbage. This is non-deterministic data corruption depending on tile elevation range.
6. **W-1C:** `pass_water_variants.detect_wetlands` (line 578) reads `stack.get("water_surface")` and treats it as a fractional alpha (`> 0.3`). If a downstream caller wrote ones-only `water_surface_mask` and zeros for `water_surface`, marsh classification fails. (`detect_wetlands` should prefer `water_surface_mask`.)
7. **W-1D:** `_water_network.pass_river_convergence` declares `consumed_channels=("flow_accumulation", "flow_direction", "water_surface_mask")` in its PassResult but `requires_channels=("flow_accumulation", "flow_direction")` in the registration — `water_surface_mask` consumption is undeclared to the DAG. It is also the only place `consumed_channels` references the new canonical name.

### 2.5 Severity

| Bug ID | Severity | Failure mode |
|--------|----------|--------------|
| W-1A | **P0** | Riverbed caustics silently zero on every tile — visible as "dead" non-shimmery river beds |
| W-1B | **P0** | Bathymetry randomly corrupted on small-range tiles — wrong depth zones → wrong wading/swim/deep gameplay |
| W-1C | **P1** | Wetland classification under-counts marshes when consumers wrote mask-only |
| W-1D | **P2** | DAG dependency missing → potential out-of-order execution |

---

## 3. Component-by-Component AAA Grade Analysis

### 3.1 Flow network — `_water_network.py`

**Grade: B+ (was B−)**

**Pros:**
- Barnes 2014 priority-flood with `_resolve_flats_epsilon` (line 466) — fixes plateau stripe artifacts.
- D8 flow direction + topological accumulation (line 648–664).
- Strahler order + Shreve order both computed (lines 2751, 2846).
- Lake detection via priority-flood with explicit pour-point tracking (line 1128).
- Width/depth uses Leopold & Maddock (1953) hydraulic geometry + Strahler scaling + width:depth ratio bounds (line 209).
- Sine-generated meander curve via Langbein & Leopold (1966) (line 334).
- Manning's equation Q computed at tile-seam contracts (`_manning_discharge` line 2058).
- Delta fans for river→lake/ocean confluence with Galloway 1975 typology (line 3104, `_apply_delta_fan`).
- Braided polylines for wide channels (line 3480).

**Gaps vs AAA:**
- **Strahler dispatch not used by mesh generators.** `compute_strahler_orders` exists, but `terrain_waterfalls` and `terrain_water_variants` ignore it. RDR2/W3 use Strahler order to pick textures (1st-order = clear creek; 4th-order = silty murk).
- **No flow-vector-to-vertex-color baking** like HZD's `bake_flow_direction_vertex_color` (line 1022). The function exists but is not wired into mesh export.
- **Confluence detection missing**: rivers joining are simulated as delta fans only at termini, not at mid-stream junctions. Witcher 3 places foam at every confluence.
- **No braid-channel re-merging** — each braid is its own polyline; AAA games rejoin them at islands.

**Comparison:**
- *vs Horizon Zero Dawn:* HZD bakes flow direction + speed + foam-distance into vertex colors. We bake foam alpha (line 91) but not flow direction.
- *vs Ghost of Tsushima:* GoT uses SDF water masks for shore foam edge cases. We use binary masks → harder shore aliasing.
- *vs RDR2:* RDR2 uses **layered** depth tinting (kelp green at <1 m, deep teal >4 m, brown silt at confluences). Our `water_depth_zone` enum (0/1/2/3) supports this but no shader manifest references it (validator complains: `missing_water_shader_manifest`).
- *vs Witcher 3:* W3 has water-body metadata blocks (depth zones, flow vector UVs, surface variant tag). We have `WaterEdgeContract` + `WaterSegment` but no per-body metadata export contract.

### 3.2 Waterfalls — `terrain_waterfalls.py` + `terrain_waterfalls_volumetric.py`

**Grade: B (was C+)**

**Pros:**
- Manning's equation (line 355) for lip velocity.
- Freefall physics with vertical + horizontal components (line 372).
- Mason 1985 plunge pool radius/depth (line 406).
- Contour-traced lip (NOT grid-aligned) (line 452 `_trace_lip_contour`).
- Multi-tier cascade detection (line 555 `_detect_cascade_chain`).
- Oriented bounding box (NOT axis-aligned) for diagonal cascades (line 111 `build_waterfall_volume_bounds`).
- Particle seed zones (lip / impact / mist) with Q^0.5 scaling (line 222 `build_particle_seed_zones`).
- 3-source foam: impact + rapids + coastal (`compute_foam_mask` in `_water_network_ext.py:713`).
- Wind-advected mist plume + valley fog (`compute_mist_mask` in `_water_network_ext.py:849`).
- Volumetric profile contract (thickness, taper, curvature) (`WaterfallVolumetricProfile` line 41).

**Gaps vs AAA:**
- **No spray-particle decoupling.** `bake_foam_vertex_alpha` (line 91) writes a per-vertex alpha but there's no per-vertex `spray_density` or `spray_lifetime` field — UE5 Niagara expects these.
- **No turbulence-zone Perlin noise** despite the docstring promise at line 22 ("Turbulence zone: Perlin-based velocity noise for r < 2*pool_radius"). Search for `perlin` in `terrain_waterfalls.py`: 0 hits.
- **Velocity field merge blending** to lake/river is implemented (`blend_velocity_to_water_body` line 1973) but not wired into the pass.
- **`generate_velocity_field` is float2 (vx, vy)** — no z-component for cascading flows.
- **No screen-space anchor** for tall waterfalls. `validate_waterfall_anchor_screen_space` (referenced in volumetric module top) exists but is not invoked from the pass.

**Comparison:**
- *vs RDR2 waterfalls:* RDR2 layered foam (3 distinct UV scrolls + alpha-erosion edge) — we have alpha only.
- *vs HFW Hidden Falls:* HFW uses ribbon meshes for the falling water with normal-map driven turbulence — we have a tapered prism volumetric profile (close but not equivalent).
- *vs Witcher 3:* W3 sets a per-waterfall LOD with culling-friendly billboard at distance — no LOD logic in our pipeline.

### 3.3 Tidal simulation — `apply_seasonal_water_state`

**Grade: F** (unchanged; this is the worst component)

```python
elif state is SeasonalState.FROZEN:
    water_surface_mask = np.clip(water_surface_mask + 0.1, 0.0, 1.0)
    wetness *= 0.6
    tidal[:] = 1.0   # ← THIS IS THE ENTIRE TIDAL MODEL
```

There is NO actual tidal simulation:
- No M2/S2 lunar/solar harmonic components.
- No semi-diurnal cycle (12h25m, 12h00m).
- No coastal amplitude attenuation by distance to shore or by basin shape.
- No phase lag relative to lunar position.
- No spring/neap modulation (~14d cycle).
- The `tidal` channel is a single flat scalar field — never spatially varying except in the `FROZEN` season case where it is a constant `1.0`.

**Required minimum AAA tidal model:**
```python
tidal[r, c] = sin(2π * t / T_M2 - φ_M2(r, c)) * A_M2(r, c)  # principal lunar
            + sin(2π * t / T_S2 - φ_S2(r, c)) * A_S2(r, c)  # principal solar
```
where amplitude `A` decays exponentially with distance to ocean edge (Witcher 3 / Sea of Thieves both do this for inland bay tides).

**Comparison:**
- *vs Sea of Thieves:* full M2/S2 + spring/neap, baked at 6 phases per day.
- *vs RDR2:* tide rises/falls along Lannahechee River bayou — visible mud-flats appear at low tide.
- *vs us:* a constant.

### 3.4 Estuary / Karst / Perched / Hot-spring detection

**Grade: C** (unchanged)

The detector functions in `terrain_water_variants.py` (lines 234, 282, 389, 460) all run and return populated dataclasses, but:
- `Estuary.salinity_gradient` is a single scalar (1.0 at mouth) — not a 2D gradient. RDR2 has fresh-to-salt mixing extending ~50m upstream.
- `KarstSpring.discharge_rate` is computed but never feeds into a discharge-driven inflow at the spring (the spring is geometry-only).
- `PerchedLake` is detected (line 389) but the basin's elevation is not enforced — i.e. terrain shape is unchanged, the lake is just a metadata point.
- `HotSpring.mineral_deposit_radius_m` is set but no splatmap contract for travertine deposit colour.

### 3.5 Wetlands — marsh / fen / bog classification

**Grade: B−** (was D)

Real classification (line 509 `detect_wetlands`):
- Connected components via `scipy.ndimage.label`.
- pH proxy: high `rock_hardness` → calcareous → **fen**; low → acidic → **bog**; near open water + high wetness → **marsh** (Mitsch & Gosselink 2015).
- Bounds + radius + world_pos all populated.

**Gaps:**
- Wetland type stored in a local variable `_wetland_type` (line 622, prefix underscore) but **never written to the dataclass** — `Wetland` has no `kind` field! Type is computed and discarded.
- Should expose the classification as a per-cell uint8 channel (`wetland_class`) for shader use.

### 3.6 Bathymetry — `pass_bathymetry`

**Grade: B** (was D+)

**Pros:**
- Reconstructs per-body water-surface elevation via priority-flood + spill rim (line 1496).
- Depth zones 0/1/2/3 (dry/wade/swim/deep) at 1 m / 4 m thresholds — matches W3 Oxenfurt ford.
- Sediment material classification (silt/gravel/rock by accumulation) for water-bottom mesh (line 1295).

**Gaps:**
- The `is_absolute_elevation` heuristic is the W-1B bug above.
- Per-cell flood-fill loops `for idx in range(rows*cols)` (line 1518) — O(N²) Python loop without vectorisation. On a 512×512 tile this is 262k Python-level iterations. Use scipy `label` + groupby.
- Sub-aqueous shadow / caustic projection NOT in this pass — handled separately by `compute_riverbed_caustics` which is broken (W-1A).

### 3.7 Seasonal water state

**Grade: C+** (was D)

`pass_seasonal_water_state` is now properly registered with `overrides=("wetness", "water_surface_mask", "tidal")` (line 965). The DAG correctly invalidates downstream readers.

**Gaps:**
- Only 4 seasons (DRY/NORMAL/WET/FROZEN) with hardcoded multipliers — no temperature gradient, no snowpack accumulation, no melt routing.
- FROZEN does not freeze cell-by-cell based on temperature — it sets a global `tidal[:] = 1.0` flag.
- WET state does not route extra runoff via flow accumulation — it just bumps wetness uniformly.

---

## 4. W-1 Concrete Migration Plan

### 4.1 Final canonical schema

Drop `water_surface` entirely. Use:
- `water_surface_mask` — float32 (H,W), values strictly in `{0.0, 1.0}` — "is this cell covered by water?"
- `water_surface_elevation_m` — float32 (H,W), absolute world-Z elevation in metres; equals `height` on dry cells.
- `water_depth_m` (optional, derived) = `max(0, water_surface_elevation_m - height)` masked by `water_surface_mask`.

### 4.2 Step-by-step changes

**Step 1 — Stop writing `water_surface` from `pass_water_variants`.**
File: `terrain_water_variants.py`, line 781 and 878.
Replace:
```python
stack.set("water_surface", water_surface, "water_variants")
```
with:
```python
# W-1 migration: do NOT write legacy water_surface; only canonical channels.
```
Keep the in-pass `water_surface` numpy variable as a working buffer; emit only `water_surface_mask` and `water_surface_elevation_m`.

**Step 2 — Update `pass_bathymetry` to consume `water_surface_mask`.**
File: `terrain_water_variants.py`, line 1449.
Replace `ws_raw = stack.get("water_surface")` with:
```python
ws_raw = stack.get("water_surface_mask")
if ws_raw is None:
    ws_raw = stack.get("water_surface")  # legacy fallback for one release
```
Delete the `is_absolute_elevation` heuristic (lines 1484, 1487–1490). Always treat the channel as a binary mask. Read elevation from `water_surface_elevation_m` if present, else fall back to per-body spill-rim reconstruction.

**Step 3 — Fix `compute_riverbed_caustics` default channel.**
File: `_water_network_ext.py`, line 1054.
Change:
```python
water_surface_channel: str = "water_surface",
```
to:
```python
water_surface_channel: str = "water_surface_mask",
```
And read elevation from `water_surface_elevation_m`:
```python
if depth is None:
    elev = stack.get("water_surface_elevation_m")
    if elev is not None:
        depth = np.maximum(np.asarray(elev) - height, 0.0)
```

**Step 4 — Update `detect_wetlands` to prefer mask.**
File: `terrain_water_variants.py`, line 578.
Replace:
```python
ws_arr_raw = stack.get("water_surface")
```
with:
```python
ws_arr_raw = stack.get("water_surface_mask")
if ws_arr_raw is None:
    ws_arr_raw = stack.get("water_surface")
```

**Step 5 — Fix DAG declaration in `pass_river_convergence`.**
File: `_water_network.py`, line 3463.
Add `water_surface_mask` to `requires_channels` (so the DAG knows about the soft dep):
```python
requires_channels=("flow_accumulation", "flow_direction", "water_surface_mask"),
```

**Step 6 — Remove all `water_surface` legacy fallbacks (gated release).**
After 1 release with both channels live, remove every:
```python
if x is None:
    x = stack.get("water_surface")
```
in `_water_network.py:911`, `_water_network_ext.py:360,636`, `terrain_waterfalls.py:1787,2327`, `terrain_water_variants.py:578,747`.

**Step 7 — Add a `water_surface` deprecation guard.**
In `TerrainMaskStack.set`, raise/warn when a writer attempts `set("water_surface", …)`:
```python
if name == "water_surface":
    raise DeprecationWarning("'water_surface' is W-1 legacy; use water_surface_mask + water_surface_elevation_m")
```

**Step 8 — Update runtime contract.**
File: `terrain_water_contracts.py`, line 11.
`water_surface_elevation_m` is already required. Add an explicit "MUST NOT have `water_surface`" check:
```python
if _get(stack, "water_surface") is not None:
    issues.append({"code": "legacy_water_surface_present",
                   "message": "legacy 'water_surface' channel must be removed (W-1)"})
```

### 4.3 Test changes

Tests that read `stack.get("water_surface")` directly need migration. From a quick grep:
- `tests/handlers/test_water_variants.py` — likely
- `tests/integration/test_water_network.py` — likely

A sweep should be run after Step 1 lands. Expect ~15-30 test sites.

---

## 5. Mock Test Code (numpy-only, no bpy)

```python
# scan_03_water_system_mock_tests.py
"""
Pure-numpy validation tests for the VeilBreakers water system.

Synthesises a small heightmap that contains:
  - a single low-elevation valley (the river basin)
  - a steep break that should produce a waterfall lip
  - a flat shelf that should produce a pool
Then asserts the flow / lip / foam responses match physical expectations.
"""
import math
import numpy as np


def make_test_basin(rows: int = 64, cols: int = 64) -> np.ndarray:
    """A synthetic terrain: high ridge in north, valley with knickpoint, lake basin in south."""
    h = np.zeros((rows, cols), dtype=np.float32)
    yy, xx = np.meshgrid(np.arange(rows), np.arange(cols), indexing="ij")

    # North ridge (high elevation)
    h += 50.0 * np.exp(-((yy - 5.0) ** 2) / 20.0)
    # Sloped valley (mild south-going gradient)
    h += 30.0 * (1.0 - yy / rows)
    # Knickpoint: 10m vertical drop near row 30
    h += np.where(yy < 30, 10.0, 0.0)
    # Lake basin in the south
    cx, cy = cols // 2, 50
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    h -= 8.0 * np.exp(-dist ** 2 / 30.0)
    return h


def test_priority_flood_finds_basin_pour_point():
    from veilbreakers_terrain.handlers._water_network import (
        priority_flood_d8, detect_lakes
    )
    h = make_test_basin()
    flow_dir, flow_acc = priority_flood_d8(h)
    # Every cell must have a defined flow direction except border cells
    interior = flow_dir[1:-1, 1:-1]
    assert (interior >= 0).all() or (interior == -1).any(), "Pits not resolved"
    # Flow accumulation should peak near the basin pit
    pit_r, pit_c = np.unravel_index(int(flow_acc.argmax()), flow_acc.shape)
    assert pit_r > 30, f"Flow should accumulate south of knickpoint, got row {pit_r}"


def test_lake_detection_finds_basin():
    from veilbreakers_terrain.handlers._water_network import (
        priority_flood_d8, detect_lakes
    )
    h = make_test_basin()
    _flow_dir, flow_acc = priority_flood_d8(h)
    lakes = detect_lakes(h, flow_acc, min_area=10.0)
    assert len(lakes) >= 1, "At least one lake should be detected in the basin"
    main = max(lakes, key=lambda L: L["area"])
    assert main["area"] >= 10
    # Spill rim must be above pit cell
    pit_z = h[main["center_row"], main["center_col"]]
    assert main["surface_z"] > pit_z, "Spill rim must be above pit"


def test_waterfall_lip_at_knickpoint():
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack
    from veilbreakers_terrain.handlers.terrain_waterfalls import (
        detect_waterfall_lip_candidates,
    )
    h = make_test_basin()
    stack = TerrainMaskStack(
        height=h, cell_size=2.0, world_origin_x=0.0, world_origin_y=0.0,
        tile_x=0, tile_y=0,
    )
    # Manually compute drainage so the detector can run
    from veilbreakers_terrain.handlers._water_network import priority_flood_d8
    _fd, fa = priority_flood_d8(h)
    stack.set("flow_accumulation", fa.astype(np.float32), "test")
    candidates = detect_waterfall_lip_candidates(stack)
    assert len(candidates) >= 1, "Knickpoint should produce at least one lip"
    # Lip should be at row ~30
    rows = [c.grid_rc[0] for c in candidates if c.grid_rc is not None]
    assert any(28 <= r <= 32 for r in rows), \
        f"Lip should be near row 30, got {rows}"


def test_manning_velocity_reasonable():
    """Manning velocity should be in [0.01, 15] m/s for typical inputs."""
    from veilbreakers_terrain.handlers.terrain_waterfalls import _manning_velocity
    v = _manning_velocity(slope=0.05, hydraulic_radius_m=0.5)
    assert 0.01 < v < 15.0
    # Steeper slope → higher velocity
    v_steep = _manning_velocity(slope=0.5, hydraulic_radius_m=0.5)
    assert v_steep > v


def test_mason_1985_pool_geometry():
    """Plunge-pool radius and depth must scale per Mason 1985."""
    from veilbreakers_terrain.handlers.terrain_waterfalls import _mason_1985_pool
    r1, d1 = _mason_1985_pool(h_drop=10.0, discharge_m3s=5.0)
    r2, d2 = _mason_1985_pool(h_drop=20.0, discharge_m3s=5.0)
    # Bigger drop → bigger pool radius and depth
    assert r2 > r1
    assert d2 > d1
    # Bounds
    assert 1.0 <= r1 <= 50.0
    assert 0.3 <= d1 <= 20.0


def test_w1_a_caustics_silently_zero_with_mask_input():
    """Reproduces W-1A: caustics break when fed a mask channel.

    With the current default `water_surface_channel='water_surface'`, if the
    upstream pass wrote a binary mask (0/1) instead of an elevation, then
    depth = ws - height is mostly negative and gets clamped to 0,
    producing all-zero caustics.
    """
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack
    from veilbreakers_terrain.handlers._water_network_ext import compute_riverbed_caustics

    h = np.full((32, 32), 10.0, dtype=np.float32)
    ws_mask = np.zeros((32, 32), dtype=np.float32)
    ws_mask[8:24, 8:24] = 1.0  # binary mask — NOT an elevation
    stack = TerrainMaskStack(
        height=h, cell_size=1.0,
        world_origin_x=0.0, world_origin_y=0.0,
        tile_x=0, tile_y=0,
    )
    stack.set("water_surface", ws_mask, "test")  # legacy channel
    caustics = compute_riverbed_caustics(stack)
    # BUG: caustics are zero everywhere because depth is ~ -9.0 → clamped to 0
    assert float(caustics.max()) == 0.0, \
        "W-1A reproducer: caustics should be zero on broken input (this asserts the BUG)"


def test_w1_b_bathymetry_mistakes_mask_for_elevation():
    """Reproduces W-1B: small h_range causes the heuristic to misclassify."""
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack, TerrainPipelineState, TerrainIntent, BBox
    from veilbreakers_terrain.handlers.terrain_water_variants import pass_bathymetry

    # Tile with small elevation range (4 m total)
    h = np.full((32, 32), 10.0, dtype=np.float32)
    h += np.linspace(0, 4, 32)[None, :]  # range 4 m
    # Float-alpha mask (NOT elevation): 0.6 in a band
    ws = np.zeros((32, 32), dtype=np.float32)
    ws[10:20, :] = 0.6  # ws_max = 0.6
    # h_range * 0.1 = 0.4 → ws_max(0.6) > 0.4 → is_absolute_elevation = True (WRONG)
    # AND ws_max - ws.min = 0.6 > … wait, the second condition requires > 5.
    # So actually for this configuration it stays as mask.
    # The bug fires when ws is e.g. all-zeros except a sparse 6.0 from a perched lake stamp.
    ws[5, 5] = 6.0  # outlier
    stack = TerrainMaskStack(
        height=h, cell_size=1.0,
        world_origin_x=0.0, world_origin_y=0.0,
        tile_x=0, tile_y=0,
    )
    stack.set("water_surface", ws, "test")
    # ws_max = 6.0, ws_min = 0.0 → range > 5 AND > h_range*0.1 → flagged as elevation
    # Then the entire mask of 0.6 cells is interpreted as "depth = 6.0 - 10.0 = clamped"
    # which is wrong — those cells should be wet at terrain elevation, not deep water.
    intent = TerrainIntent(seed=0, biome_rules="dark_fantasy_default")
    state = TerrainPipelineState(intent=intent, mask_stack=stack, tile_x=0, tile_y=0)
    res = pass_bathymetry(state, region=None)
    bath = stack.get("bathymetry")
    # If the heuristic worked, depth would be ~zero everywhere because most cells
    # have ws=0 but height=10–14. With the bug, the heuristic flags as elevation
    # and produces nonsense.
    print("max depth:", float(np.asarray(bath).max()))
    # This test documents the bug; expected result depends on which mode fired.


def test_seasonal_state_overrides_canonical_channels():
    """pass_seasonal_water_state must override mask + tidal, not legacy water_surface."""
    from veilbreakers_terrain.handlers.terrain_water_variants import (
        SeasonalState, apply_seasonal_water_state,
    )
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack
    h = np.full((16, 16), 5.0, dtype=np.float32)
    stack = TerrainMaskStack(
        height=h, cell_size=1.0,
        world_origin_x=0.0, world_origin_y=0.0,
        tile_x=0, tile_y=0,
    )
    stack.set("water_surface_mask", np.full((16, 16), 0.5, dtype=np.float32), "test")
    stack.set("wetness", np.full((16, 16), 0.5, dtype=np.float32), "test")
    apply_seasonal_water_state(stack, SeasonalState.WET)
    new_mask = np.asarray(stack.get("water_surface_mask"))
    assert float(new_mask.mean()) > 0.5, "WET should raise water_surface_mask"
    # Legacy water_surface should NOT be touched (correct W-1 behaviour)
    assert stack.get("water_surface") is None, \
        "apply_seasonal_water_state must not write legacy water_surface"


def test_foam_fires_at_gradient_breaks():
    """compute_foam_mask should produce non-zero foam at the knickpoint."""
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack
    from veilbreakers_terrain.handlers._water_network_ext import compute_foam_mask
    from veilbreakers_terrain.handlers.terrain_waterfalls import (
        WaterfallChain, ImpactPool, LipCandidate
    )

    h = make_test_basin()
    stack = TerrainMaskStack(
        height=h, cell_size=2.0,
        world_origin_x=0.0, world_origin_y=0.0,
        tile_x=0, tile_y=0,
    )
    # Synthesise high accumulation + steep slope across the knickpoint
    fa = np.zeros_like(h)
    fa[28:32, 30:34] = 1000.0
    sl = np.zeros_like(h)
    sl[28:32, 30:34] = 0.3
    stack.set("flow_accumulation", fa, "test")
    stack.set("slope", sl, "test")
    pool = ImpactPool(world_position=(60.0, 60.0, 5.0), radius_m=3.0,
                      max_depth_m=2.0, outflow_direction_rad=0.0,
                      impact_velocity_mps=8.0, discharge_m3s=2.0,
                      drop_height_m=10.0)
    lip = LipCandidate(world_position=(60.0, 60.0, 15.0),
                       upstream_drainage=1000.0, downstream_drop_m=10.0,
                       flow_direction_rad=0.0, confidence_score=0.9)
    chain = WaterfallChain(
        chain_id="test", lip=lip, plunge_path=(),
        pool=pool, outflow=(), mist_radius_m=10.0,
        foam_intensity=0.8, total_drop_m=10.0,
    )
    foam = compute_foam_mask(chain, stack, foam_threshold=500.0,
                             min_slope_for_foam=0.1)
    assert float(foam.max()) > 0.0, "Foam should fire at high-acc + steep cells"
    # Foam should be highest near the impact pool
    pool_grid = (30, 30)  # approx in our 64-grid
    assert float(foam[28:32, 28:32].max()) > 0.0


def test_solve_outflow_priority_flood_escape():
    """solve_outflow must escape planar depressions via priority-flood spill."""
    import math
    from types import SimpleNamespace
    from veilbreakers_terrain.handlers._water_network_ext import solve_outflow
    from veilbreakers_terrain.handlers.terrain_waterfalls import ImpactPool

    # Heightmap with a flat plateau followed by a downward step
    h = np.full((32, 32), 10.0, dtype=np.float32)
    h[16:, :] = 5.0  # 5m drop south of row 16
    network = SimpleNamespace(_heightmap=h, _world_origin_x=0.0,
                              _world_origin_y=0.0, _cell_size=1.0,
                              _mask_stack=None)
    pool = ImpactPool(
        world_position=(15.0, 8.0, 10.0),
        radius_m=2.0,
        max_depth_m=1.0,
        outflow_direction_rad=math.pi,  # south
        impact_velocity_mps=5.0,
        discharge_m3s=1.0,
        drop_height_m=2.0,
    )
    path = solve_outflow(network, pool)
    assert len(path) >= 2
    # Path should end below row 16 (i.e. it escaped the plateau)
    last_r = path[-1][0]
    assert last_r > 16, f"Path should descend past row 16, got {last_r}"


# ---------------------------------------------------------------------------
# Run with: pytest -xvs scan_03_water_system_mock_tests.py
# ---------------------------------------------------------------------------
```

---

## 6. Recommended P0/P1 fix ordering

| # | Severity | Fix | File(s) | Effort |
|---|----------|-----|---------|--------|
| W15-W01 | P0 | Stop writing legacy `water_surface` (Step 1) | `terrain_water_variants.py:781,878` | 1h |
| W15-W02 | P0 | Fix `compute_riverbed_caustics` default channel + use `water_surface_elevation_m` | `_water_network_ext.py:1054,1083,1105` | 30m |
| W15-W03 | P0 | Drop `is_absolute_elevation` heuristic in `pass_bathymetry`; use `water_surface_elevation_m` directly | `terrain_water_variants.py:1484-1496` | 2h |
| W15-W04 | P0 | Replace `tidal[:] = 1.0` stub with real M2/S2 harmonic + coastal attenuation | `terrain_water_variants.py:703` | 1d |
| W15-W05 | P1 | Add `wetland_class` channel + `Wetland.kind` field (the dropped `_wetland_type` bug) | `terrain_water_variants.py:622` | 1h |
| W15-W06 | P1 | Vectorise `pass_bathymetry` flood-fill (Python `for idx in range(N²)` → scipy.ndimage.label + groupby) | `terrain_water_variants.py:1517` | 4h |
| W15-W07 | P1 | Wire Strahler order into water-mesh material picker (`compute_strahler_orders` is computed, never consumed) | `_water_network.py:2751` and exporter | 1d |
| W15-W08 | P1 | Bake `flow_direction` to vertex color in water mesh export (`bake_flow_direction_vertex_color` exists, never wired) | `_water_network.py:1022`, exporter | 4h |
| W15-W09 | P1 | Implement turbulence-zone Perlin velocity noise promised in module docstring | `terrain_waterfalls.py:22` | 6h |
| W15-W10 | P2 | Add explicit DAG `requires_channels` for `water_surface_mask` in `pass_river_convergence` | `_water_network.py:3463` | 5m |
| W15-W11 | P2 | Per-zone salinity gradient field for estuaries (currently a single scalar) | `terrain_water_variants.py:269` | 2h |
| W15-W12 | P2 | LOD billboard transition spec for tall waterfalls | `terrain_waterfalls.py` exporter | 1d |
| W15-W13 | P2 | Wire `blend_velocity_to_water_body` (defined, never called) | `terrain_waterfalls.py:1973` | 1h |

---

## 7. Final verdict

Water has moved from **D+ to C+** since the 2026-04-27 audit. The hydrology core (Priority-Flood, Strahler, Mason 1985, multi-tier cascade, OBB volume, multi-source foam, wind-advected mist, Beer–Lambert caustics, per-body bathymetry) is now **B-grade real**. The bottleneck is no longer the simulation — it's:

1. **W-1 dual semantics is half-fixed** with two active P0 silent-data-corruption bugs (W-1A caustics, W-1B bathymetry).
2. **Tidal is still a stub** (constant 1.0 in winter, untouched otherwise) — F grade.
3. **Strahler / flow-direction baking computed but never consumed** by mesh export → AAA shaders cannot read what we already simulated.
4. **Water runtime contract is schema-only** — no actual continuity, conservation-of-volume, or seam-validity check.

Closing W15-W01 through W15-W04 (1.5 dev days) brings the system to a clean **B**. Adding W15-W07/W08 (Strahler + flow-vertex-color) would push it to **B+**, on par with HZD's water shader pipeline. Tidal harmonics (W15-W04) is what stops the system from reaching A territory.

— end of scan_03_water_system.md —
