# M9: Vegetation, L-System & Wildlife — Deep Dive Audit
**Date:** 2026-04-27
**Auditor:** Claude (AAA tech-lead standard)
**Files audited:**
- `veilbreakers_terrain/handlers/vegetation_lsystem.py`
- `veilbreakers_terrain/handlers/vegetation_system.py`
- `veilbreakers_terrain/handlers/terrain_assets.py`
- `veilbreakers_terrain/handlers/terrain_wildlife_zones.py`
- `veilbreakers_terrain/handlers/terrain_scatter_altitude_safety.py`
- `veilbreakers_terrain/handlers/terrain_scatter_altitude_audit_linter.py`

---

## Executive Summary

The L-system tree generation machinery is technically solid in isolation. The wildlife affinity system is reasonable. But the production pipeline wiring is broken at multiple critical junctions: the L-system trees are never generated with species-accurate types during scatter, the terrain_budget_enforcer enforces a 2,000-instance cap as "AAA spec" (it is not), the altitude safety system is a source linter with no runtime gate, and terrain_assets.py (the Bundle E scatter pass) does not feed the default pipeline at all. The vegetation system has been refactored but the deprecation chain still routes through `environment.py` with a hardcoded 2,000-instance ceiling. Wildlife zones are properly computed and exported to Unity. This audit adds 8 new P0 blockers.

---

## Critical Issues (P0)

---

**M9-P0-1** | `terrain_budget_enforcer.py:159` | `max_scatter_instances = 2000` is encoded as the "AAA spec" — it is the opposite of an AAA spec; it is a 97% density cap relative to industry standard

**Evidence:**
```python
# terrain_budget_enforcer.py:159
max_scatter_instances: int = 2000    # AAA spec: ≤2000 visible
# terrain_budget_enforcer.py:482
#   visible instance count (tree_instance_points + detail_density sum) ≤ 2000
```
The comment says "AAA spec" but Horizon Zero Dawn, Witcher 3, and Assassin's Creed all render 50,000–500,000 vegetation instances per km² via GPU instancing. Setting 2,000 as the enforced ceiling and labelling it "AAA spec" guarantees the budget enforcer will _reject_ any attempt to hit real AAA density. The enforcer actively runs after the scatter pass and will report violations if density is raised. This is not a soft warning; `scatter_over: bool` is set to `True` and propagates to the tile quality report.

**AAA gap:** Real AAA pipelines set instance budgets in the range of 50,000–500,000/km². The budget number 2,000 belongs to a mobile title, not a dark fantasy PC game. The enforcement prevents fixing density.

**Fix:** Change `max_scatter_instances` to 100,000 and update the comment. Remove the false "AAA spec" label. The budget enforcer should enforce VRAM and draw-call constraints, not a raw instance count. Estimated time: 1 hour (value change + downstream test fixes).

---

**M9-P0-2** | `environment.py:8406` | The only production caller of scatter still uses `max_veg_instances=2000` default

**Evidence:**
```python
# environment.py:8306-8406
#   max_veg_instances (int): Cap per biome. Default 2000.
...
"max_instances": params.get("max_veg_instances", 2000),
```
`environment.py` is the top-level entrypoint called by the Blender add-on to generate a tile. It passes `max_instances=2000` into `scatter_biome_vegetation`. Even if all other fixes were applied, the production call site caps output at 2,000 instances per biome. This is the same bug identified as L3-P0-2 in prior sweeps — it has not been fixed in `environment.py`.

**AAA gap:** Production tiles have a hardcoded instance ceiling that is 25x below the minimum acceptable density for a foreground forest biome.

**Fix:** Change the default to 100,000 and document the Unity GPU-instancing draw-call strategy. Time: 30 minutes.

---

**M9-P0-3** | `vegetation_lsystem.py` (entire file) | L-system trees are never used as the actual mesh type during production scatter — all biome species resolve to geometry-gen stubs

**Evidence:**
`vegetation_system.py:scatter_biome_vegetation` calls `_create_biome_vegetation_template` → `_mesh_bridge.resolve_generator("vegetation", vegetation_type)`. The biome species type strings from `BIOME_VEGETATION_SETS` are e.g. `"tree"` with style `"veil_healthy"`. The `_mesh_bridge` lookup resolves `"tree"` → `_lsystem_tree_generator(tree_type="oak", iterations=4)`. So oak L-system _is_ reachable for the generic `"tree"` type.

**However:** The vegetation system calls `_create_biome_vegetation_template(vegetation_type=p["type"], ...)` where `p["type"]` is the raw `type` field from `BIOME_VEGETATION_SETS` (e.g. `"tree"`, `"mushroom"`, `"fern"`, `"moss"`, `"vine"`, `"rock"`, `"gravestone"`, `"ember_plant"`, `"frost_lichen"`, `"tumbleweed"`, `"flower"`, `"crystal"`, `"root"`, `"bush"`). Only `"tree"`, `"dead_tree"`, `"pine_tree"`, `"tree_twisted"`, and `"tree_dead"` have L-system mesh-bridge entries. All other types — the majority of ground cover — fall through to `resolve_generator("prop", vegetation_type)`. If that also returns `None`, `_create_biome_vegetation_template` raises `ValueError` and the entire scatter materializer crashes silently or aborts that template. More critically, the biome style field (e.g. `"dark_pine"`, `"willow_hanging"`, `"charred_stump"`, `"mangrove_root"`) is **never passed to the L-system generator**. Every tree placement regardless of biome style resolves to `oak` grammar because the style is ignored in the `_mesh_bridge` lookup key. A willow-hanging cemetery tree generates oak geometry.

**AAA gap:** Rockstar/Guerrilla have species-accurate branching per tree type. Every tree style in VeilBreakers uses oak grammar. `dark_pine` should use the pine grammar; `willow_hanging` should use willow grammar; `charred_stump` should use the dead grammar.

**Fix:** In `_mesh_bridge.py`, add style-to-tree-type mapping so that tree style strings route to the correct grammar. In `_create_biome_vegetation_template`, pass both `type` and `style` so the mesh bridge can select the correct grammar. Estimated time: 4 hours.

---

**M9-P0-4** | `vegetation_lsystem.py:generate_lsystem_tree` (mesh output) + `vegetation_system.py:scatter_biome_vegetation` | L-system tree meshes have no UV coordinates — vegetation cannot be textured in Unity

**Evidence:**
```python
# vegetation_lsystem.py:branches_to_mesh (line ~858)
return {
    "vertices": vertices,
    "edges": edges,
    "faces": faces,
    "branch_depths": branch_depths,
    ...
}
```
`branches_to_mesh` generates positions and face indices but outputs **no UV coordinates**. The `generate_lsystem_tree` function does not call any UV projection function. The leaf card generator (`generate_leaf_cards`) creates face quads but also has no UV generation — vertices are raw 3D positions only.

When `scatter_biome_vegetation` calls `mesh_from_spec(spec, ...)` in Blender mode, the resulting Blender mesh object has no UV map. Unity imports this as an untextured mesh. All bark textures, leaf textures, and albedo maps will be missing from every L-system generated tree in the game.

**AAA gap:** Every AAA tree pipeline generates cylindrical UVs for bark and planar/spherical UVs for leaf cards. No UV = no texture = every tree is matte grey in Unity.

**Fix:** Add cylindrical UV generation to `branches_to_mesh` (map U = azimuth/2π around the branch ring, V = segment index / total segments). Add planar UV projection to `generate_leaf_cards`. Estimated time: 1 day.

---

**M9-P0-5** | `vegetation_system.py:scatter_biome_vegetation:1129` | `scatter_biome_vegetation` is deprecated and emits a `DeprecationWarning` but `environment.py:8406` still calls it — the replacement `handle_scatter_vegetation` is not wired

**Evidence:**
```python
# vegetation_system.py:1129-1133
warnings.warn(
    "scatter_biome_vegetation is deprecated; use handle_scatter_vegetation",
    DeprecationWarning,
    stacklevel=2,
)
```
```python
# environment.py:8406
"max_instances": params.get("max_veg_instances", 2000),
# (called via scatter_biome_vegetation)
```
The function that `environment.py` calls raises a `DeprecationWarning` in production. `handle_scatter_vegetation` does not appear anywhere in `environment.py` and is not wired into the default pipeline `pass_sequence`. The replacement does not exist as a standalone pipeline pass. All production vegetation scatter runs through the deprecated code path.

**AAA gap:** Deprecated code paths with active DeprecationWarnings in production build output are a P0 — they signal that a refactor was started and abandoned, and the new path is untested under production conditions.

**Fix:** Wire `handle_scatter_vegetation` into `environment.py` as the primary call site, or wire `scatter_intelligent` (Bundle E) into the default `pass_sequence` in `terrain_pipeline.py`. Pick one path and commit. Estimated time: 1 day.

---

**M9-P0-6** | `terrain_scatter_altitude_safety.py` | Altitude safety module is a **source linter only** — it contains zero runtime placement gates

**Evidence:**
```python
# terrain_scatter_altitude_safety.py:1-13 (entire file)
"""Deprecated compatibility alias for the scatter altitude audit linter.

# DEAD CODE: no callers found outside terrain_scatter_altitude_audit_linter tests
"""
from .terrain_scatter_altitude_audit_linter import (
    WORLD_HEIGHT_TRANSFORM_WARNING,
    audit_scatter_altitude_conversion,
)
```
```python
# terrain_scatter_altitude_audit_linter.py:9
# This is intentionally a source linter, not a runtime gate.
```
The module `terrain_scatter_altitude_safety.py` is a dead-code shim. The underlying `terrain_scatter_altitude_audit_linter.py` is a regex-based source scanner, not a runtime constraint. Neither module gates or modifies scatter placement coordinates at runtime.

The altitude safety system is documentation, not enforcement. The `audit_scatter_altitude_conversion` function scans Python source text — it does not validate placement positions, does not reject out-of-bounds instances, and is not called from any scatter pass.

**AAA gap:** Real AAA pipelines enforce altitude constraints at runtime as part of scatter placement — instances outside valid altitude bands are rejected before writing to the tile. The existing system only warns developers looking at source code.

**Fix:** Implement a runtime altitude gate in `pass_scatter_intelligent` (terrain_assets.py) that compares each placement's world Z against `rule.min_altitude_m` / `rule.max_altitude_m` and rejects violators. The existing `compute_viability` already has altitude bounds — verify they are correctly applied in metres, not normalised [0,1]. The linter remains useful for CI but cannot replace the runtime gate. Estimated time: 4 hours.

---

**M9-P0-7** | `terrain_wildlife_zones.py:pass_wildlife_zones` | Wildlife zone pass is never in the default `pass_sequence` — no wildlife data on any production tile

**Evidence:**
```python
# terrain_pipeline.py:559-567
if pass_sequence is None:
    pass_sequence = [
        "pass_generate_low_freq_hmap",
        "terrain_labels",
        "structural_masks",
        "pass_generate_high_freq_detail",
        "pass_composite_hmap",
        "validation_minimal",
    ]
```
The default `pass_sequence` has 6 entries. `wildlife_zones` is not one of them. Bundle J is registered separately via `register_bundle_j_passes()`, and `terrain_master_registrar.py:229` lists it as `("J", ...)` but the master registrar itself must be called explicitly. No caller in `environment.py` or the default pipeline invokes `register_bundle_j_passes()` or adds `"wildlife_zones"` to the sequence.

`terrain_unity_export.py:1387` calls `_wildlife_zones_json(stack)` and writes `wildlife_zones.json` to the export bundle — but `stack.wildlife_affinity` will be `None` on every production tile because the pass never ran, so the exported JSON will always be `{"schema_version": "1.0", "volumes": []}`.

**AAA gap:** In AC:Valhalla, Witcher 3, and RDR2, wildlife spawn zones are authored per-biome during world-build time and shipped to the game engine as part of each tile's metadata. An empty `wildlife_zones.json` on every tile means no data-driven wildlife spawning is possible.

**Fix:** Add `"wildlife_zones"` to the default `pass_sequence` after `"structural_masks"`. Ensure `register_bundle_j_wildlife_zones_pass()` is called during pipeline initialization. Estimated time: 2 hours.

---

**M9-P0-8** | `vegetation_system.py:load_mesh_library:1527` + `build_foliage_placement_manifest` | All mesh library entries default `lod_meshes=[]` and `physics_collider="none"` — LOD and collision are never set by the production path

**Evidence:**
```python
# vegetation_system.py:1522-1527
entry.setdefault("lod_meshes", [])
entry.setdefault("atlas_path", None)
entry.setdefault("unity_render_mode", "terrain_tree")
entry.setdefault("forestpack_reference_layer", f"FP_REF_{key}")
entry.setdefault("wind_color_baked", False)
entry.setdefault("physics_collider", "none")
```
The foliage manifest emitter defaults all mesh library entries to `lod_meshes=[]` (empty — no LOD meshes defined), `physics_collider="none"` (no collision mesh), and `wind_color_baked=False` (wind animation not baked). These are `setdefault` calls — if the mesh library JSON file does not explicitly define these fields, they remain at their defaults. No pipeline step populates these fields from the L-system generator output or from `bake_wind_vertex_colors`.

This means the foliage manifest shipped to Unity has: no LOD chain for any tree, no collision capsule/box on any tree, and no wind vertex color data. Trees in Unity will have no collision (player and physics objects pass through them), no LOD (full L-system mesh at all distances), and no wind animation.

**AAA gap:** Every single tree in a shipped AAA game has a LOD chain (typically 3–4 LODs + billboard), a simplified physics collider, and wind animation vertex data. Zero of these three are populated in production output.

**Fix:** After L-system mesh generation, call `bake_wind_vertex_colors` and write `wind_color_baked=True` into the manifest entry. Add an auto-generated simplified sphere/capsule collider entry. Wire `generate_billboard_impostor` as the LOD3 entry in `lod_meshes`. Estimated time: 2 days.

---

## Warnings (P1-equivalent)

### WR-01: `terrain_wildlife_zones.py:377` — `populate_by_pass` uses a string key but the `TerrainMaskStack` `populated_by_pass` dict is set directly without checking for existing entries

**File:** `terrain_wildlife_zones.py:373-374`
**Issue:** `stack.wildlife_affinity.update(affinity_maps)` unconditionally overwrites any previously computed affinity data. If the pass is called twice (e.g. with different rule sets across a re-run), the second call clobbers the first without merging. The `update` call on line 373 in `compute_wildlife_affinity` and again on line 438-439 in `pass_wildlife_zones` means the same channel is written twice in a single pass execution, which is wasteful but harmless. However the overwrite-without-merge pattern is fragile.

**Fix:** Replace `stack.wildlife_affinity.update(affinity_maps)` with a merge that takes the element-wise max of overlapping species channels: `stack.wildlife_affinity[species] = np.maximum(existing, new_arr)`.

---

### WR-02: `vegetation_system.py:1727` — `color_variation_seed` uses `random.randint` inside the manifest loop, breaking determinism

**File:** `vegetation_system.py:1727`
**Issue:**
```python
"color_variation_seed": int(p.get("color_variation_seed", random.randint(0, 2**31 - 1))),
```
When `color_variation_seed` is not already set on the placement (it never is — nothing in `compute_vegetation_placement` sets it), this falls back to `random.randint(0, 2**31-1)` using the module-level Python `random` state. This is not seeded by `seed` or `derive_pass_seed`, so every manifest re-run produces different color variation seeds. The foliage will visibly change appearance between pipeline re-runs even with the same input, breaking deterministic tile generation.

**Fix:** Derive the color seed from the instance's world position and the tile seed: `color_variation_seed = hash((tile_seed, wx, wy)) & 0x7FFFFFFF`.

---

### WR-03: `terrain_scatter_altitude_safety.py:1` — Dead-code shim with self-admitted "no callers" in module docstring

**File:** `terrain_scatter_altitude_safety.py:1-13`
**Issue:** The module docstring says "DEAD CODE: no callers found outside terrain_scatter_altitude_audit_linter tests". Dead code modules pollute the namespace, can be accidentally imported, and signal incomplete refactoring. This shim has existed long enough to be noted in the docstring.

**Fix:** Remove `terrain_scatter_altitude_safety.py`. Update any test imports to point directly to `terrain_scatter_altitude_audit_linter`. Estimated time: 30 minutes.

---

### WR-04: `vegetation_lsystem.py:expand_lsystem` — No grammar validation before expansion; iteration cap bypassed for non-`generate_lsystem_tree` callers

**File:** `vegetation_lsystem.py:200-280`
**Issue:** `expand_lsystem` accepts any `axiom`/`rules`/`iterations` without validation. The iteration cap (max 6, added in `generate_lsystem_tree:1089`) only applies when calling through `generate_lsystem_tree`. Direct calls to `expand_lsystem` can pass `iterations=8` or higher, producing strings up to ~8 million characters for `oak` grammar, which makes `interpret_lsystem` run for minutes. This is a latent DoS for any caller that bypasses `generate_lsystem_tree`.

**Fix:** Add `iterations = max(1, min(iterations, 6))` at the top of `expand_lsystem`, or document that the cap is the caller's responsibility and enforce it in `expand_lsystem` with a hard `ValueError` above the threshold.

---

## Info

### IN-01: `vegetation_system.py:scatter_biome_vegetation:1129` — DeprecationWarning fires in production every tile generation

Logs will contain deprecation noise on every tile. Suppressing warnings is not the fix — migrating the caller is.

---

### IN-02: `terrain_wildlife_zones.py` — Only 3 species in `DEFAULT_WILDLIFE_RULES` (deer, wolf, eagle)

For a dark fantasy world like VeilBreakers this is far too sparse. AAA games define 15–40 species with biome-specific variants. The default rules also have no dark-fantasy-specific species (corrupted beasts, banshees, wyverns). The system is architected to support more; the data just hasn't been authored.

---

### IN-03: `terrain_assets.py:terrain_assets.py` is actually `terrain_assets.py` which is misnamed as "Bundle E — Scatter Intelligence"

The module docstring says "Bundle E — Scatter Intelligence" but the file is `terrain_assets.py`. Any developer looking for the scatter logic will search for `terrain_assets` and find scatter; any developer looking for asset management will not find what they expect. This naming confusion has caused at least one prior audit sweep to mis-locate scatter logic.

---

### IN-04: `vegetation_lsystem.py:generate_lsystem_tree:1088-1089` — Iteration cap comment says "was 8" but oak at 6 iterations is ~290K verts (per comment) — needs profiling verification

The comment claims "6 iterations gives AAA-quality detail (~290K verts) while remaining real-time viable." 290,000 vertices per tree instance, with 2,000 instances per tile, is 580 million vertices. This cannot be real-time viable. The figure likely refers to a single hero tree at full detail, not scatter instances. The LOD system should reduce this for scatter placement but the comment is misleading.

---

## P0 Count Tally

**M9 adds 8 new P0 blockers: M9-P0-1 through M9-P0-8.**

Running total across all sweeps: 105 (prior) + 8 (M9) = **113 confirmed P0 blockers**.

Breakdown by module:
| File | P0s this sweep |
|------|----------------|
| `terrain_budget_enforcer.py` | 1 (M9-P0-1) |
| `environment.py` | 1 (M9-P0-2) |
| `vegetation_lsystem.py` | 2 (M9-P0-3, M9-P0-4) |
| `vegetation_system.py` | 2 (M9-P0-5, M9-P0-8) |
| `terrain_scatter_altitude_safety.py` | 1 (M9-P0-6) |
| `terrain_wildlife_zones.py` + `terrain_pipeline.py` | 1 (M9-P0-7) |
