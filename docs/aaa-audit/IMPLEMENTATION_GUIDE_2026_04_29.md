# AAA Implementation Guide 2026-04-29 - Closure Ledger

**Generated:** 2026-04-29
**Refreshed:** 2026-04-30 after Codex master-audit guardrail closure pass
**Status:** Current live repo code, wiring, callable, matrix, and test gates pass. Older open-work counts in the original sheet were stale and have been replaced by this closure ledger.

---

## Closure Summary

| Area | Current status |
|---|---|
| Batch 9 phantom callable rows | Closed by strict callable census: `1717/1717` graded, `0` uncovered. |
| Verification matrix blockers | Closed: `0` blocker, `0` high, `false_grade_A_rows=0`. |
| Best-practice matrix | Closed: `1717` live callables, `1717` matrix rows, `0` missing, `blocking=False`; `--require-a-grade --no-write` passes. |
| Test guardrail audit | Closed with `--strict-quality`; no stale/zero-collection blocker. |
| 3ds Max / Forest Pack path | Retired. DCC exporter and guide removed; replacement is Unity/GPU foliage manifest pipeline. |
| Unity runtime streaming | Closed: imported terrain now has camera-prioritized tile activation, LOD quality tiers, neighbor reconnection, floating-origin support, and GPU foliage manifest rendering. |
| Full pytest | Passed: `3720 passed in 372.38s`; no skip/warning summary. |

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
- Added runtime-side large-world support:
  - `VbTerrainRuntimeStreamer` uses `VbTerrainTileMetadata` to activate
    imported tiles by camera frustum, distance, and frame budget.
  - Active tiles reconnect neighbors through `Terrain.SetNeighbors`.
  - Near/mid/far quality tiers adjust `heightmapPixelError`,
    `detailObjectDistance`, and `treeDistance`.
  - `VbFloatingOrigin` shifts terrain/scatter/water roots and world-space
    particles before precision flicker appears.
  - `VbFoliageManifestRenderer` consumes `foliage_placement_manifest.json` and
    batches dense foliage through `Graphics.DrawMeshInstanced`.
- Unity export contracts now fail closed:
  - `export_unity_manifest(..., fail_on_validation_error=True)` raises before
    writing `unity_import_descriptor.json` on hard validation errors.
  - `handle_export_unity_bundle` enters through `@enforce_protocol`.
  - Unity importer rejects failed descriptors instead of importing invalid
    terrain bundles.
- Unity descriptor sidecars now include atmospheric volumes, wind fields, cloud
  shadows, and navmesh area-id channels, with importer references for each.
- Unity importer warns for unhandled descriptor top-level keys so new Python
  exports cannot be silently dropped.
- Binary sidecar exports now preserve explicit channel contracts, including
  float32 little-endian shadow clipmaps.
- Explicit `audio_zone_list` exports no longer require an audio raster to avoid
  being dropped.

### Erosion / Quality Profiles

- `pass_erosion` now derives hydraulic and thermal erosion budgets from `TerrainQualityProfile`.
- Added regression proving `mobile` uses lower erosion budgets than `aaa_open_world`.
- Hydraulic erosion now caches brush kernels and uses vectorized local talus
  smoothing for the high-request path.
- Small test tiles expose `iterations_requested`, simulated `iterations`, and
  `iteration_cap_applied` telemetry instead of silently grinding CI for minutes.
- High-request erosion has a wall-clock regression guard on the cap path.
- Deprecated runtime defaults using `production` were replaced by
  `aaa_open_world`; smoke tests use explicit `standard` where that is the
  intended cheaper profile.
- Phacelle/Rune-style erosion phase math now wraps phase before trig to preserve
  far-world precision.

### Materials

- `pass_materials` now writes:
  - `ambient_occlusion_bake`
  - `terrain_displacement`
  - `TerrainTextureLayerStack`
- Slope material weighting now honors priority overlap deterministically.
- Quixel/HDR texture ingest keeps float textures in linear float space and only
  normalizes out-of-range HDR payloads.
- Packed normal maps are decoded from `[0, 1]` into tangent-space `[-1, 1]`
  before blending and normalization.

### Stratigraphy / Delta Integration

- `pass_stratigraphy` stays on the canonical deferred-delta contract.
- `integrate_deltas` remains the single height writer for `strat_erosion_delta`.
- Added regression proving no double-apply.

### Atmosphere / Terrain Context

- `compute_atmospheric_placements` now validates/coerces terrain arrays and fails closed on invalid masks.
- Handler wrapper passes heightmap and terrain masks into atmosphere placement.

### Determinism / CI

- Determinism hash now recurses output directories, hashes relative paths plus bytes, and runs in a temporary directory.
- `python-package.yml` and `callable_census.yml` now run on both `push` and
  `pull_request`.
- CI now runs strict callable census, strict callable wiring scan, strict test
  guardrail audit, verification matrix, industry matrix, best-practice
  guardrail, altitude linter, and branch coverage.
- `pyproject.toml` now enables `pytest-timeout`, strict markers, durations,
  maxfail, and short tracebacks.
- `.pre-commit-config.yaml` adds local Ruff/callable/guardrail hooks.
- `scan_callable_wiring.py --strict-no-risk` now exits nonzero for true runtime
  wiring risks.
- Verification matrix rows now include wiring status, runtime exposure, and
  non-test call counts; true wiring risk becomes a blocker.

### Coast / Vegetation / Karst / Banded Terrain

- Coastline uses populated `water_surface_elevation_m`.
- Vegetation water rejection compares world height against world water elevation.
- Karst uvala composition added.
- Anti-grain smoothing scales kernel size by resolution.

---

## Verification Commands

```powershell
python scripts\callable_census_gate.py --strict-zero
python scripts\scan_callable_wiring.py --strict-no-risk
python scripts\build_test_guardrail_audit.py --strict-quality
python scripts\build_verification_matrix.py
python scripts\build_industry_best_practice_callable_matrix.py
python scripts\terrain_best_practice_guardrail.py --strict-grade-status --strict-verification
python scripts\terrain_best_practice_guardrail.py --require-a-grade --no-write
python -m pytest -q -ra --basetemp output\pytest-tmp\full-post-guardrails-4
```

All passed in the refreshed run. Final full suite: `3720 passed in 372.38s`.

---

## Remaining Caveat

No visual-quality claim is made from this document. Blender/Unity rendered viewport proof is still required before saying terrain output is visually AAA in-engine. Code, wiring, callable, matrix, and test gates are clean.

Tracked repo still has no production PBR texture database under `assets/`; code
paths for Quixel/HDR/normal ingest are stronger, but final AAA material-library
quality still requires real tracked source textures plus render proof.
