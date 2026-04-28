# D3 Audit: TerrainMaskStack Field Integrity
**Date:** 2026-04-27

---

## Source of Truth

`TerrainMaskStack` is defined in `veilbreakers_terrain/handlers/terrain_semantics.py` (line 232).

Serialization lists:
- `_ARRAY_CHANNELS` (tuple, lines 536–668): channels iterated by `to_npz` / `from_npz` / `compute_hash`.
- `_DICT_CHANNELS` (line 1036): `("wildlife_affinity", "decal_density", "detail_density")` — stored as dict-of-ndarray, handled separately.
- `_OPAQUE_CHANNELS` (lines 818–830): JSON-serialisable scalars/lists stored via `to_npz` meta blob.

`set()` validation (line 849): calls `hasattr(self, channel)` — raises `AttributeError` if the channel is not a declared field. This prevents writing completely undeclared channels via `.set()`. However it does NOT prevent direct attribute assignment (`stack.channel = value`), which bypasses provenance tracking.

---

## Fields accessed but NOT in `_DECLARED_CHANNELS`

The following channels are read via `stack.get("channel")` in production handler code but do not appear as declared fields on `TerrainMaskStack`. Because `.get()` uses `getattr(self, channel, None)` these silently return `None`.

| Channel | Where accessed | Impact |
|---------|---------------|--------|
| `forest_mask` | `terrain_navmesh_export.py:145`, `terrain_vegetation_depth.py:1560,1562,1669`, `terrain_god_ray_hints.py:205` | Vegetation density, god-ray hints, navmesh all silently skip forest input; forest-influenced passes degrade to fallback behaviour with no error |
| `material_zones` | `terrain_roughness_driver.py:159` | Roughness zone weighting always disabled; `zone_arr` is always None |
| `canopy_species_radius_m` | `terrain_vegetation_depth.py:308` | Per-species radius lookup silently returns None; canopy radius falls back to defaults |
| `hardness` / `geology` | `terrain_vegetation_depth.py:496` | Geology-driven vegetation modifier always None; vegetation ignores rock hardness via this alias path (though `rock_hardness` is declared) |
| `height_delta` | `terrain_vegetation_depth.py:508` | Uplift-driven vegetation correction always disabled |
| `vegetation_index` / `ndvi` | `terrain_vegetation_depth.py:539` | NDVI-boosted density path never activates |
| `species_density` | `terrain_vegetation_depth.py:1599` | Allelopathic exclusion pass always skipped |
| `strata_layers` | `terrain_validation.py:1338` | Stratigraphy validation check silently passes vacuously |
| `strata_depths` | `terrain_validation.py:1370` | Strata depth validation never runs |
| `limestone_proxy` | `terrain_validation.py:1672` | Karst suitability check always returns zero-proxy result |
| `hazard_zone` | `terrain_navmesh_export.py:167` | Hazard-zone navmesh restriction never applied |
| `water_depth` | `terrain_navmesh_export.py:153`, `terrain_waterfalls.py:2419` | Legacy alias for `water_depth_m`; navmesh always sees None for water depth |
| `water_network` | `_water_network.py:3547` | Water network DAG object lookup via stack returns None; actual network stored on state, not stack |
| `height_m` | `terrain_pipeline.py:1006` | Alias for `height`; always returns None, fallback to `stack.get("height")` on line 1008 works but the alias is misleading |
| `world_id` | `test_p13_unity_scale_factor.py:131` (test only), `terrain_unity_export.py` (manifest read) | Not a declared field; silently returns None in production manifest if never set via direct assignment |
| `batch_id` | `test_p13_unity_scale_factor.py:132` (test only) | Not a declared field |

---

## Fields written via `stack.set()` but NOT in `_ARRAY_CHANNELS` (silently dropped on `.to_npz()`)

`to_npz()` iterates only `_ARRAY_CHANNELS` (plus `_DICT_CHANNELS` and `_OPAQUE_CHANNELS`). Any channel written via `stack.set()` that does not appear in one of those three lists will be populated in memory but silently dropped when the stack is serialised.

| Channel | Written by | Impact |
|---------|-----------|--------|
| `terrain_ao` | `terrain_quixel_ingest.py:680`, `terrain_unity_export.py:1298` (read) | **G4 CONFIRMED**: Written to stack by Quixel ingest, read by Unity export, but NOT in `_ARRAY_CHANNELS`. Silently dropped on `.to_npz()`. PBR AO data is lost on save/load round-trip. |
| `terrain_displacement` | `terrain_quixel_ingest.py:709`, `terrain_unity_export.py` (read) | **G4 CONFIRMED**: Same as `terrain_ao`. Height/parallax displacement data lost on `.to_npz()` round-trip. |

Both `terrain_ao` and `terrain_displacement` ARE declared as Optional fields on the dataclass (lines 397–399) so `stack.set()` succeeds without raising. But they are absent from `_ARRAY_CHANNELS`, meaning `to_npz` never writes them and `from_npz` never restores them. Net effect: any Quixel-ingested AO/displacement data exists only for the lifetime of the in-process stack object.

---

## Direct attribute assignments bypassing `.set()` provenance

`__setattr__` (line 721) logs a warning if a known channel is assigned directly, but does not raise — the assignment still proceeds. Provenance (`populated_by_pass`) is NOT updated, and `dirty_channels` is NOT cleared.

### Production handler bypasses (highest severity)

| Channel | File:line | Impact |
|---------|----------|--------|
| `stack.height = ...` | `terrain_stratigraphy.py:453` (inside `simulate_fold_deformation`) | **A6 confirmed**: `height` written directly; `populated_by_pass["height"]` not updated; DAG cannot trace this mutation. |
| `stack.height = ...` | `coastline.py:1256` | Coastline erosion loop writes height directly on each iteration; provenance lost for every incremental step. |
| `stack.wetness = ...` | `terrain_weathering_timeline.py:87`, `:141` | Weathering timeline sets wetness directly twice; no provenance record. |
| `stack.tree_instance_points = arr` | `environment_scatter.py:1242` | Fallback code path (when `hasattr(stack, "set")` is False — mock objects in tests); should never fire in production but exists in handler code. |
| `stack.detail_density = merged` | `terrain_vegetation_depth.py:1675` | Dict channel written directly instead of via `stack.set()`; no provenance. |
| `stack._extra_channels = ...` | `terrain_waterfalls.py:2825` | Undeclared sidecar attribute used as legacy mirror for `wet_surface_decal`; entirely outside the stack contract. |
| `stack._extra_channels["wet_surface_decal"] = decal_list` | `terrain_waterfalls.py:2826` | Same — dual write: correct path via `stack.set("wet_surface_decal", ...)` on line 2824, then again via legacy sidecar. |

### Test bypasses (lower severity, no production impact)

| Channel | File:line | Notes |
|---------|----------|-------|
| `stack.cliff_candidate = ...` | `test_bundle_egjn_supplements.py:349,357,364,378,428` | Test fixtures only |
| `stack.slope = ...` | `test_bundle_egjn_supplements.py:358,365,379,429` | Test fixtures only |
| `stack.height = ...` | `test_bundle_egjn_supplements.py:377,554,567`, `test_terrain_unity_export_bridge.py:172`, `test_visual_qa_golden.py:242`, `test_wind_waterfall_poi_phase14.py:245`, `test_terrain_validation.py:206`, `test_environment_analysis_runtime_helpers.py:343` | Test fixtures only |
| `stack.wetness = ...` | `test_bundle_pq.py:233,272,280,286`, `test_terrain_water_vegetation_depth.py:265,286,293,310,329` | Test fixtures only |
| `stack.rock_hardness = ...` | `test_bundle_pq.py:219,226,232,239` | Test fixtures only |
| `stack.splatmap_weights_layer = ...` | `test_bundle_egjn_supplements.py:582`, `test_terrain_validation.py:333,344,356,374,391,409,524,552,566` | Test fixtures only |
| `stack.water_surface = ...` | `test_environment_analysis_runtime_helpers.py:141`, `test_terrain_water_vegetation_depth.py:294` | Test fixtures only |
| `stack.saliency_macro = ...` | `test_terrain_composition.py:465,477,486,497` | Test fixtures only |
| `stack.slope/ridge/basin/erosion/deposition/cliff_candidate/...` | Various test files | Test fixtures only |
| `stack.world_id = ...`, `stack.batch_id = ...` | `test_p13_unity_scale_factor.py:131,132` | Writes undeclared fields; only works because Python dataclasses permit dynamic attribute assignment after `__post_init__` (the `_guard_active` guard only warns, does not block). |
| `stack.heightmap = ...` | `test_terrain_visual_qa_channels.py:91,126,266` | Writes wrong field name; should be `height` not `heightmap`; silently creates extra attribute, actual `height` field unchanged. This is a bug in the test. |
| `stack.talus_mask = ...` | `test_terrain_visual_qa_channels.py:100` | Direct assignment — would trigger warning |
| `stack.water_surface_mask = ...` | `test_terrain_visual_qa_channels.py:116,135,235` | Direct assignment — would trigger warning |
| `stack.cliff_mask = ...` | `test_terrain_visual_qa_channels.py:172,251` | Direct assignment — would trigger warning |
| `stack.water_depth_m = None` | `test_terrain_visual_qa_channels.py:77` | Sets declared field to None explicitly |
| `stack.water_depth_m = ...` | `test_terrain_visual_qa_channels.py:274,285` | Direct assignment — would trigger warning |
| `stack.road_sdf_dist = ...` | `test_foliage_manifest.py:187`, `test_procedural_grass.py:162` | Test fixtures only |
| `stack.cliff_label = ...` | `test_procedural_grass.py:140` | Test fixture only |
| `stack.biome_id = ...` | `test_procedural_grass.py:188` | Test fixture only |
| `stack.drainage = ...` | `test_procedural_grass.py:203`, `test_terrain_waterfalls.py:74` | Test fixtures only |
| `stack.flow_accumulation = ...` | `test_water_network_upgrade.py:157,175` | Test fixtures only |
| `stack.detail_density = ...` | `test_terrain_assets.py:405`, `test_terrain_water_vegetation_depth.py:545` | Test fixtures only |

---

## Confirmed: `terrain_ao` and `terrain_displacement` in `_ARRAY_CHANNELS`: NO

Neither `"terrain_ao"` nor `"terrain_displacement"` appears in `_ARRAY_CHANNELS` (verified against full list, lines 540–668 of `terrain_semantics.py`). Both are declared dataclass fields (lines 397–399) and can be written via `stack.set()` without error, but are silently excluded from `to_npz()` serialisation and `from_npz()` deserialisation. **G4 CONFIRMED.**

---

## Notable Undeclared Field: `heightmap` (test QA bug)

`test_terrain_visual_qa_channels.py` writes `stack.heightmap = ...` (lines 91, 126, 266). There is no field named `heightmap` on `TerrainMaskStack` — the correct field is `height`. These assignments silently create a dangling attribute and leave `stack.height` unchanged. The tests are testing the wrong field. This is an independent bug from the serialisation issues.

---

## STATISTICS

- **Total unique channel names found across all `stack.set()` calls:** 96
- **Missing from `_DECLARED_CHANNELS` (would raise `AttributeError` on `stack.set()`):** 0 (all `stack.set()` targets are declared fields; validation in `set()` would catch truly undeclared names)
- **Missing from `_ARRAY_CHANNELS` (silently dropped on `.to_npz()`):** 2 — `terrain_ao`, `terrain_displacement`
- **Direct attribute bypasses in production handler code (non-test):** 7 distinct call sites (stratigraphy, coastline×1, weathering×2, environment_scatter fallback×1, vegetation_depth×1, waterfalls sidecar×2)
- **Channels accessed via `stack.get()` with no declared field (always returns None):** 14 (forest_mask, material_zones, canopy_species_radius_m, hardness, geology, height_delta, vegetation_index, ndvi, species_density, strata_layers, strata_depths, limestone_proxy, hazard_zone, water_depth legacy alias)

---

## Fix Priority

| Severity | Issue | Fix |
|----------|-------|-----|
| P0 | `terrain_ao` not in `_ARRAY_CHANNELS` | Add to `_ARRAY_CHANNELS` tuple |
| P0 | `terrain_displacement` not in `_ARRAY_CHANNELS` | Add to `_ARRAY_CHANNELS` tuple |
| P1 | `simulate_fold_deformation` direct `stack.height =` | Replace with `stack.set("height", ..., "simulate_fold_deformation")` |
| P1 | `coastline.py` direct `stack.height =` in loop | Replace with `stack.set("height", ..., "coastline")` |
| P1 | `terrain_weathering_timeline.py` direct `stack.wetness =` (×2) | Replace with `stack.set()` |
| P2 | `terrain_vegetation_depth.py` direct `stack.detail_density =` | Replace with `stack.set()` |
| P2 | `terrain_waterfalls.py` legacy `_extra_channels` sidecar | Remove sidecar mirror; `wet_surface_decal` is already in `_OPAQUE_CHANNELS` and written via `stack.set()` |
| P3 | `forest_mask`, `material_zones` et al never declared | Either declare as Optional fields or remove the dead code paths that read them |
| P3 | `heightmap` written in tests instead of `height` | Fix test fixtures to write `stack.height` |
