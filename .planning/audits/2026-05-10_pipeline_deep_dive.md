---
date: 2026-05-10
agent: pipeline-deep-dive
status: complete
branch: docs/biome-render-rebuild-spec
scope: cross-reference codex vs current source + wiring/channel/debris sweep
---

# Pipeline Deep Dive — 2026-05-10

## Executive Summary

1. **17-orphan-pass claim is STALE** — only 5 orphan passes remain in `build_default_pass_sequence` (terrain_pipeline.py L236-494). `cliffs`, `caves`, `karst`, `stratigraphy`, `wind_erosion`, `coastline`, `pass_water_flow_speed`, `pass_river_convergence`, `vegetation_depth`, `emergent_grass`, `pass_horizon_lod`, `pass_navmesh_export` are all now scheduled (Phase A D8-9 + Wave 3/5 + Phase C PR-A/E shipped).
2. **B15-P0-12 (Kuwahara anisotropic default) STILL OPEN** — `terrain_banded_advanced.py:542` still calls `apply_anti_grain_smoothing(..., variant="classic")` ignoring the AAA-tier `"anisotropic"` path. The 200-LOC Papari/Kyprianidis implementation is dead in production. Single-character fix.
3. **B15-P1-03 (procedural_grass biome map gap) STILL OPEN** — `procedural_grass.DEFAULT_BIOME_ID_MAP` (L257-272) has 14 entries; CANONICAL_BIOME_IDS has 18. Missing: `ruined_fortress`, `abandoned_village`, `battlefield`, `veil_crack_zone`. For those biomes, `pass_procedural_grass` falls back to id 0 (thornwood_forest), producing wrong species density.
4. **v8 mountain-render bug #1 (bbox grounding LOCAL→WORLD math) NOT FIXED** — `scripts/render_aaa_v8_mountain.py:384-399` still uses `corner[2]` from `eval_obj.bound_box` (object-local space). The `wz` calculation on L390 is dead code (computes `matrix_world @ matrix_world.inverted() @ matrix_world @ matrix_world.inverted() = identity`). Trees/rocks still float. Bugs #2 (snow), #3 (Volume Absorption), #5 (coast_* in ROCKS substring filter) ALSO confirmed unfixed.
5. **932 MB of binary archives (`vendor/BoatAttack-2.0.zip` 789 MB + `vendor/crest-4.22.4.zip` 188 MB) and 2.7 GB of free assets are untracked at repo root, with NO `.gitignore` rules covering them (as of 2026-05-10, pre-Wave-1; Wave-1 PR #69 adds these rules).** If accidentally staged via `git add -A` this commits ~3.6 GB. Five new `output/aaa_v*` dirs (1.9–8.8 GB each, totaling ~30 GB) are also untracked and not gitignored.

**Counts: still-open=8 verified, new=11 (untracked debris + dead-bbox-code + 1 phantom write at L390 + duplicate-name CSV warning fan-out + 5 v8 bugs), dead-code=2 (terrain_scatter_altitude_safety.py 13 LOC self-described "DEAD CODE" + L390 of v8 render), wiring-gaps=5 orphans + 1 phantom_read remnant ("optional_channels=canopy_density"), debris=10 top-level paths needing classification.**

**Recommended next action:** First close the v8/v9 render bug queue (single-script, single PR, fastest visible win for AAA bar), then in parallel ship B15-P0-12 + B15-P1-03 fixes (both <10 LOC) and stand up `.gitignore` rules for `assets/`, `vendor/`, `output/aaa_v*/`. The remaining 5 "registered but unscheduled" passes (`glacial`, `macro_world`, `materials_v2_volcanic`, `snow_line`, `waterfall_mist`) need owner decisions — most are deliberate dead twins per B15-P1-35/36 dead-twin cleanup.

---

## STILL OPEN from prior audits

| ID | file:line | severity | verification method | status |
|---|---|---|---|---|
| B15-P0-12 | `terrain_banded_advanced.py:542` | P0 | grep `variant="classic"` returns `apply_anti_grain_smoothing(..., variant="classic")` in production path | OPEN |
| B15-P1-03 | `procedural_grass.py:257-272` | P1 | DEFAULT_BIOME_ID_MAP has 14 keys; CANONICAL_BIOME_IDS has 18 — `ruined_fortress`, `abandoned_village`, `battlefield`, `veil_crack_zone` missing | OPEN |
| B15-P0-13 | `terrain_banded.py:293` + `terrain_banded_advanced.py:80` | P1 | two `compute_anisotropic_breakup` functions still in place; rename never landed | OPEN |
| B15-P1-35 / 36 | `terrain_geology_validator.py:703` + `terrain_horizon_lod.py:350` + `terrain_navmesh_export.py:689` | P1 | dead-twin pairs `(glacial,pass_glacial)`, `(horizon_lod, pass_horizon_lod)`, `(navmesh, pass_navmesh_export)` still both register; pipeline schedules only the prefixed variant | OPEN |
| B15-P1-39 | `terrain_pipeline.py:1644-1656` | P1 | `snow_line` pass is registered (L1648) but is not present in `build_default_pass_sequence` (verified by string-literal scan) | OPEN |
| B15-P1-38 | `terrain_materials_v2.py` registers `materials_v2_volcanic` | P1 | `materials_v2_volcanic` not present in `build_default_pass_sequence`; pipeline switches volcanic path via `include_lava` but always schedules `materials_v2`, not `materials_v2_volcanic` | OPEN |
| B15-P1-41 | `terrain_waterfalls.py:2988` (`waterfall_mist` registration) | P1 | `waterfall_mist` is registered but absent from `build_default_pass_sequence` (only `waterfalls` + `emit_particle_systems` are scheduled). `mist_zone_mask`/`wet_surface_decal` never populated in production | OPEN |
| B15-P1-42 | `atmospheric_volumes.py` (`optional_channels=("canopy_density",)`) | P2 | `canopy_density` has zero producers anywhere in the codebase (grep `stack.set("canopy_density"` + `produces_channels=...canopy_density...` = 0 hits) | OPEN |

### Items VERIFIED CLOSED (codex flagged but actually shipped)

- **B15-P0-01 height rescale (affine)**: FIXED at `_terrain_world.py:990` (`(hmap - hmap.min())/h_range_raw * _height_scale`).
- **B15-P0-02 four-biome crash**: FIXED at `_biome_grammar.py:126-129` (`blighted_mire`, `ashen_wastes`, `frozen_hollows`, `ruined_citadel` all in `BIOME_CLIMATE_PARAMS`).
- **B15-P0-08 hydraulic mass leak**: FIXED via Phase A D12-13 (PR #38) + D15.5 hotfix (PR #40), confirmed by V2 adversarial verifier ("0% mass leak on gentle ramp").
- **B15-P0-21 horizon_lod overrides**: FIXED at `terrain_horizon_lod.py:344-357` — both `horizon_lod` and `pass_horizon_lod` now declare `overrides=("lod_bias","horizon_elevation_angles")`.
- **B15-P0-28 cliffs orphan**: FIXED in current branch at `terrain_pipeline.py:372` (`*(("cliffs",) if has_scene_read else ())`).
- **B15-P0-29 caves orphan**: FIXED at `terrain_pipeline.py:364`.
- **B15-P0-30 stratigraphy/coastline/karst/wind_erosion orphans**: FIXED at `terrain_pipeline.py:301,312,351,376` (`karst` is Wave-5 line 376; `stratigraphy` at 312; `coastline` at 351; `wind_erosion` at 301).
- **B15-P0-31 stale slope post-deltas**: FIXED at `terrain_pipeline.py:391` (`structural_masks_post_deltas` runs after `integrate_deltas`).
- **B15-P0-33 water-flow-speed + river-convergence orphans**: FIXED at `terrain_pipeline.py:343`.
- **B15-P0-34 callable census `--strict-zero`**: FIXED — guardrail report shows `Live callables: 1925 / Matrix rows: 1925 / Missing rows: 0 / Non-A grade rows: 0` (see `output/verification/TERRAIN_BEST_PRACTICE_GUARDRAIL_REPORT.md`).
- **B15-P1-40 vegetation_depth + emergent_grass orphans**: FIXED at `terrain_pipeline.py:410,425`.
- **P0-P3 `_lightweight_state_copy` provenance bypass**: FIXED at `terrain_pass_dag.py:107` (now calls `new_stack.set(ch, val, producer)` so provenance is recorded).
- **P0-E2 hardcoded tree height**: FIXED at `terrain_unity_export.py:2542` (`proto_height = float(np.median(valid)) if valid.size > 0 else _TREE_HEIGHT_DEFAULT`).
- **P0-M1 splatmap merge**: PARTIALLY FIXED at `terrain_materials.py:3578-3593` — when `stack.splatmap_weights_layer` is present, Blender vertex colors are sampled from the stack; falls back to `auto_assign_terrain_layers` only when stack data is absent. Two codepaths still exist but the dual-truth risk is gated.
- **pool_deepening_delta double-apply**: FIXED — `terrain_delta_integrator.py:41-42` explicitly excludes `pool_deepening_delta` from `_DELTA_CHANNELS`.

---

## NEW FINDINGS

1. **P0 | `scripts/render_aaa_v8_mountain.py:390` | Dead code that LOOKS like fix-attempt** | A computed-but-unused `wz` expression `(eval_obj.matrix_world @ obj.matrix_world.inverted() @ obj.matrix_world @ obj.matrix_world.inverted()).to_translation().z` mathematically reduces to identity translation. Adjacent line 393 has `world_corner = eval_obj.matrix_world @ obj.data.vertices[0].co.copy() if False else None` — a `if False` short-circuit, also dead. The actually-used grounding (L395) reads `corner[2]` from `eval_obj.bound_box`, which is in object-local coordinates per Blender semantics. Fix: replace with `world_corner = eval_obj.matrix_world @ Vector(corner); min_z = min(min_z, world_corner.z)`.

2. **P0 | `scripts/render_aaa_v8_mountain.py:88` | "Ridge-noise" mountains commented as `max(peak_a, peak_b)`** | Comment says "max of two peak fields = ridge", but two Gaussian peaks max'd are still two domes — there is no ridge-noise term (e.g. `1 - abs(noise)` or signed-distance ridge construct). User-flagged bug #6. Fix: add `ridge = 1 - np.abs(perlin(GRID, 60, 1.0, SEED+10))` and blend.

3. **P0 | `scripts/render_aaa_v8_mountain.py:289-298` | Water has no Volume Absorption** | Lake material uses Glass+Glossy mix shader without `ShaderNodeVolumeAbsorption` on the Volume socket. Deep water reads pure surface refraction, not absorptive depth. User-flagged bug #3. Fix: add `ShaderNodeVolumeAbsorption(color=(0.06,0.25,0.35), density=0.15)` linked to `output.Volume`.

4. **P0 | `scripts/render_aaa_v8_mountain.py:420` | `ROCKS = [b for b in ... if any(k in b for k in ("boulder", "rock"))]` still matches `coast_land_rocks_03.blend`** | Substring `"rock"` matches `coast_land_rocks` (because the asset name contains "rocks"). User-flagged bug #5 said to DROP coast_* photoscan rocks; current code re-includes them. Fix: explicit blocklist or strip `coast_*` prefix from candidates.

5. **P0 | `scripts/render_aaa_v8_mountain.py:208-212` | Snow transition 10 m band (SNOW_LINE±5) too sharp** | User-flagged bug #2. The MapRange `From Min=20`, `From Max=30` makes snow go from 0→1 across a 10-m vertical strip — at AAA bar this reads as a hard line. Fix: widen to `From Min=15`, `From Max=35` or add Voronoi noise for break-up.

6. **P0 | `scripts/render_aaa_v8_mountain.py:158` | PBR `mapping.Scale=(4,4,4)` for all 5 materials at 320 m plane** | The plane is 320 m wide and the mapping is UV-based, so a "Scale=4" means texture tiles 4× across the UV ([0,1]), i.e. each tile = 80 m. That makes 1 m² rock at 80 m of terrain. User-flagged bug #4. AAA scale should be ~2 m / tile = Scale=160. Fix: per-material scale, snow/sand at 100, grass at 80, rock at 40, dirt at 80.

7. **P1 | `veilbreakers_terrain/handlers/atmospheric_volumes.py` | `optional_channels=("canopy_density",)` is a phantom optional** | No production writer for `canopy_density` exists anywhere (grep `produces_channels=*canopy_density*` and `stack.set("canopy_density"` both return 0 hits). The optional read silently degrades to None. Either delete the optional decl or wire `canopy_density` production into `pass_procedural_grass` from grass density × tree exclusion.

8. **P1 | `veilbreakers_terrain/handlers/terrain_pipeline.py:236-494` (pass-sequence scan)** | 5 registered passes remain unscheduled in every default sequence:
   - `glacial` (dead twin of `pass_glacial` per B15-P1-35) — safe to delete the legacy registration in `terrain_geology_validator.py:703-705`.
   - `macro_world` (legacy alias; `pass_generate_low_freq_hmap` is the canonical equivalent) — verify nothing reads via `state.controller.run_pass("macro_world", ...)` then drop.
   - `materials_v2_volcanic` (only fires when `include_lava=True` requires explicit sequence variant per B15-P1-38) — wire `pass_sequence.append("materials_v2_volcanic" if include_lava else "materials_v2")`.
   - `snow_line` (Bundle A baseline of `snow_line_factor` per B15-P1-39) — `pass_glacial` is the only current writer. Schedule before `pass_glacial` so two-stage baseline-refinement actually runs.
   - `waterfall_mist` (per B15-P1-41) — `mist_zone_mask`/`wet_surface_decal` permanently null. Schedule after `waterfalls`.

9. **P1 | `veilbreakers_terrain/handlers/terrain_pipeline.py:412` | `pass_horizon_lod` schedule gated on `not skip_scatter`** | Horizon LOD is independent of scatter — gating it on the same flag means tests/configs that disable scatter also lose far-terrain LOD. Fix: split out of the scatter group: `*(("pass_horizon_lod",) if has_scene_read else ())`.

10. **P1 | `output/verification/TERRAIN_BEST_PRACTICE_GUARDRAIL_REPORT.md:18-32` | 14 duplicate callable-name groups** | `from_dict` (9 modules), `to_dict` (23 modules), `add` (3 modules), `_to_float`, `_to_int`, `_vec3`, `_ndimage_callable`, `_scipy_distance_transform_edt`, `_scipy_uniform_filter`, `_apply_unity_scale`×3, `derive_pass_seed`×2 (terrain_pipeline + terrain_rng — actual canonical drift risk), `generate_terrain_bridge_mesh`×2 (`_bridge_mesh.py` + `_terrain_depth.py` — also drift risk), `priority_flood_d8`×3 (all in `_water_network.py`, likely 3 separate registrations of same body). The `derive_pass_seed` duplication is the highest-risk — two import paths can silently diverge.

11. **P2 | `veilbreakers_terrain/handlers/terrain_pass_dag.py:64` | `_lightweight_state_copy` toggles `_guard_active` via `object.__setattr__`** | The provenance fix is correct (re-records via `set()`) but the guard-disable still uses `object.__setattr__` rather than a context-manager guard, so any exception during the build leaves `_guard_active=False` on the partially-built stack. Wrap in try/finally.

12. **P2 | `veilbreakers_terrain/handlers/asset_generation.py:305` | `_BackendBase.generate` raises bare `NotImplementedError`** | No message, no exception class chain. If a caller hits this it crashes without context. Convert to `raise NotImplementedError(f"{type(self).__name__} must override generate()")`.

13. **P2 | `veilbreakers_terrain/handlers/environment_scatter.py:86` | `generate_billboard_impostor` shim raises `NotImplementedError`** | Comment cross-references "Phase 9C of the 12-phase plan" — Phase 9C status unclear in current STATE.md. If this is a deliberate stub, document the milestone in the docstring; otherwise it is a latent crash in scatter path.

---

## DEAD CODE / UNREFERENCED MODULES

- `veilbreakers_terrain/handlers/terrain_scatter_altitude_safety.py` (13 LOC). Self-described in the module docstring: `"# DEAD CODE: no callers found outside terrain_scatter_altitude_audit_linter tests — candidate for removal in next cleanup."` Confirmed: no production module imports it. Safe to delete; the canonical module is `terrain_scatter_altitude_audit_linter.py`.
- `veilbreakers_terrain/handlers/_bridge_mesh.py` (963 LOC). Only referenced by tests + `_terrain_depth.generate_terrain_bridge_mesh`. Per guardrail report duplicate-name group, this collides with `_terrain_depth.generate_terrain_bridge_mesh`. One of the two implementations is the legacy path and should be retired after confirming road/bridge tests cover both.
- `scripts/render_aaa_v8_mountain.py:390-393` — dead code blocks inside the bbox grounding loop (identity-matrix multiply + `if False`-short-circuited expression). Should be deleted in v9 patch.
- `scripts/render_aaa_v8_mountain.py:74-94` — unreferenced top-level `ANGLES` variable name collides with cameras placement loop `ANGLES` (re-defined L570). Not a bug, but confusing.

The 17-orphan claim from 2026-05-09 pickup state is STALE — only 5 orphans remain (per Wiring Gaps section below) and most are deliberate dead-twin registrations awaiting B15-P1-35/36 cleanup. None of the remaining orphans are blockers; all are tracked in the audit codex.

---

## WIRING GAPS

### Orphan Passes (registered but absent from `build_default_pass_sequence`)

| Pass name | Registered at | Status | Recommendation |
|---|---|---|---|
| `glacial` | `terrain_geology_validator.py:703-705` | Dead twin of `pass_glacial` (B15-P1-35) | DELETE legacy registration |
| `macro_world` | `terrain_pipeline.py:1874` | Legacy alias of `pass_generate_low_freq_hmap` | Verify zero non-default callers, then delete |
| `materials_v2_volcanic` | `terrain_materials_v2.py` | Intended for `include_lava=True` path; never wired (B15-P1-38) | Wire via ternary in `build_default_pass_sequence` |
| `snow_line` | `terrain_pipeline.py:1648` | Bundle A baseline (B15-P1-39); refinement pass `pass_glacial` overwrites alone | Schedule before `pass_glacial` |
| `waterfall_mist` | `terrain_waterfalls.py:2988` | Produces `mist_zone_mask`, `wet_surface_decal` (B15-P1-41); production tiles ship without wet-rock decals | Schedule after `waterfalls` |

### Unconsumed Channels (written but no production reader)

After cross-referencing write sites against `terrain_unity_export.py`, `terrain_delta_integrator.py`, `terrain_semantics.py` (declaration-only), and other handler reads, ~49 channels are written but consumed only by tests or declared-only in semantics:

Genuinely unread in production (semantic-decl only): `baked_cloud_shadow`, `cave_stalactite_length`, `cave_stalagmite_length`, `cliff_contour_spline`, `ecotone_blend_weights`, `grass_placement_records`, `horizon_elevation_angles`, `ice_factor`, `label_stack`, `lava_depth`, `lava_surface_mask`, `mist_fog_volume`, `mist_zone_mask`, `poi_mask`, `riverbed_caustics`, `road_mask`, `shadow_map`, `shoreline_blend`, `snow_coverage`, `stochastic_uv_mask`, `strata_mask`, `talus_displaced`, `talus_mask`, `terrain_brucks_weight`, `terrain_feature_mesh_specs`, `tidal_zone_label`, `unconformity_mask`, `wave_amplitude_per_vertex`, `wave_energy`, `wet_surface_decal`.

This is ~30 channels (not 108 as the 2026-05-09 pickup state claimed — that number is STALE — most likely fixed via the Phase D pre-work URP manifest schema in PRs #48/#49/#50).

Channels consumed by `terrain_unity_export.py` and thus shipped to Unity: `bedrock_height`, `biome_surface_feature_delta`, `coastline_delta`, `confluence_foam`, `convexity`, `delta_fan_direction`, `glacial_delta`, `grass_density_map`, `heightmap_raw_u16`, `lod_bias`, `material_weights`, `morphology_delta`, `pool_deepening_delta`, `river_mouth_mask`, `road_worn_path_delta`, `sediment_accumulation_at_base`, `sediment_height`, `water_depth_zone`, `wind_erosion_delta`. These are properly wired.

### Phantom Reads (consumed/required but no production writer)

Cross-grep of `requires_channels` / `optional_channels` / `stack.get(...)` returned the following channel names with no production producer:

- `canopy_density` — `pass_atmospheric_volumes` reads optionally; no producer (P1-NEW-7 above).
- `canopy_species_radius_m`, `species_density`, `vegetation_index`, `ndvi` — likely Unity-importer-side concepts surfaced as channel names; verify these aren't supposed to come from Python.
- `climate_zone`, `geology`, `hardness`, `limestone_proxy`, `material_zones`, `rock_mask`, `strata_depths`, `strata_layers` — likely intent-side context, not stack channels. Audit for confusion.
- `east_edge`, `west_edge`, `north_edge`, `south_edge` — these read inter-tile edges; should be sourced from `terrain_chunking` neighbor metadata, not stack. Confirm consumers route correctly.
- `forest_mask`, `hazard_zone`, `water_body`, `water_network`, `water_surface_elevation` — naming aliases; the canonical channels are `forest_density_mask`, `hazard_zones`, `water_surface_mask`, `water_surface_elevation_m`. Three callers use the unprefixed/unsuffixed name and silently get None.
- `height_delta` — used as both a generic delta noun in docstrings and as a real channel reference; spot-check needed.
- `height_m` — likely a documentation-only alias for `height`; verify no `stack.get("height_m")` exists in actual reads.
- `lava_source_mask` — Lava pass consumes via `getattr(intent.mask_stack, "lava_source_mask", None)` (terrain_pipeline.py L218); only authored from intent, no terrain-pass writer. Correct as-is.

---

## UNTRACKED DEBRIS (top-of-repo)

| Path | Size | Classification | Reason |
|---|---|---|---|
| `assets/` | 2.7 GB | GITIGNORE | Free PBR/HDRI/tree assets — large binary, regenerable via `scripts/fetch_ambientcg.py` and `scripts/fetch_polyhaven.py` (or from CC0 sources directly). Should NOT be committed; add `assets/` to `.gitignore`. |
| `vendor/BoatAttack-2.0.zip` | 789 MB | GITIGNORE (or DELETE after unpacking) | Boat Attack URP sample binary archive. Phase D pre-work decision per STATE.md: Boat Attack is a decision dep. Keep archive locally for installers; never commit. Add `vendor/` to `.gitignore`. |
| `vendor/crest-4.22.4.zip` | 188 MB | GITIGNORE | Crest 4.x archive. Same logic as Boat Attack. |
| `output/aaa_demo/` | 5.4 MB | GITIGNORE | Demo render outputs from `render_aaa_demo.py`. Pattern `output/aaa_*` already partially in .gitignore (lines 57-62 cover `output/aaa_node_v*` and `output/aaa_*_node_v1/`); add `output/aaa_demo/` + `output/aaa_v*/`. |
| `output/aaa_v2/` … `output/aaa_v8/` (7 dirs) | ~30 GB total | GITIGNORE | Render outputs from v2-v8 mountain scripts. Same pattern as above — extend `.gitignore` to `output/aaa_v*/`. |
| `scripts/render_aaa_demo.py` through `render_aaa_v8_mountain.py` (8 scripts) | ~12-15 KB ea | KEEP | These are progression of AAA render attempts; v8 is the active one. KEEP all in repo (small text, version-marker scripts useful for diff). Optionally MOVE `render_aaa_v2.py` through `v7` to `scripts/archive/` and keep only `render_aaa_v8_mountain.py` + new `render_aaa_v9_mountain.py` as the active rev. |
| `zero_assert_audit.py` | 3 KB | MOVE-TO-`scripts/audits/` | One-shot audit tool at repo root. Move to `scripts/audits/zero_assert_audit.py` or `scripts/diagnostic/zero_assert_audit.py` to keep root clean. |

**Critical .gitignore deltas** (additions needed):
```gitignore
assets/
vendor/
output/aaa_demo/
output/aaa_v*/
```
Without these, a casual `git add -A` would stage ~33 GB.

---

## V9 Bug Queue Verification

| Bug | Location | Current state | Confidence |
|---|---|---|---|
| 1. bbox grounding LOCAL→WORLD math | `scripts/render_aaa_v8_mountain.py:384-399` | NOT FIXED — L395 uses `corner[2]` from object-local `eval_obj.bound_box`; the dead code on L390 (`wz` calculation) and L393 (`if False`) are red herrings. Trees/rocks still float by `terrain_z + (object-local min_z)` instead of `terrain_z - (world min_z)`. | HIGH |
| 2. snow transition too sharp | `scripts/render_aaa_v8_mountain.py:208-212` | NOT FIXED — `MapRange` band is SNOW_LINE-5 to SNOW_LINE+5 (10 m vertical strip). Original v8 default; not softened. | HIGH |
| 3. water Volume Absorption | `scripts/render_aaa_v8_mountain.py:285-298` | NOT FIXED — Lake material has Glass+Glossy surface mix, NO `ShaderNodeVolumeAbsorption`. | HIGH |
| 4. PBR tile scale wrong | `scripts/render_aaa_v8_mountain.py:158` | NOT FIXED — All 5 materials share `mapping.Scale=(4,4,4)`. Plane is 320 m, UV=[0,1] → 80 m per texture tile. | HIGH |
| 5. drop coast_* photoscan rocks | `scripts/render_aaa_v8_mountain.py:420` | NOT FIXED — `ROCKS = [b ... if "rock" in b or "boulder" in b]` matches `coast_land_rocks_03.blend` because "rock" is a substring of "rocks". | HIGH |
| 6. ridge-noise mountains (user-flagged) | `scripts/render_aaa_v8_mountain.py:74-94` | NOT FIXED — Two Gaussian peaks max'd produce two domes, not ridge noise. `mountain_macro = np.maximum(peak_a, peak_b)` is not ridge construction. No `1 - abs(noise)` ridge term. | HIGH |

All 6 v9 known bugs are unfixed and visible in `scripts/render_aaa_v8_mountain.py`. A v9 script (or in-place fix to v8) is required before "AAA bar" claims hold.

---

## TODO/FIXME Hotspots

Grep over `veilbreakers_terrain/` returned 1 marker total — and that was inside a test file (`test_batch14_p1_export.py:153`) flagging "placeholder" strings to detect, not a TODO of work to do. No production-side TODO/FIXME/HACK/XXX/BUG markers exist in the package.

**Sub-finding (not in the 7 task buckets but worth flagging):** The absence of TODO markers in production source means the codex is the only system-of-record for work-to-do. If `docs/aaa-audit/*` is lost or rotated, there is no in-source bread-crumb trail for what's still open. Consider adding `# AUDIT(B15-P0-12): variant should default to anisotropic — see batch15 MASTER_AUDIT_BATCH15.md` style annotations on the 8 still-open items so future grep finds them.

Two latent NotImplementedError sites (production code, not in test/scripts):
- `veilbreakers_terrain/handlers/asset_generation.py:305` — `_BackendBase.generate` bare raise.
- `veilbreakers_terrain/handlers/environment_scatter.py:86` — `generate_billboard_impostor` shim conditional raise pending Phase 9C.

Both are documented and are not bugs per se, but they are the only "explicit stub" sites in production and worth listing alongside any V9 cleanup pass.

---

## Cross-cutting observations

- The Phase A+B+C+D-pre-work runs have closed almost all wiring blockers from the 2026-05-03 / 2026-05-04 codex; the remaining work is now CONTENT (V9 visual fixes) and CLEANUP (dead twins, debris .gitignore, B15-P0-12/B15-P1-03 small fixes).
- The Wave-5 fix landing `cliffs` + `karst` (in current uncommitted `terrain_pipeline.py` diff) successfully closes 4 of the historic top-of-orphan-list items in one chunk. That diff also adds vegetation_depth scheduling between materials_v2 and scatter_intelligent (PR-E).
- The current modified-but-uncommitted `terrain_pipeline.py` has a mojibake character ("�" at line 366) inside the `cliffs` insertion comment that should be cleaned before commit.
- `pass_horizon_lod` is unconditionally inside the scatter group — if `skip_scatter=True`, far-terrain LOD silently drops. Minor wiring tightening.
- `derive_pass_seed` exists in BOTH `terrain_pipeline.py` and `terrain_rng.py` per the guardrail report. The two implementations must stay byte-identical or determinism degrades silently.
