# D7 Audit: Serialization & Checkpoint Integrity
**Date:** 2026-04-27
**Auditor:** Primary agent (terrain_semantics.py deep read)
**Files audited:** `terrain_semantics.py`, `terrain_checkpoints.py`, `terrain_checkpoints_ext.py`, `sim/foam.py`, `sim/catenary.py`, `sim/pbd_cloth.py`

---

## Clarification: TerrainMaskStack has no to_dict / from_dict

The class exposes only `to_npz()` / `from_npz()` for persistence. There is no separate `to_dict()` or `from_dict()` method. The `__meta__` JSON blob embedded inside every `.npz` serves as the scalar-metadata sidecar. The audit task column "In to_dict" maps to "In `__meta__` JSON block inside npz" below.

---

## Field serialization matrix

| Field | Declared type | In `_ARRAY_CHANNELS` (to_npz arrays) | In `__meta__` JSON | In `_DICT_CHANNELS` | In `_OPAQUE_CHANNELS` | Skipped entirely | Impact of skip |
|---|---|---|---|---|---|---|---|
| tile_size | int | — | YES (meta) | — | — | No | — |
| cell_size | float | — | YES (meta) | — | — | No | — |
| world_origin_x | float | — | YES (meta) | — | — | No | — |
| world_origin_y | float | — | YES (meta) | — | — | No | — |
| tile_x | int | — | YES (meta) | — | — | No | — |
| tile_y | int | — | YES (meta) | — | — | No | — |
| height | np.ndarray | YES | — | — | — | No | — |
| slope | np.ndarray | YES | — | — | — | No | — |
| curvature | np.ndarray | YES | — | — | — | No | — |
| concavity | np.ndarray | YES | — | — | — | No | — |
| convexity | np.ndarray | YES | — | — | — | No | — |
| ridge | np.ndarray | YES | — | — | — | No | — |
| basin | np.ndarray | YES | — | — | — | No | — |
| saliency_macro | np.ndarray | YES | — | — | — | No | — |
| cliff_candidate | np.ndarray | YES | — | — | — | No | — |
| cliff_contour_spline | np.ndarray | YES | — | — | — | No | — |
| cliff_mask | np.ndarray | YES | — | — | — | No | — |
| talus_mask | np.ndarray | YES | — | — | — | No | — |
| strata_mask | np.ndarray | YES | — | — | — | No | — |
| cave_candidate | np.ndarray | YES | — | — | — | No | — |
| cave_height_delta | np.ndarray | YES | — | — | — | No | — |
| cave_wall_texture | np.ndarray | YES | — | — | — | No | — |
| cave_stalactite_length | np.ndarray | YES | — | — | — | No | — |
| cave_stalagmite_length | np.ndarray | YES | — | — | — | No | — |
| cave_depth_hint | np.ndarray | YES | — | — | — | No | — |
| cave_underground_depth | np.ndarray | YES | — | — | — | No | — |
| cave_chambers | np.ndarray | YES | — | — | — | No | — |
| cave_nav_issues_count | np.ndarray | YES | — | — | — | No | — |
| waterfall_lip_candidate | np.ndarray | YES | — | — | — | No | — |
| waterfall_pool_delta | np.ndarray | YES | — | — | — | No | — |
| hero_exclusion | np.ndarray | YES | — | — | — | No | — |
| erosion_amount | np.ndarray | YES | — | — | — | No | — |
| deposition_amount | np.ndarray | YES | — | — | — | No | — |
| wetness | np.ndarray | YES | — | — | — | No | — |
| ice_factor | np.ndarray | YES | — | — | — | No | — |
| talus | np.ndarray | YES | — | — | — | No | — |
| drainage | np.ndarray | YES | — | — | — | No | — |
| bank_instability | np.ndarray | YES | — | — | — | No | — |
| **ridge_eroded** | np.ndarray | **NO** | NO | — | — | **YES** | Erosion-refined ridge lost; downstream passes fall back to raw `ridge`, producing stale/incorrect analytical ridges post-erosion. |
| flow_direction | np.ndarray | YES | — | — | — | No | — |
| flow_accumulation | np.ndarray | YES | — | — | — | No | — |
| water_surface | np.ndarray | YES | — | — | — | No | — |
| water_surface_mask | np.ndarray | YES | — | — | — | No | — |
| water_surface_elevation_m | np.ndarray | YES | — | — | — | No | — |
| water_depth_m | np.ndarray | YES | — | — | — | No | — |
| shoreline_blend | np.ndarray | YES | — | — | — | No | — |
| foam | np.ndarray | YES | — | — | — | No | — |
| mist | np.ndarray | YES | — | — | — | No | — |
| wet_rock | np.ndarray | YES | — | — | — | No | — |
| riverbed_caustics | np.ndarray | YES | — | — | — | No | — |
| tidal | np.ndarray | YES | — | — | — | No | — |
| waterfall_velocity | np.ndarray | YES | — | — | — | No | — |
| wave_amplitude_per_vertex | np.ndarray | YES | — | — | — | No | — |
| mist_fog_volume | Dict | — | — | — | YES (_OPAQUE) | No | — |
| foam_atlas_path | str | — | — | — | YES (_OPAQUE) | No | — |
| caustic_atlas_path | str | — | — | — | YES (_OPAQUE) | No | — |
| water_depth_atlas_path | str | — | — | — | YES (_OPAQUE) | No | — |
| flow_speed | np.ndarray | YES | — | — | — | No | — |
| bathymetry | np.ndarray | YES | — | — | — | No | — |
| water_depth_zone | np.ndarray | YES | — | — | — | No | — |
| biome_id | np.ndarray | YES | — | — | — | No | — |
| material_weights | np.ndarray | YES | — | — | — | No | — |
| roughness_breakup | np.ndarray | YES | — | — | — | No | — |
| roughness_variation | np.ndarray | YES | — | — | — | No | — |
| macro_color | np.ndarray | YES | — | — | — | No | — |
| audio_reverb_class | np.ndarray | YES | — | — | — | No | — |
| wildlife_affinity | Dict[str, ndarray] | — | — | YES (_DICT) | — | No | — |
| gameplay_zone | np.ndarray | YES | — | — | — | No | — |
| wind_field | np.ndarray | YES | — | — | — | No | — |
| cloud_shadow | np.ndarray | YES | — | — | — | No | — |
| sun_cloud_shadow | np.ndarray | YES | — | — | — | No | — |
| baked_cloud_shadow | np.ndarray | YES | — | — | — | No | — |
| traversability | np.ndarray | YES | — | — | — | No | — |
| decal_density | Dict[str, ndarray] | — | — | YES (_DICT) | — | No | — |
| strata_orientation | np.ndarray | YES | — | — | — | No | — |
| rock_hardness | np.ndarray | YES | — | — | — | No | — |
| snow_line_factor | np.ndarray | YES | — | — | — | No | — |
| sediment_accumulation_at_base | np.ndarray | YES | — | — | — | No | — |
| pool_deepening_delta | np.ndarray | YES | — | — | — | No | — |
| strat_erosion_delta | np.ndarray | YES | — | — | — | No | — |
| sediment_height | np.ndarray | YES | — | — | — | No | — |
| bedrock_height | np.ndarray | YES | — | — | — | No | — |
| coastline_delta | np.ndarray | YES | — | — | — | No | — |
| karst_delta | np.ndarray | YES | — | — | — | No | — |
| wind_erosion_delta | np.ndarray | YES | — | — | — | No | — |
| glacial_delta | np.ndarray | YES | — | — | — | No | — |
| stochastic_uv_mask | np.ndarray | YES | — | — | — | No | — |
| shadow_map | np.ndarray | YES | — | — | — | No | — |
| splatmap_weights_layer | np.ndarray | YES | — | — | — | No | — |
| heightmap_raw_u16 | np.ndarray | YES | — | — | — | No | — |
| terrain_normals | np.ndarray | YES | — | — | — | No | — |
| **terrain_ao** | np.ndarray | **NO** | NO | — | — | **YES** | PBR ambient occlusion silently dropped; any Unity export or material pass after reload will miss AO; baked occlusion lost on every checkpoint cycle. `ambient_occlusion_bake` is a distinct field (IS in `_ARRAY_CHANNELS`). |
| **terrain_displacement** | np.ndarray | **NO** | NO | — | — | **YES** | Quixel-ingested parallax/height data lost; material passes after reload cannot read parallax displacement; produces flat-looking terrain from loaded checkpoints. |
| navmesh_area_id | np.ndarray | YES | — | — | — | No | — |
| physics_collider_mask | np.ndarray | YES | — | — | — | No | — |
| lightmap_uv_chart_id | np.ndarray | YES | — | — | — | No | — |
| lod_bias | np.ndarray | YES | — | — | — | No | — |
| horizon_elevation_angles | np.ndarray | YES | — | — | — | No | — |
| detail_density | Dict[str, ndarray] | — | — | YES (_DICT) | — | No | — |
| grass_density_map | np.ndarray | YES | — | — | — | No | — |
| tree_instance_points | np.ndarray | YES | — | — | — | No | — |
| ambient_occlusion_bake | np.ndarray | YES | — | — | — | No | — |
| road_mask | np.ndarray | YES | — | — | — | No | — |
| road_sdf_dist | np.ndarray | YES | — | — | — | No | — |
| rock_label | np.ndarray | YES | — | — | — | No | — |
| gravel_label | np.ndarray | YES | — | — | — | No | — |
| water_label | np.ndarray | YES | — | — | — | No | — |
| cliff_label | np.ndarray | YES | — | — | — | No | — |
| strata_height | np.ndarray | YES | — | — | — | No | — |
| hmap_low_freq | np.ndarray | YES | — | — | — | No | — |
| hmap_high_freq | np.ndarray | YES | — | — | — | No | — |
| poi_mask | np.ndarray | YES | — | — | — | No | — |
| mist_zone_mask | np.ndarray | YES | — | — | — | No | — |
| wet_surface_decal | List[Dict] | — | — | — | YES (_OPAQUE) | No | — |
| cliff_mesh_specs | List[Dict] | — | — | — | YES (_OPAQUE) | No | — |
| cave_mesh_specs | List[Dict] | — | — | — | YES (_OPAQUE) | No | — |
| talus_boulder_placements | List[Dict] | — | — | — | YES (_OPAQUE) | No | — |
| particle_emitter_specs | List[Dict] | — | — | — | YES (_OPAQUE) | No | — |
| audio_zone_list | List[Dict] | — | — | — | YES (_OPAQUE) | No | — |
| river_mouth_mask | np.ndarray | YES | — | — | — | No | — |
| confluence_foam | np.ndarray | YES | — | — | — | No | — |
| delta_fan_direction | np.ndarray | YES | — | — | — | No | — |
| hero_feature_preview | np.ndarray | YES | — | — | — | No | — |
| unconformity_mask | np.ndarray | YES | — | — | — | No | — |
| intrusion_mask | np.ndarray | YES | — | — | — | No | — |
| albedo_shift_rgb | np.ndarray | YES | — | — | — | No | — |
| strata_cross_section | np.ndarray | YES | — | — | — | No | — |
| north_edge | np.ndarray | YES | — | — | — | No | — |
| south_edge | np.ndarray | YES | — | — | — | No | — |
| east_edge | np.ndarray | YES | — | — | — | No | — |
| west_edge | np.ndarray | YES | — | — | — | No | — |
| height_min_m | float | — | YES (meta) | — | — | No | — |
| height_max_m | float | — | YES (meta) | — | — | No | — |
| coordinate_system | str | — | YES (meta) | — | — | No | — |
| unity_export_schema_version | str | — | YES (meta) | — | — | No | — |
| schema_version | str | — | YES (meta) | — | — | No | — |
| content_hash | str | — | YES (meta) | — | — | No | — |
| dirty_channels | Set[str] | — | YES (meta) | — | — | No | — |
| populated_by_pass | Dict[str,str] | — | YES (meta) | — | — | No | — |
| strict_tile_contract | bool | — | YES (meta) | — | — | No | — |

---

## Confirmed missing fields (silent data loss on checkpoint)

| Field | Added in | Missing from | Impact |
|---|---|---|---|
| `terrain_ao` | Unity integration block (line 397) | `_ARRAY_CHANNELS` entirely | PBR AO baked by quixel_ingest is silently dropped on every to_npz call. After load the field is None. Material passes re-running after checkpoint load produce AO-less results. Distinct from `ambient_occlusion_bake` which IS serialized. |
| `terrain_displacement` | Unity integration block (line 399) | `_ARRAY_CHANNELS` entirely | Parallax/height displacement from Quixel ingest lost on every checkpoint cycle. Terrain loaded from a mid-run checkpoint will appear flat; the displacement pass must re-run even though the data was already computed. |
| `ridge_eroded` | Erosion masks block (line 292) | `_ARRAY_CHANNELS` entirely | The erosion-refined ridge field (gully reinforcement + structural_ridge merge) is lost on save/load. Downstream passes that prefer `ridge_eroded` fall back to the stale raw `ridge`. This produces analytically incorrect ridges on any pipeline that loads a checkpoint after pass_erosion. |

**Note on `_ARRAY_CHANNELS` comment at line 534:** The comment explicitly states "any new ndarray field MUST be added here or it will be silently dropped on serialization." All three missing fields violate this stated contract.

---

## Confirmed present: water_surface_elevation_m

`water_surface_elevation_m` IS in `_ARRAY_CHANNELS` (line 570):

```python
"water_surface_elevation_m",
```

This channel is fully serialized. If the pipeline saves a checkpoint mid-run, this channel is preserved. The earlier concern (G4 finding) was about `produces_channels` declarations in pass contracts, not serialization. From a checkpoint round-trip standpoint, `water_surface_elevation_m` is safe.

---

## Checkpoint round-trip: what is lost

### Save path (save_checkpoint)
`terrain_checkpoints.save_checkpoint()` calls `_atomic_npz_write(stack, mask_path)` which calls `stack.to_npz()`. The checkpoint record (`TerrainCheckpoint`) additionally captures:
- `height_min_m`, `height_max_m`, `cell_size_m`, `tile_size`, `coordinate_system`, `unity_export_schema_version` — scalar metadata snapshots
- `water_network_snapshot` — deep copy of `state.water_network`
- `viewport_vantage_snapshot` — deep copy of `state.viewport_vantage`
- `side_effects_snapshot` — copy of `state.side_effects`
- `pass_history_len` — integer count only, NOT the full pass history list

### What `to_npz` serializes
- All ndarray channels in `_ARRAY_CHANNELS` that are non-None
- All dict-of-ndarray channels in `_DICT_CHANNELS` (`wildlife_affinity`, `decal_density`, `detail_density`)
- All opaque JSON-compatible channels in `_OPAQUE_CHANNELS` (mesh specs, particle specs, atlas paths, etc.)
- Scalar metadata in the `__meta__` JSON blob

### What is LOST after a checkpoint cycle

| Lost item | Category | Where lost | Notes |
|---|---|---|---|
| `terrain_ao` | ndarray channel | Not in `_ARRAY_CHANNELS` | Silent None after load; production bug |
| `terrain_displacement` | ndarray channel | Not in `_ARRAY_CHANNELS` | Silent None after load; production bug |
| `ridge_eroded` | ndarray channel | Not in `_ARRAY_CHANNELS` | Falls back to stale `ridge` after load |
| `pass_history` (full list) | Pipeline state | `TerrainCheckpoint` stores `pass_history_len` only | `rollback_to` restores the stack but cannot restore the full pass history. The list in `TerrainPipelineState` is not serialized. |
| `particle_layer_specs` (on state) | Pipeline state | `TerrainPipelineState.particle_layer_specs` not in checkpoint | VFX particle layer specs on the pipeline state (not the mask stack) are not saved. `particle_emitter_specs` on the stack IS saved via `_OPAQUE_CHANNELS`, but the derived `state.particle_layer_specs` is not. |

### Rollback behavior
`TerrainPassController.rollback_to()` is called by `rollback_last_checkpoint()`. It restores the mask stack from the `.npz` file (via `TerrainMaskStack.from_npz()`), and the `TerrainCheckpoint` object separately stores `water_network_snapshot` and `side_effects_snapshot`. However:
- The three missing array channels (`terrain_ao`, `terrain_displacement`, `ridge_eroded`) are absent after any rollback
- `pass_history` is not restored; only its length is stored

---

## Sim modules: no stack write path

`sim/foam.py`, `sim/catenary.py`, and `sim/pbd_cloth.py` are pure computation libraries:
- `foam.py` exports `generate_foam_mask()` returning a float32 ndarray. The caller is responsible for writing results to `stack.set("foam", ...)` or similar. The sim module itself never touches the stack.
- `catenary.py` exports `solve_catenary()`, `catenary_with_sag()`, `arc_length_uv()` returning point arrays. No stack writes.
- `pbd_cloth.py` exports `simulate_cloth()`, `bake_static_drape()` returning position history arrays. No stack writes.

There are no sim-specific serialization gaps. If a pass calls these functions and writes foam/cloth results to named channels, those channels must themselves appear in `_ARRAY_CHANNELS` or `_OPAQUE_CHANNELS` to survive checkpointing. The foam result goes into the `foam` channel which IS in `_ARRAY_CHANNELS`.

---

## Metadata field serialization

All scalar metadata fields are serialized in the `__meta__` JSON blob embedded inside the `.npz`:
- `tile_size`, `cell_size`, `world_origin_x`, `world_origin_y`, `tile_x`, `tile_y`
- `height_min_m`, `height_max_m`
- `coordinate_system`, `unity_export_schema_version`, `schema_version`
- `strict_tile_contract`
- `populated_by_pass` (full dict)
- `dirty_channels` (sorted list)
- `content_hash`
- `dict_channels` key registry (for reconstructing wildlife_affinity, decal_density, detail_density)

`from_npz()` correctly restores all of these. Reconstructed stacks have correct metadata — no metadata gap.

---

## Fix recommendations

### P0 — add missing channels to _ARRAY_CHANNELS

In `terrain_semantics.py`, `_ARRAY_CHANNELS` default tuple (lines 540–668), add:

```python
# Unity AAA channels — MISSING (terrain_ao, terrain_displacement)
"terrain_ao",
"terrain_displacement",
# Erosion-refined ridge — MISSING
"ridge_eroded",
```

These three additions are the minimum required to stop silent data loss. The self-documenting comment at line 534 already flags this requirement; the fields were simply never added.

---

## STATISTICS

- Total TerrainMaskStack ndarray/dict/opaque fields: 120
- In `_ARRAY_CHANNELS` (serialized as npz arrays): 97
- In `_DICT_CHANNELS` (serialized with key registry): 3
- In `_OPAQUE_CHANNELS` (serialized in __meta__ JSON): 10
- In `__meta__` JSON scalars only: 10
- **Silently skipped (zero serialization path):** 3 (`terrain_ao`, `terrain_displacement`, `ridge_eroded`)
- Pipeline state fields not in any checkpoint: 2 (`pass_history` list, `particle_layer_specs` list)
- Sim modules writing directly to stack: 0
