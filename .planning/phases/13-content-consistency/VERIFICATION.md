---
phase: 13-content-consistency
verified: 2026-04-19T00:00:00Z
status: passed
score: 7/7
overrides_applied: 0
---

# Phase 13: Content Consistency — Verification Report

**Phase Goal:** Foam vertex alpha, wind bend vertex color, and UNITY_SCALE_FACTOR=0.85 — three surgical content-system fixes baked into water and tree mesh export.
**Verified:** 2026-04-19
**Status:** COMPLETE
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `bake_foam_vertex_alpha` present in `terrain_waterfalls.py` with exact formula | PASS | Line 67–93; formula matches spec |
| 2 | Foam values clamped [0,1] via `saturate()` | PASS | `saturate()` wraps both `prox_ratio` and final result; line 90, 93 |
| 3 | `UNITY_SCALE_FACTOR = 0.85` defined in `terrain_unity_export.py` | PASS | Line 25, type-annotated `UNITY_SCALE_FACTOR: float = 0.85` |
| 4 | `compute_wind_bend_vertex_color` present with R=xz bend, quadratic height falloff | PASS | Lines 700–763; R channel at line 759 |
| 5 | `_tree_instances_json` reads `tree_instance_points` and emits `vertex_color` | PASS | Lines 766–802; `stack.tree_instance_points` read at 768, `vertex_color` emitted at 800 |
| 6 | `export_water_mesh_vertices` present and calls `bake_foam_vertex_alpha` | PASS | Lines 96–137; called at line 123 |
| 7 | No conflicting scale factor overrides (no 1.0 or other hard-coded multiplier) | PASS | Only `UNITY_SCALE_FACTOR`-based multiplication in export path; no competing scale constant found |

**Score: 7/7**

---

## Deliverable Detail

### 1. Foam Vertex Alpha (`terrain_waterfalls.py`)

**File:** `veilbreakers_terrain/handlers/terrain_waterfalls.py`

**Constants:**
- `FOAM_RADIUS_DEFAULT: float = 2.0` — line 58
- `MAX_FOAM_SPEED_DEFAULT: float = 5.0` — line 59

**`saturate()` — line 62–64:**
```python
return np.clip(x, 0.0, 1.0) if isinstance(x, np.ndarray) else max(0.0, min(1.0, float(x)))
```
Handles both scalar and ndarray. Status: PASS

**`bake_foam_vertex_alpha()` — lines 67–93:**
```python
prox_ratio = saturate(obstacle_proximity / max(foam_radius, 1e-9))
speed_ratio = 1.0 - flow_speed / max(max_foam_speed, 1e-9)
result = prox_ratio * speed_ratio
return saturate(result)
```

Formula check vs spec (`saturate(proximity / foam_radius) * (1.0 - speed / max_speed)`):
- Prox term: `saturate(obstacle_proximity / foam_radius)` — MATCHES (1e-9 guard for zero-division is a correctness addition, not a deviation)
- Speed term: `1.0 - flow_speed / max_foam_speed` — MATCHES
- Output clamp: double `saturate()` ensures [0,1] even for negative speed ratios — MATCHES requirement
- Status: PASS

**Boundary checks confirmed by tests:**
- proximity=0 → 0.0 (test_zero_proximity_gives_zero)
- proximity=foam_radius, speed=0 → 1.0 (test_full_proximity_zero_speed_gives_one)
- proximity=foam_radius, speed=max → 0.0 (test_max_speed_gives_zero)
- speed > max → 0.0, not negative (test_above_max_speed_clamped_to_zero)

**`export_water_mesh_vertices()` — lines 96–137:**
- Builds per-vertex dicts with `"position"` and `"foam_alpha"` keys
- Calls `bake_foam_vertex_alpha(obstacle_prox, flow_speed_field)` at line 123
- Falls back to EDT from `rock_mask` if available, else zeros
- Listed in `__all__` at line 1207
- Status: PASS

---

### 2. Wind Bend Vertex Color (`terrain_unity_export.py`)

**File:** `veilbreakers_terrain/handlers/terrain_unity_export.py`

**Constants:**
- `_WIND_DIR_DEFAULT = (1.0, 0.0)` — line 692
- `_TREE_HEIGHT_DEFAULT = 10.0` — line 693

**`compute_wind_bend_vertex_color()` — lines 700–763:**

Formula (lines 736, 753–756):
```python
height_ratio = np.clip(heights / th, 0.0, 1.0) ** 2          # quadratic falloff
dot = np.abs(nxz[:, 0] * wd[0] + nxz[:, 1] * wd[1])         # abs(dot(normal_xz, wind_dir))
wind_bend_xz = np.clip(dot * height_ratio, 0.0, 1.0)          # R channel
wind_bend_y  = np.clip(0.1 * wind_bend_xz, 0.0, 1.0)          # G = 0.1 * R
rgba[:, 0] = wind_bend_xz   # R
rgba[:, 1] = wind_bend_y    # G
rgba[:, 3] = 1.0            # A always 1
```

Spec check:
- R = `dot(wind_dir, normal_xz) * (height / total_height)^2` — MATCHES (abs applied, wind_dir normalized first)
- Values stored in vertex color R channel — MATCHES (rgba[:,0])
- [0,1] clamp — MATCHES (np.clip on both channels)
- Status: PASS

**Note on spec wording:** The user prompt says `dot(wind_dir, normal_xz)` while the CONTEXT.md and plan both specify `abs(dot(...))`. The implementation uses `abs`, which is the correct AAA behavior (sway magnitude is direction-agnostic). This is consistent with all three plan documents.

**Wiring into `_tree_instances_json()` — lines 776–800:**
- `compute_wind_bend_vertex_color` called inside the per-tree loop at line 780
- `"vertex_color"` key present in every tree entry dict at line 800
- Status: PASS

---

### 3. UNITY_SCALE_FACTOR = 0.85 (`terrain_unity_export.py`)

**File:** `veilbreakers_terrain/handlers/terrain_unity_export.py`, line 25

```python
UNITY_SCALE_FACTOR: float = 0.85
```

Type-annotated form. The test suite (test_p13_unity_scale_factor.py) explicitly checks `UNITY_SCALE_FACTOR == 0.85` at runtime and confirms literal source text.

**`_apply_unity_scale()` — lines 32–36:** Centralizes all multiplication; used in:
- `export_unity_manifest()`: `cell_size`, `world_origin_x_m`, `world_origin_y_m`, `unity_world_origin`, `height_min_m`, `height_max_m` — lines 531–536
- `_decals_json()`: all three `position_zup` components — lines 676–678
- `_tree_instances_json()`: `row[0]`, `row[1]`, `row[2]` before `_zup_to_unity_vector()` — lines 794–796

**Not scaled (correct):** `tile_size`, `tile_x`, `tile_y`, heightmap raw uint16 bytes, terrain normals.

**Conflicting scale audit:** No other `SCALE_FACTOR` constant or competing multiplier found in `terrain_unity_export.py`. The grep for `scale_factor|SCALE_FACTOR|\* 0\.\d\d[^5]` returns only `UNITY_SCALE_FACTOR` entries. Status: PASS

---

### 4. _tree_instances_json Wiring

- Reads `stack.tree_instance_points` directly (attribute, not channel) at line 768
- Shape guard: requires ndim==2 and shape[1] >= 5
- Each row: col 0,1,2 = world position → scaled by `_apply_unity_scale`, col 3 = yaw, col 4 = prototype_id
- `"vertex_color"` key added per tree at line 800
- Status: PASS

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `veilbreakers_terrain/handlers/terrain_waterfalls.py` | `bake_foam_vertex_alpha`, `saturate`, `export_water_mesh_vertices` | PASS | All three present and in `__all__` |
| `veilbreakers_terrain/handlers/terrain_unity_export.py` | `UNITY_SCALE_FACTOR`, `_apply_unity_scale`, `compute_wind_bend_vertex_color` | PASS | All present, wired into `_tree_instances_json` and `export_unity_manifest` |
| `docs/TERRAIN_GENERATION_GUARDRAILS.md` | §9.5 Unity Scale Factor | PASS | Section present at line 869 |
| `veilbreakers_terrain/tests/test_p13_foam_vertex_alpha.py` | 15 tests, formula coverage | PASS | 15 tests, all PASS |
| `veilbreakers_terrain/tests/test_p13_wind_bend_vertex_color.py` | 12 tests, channel coverage | PASS | 12 tests, all PASS |
| `veilbreakers_terrain/tests/test_p13_unity_scale_factor.py` | 15 tests, manifest + tree scaling | PASS | 15 tests, all PASS |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `bake_foam_vertex_alpha` | foam_alpha vertex channel | `export_water_mesh_vertices` line 123 | WIRED | Called with obstacle_prox + flow_speed_field grids |
| `compute_wind_bend_vertex_color` | `vertex_color` in tree JSON | `_tree_instances_json` line 780 | WIRED | Called per-tree, result serialized at line 786–800 |
| `_apply_unity_scale` | manifest coord fields | `export_unity_manifest` lines 531–536 | WIRED | 6 coordinate fields scaled |
| `_apply_unity_scale` | decal positions | `_decals_json` lines 676–678 | WIRED | All 3 position_zup components |
| `_apply_unity_scale` | tree positions | `_tree_instances_json` lines 794–796 | WIRED | row[0], row[1], row[2] before zup conversion |
| `stack.tree_instance_points` | tree_instances.json | `_tree_instances_json` line 768 | WIRED | Direct attribute read; falls back to empty if None |

---

### Test Coverage

| Suite | Tests | Result |
|-------|-------|--------|
| `test_p13_foam_vertex_alpha.py` | 15 | 15 PASS |
| `test_p13_wind_bend_vertex_color.py` | 12 | 12 PASS |
| `test_p13_unity_scale_factor.py` | 15 | 15 PASS |
| **P13 total** | **42** | **42 PASS** |
| Full suite | 2710 | 2710 PASS, 0 FAIL, 3 SKIP |

Specific boundary coverage confirmed:
- Foam: proximity=0 → 0; proximity=foam_radius, speed=0 → 1.0; speed >= max → 0 (clamped, not negative)
- Wind bend: R range [0,1] — random-input test with 500 vertices confirms no out-of-range values
- UNITY_SCALE_FACTOR: 1.4m terrain → 1.19 Unity units (tolerance 0.001); tile_size not scaled (pixel count guard)

---

### Anti-Pattern Scan

No TODOs, FIXMEs, placeholder returns, or hardcoded empty arrays in the three modified functions. `export_water_mesh_vertices` uses zeros as a documented fallback for missing optional inputs (rock_mask, flow_speed), not as a stub — real data is substituted when the stack channel is available.

---

## Overall Verdict: COMPLETE

All 7 deliverables verified against source. Formulas match spec exactly (with approved addons: division-by-zero guards, `abs()` on dot product per plan). All 42 new tests pass. Full suite at 2710 passed / 0 failed. No conflicting scale constants found.

---

_Verified: 2026-04-19_
_Verifier: Claude (gsd-verifier)_
