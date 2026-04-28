# M12 Deep Audit — Materials, Contracts, Decals & Remaining Handlers

**Date:** 2026-04-27
**Auditor:** Senior Tech Lead (Rockstar / Guerrilla Games standard)
**Files audited (13):**
- `veilbreakers_terrain/handlers/terrain_materials.py`
- `veilbreakers_terrain/handlers/terrain_materials_ext.py`
- `veilbreakers_terrain/handlers/procedural_materials.py`
- `veilbreakers_terrain/handlers/terrain_unity_export_contracts.py`
- `veilbreakers_terrain/handlers/terrain_path_contracts.py`
- `veilbreakers_terrain/handlers/terrain_protocol.py`
- `veilbreakers_terrain/handlers/terrain_blender_safety.py`
- `veilbreakers_terrain/handlers/terrain_decal_placement.py`
- `veilbreakers_terrain/handlers/terrain_destructibility_patches.py`
- `veilbreakers_terrain/handlers/terrain_macro_color.py`
- `veilbreakers_terrain/handlers/terrain_palette_extract.py`
- `veilbreakers_terrain/handlers/terrain_readability_bands.py`
- `veilbreakers_terrain/handlers/terrain_readability_semantic.py`

---

## Executive Summary

This sweep covers the materials layer, all validation/contract modules, and the five secondary-output handlers (decals, destructibility, macro color, readability). The findings are severe. The Unity export contract validator is entirely dead — it is never invoked at export time, meaning Unity receives unvalidated data on every single build. The Blender safety serialization lock does not enforce the contract it claims to. The protocol enforcement engine silently swallows Rule 2 violations in every automated/headless run. Four complete secondary-output systems (decals, destructibility, macro color, readability) compute results that are never written to disk and never exported to Unity. Two slope computation paths in the same material system produce different zone boundaries and are falsely claimed to be equivalent. The texel-density tier classifier assigns the wrong AAA tier to the highest-fidelity geometry in the project (triplanar cliff faces).

This sweep adds **14 P0 blockers**.

---

## P0 Findings

---

**M12-P0-1** | `terrain_unity_export_contracts.py` (entire module) | Unity export validation is dead code — never called at export time

**Evidence:**
```python
# terrain_unity_export_contracts.py defines:
def validate_bit_depth_contract(...) -> list[ValidationIssue]: ...
def validate_mesh_attributes_present(...) -> list[ValidationIssue]: ...
def validate_vertex_attributes_present(...) -> list[ValidationIssue]: ...
def write_export_manifest(...) -> None: ...

# Zero callers found across the entire codebase:
# grep -r "validate_bit_depth_contract\|validate_mesh_attributes_present\|write_export_manifest" handlers/
# → no matches
```

**AAA gap:** At Guerrilla/Rockstar, the export validator is the gate that prevents broken data from reaching the engine. It is a required step in the Perforce submit hook or pre-build script, not optional documentation. A terrain heightmap with wrong bit depth crashes the Unity terrain engine on load. This module existing and never being called is identical to it not existing.

**Fix:** Wire `validate_bit_depth_contract`, `validate_mesh_attributes_present`, and `validate_vertex_attributes_present` into `terrain_unity_exporter.py`'s export path. Call them before writing any file and raise on any `severity="hard"` issue. Call `write_export_manifest` at the end of every export run. **Estimated: 2 hours.**

---

**M12-P0-2** | `terrain_unity_export_contracts.py:259-260` | Splatmap encoding check silently skipped when `encoding` key is absent from metadata

**Evidence:**
```python
if kind == "splatmap":
    enc = meta.get("encoding", "")   # defaults to empty string, not None
    if enc and enc != contract.splatmap_encoding:   # empty string is falsy → check skipped
        issues.append(...)
```

**AAA gap:** An absent `encoding` key in metadata means the exporter forgot to write it — that is the failure case, not the pass case. The guard must treat a missing key as a violation (`enc is None or enc != contract.splatmap_encoding`). Unity's splatmap importer silently reinterprets channels when encoding is wrong, producing garbage material blending in-engine with no error message.

**Fix:**
```python
enc = meta.get("encoding")   # None if absent
if enc != contract.splatmap_encoding:   # catches None and wrong value
    issues.append(...)
```
Apply identically to `heightmap` and `terrain_normals` checks at lines 243-244 and 274-275. **Estimated: 30 minutes.**

---

**M12-P0-3** | `terrain_materials_ext.py:145` | Triplanar (cliff face) channels validated against terrain-base tier instead of hero tier — 2× texel density requirement silently accepted as passing

**Evidence:**
```python
# Line 144 comment: "Triplanar channels are cliff/rock-face → terrain tier minimum"
tier_min = _TERRAIN_MIN if ch.triplanar else _LOD1_MIN
# _TERRAIN_MIN = 512 px/m, _HERO_MIN = 1024 px/m, _LOD1_MIN = 256 px/m
```

**AAA gap:** Triplanar projection is specifically used on cliff faces and hero rock features — the highest-visual-fidelity geometry in the project. MicroSplat, UE5 Landscape, and every shipping AAA terrain system assigns hero tier (1024 px/m minimum) to triplanar surfaces precisely because they appear at close range in cinematic shots. The comment acknowledges this ("cliff/rock-face") and then specifies the wrong minimum anyway. A 512 px/m cliff face will look blurry in every close-range player interaction zone and every cinematics camera.

**Fix:**
```python
tier_min = _HERO_MIN if ch.triplanar else _TERRAIN_MIN
tier_name = "hero (1024 px/m)" if ch.triplanar else "terrain (512 px/m)"
```
**Estimated: 15 minutes.**

---

**M12-P0-4** | `terrain_materials.py:546` + `procedural_materials.py:742` | `"sand"` key collision — `TERRAIN_MATERIALS["sand"]` silently overrides `MATERIAL_LIBRARY["sand"]` with wrong base color and wrong PBR params

**Evidence:**
```python
# terrain_materials.py:546 — resolved first by _get_material_def():
"sand": {
    "base_color": (0.22, 0.18, 0.12, 1.0),  # too dark, brown-grey
    "roughness": 0.88,
    "detail_scale": 12.0,
}

# procedural_materials.py:742 — never reached when key "sand" is requested:
"sand": {
    "base_color": (0.28, 0.25, 0.18, 1.0),  # desaturated, correct for dark fantasy
    "roughness": 0.82,
    "detail_scale": 15.0,
}

# _get_material_def() checks TERRAIN_MATERIALS first, procedural_materials second.
# All callers requesting "sand" silently get TERRAIN_MATERIALS version.
```

**AAA gap:** Silent key collision between two material libraries creates a maintenance trap: editing the "authoritative" sand definition in procedural_materials.py has zero effect on production output. The two definitions differ not only in color (0.22 vs 0.28 R channel) but also in roughness and detail scale. Every desert/arid terrain biome is using the wrong sand color with no error, warning, or test failure. At any AAA studio, duplicate material keys across libraries would be caught by an asset name collision check in the build system.

**Fix:** Rename the terrain-specific entry to `"terrain_sand"` and update all `BIOME_PALETTES` / `BIOME_PALETTES_V2` references that specify `"sand"` to use `"terrain_sand"`. Add a startup assertion in `_get_material_def` that verifies no key appears in both libraries. **Estimated: 1 hour.**

---

**M12-P0-5** | `terrain_materials.py:3163` vs `terrain_materials.py:2661` | Two slope computation paths in the same module return incompatible units — `compute_world_splatmap_weights` uses degrees, `auto_assign_terrain_layers` uses radians — both claim to produce the same zone boundaries

**Evidence:**
```python
# compute_world_splatmap_weights (line 3163):
slope_map = compute_slope_map(hmap, cell_size=cell_size)
# compute_slope_map is aliased to compute_slope_map_degrees → returns [0, 90] degrees
# flat_deg and cliff_deg thresholds applied directly in degrees → correct

# auto_assign_terrain_layers (line 2661) — face-normal averaging:
nz_n = nz / length if length > 1e-9 else 1.0
dot = max(-1.0, min(1.0, nz_n))
vert_slopes.append(math.acos(dot))   # returns radians [0, π/2]
# Thresholds flat_deg/cliff_deg are then applied to these radian values as if they were degrees
# A 30° slope → 0.524 rad → compared against flat_deg=0.3 (treated as 0.3°) → wrong classification
```

**AAA gap:** The vertex-face-normal slope (radians) is used directly against degree thresholds. A slope of 30° (0.524 rad) would be classified as a cliff when compared against a `cliff_deg` threshold of 0.5 (interpreted as 0.5 radians, which is 28.6°). Zone boundaries are systematically wrong from `auto_assign_terrain_layers`. In production this means material boundaries in Blender do not match the splatmap boundaries exported to Unity — visible as material seams at ~30° slopes.

**Fix:** Either convert `vert_slopes` to degrees before threshold comparison:
```python
vert_slopes.append(math.degrees(math.acos(dot)))
```
or convert `flat_deg`/`cliff_deg` to radians for the face-normal path. Add a unit test that verifies both paths produce the same zone boundary for a synthetic 30° ramp. **Estimated: 1 hour.**

---

**M12-P0-6** | `terrain_protocol.py:135-141` | Rule 2 silently passes (warn + return) when `viewport_vantage is None` — every automated and headless run bypasses the player-view readability gate without opting out

**Evidence:**
```python
if vantage is None:
    _rule2_log.warning(
        "rule_2/soft: state.viewport_vantage is None — Rule 2 check skipped. ..."
    )
    return   # ← silent pass, not a ProtocolViolation
```

**AAA gap:** Rule 2 exists specifically to prevent shipping terrain that is unreadable from the player camera. The correct behavior when `viewport_vantage is None` is to raise `ProtocolViolation` unless the caller has explicitly passed `out_of_view_ok=True`. The current design means that any pipeline run that does not set `viewport_vantage` — including every CI build, every automated tile generation run, and every export-mode invocation — silently skips the readability gate. The `out_of_view_ok` escape hatch exists for exactly this use case and is correctly documented. The missing check is a pure logic error.

**Fix:**
```python
if vantage is None:
    raise ProtocolViolation(
        "Rule 2: state.viewport_vantage is None. "
        "Call terrain_viewport_sync.read_user_vantage() and assign to "
        "state.viewport_vantage, or pass out_of_view_ok=True for headless runs."
    )
```
**Estimated: 15 minutes.**

---

**M12-P0-7** | `terrain_blender_safety.py:369-371` | GLTF import serialization lock wraps only the log append — the actual `bpy.ops.import_scene.gltf()` call happens outside the lock in caller code, making the serialization contract unenforceable

**Evidence:**
```python
with _GLTF_IMPORT_LOCK:
    out.append(path)
    _GLTF_IMPORT_LOG.append(path)   # ← lock held only around list mutations
# bpy.ops call is documented as happening "inside the with-block in caller code"
# but the function returns the path — a caller can call bpy.ops before or after
```

**AAA gap:** The lock is held for microseconds while two lists are appended. The import itself — the operation that crashes Blender when two GLB files are loaded concurrently — runs entirely outside the lock. This is a classic check-then-act race condition. Any caller that schedules GLB imports on a thread pool will still execute the actual `bpy.ops` calls concurrently. The docstring comment "Real Blender would call bpy.ops...inside the with-block" is advisory documentation, not enforcement.

**Fix:** Restructure `import_gltf_serialized` to accept a callback and execute it inside the lock:
```python
def import_gltf_serialized(glb_paths, *, import_fn=None, require_exists=True):
    out = []
    for p in glb_paths:
        ...validate path...
        with _GLTF_IMPORT_LOCK:
            if import_fn is not None:
                import_fn(path)
            out.append(path)
            _GLTF_IMPORT_LOG.append(path)
    return out
```
Callers pass `import_fn=lambda p: bpy.ops.import_scene.gltf(filepath=str(p))`. **Estimated: 1 hour.**

---

**M12-P0-8** | `terrain_path_contracts.py` (entire module) | Path/road/bridge validation returns `list[dict[str, str]]` instead of `list[ValidationIssue]` — incompatible with validation system; never called from production

**Evidence:**
```python
def validate_path_network_contract(network: PathNetworkContract) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    ...
    issues.append({"code": "deep_water_crossing_requires_bridge", "message": ...})
    return issues
# All other validators in the codebase return list[ValidationIssue]
# grep -r "validate_path_network_contract" → zero production callers
```

**AAA gap:** Path/road/bridge contracts are the entire seam between procedural road generation and the terrain mesh. If the bridge clearance check, grade budget check, and water-crossing validation are never run, roads ship with physically wrong geometry (grades too steep for a cart, bridges without clearance, fords through 2m-deep rivers). The type mismatch also means this function cannot be plugged into any existing validation aggregation without a conversion wrapper.

**Fix:** Change return type to `list[ValidationIssue]` and replace dict literals with `ValidationIssue(code=..., severity="hard"|"soft", affected_feature=..., message=..., remediation=...)`. Wire `validate_path_network_contract` into the road generation handler's post-generate validation chain. **Estimated: 2 hours.**

---

**M12-P0-9** | `terrain_path_contracts.py:185` | Bridge clearance formula allows clearance below water depth for deep crossings

**Evidence:**
```python
if segment.bridge_clearance_m < max(0.75, segment.water_depth_m * 0.5):
    issues.append({"code": "bridge_clearance_too_low", ...})
# For water_depth_m = 4.0 m: minimum_clearance = max(0.75, 2.0) = 2.0 m
# But a 4.0 m deep river requires at least 4.0 m clearance for a navigable channel
# The formula permits clearance = water_depth * 0.5 = half the water depth
```

**AAA gap:** A bridge with clearance less than the water depth it crosses is partially submerged — visually and physically impossible. The clearance formula `water_depth * 0.5` produces a submerged bridge deck for any water depth above 1.5m. The correct minimum clearance is `max(flood_allowance, water_depth + freeboard)` where freeboard is typically 0.5–1.0m above the water surface. At absolute minimum, `clearance >= water_depth` must hold.

**Fix:**
```python
min_clearance = max(0.75, segment.water_depth_m + 0.5)  # water_depth + 0.5m freeboard
if segment.bridge_clearance_m < min_clearance:
    issues.append(...)
```
**Estimated: 15 minutes.**

---

**M12-P0-10** | `terrain_decal_placement.py` (entire module) | Decal density system computes results that are never exported to Unity; `register_bundle_j_decals_pass()` never called from production pipeline init

**Evidence:**
```python
# pass_decals() writes to stack.decal_density (dict)
# grep -r "register_bundle_j_decals_pass\|decal_density" handlers/ terrain_exporter.py → 
#   register_bundle_j_decals_pass: defined once, called zero times from pipeline init
#   decal_density: written by pass_decals, read nowhere in export pipeline
```

**AAA gap:** Decals are a primary visual fidelity differentiator for dark-fantasy terrain. Crack decals on cliff faces, moss patches in sheltered concavities, blood stains in combat zones — these are the micro-detail layer that separates AAA from indie. The full system is implemented correctly (Far Cry 6 reference is sound) and then completely disconnected from output. Unity never receives this data. Every terrain tile ships with no decal placement data regardless of how well the density maps are computed.

**Fix:** (1) Call `register_bundle_j_decals_pass()` from `terrain_pipeline.py`'s `_register_default_passes()`. (2) Add `decal_density` serialization to the Unity exporter — write each `DecalKind` layer as a separate 8-bit PNG or pack 4 channels per RGBA texture. (3) Add `GameplayZoneType.COMBAT.value` reference at line 227 instead of hardcoded `== 1`. **Estimated: 4 hours.**

---

**M12-P0-11** | `terrain_destructibility_patches.py` (entire module) | No pass registration, no export path — `export_destructibility_json()` never called; biome_id mode fallback produces wrong `material_id` when biome values include negatives

**Evidence:**
```python
# No register_bundle_q_*_pass() function exists in the module
# grep -r "detect_destructibility_patches\|export_destructibility_json" → zero production callers

# Fallback grid scan biome_id handling (lines 134-136):
block = stack.biome_id[r0:r1, c0:c1].ravel().astype(np.int64)
counts = np.bincount(block - block.min(), minlength=1)
material_id = int(block.min() + int(counts.argmax()))
# If biome_id contains [-1, 0, 1]: block.min()=-1, bincount([0,1,2])=[n,-1+mode]
# argmax() picks highest count index in shifted space, but +block.min() can give -1
# material_id = -1 is an invalid material reference in Unity
```

**AAA gap:** Destructibility is a Unity physics feature that requires per-cell material IDs to drive debris spawning and collision response. An invalid `material_id = -1` will silently use the wrong debris type or throw a null reference in the Unity physics engine. The module being entirely disconnected from the pipeline is the primary issue; the biome-ID bug is secondary but ensures even manual calls can produce corrupt output.

**Fix for biome bug:**
```python
block_pos = block - block.min()   # shift to non-negative
mode_shifted = int(counts.argmax())
material_id = int(block.min()) + mode_shifted
# Guard: clamp to valid range
material_id = max(0, material_id)
```
Register a pass and wire `export_destructibility_json` into the export pipeline. **Estimated: 3 hours.**

---

**M12-P0-12** | `terrain_macro_color.py:224-230` | `pass_macro_color` declares only `("height",)` as `consumed_channels` — biome_id, wetness, erosion_amount, deposition_amount, snow_line_factor are consumed but undeclared, breaking pipeline dependency ordering

**Evidence:**
```python
return PassResult(
    pass_name="macro_color",
    ...
    consumed_channels=("height",),   # ← only height declared
    produced_channels=("macro_color",),
    ...
)
# compute_macro_color() actually reads:
#   stack.get("biome_id"), stack.get("wetness"), stack.get("erosion_amount"),
#   stack.get("deposition_amount"), stack.get("snow_line_factor"),
#   stack.get("strata_cross_section")
```

**AAA gap:** The `TerrainPassController` uses `consumed_channels` to determine pass ordering. If `macro_color` declares it only needs `height`, the scheduler is free to run it before `wetness`, `erosion_amount`, or `snow_line_factor` passes complete. On a multi-threaded build this produces non-deterministic macro color output — the result depends on which passes happened to have completed before macro_color was dispatched. Identical intent produces different output on different machines.

**Fix:**
```python
consumed_channels=("height", "biome_id", "wetness", "erosion_amount",
                   "deposition_amount", "snow_line_factor", "strata_cross_section"),
```
Mark all as optional in the pass definition so the scheduler waits for them if present without failing if absent. **Estimated: 20 minutes.**

---

**M12-P0-13** | `terrain_macro_color.py` (`DARK_FANTASY_PALETTE` + export) | Palette covers only biome IDs 0–7; system has 14+ biomes — IDs 8–13 silently render as flat grey `(0.3, 0.3, 0.3)`; macro_color never exported to Unity

**Evidence:**
```python
DARK_FANTASY_PALETTE: Dict[int, Tuple[float, float, float]] = {
    0: (0.32, 0.30, 0.24),  # lowland_earth
    1: (0.22, 0.30, 0.18),  # forest
    2: (0.45, 0.42, 0.32),  # grassland
    3: (0.38, 0.34, 0.28),  # rocky_slope
    4: (0.50, 0.49, 0.47),  # highland_ash
    5: (0.82, 0.83, 0.88),  # snowcap
    6: (0.18, 0.22, 0.26),  # bog
    7: (0.28, 0.25, 0.20),  # scorched
}
# BIOME_PALETTES in terrain_materials.py maps 14+ named biomes to integer IDs
# Biome IDs 8-13 fall through to:
default_rgb = np.array(pal.get(DEFAULT_BIOME_ID, (0.3, 0.3, 0.3)), dtype=np.float64)
# → all unmapped biomes render as identical grey

# export path: macro_color written to stack.macro_color (numpy array)
# grep -r "macro_color" terrain_unity_exporter.py → no matches
```

**AAA gap:** A grey fallback for half the project's biomes is not a graceful degradation — it is a broken 2D LUT that makes every arid, volcanic, tundra, and dead-zone biome identical in the Unity shader. The macro_color 2D LUT is the primary biome identity signal for the terrain shader. Missing biomes produce large grey terrain patches with zero visual biome identity. Combined with never being exported, the entire Bundle K output is wasted compute.

**Fix:** (1) Extend `DARK_FANTASY_PALETTE` to cover all biome IDs present in `BIOME_PALETTES` (add entries 8–13 with appropriate dark-fantasy colors). (2) Add `macro_color` serialization to the Unity exporter — write as a 16-bit EXR or float PNG for the 2D LUT. (3) Add a startup assertion that `DARK_FANTASY_PALETTE.keys()` is a superset of all IDs in `BIOME_PALETTES.values()`. **Estimated: 2 hours.**

---

**M12-P0-14** | `terrain_readability_semantic.py:194-212` | Cliff silhouette connected-component labeling uses pure Python BFS with a Python list as a stack — O(n²) worst case, will timeout on production 1K×1K grids

**Evidence:**
```python
labels = np.zeros(cliff_mask.shape, dtype=np.int32)
r_count, c_count = cliff_mask.shape
for r0 in range(r_count):
    for c0 in range(c_count):
        if not cliff_mask[r0, c0] or labels[r0, c0] != 0:
            continue
        bfs: List[Tuple[int, int]] = [(r0, c0)]
        while bfs:
            r, c = bfs.pop()   # ← list used as stack (DFS, not BFS)
            if r < 0 or r >= r_count or ...:
                continue
            if not cliff_mask[r, c] or labels[r, c] != 0:
                continue
            labels[r, c] = comp_id
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    bfs.append((r + dr, c + dc))   # 8-connected, appends blindly
```

**AAA gap:** The BFS stack grows without bounds checking — every visited cell appends up to 8 neighbors before the bounds/visited check, meaning the Python list holds O(n) entries at peak. On a 1024×1024 heightmap with a large cliff region (common in dark-fantasy terrain), this produces millions of Python object allocations and a stack depth that causes memory pressure and runtimes measured in minutes, not seconds. Guerrilla's Horizon terrain validation runs in sub-second wallclock on equivalent grid sizes by using scipy.ndimage.label or numpy-vectorized flood fill. `scipy.ndimage.label` is already used elsewhere in this codebase (terrain_destructibility_patches.py:72) and is available.

**Fix:**
```python
try:
    from scipy.ndimage import label as _label
    struct8 = np.ones((3, 3), dtype=np.int32)   # 8-connected
    labels, _ = _label(cliff_mask, structure=struct8)
except ImportError:
    # keep Python fallback but add visited-check BEFORE appending to stack:
    if labels[r + dr, c + dc] == 0 and cliff_mask[r + dr, c + dc]:
        bfs.append((r + dr, c + dc))
```
**Estimated: 1 hour.**

---

## P0 Count Tally

**M12 sweep: 14 new P0 blockers.** Running total across all sweeps (A/D/E/F/H/I/J/K/L/M1-M12): **119 confirmed P0 blockers.**

Key cluster: Unity export validation is entirely dead (M12-P0-1/2), four complete output systems are disconnected from the export pipeline (M12-P0-10/11/12/13), and the protocol enforcement gate silently passes every automated run (M12-P0-6). These are not implementation gaps — they are wiring failures where working code produces zero production effect.
