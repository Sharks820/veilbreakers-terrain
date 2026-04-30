# AAA Implementation Guide 2026-04-29 — Closure Ledger

**Generated:** 2026-04-29  
**Refreshed:** 2026-04-29 after Codex master-audit closure pass  
**Status:** Current live repo gates pass. Older open-work counts in the original sheet were stale and have been replaced by this closure ledger.

---

## Closure Summary

| Area | Current status |
|---|---|
| Batch 9 phantom callable rows | Closed by strict callable census: `1711/1711` graded, `0` uncovered. |
| Verification matrix blockers | Closed: `0` blocker, `0` high, `false_grade_A_rows=0`. |
| Best-practice matrix | Closed: `1713` live callables, `1723` matrix rows, `0` missing, `blocking=False`. |
| Test guardrail audit | Closed with `--strict-quality`; no stale/zero-collection blocker. |
| 3ds Max / Forest Pack path | Retired. DCC exporter and guide removed; replacement is Unity/GPU foliage manifest pipeline. |
| Full pytest | Passed: `3688 passed, 4 skipped, 41 warnings`. |

---

## Implemented Fix Groups

### Foliage / Scatter Export

- Removed `scripts/export_3dsmax.py`.
- Removed `docs/3DSMAX_PIPELINE.md`.
- Added `scripts/export_foliage_manifest.py`.
- Added `docs/FOLIAGE_MANIFEST_PIPELINE.md`.
- Replaced DCC manifest hints with runtime `render_batch_key`.
- Renamed stale scatter test file to `test_scatter_engine_distribution.py`.
- Deleted stale generated `output/3dsmax/` artifacts.

### Unity Export

- Added tangent-space RGBA8 terrain normal-map export:
  - `terrain_normals_tangent.png`
  - manifest file metadata with encoding, shape, byte size, and hash
  - `unity_import_descriptor.json` normal-map file field
- Unity importer now imports the normal map as a Unity `TextureImporterType.NormalMap` asset and stores the asset path on `VbTerrainTileMetadata`.

### Erosion / Quality Profiles

- `pass_erosion` now derives hydraulic and thermal erosion budgets from `TerrainQualityProfile`.
- Added regression proving `mobile` uses lower erosion budgets than `aaa_open_world`.

### Materials

- `pass_materials` now writes:
  - `ambient_occlusion_bake`
  - `terrain_displacement`
  - `TerrainTextureLayerStack`
- Slope material weighting now honors priority overlap deterministically.

### Stratigraphy / Delta Integration

- `pass_stratigraphy` stays on the canonical deferred-delta contract.
- `integrate_deltas` remains the single height writer for `strat_erosion_delta`.
- Added regression proving no double-apply.

### Atmosphere / Terrain Context

- `compute_atmospheric_placements` now validates/coerces terrain arrays and fails closed on invalid masks.
- Handler wrapper passes heightmap and terrain masks into atmosphere placement.

### Determinism / CI

- Determinism hash now recurses output directories, hashes relative paths plus bytes, and runs in a temporary directory.

### Coast / Vegetation / Karst / Banded Terrain

- Coastline uses populated `water_surface_elevation_m`.
- Vegetation water rejection compares world height against world water elevation.
- Karst uvala composition added.
- Anti-grain smoothing scales kernel size by resolution.

---

## Verification Commands

```powershell
python scripts\callable_census_gate.py --strict-zero
python scripts\build_verification_matrix.py
python scripts\terrain_best_practice_guardrail.py
python scripts\build_test_guardrail_audit.py --strict-quality
python -m pytest -q --basetemp output\pytest-tmp\full-final
```

All passed in the refreshed run.

---

## Remaining Caveat

No visual-quality claim is made from this document. Blender/Unity rendered viewport proof is still required before saying terrain output is visually AAA in-engine. Code, wiring, callable, matrix, and test gates are clean.
