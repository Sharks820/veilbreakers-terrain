# Master Audit V5

Supersedes as the live post-fix status snapshot:
- `docs/aaa-audit/MASTER_AUDIT_V4_2026_04_19.md`
- `.planning/phases/12-erosion-architecture/VERIFICATION.md` (older contents)
- `.planning/phases/14-terrain-features-quality/VERIFICATION.md` (older contents)

Audit date: 2026-04-19

## Scope

V5 records the current branch truth after the late-night Phase 12 and Phase 14 closure work:

- continuous wind-direction erosion with an edge-safe fractional fallback
- hardened Phase 14 regression tests that distinguish fixed behavior from stale bug patterns
- absolute hydraulic erodibility scaling in the droplet erosion stage
- updated grade-sheet entries for the corrected functions
- re-verified phase documents aligned to the live tree

## Current Phase State

### Passed

- Phase 07 — AAA Algorithm Upgrades
- Phase 08 — Road System Rebuild
- Phase 09 — Scatter / Vegetation Wiring
- Phase 10 — Texturing Formula Upgrades
- Phase 11 — Noise System Upgrades
- Phase 12 — Erosion Architecture
- Phase 13 — Content Consistency
- Phase 14 — Terrain Features Quality

## High-Signal Fixes In This Pass

### 1. Phase 12 hydraulic erodibility is now absolute, not only relative

The explorer review found that `apply_hydraulic_erosion_masks()` normalized `erodibility_map` by its mean, which collapsed any positive uniform map to the same behavior. That meant a uniformly hard tile and a uniformly soft tile eroded identically in the hydraulic stage.

Current fix:
- [`_terrain_erosion.py`](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/_terrain_erosion.py) now scales hydraulic erosion against the fixed baseline `K = 0.001`
- uniformly hard (`0.0002`) and uniformly soft (`0.001`) maps now diverge as intended
- zero erodibility now blocks hydraulic erosion entirely

### 2. Phase 14 wind-direction continuity is now proven on both paths

- [`terrain_wind_erosion.py`](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_wind_erosion.py) now uses `_shift_fractional_with_edge_repeat(...)`
- SciPy path uses `map_coordinates` bilinear sampling
- no-SciPy fallback uses explicit bilinear sampling with edge clamping
- tests now compare `pi/12` vs `pi/10`, which would collide under old `int(round(...))` snapping

### 3. Roughness regression guards now match the live implementation

- [`terrain_roughness_driver.py`](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_roughness_driver.py) already used a neutral `0.55` replace base
- [`test_phase14_wave1.py`](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/test_phase14_wave1.py) now uses a threshold that rejects the stale additive path
- `PassResult.consumed_channels` now reflects the channels the pass actually reads

### 4. Waterfall mist docs now follow the live branch, not stale audit text

The current tree already had:
- Bundle C mist registration
- `mist_radius_m = max(2.0, total_drop_m * 0.3)` in solved chains
- `generate_mist_zone()` using `H * 0.3 * wind_factor` with anisotropic wind bias

The earlier “mist disconnected / formula drift” claims are historical, not live.

## Validation

Focused validation completed on the current tree:

- `pytest veilbreakers_terrain/tests/test_phase14_wave1.py -q`
- `pytest veilbreakers_terrain/tests/test_wind_waterfall_poi_phase14.py -q`
- `pytest veilbreakers_terrain/tests/test_terrain_waterfalls.py -q -k mist_zone`
- `pytest veilbreakers_terrain/tests/test_stream_power_erosion.py -q`

## Independent Agent Scan Summary

### Explorer 1: Phase 12

Initial finding:
- hydraulic erodibility was only relative because of mean-normalization

Resolution:
- fixed locally in `_terrain_erosion.py`
- tests strengthened to prove absolute low-vs-high erodibility behavior

### Explorer 2: Phase 14

Findings:
- no remaining blocker in the requested Phase 14 slice
- main remaining issues were stale reports and grade artifacts, not code defects

Follow-up:
- grade rows updated in `GRADES_VERIFIED.csv`
- new phase verification docs written

## Artifact Alignment

Updated in this pass:

- [`docs/aaa-audit/GRADES_VERIFIED.csv`](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/docs/aaa-audit/GRADES_VERIFIED.csv)
- [Phase 12 verification](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/.planning/phases/12-erosion-architecture/VERIFICATION.md)
- [Phase 14 verification](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/.planning/phases/14-terrain-features-quality/VERIFICATION.md)
- [`scripts/update_r9_grades.py`](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/scripts/update_r9_grades.py)

Historical files such as V4 remain useful as provenance, but should no longer be treated as the live branch state for Phases 12 and 14.

## Follow-On Tranche: Wiring and Shared Runtime Quality

After the Phase 12/14 closure pass, the next high-leverage live issues were:

- runtime-primary MCP bridge handlers in [`handlers/__init__.py`](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/__init__.py) that were callable but still ungraded
- wet-rock mask quality in [`_water_network_ext.py`](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/_water_network_ext.py)
- shared noise helper churn in [`terrain_features.py`](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/handlers/terrain_features.py)

### 5. MCP bridge wrappers are now evidence-backed in the grade sheet

- Expanded [`test_mcp_dispatch.py`](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/veilbreakers_terrain/tests/test_mcp_dispatch.py) to exercise the preview, hot-reload, addon-health, safety, mesh, vertex-paint, weathering, animation, validation, navmesh, and quality-profile bridges
- result: `103 passed`
- `GRADES_VERIFIED.csv` now records those runtime-primary wrappers instead of leaving them as ungraded callable holes

### 6. Wet-rock masks now inherit the nearest water source strength

The previous implementation multiplied a radial distance field by a global flow-weight field. That blurred source strength across unrelated cells and left the no-SciPy path with nested Python loops.

Current fix:

- SciPy path now uses `distance_transform_edt(..., return_indices=True)` so each cell inherits the strength of its nearest water seed
- source strength now comes from the strongest available hydrology signal at the source cell: `flow_accumulation`, `_outflow_discharge`, or uniform fallback
- no-SciPy fallback now uses vectorized local radial stamps instead of per-cell Python loops
- new tests prove both high-flow amplification and fallback-path parity

Validation:

- `pytest veilbreakers_terrain/tests/test_water_network_upgrade.py -q`

### 7. terrain_features noise helpers no longer thrash generators across seeds

The previous `terrain_features` noise backbone used:

- a mutable module-global singleton in `_hash_noise`
- a fresh `_make_noise_generator(seed)` construction inside every `_fbm` call

Current fix:

- added cached per-seed `_get_feature_noise(...)` provider using `lru_cache(maxsize=64)`
- `_hash_noise` and `_fbm` now both reuse the same cached generator per seed
- `_fbm` now short-circuits cleanly for `octaves <= 0`
- direct tests now cover mixed-seed reuse and zero-octave short-circuiting

Validation:

- `pytest veilbreakers_terrain/tests/test_road_coastline_terrain_features.py -q`
- `pytest veilbreakers_terrain/tests/test_terrain_features_v2.py -q`

### 8. The runtime callable audit is back in sync with the current tree

- regenerated [`CALLABLE_WIRING_AUDIT_2026_04_19.csv`](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/output/spreadsheet/CALLABLE_WIRING_AUDIT_2026_04_19.csv)
- regenerated [`CALLABLE_WIRING_SUMMARY_2026_04_19.md`](/C:/Users/Conner/OneDrive/Documents/veilbreakers-terrain/output/spreadsheet/CALLABLE_WIRING_SUMMARY_2026_04_19.md)
- runtime-primary missing-row debt dropped to the single synthetic Quixel registrar closure that has now been replaced by a named top-level wrapper

Validation:

- `python scripts/scan_callable_wiring.py`

## Bottom Line

The implementation-phase track is complete on the current branch. The late audit found one real hydraulic-hardness defect and one contract-fidelity issue; both were resolved. The remaining discrepancies are historical-report lag and broader repo-wide AAA-grade ambition, not open blockers inside the completed Phase 7-14 implementation sheet.
