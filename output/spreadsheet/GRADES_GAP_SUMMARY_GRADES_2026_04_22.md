# GRADES Verified Gap Summary

- Grade source CSV: `docs/aaa-audit/GRADES.csv`
- UTC date tag: `2026_04_22`
- Total handler callables: **1730**
- Exact graded callables: **206**
- Name-only matches (needs explicit file-level row): **36**
- Ambiguous name matches (manual disambiguation required): **1**
- Missing callable grades: **1487**
- Stale grade rows (in CSV but no longer in code): **7**
- Class rows in CSV (tracked but non-callable by this audit): **10**

## Final grade distribution (exact+heuristic matches)

- (blank): 1730

## Files with most non-exact coverage

- environment.py: 88
- __init__.py: 57
- _terrain_noise.py: 53
- animation_environment.py: 42
- terrain_baked.py: 40
- environment_scatter.py: 38
- terrain_caves.py: 37
- terrain_validation.py: 37
- terrain_unity_export.py: 34
- terrain_semantics.py: 33
- road_network.py: 31
- terrain_cliffs.py: 31
- terrain_dirty_tracking.py: 27
- lod_pipeline.py: 26
- _scatter_engine.py: 25
- _water_network.py: 24
- terrain_iteration_metrics.py: 23
- terrain_banded.py: 21
- terrain_vegetation_depth.py: 20
- terrain_water_variants.py: 20

## Top stale grade rows

- terrain_advanced.py::TerrainLayer.__init__
- terrain_advanced.py::TerrainLayer.from_dict
- terrain_advanced.py::TerrainLayer.to_dict
- terrain_pipeline.py::TerrainPassController._save_checkpoint
- terrain_pipeline.py::TerrainPassController.enforce_protected_zones
- terrain_pipeline.py::TerrainPassController.run_pass
- terrain_pipeline.py::TerrainPassController.run_pipeline

## CSV class rows (not counted as callables)

- terrain_advanced.py::TerrainLayer
- terrain_pipeline.py::TerrainPassController
- terrain_semantics.py::BBox
- terrain_semantics.py::PassResult
- terrain_semantics.py::ProtectedZoneSpec
- terrain_semantics.py::TerrainIntentState
- terrain_semantics.py::TerrainMaskStack
- terrain_semantics.py::TerrainPipelineState
- terrain_semantics.py::ValidationIssue
- terrain_semantics.py::WorldHeightTransform
