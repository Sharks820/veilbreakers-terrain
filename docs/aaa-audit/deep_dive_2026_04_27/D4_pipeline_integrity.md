# D4 Audit: Pipeline Integrity
**Date:** 2026-04-27

---

## Default pass execution order

The `run_pipeline()` method in `terrain_pipeline.py` constructs the default sequence at lines 560–569. There are two variants depending on whether `intent.scene_read` is populated.

### Without scene_read (headless / unit test path)
```
1. pass_generate_low_freq_hmap
2. terrain_labels
3. structural_masks
4. pass_generate_high_freq_detail
5. pass_composite_hmap
6. validation_minimal
```

### With scene_read (the production path — P0-A1-3 splice active)
Splice `pass_sequence[3:3] = ["pass_hydrology", "erosion"]` is applied:
```
1. pass_generate_low_freq_hmap
2. terrain_labels
3. structural_masks
4. pass_hydrology          ← spliced in at index 3
5. erosion                 ← spliced in at index 4
6. pass_generate_high_freq_detail
7. pass_composite_hmap
8. validation_minimal
```

After the sequence is built, `_normalize_delta_integration_sequence()` is called.
If `integrate_deltas` is registered and any pass in the sequence produces a `_delta`
channel, `integrate_deltas` is automatically inserted immediately after the last
delta-producing pass. In the default 6-pass headless sequence no delta producers
are present, so no insertion occurs. In the scene_read path, `erosion` produces no
`_delta` channels (it directly overwrites `height`), so again no insertion occurs.

---

## Pass names with no matching PassDefinition (runtime KeyError risk)

The following analysis cross-references every pass name in the default pipeline
sequences against all `PassDefinition(name=...)` registrations found in the
handler source files.

### Default pipeline passes — registration status

| Pass name | PassDefinition found? | Source file |
|---|---|---|
| `pass_generate_low_freq_hmap` | YES | `terrain_pipeline.py` `register_default_passes()` |
| `terrain_labels` | YES | `terrain_pipeline.py` `register_terrain_label_passes()` |
| `structural_masks` | YES | `terrain_pipeline.py` `register_default_passes()` |
| `pass_hydrology` | YES | `_water_network.py` `register_pass_hydrology()` |
| `erosion` | YES | `terrain_pipeline.py` `register_default_passes()` |
| `pass_generate_high_freq_detail` | YES | `terrain_pipeline.py` `register_default_passes()` |
| `pass_composite_hmap` | YES | `terrain_pipeline.py` `register_default_passes()` |
| `validation_minimal` | YES | `terrain_pipeline.py` `register_default_passes()` |

**Result: zero unregistered pass names in the default pipeline itself.** All 8 passes
(6 headless + 2 scene_read spliced) have matching `PassDefinition` entries.

### Additional passes registered by `register_default_passes()` (supplemental)

These are registered in the same call but are NOT in the default execution sequence.
They are only invoked if a caller builds a custom `pass_sequence` that includes them.

| Pass name | PassDefinition found? |
|---|---|
| `macro_world` | YES (legacy; overridden by `pass_generate_low_freq_hmap`) |
| `integrate_deltas` | YES (`terrain_delta_integrator.py`) |
| `pass_water_flow_speed` | YES (`_water_network.py`) |
| `pass_river_convergence` | YES (`_water_network.py`) |
| `pass_water_depth` | YES (`terrain_pipeline.py`) |
| `snow_line` | YES (`terrain_pipeline.py`) |

---

## P0-A1-3 confirmed execution order

**Splice location:** `terrain_pipeline.py` line 569:
```python
if getattr(self.state.intent, "scene_read", None) is not None:
    pass_sequence[3:3] = ["pass_hydrology", "erosion"]
```

This inserts at index 3 (before the element that was at index 3).

**Before splice:**
```
[0] pass_generate_low_freq_hmap
[1] terrain_labels
[2] structural_masks
[3] pass_generate_high_freq_detail   ← was at position 3
[4] pass_composite_hmap
[5] validation_minimal
```

**After splice:**
```
[0] pass_generate_low_freq_hmap
[1] terrain_labels
[2] structural_masks
[3] pass_hydrology
[4] erosion
[5] pass_generate_high_freq_detail   ← pushed to position 5
[6] pass_composite_hmap
[7] validation_minimal
```

**Execution order implication:**
`erosion` runs at position 4, `pass_generate_high_freq_detail` runs at position 5.
**Erosion runs BEFORE `pass_generate_high_freq_detail`.** This is the correct order
for the Fix 12.1 decomposition: low-freq base is eroded first, then high-freq detail
noise is generated, then both are composited by `pass_composite_hmap`. The splice
is architecturally sound.

**However**, `erosion` has `requires_scene_read=True` in its `PassDefinition`. The
splice is only applied when `scene_read` is not None — which matches. The guard is
consistent.

**One residual risk:** `erosion` requires `hmap_low_freq` (from
`pass_generate_low_freq_hmap`) but `structural_masks` requires `height`. After the
splice, `structural_masks` runs at position 2 (before `erosion` at 4), so
`structural_masks` sees the *pre-erosion* height. This means `slope`, `curvature`,
`ridge`, etc. are computed on the raw macro heightmap, not the hydraulically-eroded
one. `erosion` rewrites `height` and `hmap_low_freq` but does NOT re-trigger
`structural_masks`. Downstream passes that consume `slope` or `ridge` after erosion
are working from stale pre-erosion geometry. This is a pre-existing design issue, not
introduced by the splice, but worth flagging.

---

## Delta integrator analysis

### _DELTA_CHANNELS declared in `terrain_delta_integrator.py`

```python
_DELTA_CHANNELS = (
    "waterfall_pool_delta",
    "cave_height_delta",
    "strat_erosion_delta",
    "pool_deepening_delta",
    "coastline_delta",
    "karst_delta",
    "wind_erosion_delta",
    "glacial_delta",
)
```

### Passes writing `_delta` channels (PassDefinition `produces_channels`)

| Delta channel | Pass name | PassDefinition source |
|---|---|---|
| `waterfall_pool_delta` | `waterfalls` | `terrain_waterfalls.py` |
| `cave_height_delta` | `caves` | `terrain_caves.py` |
| `strat_erosion_delta` | `stratigraphy` | `terrain_geology_validator.py` |
| `glacial_delta` | `glacial` | `terrain_geology_validator.py` |
| `wind_erosion_delta` | `wind_erosion` | `terrain_geology_validator.py` |
| `coastline_delta` | `coastline` | `terrain_geology_validator.py` |
| `karst_delta` | `karst` | `terrain_geology_validator.py` |
| `pool_deepening_delta` | **NONE — PHANTOM CHANNEL** | — |

#### CRITICAL: `pool_deepening_delta` is a phantom delta channel

`pool_deepening_delta` appears in `_DELTA_CHANNELS` but:
- No `PassDefinition` has it in `produces_channels`.
- No `stack.set("pool_deepening_delta", ...)` call exists in any pass function in
  the handlers directory.
- The value IS computed inside `_terrain_erosion.py`'s `ErosionMasks` dataclass
  (`apply_hydraulic_erosion_masks`) but it is never written back to `TerrainMaskStack`.
- The `erosion` pass (`_terrain_world.py` `pass_erosion`) does not call
  `stack.set("pool_deepening_delta", ...)`.

**Effect:** `_collect_deltas()` in `terrain_delta_integrator.py` calls
`stack.get("pool_deepening_delta")` which always returns `None`. The channel is
silently skipped each run. Pool deepening deltas computed during erosion are **never
applied to the final heightmap**. This is a dead-delta bug of the same class as the
ones Phase 51 was meant to fix.

### Is `pass_integrate_deltas` in the DEFAULT_PIPELINE?

**NO.** The default `pass_sequence` constructed in `run_pipeline()` (lines 560–569)
does not include `integrate_deltas` directly. However, the pipeline does call
`_normalize_delta_integration_sequence(pass_sequence)` at line 573. This function
auto-inserts `integrate_deltas` after the last delta-producing pass **only if**:
1. `integrate_deltas` is registered in `PASS_REGISTRY`, AND
2. at least one pass in `pass_sequence` produces a `_delta` channel.

In the **default pass sequence** (both headless and scene_read variants), none of the
8 passes produce any `_delta` channel:
- `pass_generate_low_freq_hmap` → `height`, `hmap_low_freq`
- `terrain_labels` → label channels
- `structural_masks` → `slope`, `curvature`, etc.
- `pass_hydrology` → flow channels
- `erosion` → `height`, `hmap_low_freq`, `erosion_amount`, etc. (no `_delta`)
- `pass_generate_high_freq_detail` → `hmap_high_freq`
- `pass_composite_hmap` → `height`
- `validation_minimal` → nothing

**Result: `integrate_deltas` is NEVER auto-inserted into the default pipeline.**
`_normalize_delta_integration_sequence()` finds zero delta producers and returns
the sequence unchanged.

The delta channels (`waterfall_pool_delta`, `cave_height_delta`, etc.) are only
written by passes registered in Bundles C, F, I (waterfalls, caves, stratigraphy,
glacial, wind_erosion, coastline, karst). These bundles are never in the default
6/8-pass sequence. Any caller who runs a custom pipeline that includes `waterfalls`
or `caves` but omits `integrate_deltas` will have deltas silently ignored unless
`_normalize_delta_integration_sequence` auto-inserts it.

**When deltas ARE applied:** Only when a custom `pass_sequence` argument is passed
to `run_pipeline()` that (a) includes one or more delta-producing passes AND
(b) `integrate_deltas` is registered. In that case, the normalizer auto-inserts it.
This is a fragile contract: `integrate_deltas` must already be in the registry
(requires `register_default_passes()` to have been called, which calls
`register_integrator_pass()`). If the registry was not initialized, the normalizer
silently skips insertion (line 97: `if not seq or "integrate_deltas" not in
TerrainPassController.PASS_REGISTRY: return seq`).

### Summary table

| Question | Answer |
|---|---|
| Passes writing `*_delta` channels (registered) | 7 |
| `pool_deepening_delta` writer (registered) | NONE — phantom channel |
| `pass_integrate_deltas` in default pipeline | NO |
| Deltas applied when only default pipeline runs | NO — no delta producers in default sequence |
| Deltas applied when custom pipeline includes delta passes | CONDITIONAL — only if registry was initialized |
| Auto-insertion guard reliable | NO — silently skips if registry uninitialized |

---

## Registration order violations

The master registrar (`terrain_master_registrar.py`) loads bundles in this order:
```
A → B-cliffs → G → H-framing → F → I → C → B-materials → E → D → H-saliency
  → J → K → L → N → O
```

Checking declared `requires_channels` vs. registration order for cross-bundle
channel dependencies:

| Consumer pass (bundle) | Required channel | Producer pass (bundle) | Producer registers before consumer? |
|---|---|---|---|
| `banded_macro` (G) | `height` | `pass_generate_low_freq_hmap` (A) | YES — A before G |
| `framing` (H) | `height`, `slope` | `structural_masks` (A), `banded_macro` (G) | YES — A,G before H |
| `caves` (F) | `height` | A | YES |
| `stratigraphy`/`glacial`/`wind_erosion`/`coastline`/`karst` (I) | `height` | A | YES |
| `waterfalls` (C) | `height`, `slope`, `flow_accumulation` | A + `pass_hydrology` (A supplemental) | YES — all in A |
| `materials_v2` (B-materials) | `height`, `slope`, `rock_hardness` | A, A, stratigraphy(I) | YES — I before B-materials |
| `scatter_intelligent` (E) | `height`, `slope`, `materials_v2` | A, A, B-materials | YES — B-materials before E |
| `validation_full` (D) | `height`, `slope` | A | YES |
| `saliency_refine` (H-saliency) | `saliency_macro` | `structural_masks` (A) | YES |
| `audio_zones` / `wildlife_zones` / `gameplay_zones` (J) | `height`, `slope` | A | YES |
| `macro_color` (K) | `height`, `slope`, `saliency_macro` | A | YES |
| `wind_field` (J) | `height` | A | YES |
| `water_variants` (O) | `height` | A | YES |
| `bathymetry` (O) | `height`, `water_surface` | A, `water_variants` (O) | YES — `water_variants` registers before `bathymetry` within Bundle O |
| `vegetation_depth` (O) | `height`, `slope`, `splatmap` | A, A, B-materials | YES — B-materials before O |
| `emergent_grass` (O) | `splatmap` | `materials_v2` (B-materials) | YES |

**No registration order violations found for declared `requires_channels`.**

### Notable non-violation: `snow_line_factor` dual producer

Both Bundle A's `snow_line` pass (registered in `register_default_passes()`) and
Bundle I's `glacial` pass produce `snow_line_factor`. The `glacial` PassDefinition
declares `overrides=("snow_line_factor",)` at `terrain_geology_validator.py:543`,
so `register_pass()` accepts the duplicate without raising `ChannelOwnershipError`.
At runtime, whichever pass runs last owns the channel value. In the default pipeline,
`snow_line` is registered but never in the default sequence, so this only matters in
custom sequences that include both.

### Notable concern: `structural_masks` precedes `erosion` in registration and execution

As noted in the erosion splice section above: `structural_masks` runs before `erosion`
in both registration order (both in Bundle A) and execution order (position 2 vs. 4).
The `slope`, `ridge`, `basin` channels it produces reflect the pre-erosion
heightmap. `erosion` overwrites `height` and `hmap_low_freq` but does not invalidate
or re-compute these derivative channels. Passes that consume `slope` after `erosion`
(e.g., `cliffs`, `materials_v2`, `scatter_intelligent`) are working from stale data.
This is a channel staleness hazard, not a registration order violation per se, but
it is architecturally incorrect for production quality.

---

## STATISTICS

| Metric | Value |
|---|---|
| Total passes in default headless sequence | 6 |
| Total passes in default scene_read sequence (with splice) | 8 |
| Unregistered pass references in default sequence | **0** |
| PassDefinitions registered by `register_default_passes()` (total) | 14 (7 core + 7 supplemental) |
| `_delta` channel declarations in `_DELTA_CHANNELS` | 8 |
| `_delta` channel writers with registered PassDefinition | **7** |
| `_delta` channels with NO registered writer (phantom) | **1** (`pool_deepening_delta`) |
| Delta integrator in default pipeline: enforced | **NO** |
| Delta integrator auto-inserted when delta producers present in custom sequence | CONDITIONAL |
| Registration order violations (declared requires_channels) | **0** |
| Channel staleness hazards (structural_masks pre-erosion) | **1 (P1)** |
| Phantom delta channel bugs | **1 (P1)** |
