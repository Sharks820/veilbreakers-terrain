# K8 — Audio Zones, Atmosphere Volumes, Saliency, Performance & Corruption Wiring (Audit 2026-04-27)

**Auditor:** Opus deep-dive K8
**Date:** 2026-04-27
**Scope:** Verify whether secondary world-data systems (audio reverb zones, atmospheric volumes, saliency, performance reports, corruption/darkness, rhythm, readability) are wired into production and exported to Unity. Cross-checks J1 (orphan registry) and J2 (actual production pipeline).

---

## TL;DR — Severity Assessment

The pipeline LOOKS rich. Execution-and-export reality is much thinner. Of the seven secondary systems audited:

| System | Pass exists? | Registered? | In production pipeline? | On TerrainMaskStack? | Exported to Unity? |
|---|---|---|---|---|---|
| `terrain_audio_zones.py` (`audio_zones`) | YES (`pass_audio_zones`) | YES (`register_bundle_j_audio_zones_pass`) | **NO** (Bundle J never sequenced — see J1/J2) | YES if pass were run | **PARTIAL** — exporter regenerates zones from raster with HARD-CODED constants, ignores the rich `audio_zone_list` (Sabine RT60, cliff echo) |
| `atmospheric_volumes.py` (fog/dust/firefly/god-ray volumes) | NO pass function | **NO pass registration** at all | NO | NO | **NO** — exposed only as a Blender MCP RPC handler |
| `terrain_saliency.py` (`saliency_refine`) | YES | YES (Bundle H-saliency) | **NO** (orphan, J1) | `saliency_macro` is seeded by `structural_masks`; refine never runs | YES (channel name `saliency_macro` is in export loop) but content is the unrefined seed |
| `terrain_performance_report.py` | NO (it's a collector, not a pass) | NO | **NO** auto-call | NO | **NO** — only invokable via `terrain_performance_report` MCP RPC handler with caller-supplied stack |
| Corruption/darkness zones | NO terrain pass | NO | NO (computed in `world_map._biome_grammar`) | **NO** — `corruption_map` lives on `WorldMapSpec`, never lands on `TerrainMaskStack` | **NO** — only baked indirectly into vertex `macro_color` via `apply_corruption_tint` |
| `terrain_rhythm.py` | NO (`analyze_feature_rhythm` is a library helper) | NO | NO | NO | NO |
| `terrain_readability_bands.py` | NO pass; **always-on post-pipeline hook** | n/a (Bundle N hook) | YES — runs after every successful pipeline | Score lives on `PassResult.metrics`, not stack | **NO** — readability score never enters Unity export manifest |

**Three additional P0-class orphan/unexport failures emerge that are NOT already counted in I5-P0-4 (orphan passes), I2-P0-2/3 (grass density / horizon angles), or J4 saliency_refine.** They are listed in §6.

---

## 1. `terrain_audio_zones.py` — Computed but Drop-On-Floor at Export

### 1.1 What it produces

`compute_audio_reverb_zones` (line 609) returns an int8 raster of `AudioReverbClass` values (OPEN_FIELD/FOREST_SPARSE/FOREST_DENSE/CAVE/CANYON/WATER_NEAR/MOUNTAIN_HIGH/INTERIOR). `compute_audio_zone_list` (line 646) returns a rich list of dicts, one per connected component, with **per-zone Sabine-corrected RT60**, pre-delay, diffusion, hf_damping, lf_reference, absorption, and (for canyon/cliff zones) per-cell **echo-delay seconds = 2·dist/343 m·s⁻¹**.

`pass_audio_zones` (line 878) writes BOTH onto the stack:

```
veilbreakers_terrain/handlers/terrain_audio_zones.py:899
    stack.set("audio_reverb_class", reverb_class_raster, "audio_zones")
veilbreakers_terrain/handlers/terrain_audio_zones.py:905
    stack.set("audio_zone_list", zones, "audio_zones")
```

### 1.2 Pass registration

`register_bundle_j_audio_zones_pass()` (line 953) registers the pass with `produces_channels=("audio_reverb_class","audio_zone_list")`. It is loaded via Bundle J central registrar:

```
veilbreakers_terrain/handlers/terrain_bundle_j.py:53
    terrain_audio_zones.register_bundle_j_audio_zones_pass()
```

Bundle J is loaded by `terrain_master_registrar.py:229`.

### 1.3 Production-pipeline reality (CRITICAL)

J1 (`§1.1 Orphan-by-bundle breakdown`) and J2 (`§1` ordered sequence) confirm: **the production controller pipeline is exactly 8 passes** — none of them are `audio_zones`. Bundle J's nine passes are *registered* but the pipeline list constructed in `environment.py:2005-2034` never appends any of them. Bundle J orphan rate: **9/9 = 100 %**.

So in production: `audio_reverb_class` and `audio_zone_list` are **never written**. `stack.audio_reverb_class is None` for every shipped tile.

### 1.4 Unity export reality (P0 even if pass were wired)

The Unity exporter conditionally writes the raster (`terrain_unity_export.py:1264` includes `audio_reverb_class` in the channel-write loop) and emits `audio_zones.json`. But `_audio_zones_json` (line 1633) re-derives zone parameters by **looking up hardcoded class constants** in a private dict (line 1640):

```
class_params = {
    0: ("open_field", 0.15, 0.2, 0.4),
    1: ("forest_dense", 0.45, 0.3, 0.7),
    ...
}
...
zones.append({..., "wet_mix": wet, "early_reflections": er, "tail_length": tail, ...})
```

**`stack.audio_zone_list` is never read by the exporter.** Sabine-corrected RT60 (which adapts per zone to actual cave volume / canyon footprint), per-cell cliff-echo `echo_delay_s`, diffusion, hf_damping, and lf_reference are all dropped on the floor. Unity sees only a 4-tuple of presets indexed by class enum — exactly what a hardcoded ScriptableObject would have given them.

**Net AAA reality:** even after Bundle J is wired, the audio system gets *categorical* zones and not the physical numeric model that justifies having a pass in the first place.

---

## 2. `atmospheric_volumes.py` — No Pass, No Pipeline, No Export

### 2.1 What it produces

`compute_atmospheric_placements(biome_name, area_bounds, seed, ...)` (line 236) returns a list of placement dicts: type (ground_fog/dust_motes/fireflies/god_rays/smoke/spore_clouds/void_shimmer), shape (box/sphere/cone), bounds, density, color, opacity, animation, animation_speed, particle_type. `compute_volume_mesh_spec` (line ~600) gives a vertex/index array for the volume hull. `estimate_atmosphere_performance` rolls up GPU cost.

### 2.2 Wiring reality

Repo-wide grep:

```
$ grep -rn 'register_pass\|PassDefinition' atmospheric_volumes.py
(no matches)
```

There is **no pass function**. There is **no PassDefinition**. There is **no entry in any bundle registrar**. The module is exposed only as three Blender MCP socket-server handlers:

```
veilbreakers_terrain/handlers/__init__.py:361-363
    handlers["env_compute_atmospheric_placements"] = ...
    handlers["env_volume_mesh_spec"] = ...
    handlers["env_atmosphere_performance"] = ...
```

These run when an external client (Unity Editor, an inline test) calls them over the MCP socket. They never run as part of `compose_map`/`handle_generate_terrain_aaa`, never write to a `TerrainMaskStack` field, and have no representation in `TerrainMaskStack` at all (no `atmospheric_volume_specs` or similar field — confirmed by reading `terrain_semantics.py` lines 380-460).

### 2.3 Unity export reality

```
$ grep -in 'atmospheric\|atmosphere\|fog_volume' terrain_unity_export.py
(no matches besides the water `fog_distance_m` shader manifest property)
```

`terrain_unity_export.py` has zero references to atmospheric volumes, no `atmosphere_volumes.json` or equivalent file, and no field in `ecosystem_meta.json`. Unity gets nothing.

### 2.4 P0-class verdict — **NEW (K8-P0-1)**

The entire atmospheric-volumes subsystem is a 1018-LOC dead-import in production. No pass registers it; no pipeline appends it; no exporter emits it. Tests at `test_atmospheric_volumes.py` and `test_world_map_light_atmosphere.py` exercise the API in isolation, giving the false impression that the system is shippable. This is the cleanest possible orphan: **secondary data system fully computed by an MCP RPC, never landed in production**.

---

## 3. `terrain_saliency.py` — Pass Orphaned, Channel Exported with Stale Content

The orphan status of `saliency_refine` is already counted under I5-P0-4 (J1 explicitly enumerates it at row 6 of §1). To avoid double-counting, this audit only verifies the export-side status:

- `saliency_macro` is seeded by `structural_masks` from curvature/concavity/ridge geometry (J1 §1 row 6 quote: *"`structural_masks` already seeds `saliency_macro` from curvature alone; the polish layer never runs"*).
- The exporter DOES write `saliency_macro` to the export bundle: `terrain_unity_export.py:1267` includes it in the `for channel in (...)` loop.
- Net: Unity does receive a saliency channel, but it is the unrefined geometric heuristic, not the 8-factor UE5-style tactical scoring (sight-lines, water proximity, vantage coverage) that the file's docstring advertises.

Saliency is also never used by anything else in production (no scatter / camera placement / LOD pass declares `saliency_macro` as `requires_channels` or `optional_channels` — confirmed by repo-wide grep). Even on the export side, it is emitted as a debug-grade visualization channel rather than a runtime gameplay input.

---

## 4. `terrain_performance_report.py` — Real Collector, Zero Production Auto-Calls

### 4.1 What it does

`collect_performance_report(stack, budgets=…)` (line 50) computes triangle counts (per category), instance counts, material count (= `splatmap_weights_layer.shape[2]`), draw-call proxy, texture memory in MB, and `within_budget` per category. Status is `not_available` when inputs are missing, `ok` when within all budgets, `over_budget` otherwise. The file's own docstring explicitly disclaims the prior fake-`ok` stub.

### 4.2 Wiring reality

```
$ grep -rn 'collect_performance_report\|TerrainPerformanceReport' veilbreakers_terrain
veilbreakers_terrain/handlers/__init__.py:970   handlers["terrain_performance_report"]
veilbreakers_terrain/handlers/terrain_performance_report.py  (definition)
veilbreakers_terrain/tests/test_bundle_egjn_supplements.py:51 (and 7 callers, all tests)
```

It is exposed as an MCP RPC handler in `handlers/__init__.py:967-973` but the handler is invoked only when an external client supplies its own `mask_stack`. Inside the production pipeline:

- `_execute_terrain_pipeline` does NOT call `collect_performance_report` (verified by reading `environment.py:2755-3135`).
- Bundle N's post-pipeline hook (`terrain_bundle_n.run_bundle_n_post_pipeline_hooks`, line 247) does NOT call it (it calls `enforce_budget` and `compute_readability_bands` only — see lines 309-310).
- No CI test calls `collect_performance_report` with a real production stack — every test in `test_bundle_egjn_supplements.py` constructs a fixture stack inline.

Net: the report **never fires automatically** during a tile generation. The "performance gate" is in practice the `enforce_budget` budget enforcer, which is a *different* system that does not consume `TerrainPerformanceReport` and reports its own metrics.

### 4.3 P0-class verdict — **NEW (K8-P0-2)**

The performance-report module exists, runs correctly when invoked, and emits a structured report. But the production pipeline never invokes it, so AAA-budget regressions on triangle counts, instance counts, draw calls, and texture memory are silent — they fail by manifesting on-target in Unity rather than at terrain-generation time. This is consistent with the orphan pattern. Severity: **P0** because terrain budget overruns hit the developer at frame-render time in Unity rather than at deterministic CI build time.

---

## 5. Corruption / Darkness Zones — Computed in `_biome_grammar`, Stranded on `WorldMapSpec`

### 5.1 What exists

`_generate_corruption_map` (`_biome_grammar.py:288`) produces a Perlin-domain-warped fBm corruption intensity raster in `[0, 1]`. It lives on:

```
veilbreakers_terrain/handlers/_biome_grammar.py:110
    corruption_map: np.ndarray   # (height, width) float64 in [0, 1]   — on WorldMapSpec
veilbreakers_terrain/handlers/_biome_grammar.py:192
    corruption_map = _generate_corruption_map(...)
```

It is consumed in `environment.py:8416-8508` to (a) count `corruption_zones = (corruption_map > 0.3).sum()` for debug, and (b) apply per-vertex MicroSplat height-blend tinting (`_CORRUPTION_R/G/B/H`) in `apply_corruption_tint`.

It was previously also present as a `corruption_spread_radius_m` field on `TerrainQualityProfile` (`terrain_quality_profiles.py:194,358,414,470,526,740-742`) — but per memory note `I3-P0-1` that field is dead.

### 5.2 What is missing

```
$ grep -rn 'set("corruption' veilbreakers_terrain/handlers
(no matches)
$ grep -in 'corruption' terrain_semantics.py
(no matches — TerrainMaskStack has no corruption_map field)
$ grep -in 'corruption' terrain_unity_export.py
(no matches)
```

The corruption raster:
- never lands on `TerrainMaskStack` (no field exists for it);
- has no terrain pass that writes it;
- has no Unity export channel — Unity receives only the *baked vertex colors* via `macro_color`, with no way to recover per-cell corruption intensity for shader masks, gameplay queries (e.g. "is the player in a high-corruption zone?"), or AI behavior tuning.

The corruption geometry/material affect is therefore baked-only. It does **not** deform terrain (no `corruption_height_delta`), does not feed audio reverb (no corruption→audio edge), does not affect scatter (no `requires_channels=("corruption_map",)` anywhere), and does not surface to gameplay code at runtime in any retrievable form.

### 5.3 P0-class verdict — **NEW (K8-P0-3)**

Corruption is the project's signature dark-fantasy mechanic. It is computed (in `_biome_grammar`), used to tint vertices once at bake, and then forgotten. Unity gets no corruption channel, gameplay scripts can't query corruption intensity, and downstream passes (audio, scatter, fog, navmesh) cannot be modulated by corruption. Severity: **P0** — entire signature world-data system absent from Unity export. Consistent with orphan pattern but newly identified (not in I5-P0-4 / I2-P0-2/3 / J1's orphan list).

---

## 6. `terrain_rhythm.py` — Library With Zero Production Callers

`analyze_feature_rhythm` (line ~150), `enforce_rhythm`, `validate_rhythm`, and `_ripley_k_proxy` are pure analytical helpers (Ripley K, Lloyd relaxation, NN-distance histograms, Spearman density gradient).

```
$ grep -rn 'from .terrain_rhythm\|terrain_rhythm\.' veilbreakers_terrain/handlers
(no matches in handlers/ — only tests reference it)
```

Production callers: **0**. The contract YAML (`contracts/terrain.yaml:216`) explicitly notes: *"No pass function, no registration"*. This is dead code in the production sense — only `test_terrain_composition.py` and `test_environment_analysis_runtime_helpers.py` import it. It is not P0 by itself (no data is silently generated and dropped) but it is sustaining a 564-line-of-code maintenance liability that would warrant deletion or wiring in.

---

## 7. `terrain_readability_bands.py` — Wired Post-Pipeline, Score Never Reaches Unity

### 7.1 Wiring

This one is actually wired. Bundle N's post-pipeline hook `run_bundle_n_post_pipeline_hooks` (`terrain_bundle_n.py:309-313`) always invokes it:

```python
bands = terrain_readability_bands.compute_readability_bands(stack)
readability_score = terrain_readability_bands.aggregate_readability_score(bands)
summary["readability_score"] = float(readability_score)
summary["readability_band_scores"] = {band.band_id: float(band.score) for band in bands}
```

The 5 bands (silhouette, volume, value, texture, color) are scored 0-10 per-band and weight-aggregated into a single readability score. This information is merged into the *last* `PassResult.metrics["bundle_n"]` dict via `_merge_bundle_n_metrics`.

### 7.2 Export reality

```
$ grep -in 'readability' terrain_unity_export.py
(no matches)
```

The score is computed and stored in `PassResult.metrics`, but the manifest and `unity_import_descriptor.json` (`terrain_unity_export.py:990-1022`) carry no `readability_score` or `readability_band_scores`. Unity has no per-tile QA score available at runtime, so the metric is purely a CI / telemetry quantity.

This is a softer issue than the others — the data exists in metrics for telemetry/CI, just not in the Unity payload. Not P0 by the K8 threshold (the system is wired and the data is captured in Bundle N's record_telemetry path), but worth flagging as a P1 export gap if Unity wants per-tile readability gates.

---

## 8. Summary of NEW P0 Findings (Not Already Counted)

| ID | System | Source line | Severity | Pattern |
|---|---|---|---|---|
| **K8-P0-1** | `atmospheric_volumes.py` (1018 LOC) — fog/dust/firefly/god-ray/smoke/spore/void-shimmer placement system | `atmospheric_volumes.py:236` (compute_atmospheric_placements); zero pass registration | P0 | Entire secondary data system: never registered, never sequenced, never exported. Lives only as MCP RPC. |
| **K8-P0-2** | `terrain_performance_report.py` — triangle/instance/draw/material/texture-memory budget collector | `terrain_performance_report.py:50` (collect_performance_report); zero auto-invocation in `environment.py` or `terrain_bundle_n.py` | P0 | AAA budget regressions undetectable at terrain-gen time; dev finds them at Unity render time. Fake-`ok` was previously fixed — but there is now no caller. |
| **K8-P0-3** | Corruption / darkness raster (signature gameplay system) | `_biome_grammar.py:192` (`_generate_corruption_map`); never lands on `TerrainMaskStack`; absent from `terrain_unity_export.py` channel loop | P0 | Per-cell corruption intensity is baked into vertex colors and forgotten. Unity gameplay/AI/shaders cannot recover it. |

Each of these maps cleanly onto the K8 P0 threshold: *"an entire secondary data system is computed and then silently not exported."*

### Re-confirmed already-counted P0s (no new claim)

- **I5-P0-4**: Bundle J orphan (audio_zones, wildlife_zones, gameplay_zones, wind_field, cloud_shadow, decals, navmesh, ecotones), Bundle L orphan (horizon_lod, fog_masks, god_ray_hints), `saliency_refine`. Confirmed by J1 (rate of orphan in Bundles H/I/J/K/L/O = 100%) and J2 (production sequence is 8 passes, none of these).
- **I2-P0-2/3**: `grass_density_map` and `horizon_elevation_angles` are TerrainMaskStack fields not in the Unity export channel loop. Verified at `terrain_unity_export.py:1261-1290` — `grass_density_map` and `horizon_elevation_angles` do not appear, even though `stack.horizon_elevation_angles` is written by `terrain_horizon_lod.py:308` (when that orphan pass would run).

### Lower-severity follow-ups (NOT counted as P0)

- **K8-P1-A** (`audio_zones` exporter discards `audio_zone_list`): even if Bundle J were wired, `_audio_zones_json` (`terrain_unity_export.py:1633-1676`) ignores `stack.audio_zone_list` and re-derives zone params from a hardcoded constants table. Sabine-corrected RT60, cliff echo delay, per-zone diffusion / hf_damping / lf_reference / absorption / pre_delay are dropped. This is a P1 — fix only relevant after Bundle J is sequenced.
- **K8-P1-B** (`readability_score` not in Unity manifest): score is computed and recorded in PassResult metrics + telemetry NDJSON, but is absent from `unity_import_descriptor.json` and `manifest.json`. P1.
- **K8-P2-A** (`terrain_rhythm.py` 564 LOC of zero-caller library code): contract yaml acknowledges "No pass function, no registration." Not P0 (no silent data loss), but a maintenance liability.

---

## 9. Verification Notes (every claim, source-line cited)

1. `pass_audio_zones` registered: `terrain_audio_zones.py:953-976` ✓
2. Bundle J registrar imports audio: `terrain_bundle_j.py:53` ✓
3. Bundle J central registrar called: `terrain_master_registrar.py:229` ✓
4. Bundle J ORPHAN status: J1 audit `§1.1` "Bundle J — 9 orphans (entire bundle unwired)"; cross-verified by reading `environment.py:1975-2034` (no audio_zones / fog_masks / god_ray / saliency_refine / etc. in the appended pipeline list).
5. Audio exporter ignores zone_list: `terrain_unity_export.py:1633-1676` reads `stack.audio_reverb_class` only; class_params is the hardcoded preset table at `:1640-1649` ✓
6. `atmospheric_volumes.py` has no pass: confirmed by `grep -n 'register_pass\|PassDefinition\|def pass_' atmospheric_volumes.py` returning 0 hits.
7. `atmospheric_volumes.py` is exposed only as RPC: `handlers/__init__.py:346-365` ✓
8. `atmospheric_volumes.py` not in Unity export: `grep -in atmospher terrain_unity_export.py` returns 0 hits.
9. Saliency_macro export: `terrain_unity_export.py:1267` (in the channel-write tuple) ✓
10. Saliency_refine orphan: J1 §1 row 6 ✓
11. Performance-report wiring: only call site is RPC handler at `handlers/__init__.py:967-973`. Confirmed by `grep -rn 'collect_performance_report' veilbreakers_terrain/handlers` (definition + 1 RPC handler only).
12. `corruption_map` on WorldMapSpec only: `_biome_grammar.py:110, 192, 277` ✓
13. `corruption_map` absent from TerrainMaskStack: `grep -in corruption terrain_semantics.py` returns 0 hits ✓
14. `corruption_map` absent from Unity export: `grep -in corruption terrain_unity_export.py` returns 0 hits ✓
15. `terrain_rhythm.py` 0 production callers: `grep -rn 'from \.terrain_rhythm\|terrain_rhythm\.' veilbreakers_terrain/handlers` returns 0 (only tests + contract yaml reference it).
16. Readability bands wired: `terrain_bundle_n.py:309-310` ✓
17. Readability score absent from Unity manifest: `grep -in readability terrain_unity_export.py` returns 0 hits ✓
18. Production pipeline = 8 passes: J2 `§1` final list `['macro_world','structural_masks','pass_hydrology','erosion','structural_masks','cliffs','emit_overhang_meshes','validation_minimal']` ✓
19. `mist` channel IS exported: `terrain_unity_export.py:1271` ✓ (so Bundle L's `fog_masks` pass would deliver if wired — but per J2 it isn't sequenced)
20. `lod_bias` IS exported: `terrain_unity_export.py:1277` ✓ but `horizon_elevation_angles` is NOT in the same loop (verified — already counted as I2-P0-3).

---

## 10. Recommended Remediation (informational, not in scope of this audit)

The three new P0s share one fix pattern: *bridge the existing computation into the existing pipeline + export bundle.*

1. **K8-P0-1** — register `atmospheric_volumes` as a Bundle J or Bundle L pass that calls `compute_atmospheric_placements` per biome, writes a new `atmospheric_volume_specs` channel onto the stack, and emit `atmospheric_volumes.json` from the exporter. ~80 LOC.
2. **K8-P0-2** — invoke `collect_performance_report` from `run_bundle_n_post_pipeline_hooks` adjacent to readability_bands, attach to summary, push into `unity_import_descriptor.json`. ~20 LOC.
3. **K8-P0-3** — write `corruption_map` from `_biome_grammar` onto `TerrainMaskStack.corruption_map` (new field), include it in the Unity-export channel write loop, surface it on `ecosystem_meta.json`. ~30 LOC.

After these three fixes, K8-P1-A (audio zone_list discard), K8-P1-B (readability score in manifest), and the broader Bundle-J/K/L orphan epidemic become the natural next remediation wave — but those are I5-P0-4 territory.
