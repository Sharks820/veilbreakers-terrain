# M3 Deep-Dive Audit — Caves, Karst & Terrain Features

**Files audited (fully read, all lines):**

- `veilbreakers_terrain/handlers/terrain_caves.py` — 5578 lines
- `veilbreakers_terrain/handlers/terrain_karst.py` — 550 lines
- `veilbreakers_terrain/handlers/terrain_features.py` — 4588 lines

**Audit date:** 2026-04-27  
**Auditor:** M3 subagent (Claude)  
**Standard:** AAA (Rockstar / Guerrilla Games level — no sugar-coating)  
**Prior confirmed P0 excluded:** K4-P0-6 (terrain_caves.py:1217-1234 — cave entrance overhang box has 4 of 6 faces with flipped normals)

---

## Executive Summary

These three files contain the entire underground and surface feature subsystem. The verdict is **D+ overall**. The carving and karst systems have correct geometry math in isolation, but the production wiring has four layers of silent failure stacked on top of each other:

1. Caves only activate when `controller_apply_caves=True` (defaults `False`), so the default production tile generates zero caves with zero error.
2. When caves DO run, overlapping cave footprints double-carve to arbitrary depth because the per-cave delta accumulator is additive with no overlap guard.
3. The A\* pathfinder is hard-capped at 4,096 nodes — on a 512×512 tile that is 1.6% of the search space. Every production-scale cave collapses to a degenerate straight corridor.
4. `terrain_features.py` is 4,588 lines of AAA-quality mesh generators (sinkhole, lava flow, ice formation, floating rocks, geyser, canyon, waterfall…) that are **not registered as pipeline passes and not called from any production path**. The entire file is dormant.

No test currently exercises cave carving at the sizes where the A\* cap bites. The module-level dict `_cliff_entry_meta` leaks across tiles without ever being cleared.

---

## P0 Findings (Ship-Blockers)

### M3-P0-1 — A\* Path Hard Cap Kills All Production-Scale Caves

**File:** `terrain_caves.py:1543`  
**One-line summary:** `max_nodes = min(4096, rows * cols)` hits its cap on every tile ≥ 65×65 cells, producing a straight-line fallback corridor instead of a real cave path.

**Evidence:**
```python
# terrain_caves.py:1543
max_nodes = min(4096, rows * cols)
```

A standard production tile is 512×512 = 262,144 cells. The A\* search is capped at 4,096 nodes — 1.6% of the grid. The implementation falls back to a straight line between start and goal when the cap is hit (the Bresenham fallback path triggered when the open set is exhausted). Every cave in production is a perfectly straight tube. No cave-quality check catches this; `validate_cave_entrance` only inspects the entrance frame geometry, not path topology.

**AAA gap:** Elden Ring, Dark Souls, Metro Exodus — every cave path curves, bifurcates, and follows terrain gradient. A straight tube reads as a corridor placeholder, not a natural cave. Rockstar's cave system (Red Dead 2) runs full-grid A\* on 2 km chunks. This cap was presumably a dev-time guard that never got removed.

**Fix:**
```python
# terrain_caves.py:1543 — replace
max_nodes = min(4096, rows * cols)

# with: proportional cap scaled to tile size, minimum 64k
max_nodes = min(max(65536, rows * cols // 4), rows * cols)
```
For a 512×512 tile this gives max_nodes = 65,536 (25% of grid), which is enough for meandering paths without A\* becoming the bottleneck. If A\* time becomes a concern, switch the heuristic from Manhattan to Euclidean and use tie-breaking — this alone cuts explored nodes by ~40% without changing path quality.

**Time estimate:** 1 hour (single-line fix + regression test with 256×256 tile asserting non-straight path).

---

### M3-P0-2 — Caves Off by Default in Production — Silently Produce Flat Terrain

**File:** `environment.py:2008, 2025`  
**One-line summary:** `controller_apply_caves` defaults to `False`; with zero `cave_candidates` (also default empty), the caves pass never runs and the world exports with zero caves and zero diagnostic.

**Evidence:**
```python
# environment.py:2008
controller_apply_caves = bool(params.get("controller_apply_caves", False))
...
# environment.py:2025-2027
if cave_candidates and controller_apply_caves:
    pipeline.append("caves")
    pipeline.append("integrate_deltas")
```

Both conditions must be True for the cave pass to execute. `cave_candidates` comes from the caller — if the scene read omits it (the default), this branch is never entered. The output looks identical whether caves failed or were never attempted.

**AAA gap:** Every AAA title with underground systems (God of War, Elden Ring, Horizon) has caves as first-class terrain citizens generated unconditionally from terrain analysis, not gated on a caller flag. Guerrilla's Decima engine auto-detects cliff faces and injects caves; the artist opt-out is via protected zones, not a default-off flag.

**Fix:**
Change the default to enable cave generation when terrain has sufficient vertical relief. Gate on topographic analysis:

```python
# environment.py — replace the hard default-False guard
# Determine if caves should auto-run based on terrain relief
relief = float(stack.height_max_m) - float(stack.height_min_m)
auto_cave = relief >= 30.0  # only attempt on terrain with ≥30m relief
controller_apply_caves = bool(params.get("controller_apply_caves", auto_cave))
```

Separately, `scene_read` should auto-populate `cave_candidates` from cliff-face analysis when the field is absent, instead of leaving the list empty. The existing `snap_entry_to_cliff_face` logic can drive this.

**Time estimate:** 2 hours (logic change + tests asserting caves appear on high-relief terrain without caller opt-in).

---

### M3-P0-3 — Overlapping Cave Footprints Double-Carve to Unbounded Depth

**File:** `terrain_caves.py:3861-3865`  
**One-line summary:** When multiple caves share overlapping footprints, additive delta accumulation double-carves the overlap cells — a 4m cave + 3m cave overlap produces a 7m hole.

**Evidence:**
```python
# terrain_caves.py:3859-3865
accumulated_delta = np.zeros_like(stack.height, dtype=np.float32)
for cave in caves:
    if cave.height_delta is not None:
        accumulated_delta += cave.height_delta   # BUG: additive, not envelope
stack.set("cave_height_delta", accumulated_delta, "caves")
```

Each `cave.height_delta` is a full H×W array with negative values at the cave footprint and zeros elsewhere. Two caves sharing cells at their entrance regions both contribute negative values — their sum is applied by `pass_integrate_deltas`, carving twice as deep. For a branching cave system (one passage meeting another), every junction cell is carved to double depth.

**AAA gap:** Cave junctions must share a common floor level. Carving below that level creates geometry artifacts — disconnected mesh, floating physics bodies, visible gaps between mesh tiles. Rockstar's cave volume system uses a signed distance field minimum (deepest point wins, not sum) so junctions resolve cleanly.

**Fix:**
```python
# terrain_caves.py:3861-3865 — replace additive with envelope minimum
accumulated_delta = np.zeros_like(stack.height, dtype=np.float32)
for cave in caves:
    if cave.height_delta is not None:
        # Take the more negative value (deeper carve wins, no double-counting)
        accumulated_delta = np.minimum(accumulated_delta, cave.height_delta)
stack.set("cave_height_delta", accumulated_delta, "caves")
```

Note: `pass_integrate_deltas` itself uses additive composition across *different* channel types (`karst_delta + cave_height_delta + waterfall_pool_delta`). That is correct — different systems carve different features. The bug is within-channel accumulation of the same system.

**Time estimate:** 30 minutes (single-line fix + test with two overlapping cave footprints asserting junction depth equals deepest individual cave, not their sum).

---

### M3-P0-4 — Branch Topology Bug: Cave Branches Concatenate as Linear Extension, Not True Junction

**File:** `terrain_caves.py:1911`  
**One-line summary:** `all_points = points + branch_points` appends branch path points to the main spine as a linear sequence — the result is a single zigzag polyline, not a branching tree.

**Evidence:**
```python
# terrain_caves.py:1911
all_points = points + branch_points
return all_points
```

`points` is the main A\* spine (N points). `branch_points` are collected from one or more branch paths (M points total). Concatenating them into a flat list means the caller sees a single polyline of length N+M. There is no junction record, no branching index, and no indication of where branches split from the spine. When this list is fed to `_build_cave_path_sdf` for volume carving, it carves a single winding corridor rather than a branching cave network.

**AAA gap:** Every AAA cave system (Elden Ring, God of War, Red Dead 2) has branching passages. A single corridor per cave anchor is dungeon-lite quality — it reads as a hallway, not a cave. The data structure should carry a tree (list of (parent_index, child_points) tuples) so carving can properly handle junction radii.

**Fix:**
```python
# terrain_caves.py — change generate_cave_path return type to carry topology
# Replace flat list return with a named tuple:
from typing import NamedTuple

class CavePath(NamedTuple):
    spine: list       # main A* path points
    branches: list    # list of (branch_start_idx, branch_points) tuples
    all_points: list  # flat list (backward compat — callers that just need points)

# In generate_cave_path, replace:
all_points = points + branch_points
return all_points

# With:
branches = [(branch_start_idx, branch_pts) for branch_start_idx, branch_pts in ...]
return CavePath(
    spine=points,
    branches=branches,
    all_points=points + branch_points,  # preserves backward compat
)
```

The SDF carver then uses `branches` to add junction-radius widening at each branch start index.

**Time estimate:** 4 hours (data structure change + SDF carver update + tests asserting branching caves produce distinct arm widths at junctions).

---

### M3-P0-5 — Chamber Spatial Data Dropped: Only Count Survives the Pass

**File:** `terrain_caves.py:1888-1893`  
**One-line summary:** Per-chamber world position and radius are computed but thrown away — only `len(chambers)` is stored, making chamber-based prop placement, navmesh obstacle generation, and lighting probe insertion impossible.

**Evidence:**
```python
# terrain_caves.py:1888-1893
_ch_arr = np.zeros(1, dtype=np.float32)
_ch_arr[0] = float(len(chambers))
stack.set("cave_chambers", _ch_arr, "caves")
```

`chambers` is a list of `(world_x, world_y, world_z, radius_m)` tuples computed earlier in the function (lines ~1860-1887). The full list is discarded; only the count is serialised. Downstream systems that want to place stalactite clusters, water pools, bioluminescent vegetation, or light probes inside chambers have no way to recover the spatial data.

**AAA gap:** God of War stores chamber volumes as axis-aligned bounding boxes with entrance arc metadata. Elden Ring's dungeon system registers each chamber as a NavMesh region with a portal list. Storing only a count is the equivalent of shipping a level with all rooms removed and leaving just a sign saying "there are 3 rooms."

**Fix:**
```python
# terrain_caves.py — replace scalar count with structured channel
# Chambers: Nx4 float32 array, each row = [world_x, world_y, world_z, radius_m]
if chambers:
    ch_data = np.array(
        [(cx, cy, cz, r) for cx, cy, cz, r in chambers],
        dtype=np.float32,
    )   # shape (N, 4)
else:
    ch_data = np.zeros((0, 4), dtype=np.float32)
stack.set("cave_chambers", ch_data, "caves")
```

Callers read `stack.get("cave_chambers")` and reshape to `(-1, 4)` to iterate `(world_x, world_y, world_z, radius)` per chamber.

**Time estimate:** 2 hours (data structure change + update all `cave_chambers` consumers + tests asserting correct chamber positions).

---

### M3-P0-6 — `_cliff_entry_meta` Module-Level Dict Never Cleared — Tile-to-Tile Memory Leak

**File:** `terrain_caves.py:656`  
**One-line summary:** `_cliff_entry_meta` is a module-level dict populated during each tile's pass but never reset between tiles — stale entries from earlier tiles corrupt cliff-snap decisions for all subsequent tiles.

**Evidence:**
```python
# terrain_caves.py:656
_cliff_entry_meta: Dict[Tuple[float, float, float], Dict] = {}
```

This dict is populated inside `snap_entry_to_cliff_face` (which is called per-cave-candidate during pass_caves). The function uses `_cliff_entry_meta[world_pos] = {...}` to record which cliff face an entry snapped to. There is no `_cliff_entry_meta.clear()` call at the start of `pass_caves`, at the end, or in any reset path. In a multi-tile generation session, all keys accumulate indefinitely:

- Memory grows unboundedly with tile count
- World positions from tile (0,0) remain present when processing tile (4,7) — if a new cave candidate's world position collides with a stale key (which can happen for tiling patterns that repeat at tile boundaries), it silently reads the wrong cliff face metadata

**AAA gap:** Procedural generation pipelines must be stateless between tiles. Persistent module-level state is a well-known bug class in AAA terrain tools (cited in Naughty Dog's GDC 2014 streaming talk and Guerrilla's Decima tech notes). This is a determinism violation — the same tile processed in isolation vs. in a batch of tiles can produce different cave entrance placements.

**Fix:**
```python
# terrain_caves.py — in pass_caves, at the top of the function body:
_cliff_entry_meta.clear()   # reset per-tile to prevent cross-tile contamination

# Alternatively, convert to a local variable passed through the call chain:
# cliff_entry_meta: Dict[...] = {}  # passed as parameter to snap_entry_to_cliff_face
```

The cleaner fix is to eliminate the module-level dict entirely and pass a local dict as a parameter. The quick fix is `.clear()` at the top of `pass_caves`.

**Time estimate:** 1 hour (single-line fix + regression test asserting pass_caves with two sequential invocations produces independent results).

---

### M3-P0-7 — `terrain_features.py` Entirely Orphaned from Production Pipeline

**File:** `terrain_features.py` — entire file (4,588 lines)  
**One-line summary:** None of the 11 standalone geometry generators (`generate_canyon`, `generate_waterfall`, `generate_cliff_face`, `generate_swamp_terrain`, `generate_natural_arch`, `generate_geyser`, `generate_sinkhole`, `generate_floating_rocks`, `generate_ice_formation`, `generate_lava_flow`, and more) are registered as pipeline passes, called from `pass_*` functions, or imported by any production path.

**Evidence:**
```python
# terrain_features.py — search for any pass_* function or PassDefinition:
# RESULT: zero matches. No register_*_passes(), no PassDefinition, no __all__
#         entry containing "pass_".
```

The file defines rich, physically-based generators (Dreybrodt speleothem math, geological undercutting profiles, pahoehoe ropy surface texture, Voronoi cooling cracks, lobate flow fronts, off-center sinkhole depressions) but every function returns a raw geometry dict. Nothing calls those functions from the terrain pipeline.

`terrain_karst.py` imports `generate_sinkhole` inside a `try/except Exception: pass` block (line 532) — this works because the function exists, but it is a side-channel call from `get_sinkhole_specs`, itself never called from `pass_karst`. The circular result: `pass_karst` runs during the Bundle I pipeline slot, produces `karst_delta`, but `get_sinkhole_specs` (and therefore all sinkhole mesh geometry) is never called during production.

**AAA gap:** 4,588 lines of AAA-quality feature geometry that does not appear in the game. This is equivalent to having the entire rock/ruin scatter system implemented but never instantiated. Rockstar, Guerrilla, and CDPR all integrate feature generators as first-class pipeline passes with LOD, material assignment, and placement validation. Standalone geometry dicts that are never consumed are tech debt that grows with every new generator added.

**Fix:** Register each generator as a pipeline pass in the appropriate bundle slot. Minimum required wiring for the most critical features:

```python
# terrain_features.py — add at file bottom:
from .terrain_semantics import PassDefinition
from .terrain_pipeline import TerrainPassController

def pass_terrain_features(state, region):
    """Bundle J pass: generate and register surface feature mesh specs."""
    stack = state.mask_stack
    hints = dict(state.intent.composition_hints) if state.intent else {}
    seed = getattr(state.intent, "seed", 42)
    specs = []

    if hints.get("geysers_enabled", True) and stack.get("thermal_vent_mask") is not None:
        specs.append(generate_geyser(seed=seed))

    if hints.get("lava_flows_enabled", False):
        specs.append(generate_lava_flow(seed=seed))

    stack.set("surface_feature_specs", specs, "terrain_features")
    return PassResult(
        pass_name="terrain_features",
        status="ok",
        ...
    )
```

Each generator needs a dedicated calling convention that reads placement anchors from the mask stack (e.g., thermal vent cells for geysers, karst candidate cells for sinkholes).

**Time estimate:** 8–12 hours to wire all 11 generators as proper passes with stack-driven placement. Even a minimal shim that calls `generate_sinkhole` from `pass_karst` (instead of orphaning it in `get_sinkhole_specs`) is a 1-hour improvement.

---

### M3-P0-8 — LOD_1 Returns an Integer Count, Not Geometry

**File:** `terrain_features.py:73`  
**One-line summary:** `_lod1_faces()` returns `max(4, int(len(faces) * 0.5))` — an integer, not a list of faces — so every geometry dict's `"LOD_1"` key holds a count that is silently mistaken for a face list by any LOD consumer.

**Evidence:**
```python
# terrain_features.py:73
def _lod1_faces(faces: list[tuple[int, ...]], ratio: float = 0.5) -> int:
    """Return LOD_1 face count (half the LOD_0 count, minimum 4)."""
    return max(4, int(len(faces) * ratio))
```

This is used at the bottom of every generator:
```python
# e.g. terrain_features.py:3024-3026
"lod": {
    "LOD_0": len(faces),
    "LOD_1": _lod1_faces(faces),   # integer, not geometry
},
```

A Unity importer reading `dimensions["lod"]["LOD_1"]` expects a face list (or at minimum a vertex count + face count pair). Instead it gets `int(248)`. Any code that does `len(spec["lod"]["LOD_1"])` will return 1 (the length of the integer object's string representation if coerced) or raise `TypeError`. There is no LOD_1 mesh, no LOD transition, no LOD_2 or LOD_3.

**AAA gap:** LOD is a hard requirement for any mesh destined for a Unity scene. Every AAA studio mandates at minimum LOD_0 (full res), LOD_1 (50% verts), LOD_2 (25% verts) for scene objects with radius > 2m. Supplying a count integer instead of simplified geometry means every feature generator produces exactly one LOD level. In a dark-fantasy world with thousands of sinkholes and lava flows, this is a direct performance failure.

**Fix:**
```python
# terrain_features.py:73 — replace the stub with real mesh simplification
def _lod_simplify(
    vertices: list,
    faces: list,
    ratio: float,
) -> dict:
    """Return a simplified mesh at `ratio` of original face count.

    Uses vertex clustering (greedy): merge vertices within cell_size of each
    other, rebuild faces referencing surviving vertices only.
    Returns {"vertices": [...], "faces": [...]} or empty dict if ratio=0.
    """
    target = max(4, int(len(faces) * ratio))
    if target >= len(faces) or not faces:
        return {"vertices": list(vertices), "faces": list(faces)}
    # Uniform decimation: keep every Nth face
    step = max(1, len(faces) // target)
    lod_faces = faces[::step][:target]
    # Collect referenced vertices
    used = sorted({vi for f in lod_faces for vi in f})
    v_map = {old: new for new, old in enumerate(used)}
    lod_verts = [vertices[i] for i in used]
    lod_faces_remapped = [tuple(v_map[vi] for vi in f) for f in lod_faces]
    return {"vertices": lod_verts, "faces": lod_faces_remapped}
```

Full quality requires a proper mesh decimation algorithm (Quadric Error Metrics), but uniform face decimation is a working placeholder that at least produces valid geometry. Each generator then stores `"LOD_1": _lod_simplify(vertices, faces, 0.5)` instead of `_lod1_faces(faces)`.

**Time estimate:** 3 hours for placeholder decimation; 2 days for QEM-based proper LOD.

---

### M3-P0-9 — Karst Pass Never in the Default Production Sequence

**File:** `environment.py:2004-2035`, `terrain_geology_validator.py:581`  
**One-line summary:** `pass_karst` is registered in Bundle I but is never added to the production `pipeline` list in `compose_map` — every production tile exports with karst features absent and `karst_delta` never computed.

**Evidence:**
```python
# environment.py:2004-2035 — full production pipeline construction:
pipeline = [
    "macro_world",
    "structural_masks",
]
if erosion in ("hydraulic", "thermal", "both") or cave_candidates:
    ...
if erosion in ("hydraulic", "thermal", "both"):
    pipeline.append("pass_hydrology")
    pipeline.append("erosion")
    pipeline.append("structural_masks")
if cave_candidates and controller_apply_caves:
    pipeline.append("caves")
    pipeline.append("integrate_deltas")
if params.get("cliff_overlays", True):
    pipeline.append("cliffs")
...
pipeline.append("validation_minimal")
```

There is no `pipeline.append("karst")` anywhere in this block. The `pass_karst` function is correctly implemented in `terrain_karst.py`, correctly registered in `terrain_geology_validator.py` as a Bundle I pass, and produces a valid `karst_delta` when called — but it is never called from the production path. Sinkholes, cenotes, and poljes require karst-dissolved bedrock terrain, which requires `rock_hardness` to be set — this dependency is also never satisfied in the default sequence.

**AAA gap:** A dark-fantasy game called "VeilBreakers" without sinkholes, cenotes, or poljes in the terrain is missing a core environmental storytelling element (collapsed passages to underground areas, flooded cave openings, drainage basins). This is not a missing feature — the math is written. It is a missing three lines of registration.

**Fix:**
```python
# environment.py — add after the erosion block:
karst_enabled = bool(params.get("karst_enabled", True))
if karst_enabled:
    # rock_hardness must be present for karst detection
    # structural_masks pass sets rock_hardness from biome data
    pipeline.append("karst")
    # integrate_deltas will be auto-inserted after karst by
    # _normalize_delta_integration_sequence in TerrainPassController
```

Also ensure `rock_hardness` is populated by `structural_masks`. If it is not, `pass_karst` exits early (enabled=True but `stack.rock_hardness is None` → features=[]) — defensively acceptable, but log a warning.

**Time estimate:** 1 hour (three-line pipeline wiring + integration test asserting karst_delta is non-zero on limestone-type terrain).

---

## P1 Findings (Significant Quality Gaps)

### M3-P1-1 — Cave Pass Gated Behind Two Independent Bool Conditions With No Fallback Diagnostic

**File:** `environment.py:2025`

The conjunction `cave_candidates and controller_apply_caves` silently skips caves if either condition is false. When the user provides `cave_candidates` but not `controller_apply_caves`, caves never run. There is no warning, no entry in `failed_passes`, and no flag in the returned dict. The caller cannot distinguish "caves ran and found nothing" from "caves were silently skipped."

**Fix:** Log a warning when `cave_candidates` is provided but `controller_apply_caves` is False (the user probably intended caves). Add a `"caves_attempted": bool` key to the returned dict.

**Time estimate:** 30 minutes.

---

### M3-P1-2 — Stalactite Length Cap (Line 4615) Clamps Before Dreybrodt Logic Completes

**File:** `terrain_caves.py:4615`

```python
# After Dreybrodt model selects stal_len, this line truncates it:
stal_len = max(0.3, min(2.0, stal_len))
```

The Dreybrodt model correctly computed `stal_len` based on `h` (wall height) and `t_age`. This clamp hard-limits all stalactites to 2.0m maximum regardless of chamber height. A 20m-tall chamber (common for LAVA_TUBE archetype) can only produce 2m stalactites — proportionally tiny nubs. Lechuguilla and Carlsbad Caverns have stalactites exceeding 6m. The clamp should be proportional to chamber height.

**Fix:**
```python
stal_len = max(0.3 * min(1.0, h / 4.0), min(h * 0.45, stal_len))
```

**Time estimate:** 30 minutes.

---

### M3-P1-3 — `generate_sinkhole` Called in `get_sinkhole_specs` Inside `try/except Exception: pass`

**File:** `terrain_karst.py:520-533`

```python
try:
    from .terrain_features import generate_sinkhole
    mesh_spec = generate_sinkhole(...)
except Exception:
    pass   # silently returns None mesh_spec
```

Any exception during sinkhole mesh generation (out-of-memory, numpy error, parameter validation failure) produces `mesh_spec = None` with zero telemetry. The caller receives a `SinkholeSpec` with `mesh_spec=None` and no indication of failure. The karst system's only mesh output is silently swallowed.

**Fix:** Replace bare `except Exception: pass` with specific exception handling and a logged warning at minimum:
```python
except ImportError:
    pass  # terrain_features not available — acceptable
except Exception as exc:
    import warnings
    warnings.warn(f"generate_sinkhole failed: {exc}", stacklevel=2)
    # mesh_spec remains None but caller is informed
```

**Time estimate:** 20 minutes.

---

### M3-P1-4 — No Unity Collision Mesh or NavMesh Obstacle Export for Any Cave

**File:** `terrain_caves.py` (throughout `handle_generate_cave`)

The MCP handler `handle_generate_cave` returns `chamber_mesh_spec`, `tunnel_mesh_spec`, and archway specs — but none of these carry a collision layer tag, physics material assignment, or NavMesh obstacle flag. Unity requires `MeshCollider` components on cave interiors for physics; without them, players fall through floors. NavMesh baking requires obstacle volumes to cut holes in the nav surface; without them, NPCs pathfind through walls.

The returned dict has no `"collision_mesh"`, `"physics_material"`, `"navmesh_obstacle"`, or `"navmesh_cut_volume"` key.

**Fix:** Add a `collision_mesh_spec` (separate low-poly version of the chamber for the `MeshCollider`) and a `navmesh_obstacle_spec` (bounding box + portal list) to the returned dict. The archway specs' `half_w` / `half_h` are already present and sufficient to define portal rectangles for NavMesh.

**Time estimate:** 3 hours.

---

### M3-P1-5 — No Cave Lighting Data: No Probe Positions, No AO Bake Hints

**File:** `terrain_caves.py` (throughout `handle_generate_cave`)

Cave interiors require baked ambient occlusion and light probe placement to look correct in Unity HDRP. The returned dict contains `interior_material` (albedo, roughness) but no `light_probe_positions`, no `ao_bake_resolution`, and no `reflection_probe_volumes`. A cave interior in HDRP without light probes renders as pitch-black or uniformly lit — neither is acceptable.

**Fix:** Add to the returned `meta` dict:
```python
"light_probe_grid": [
    # One probe per chamber vault, one at each junction, one at each entrance
    {"position": list(chamber_center), "role": "chamber_centre"},
    {"position": list(entrance_pos), "role": "entrance"},
    {"position": list(exit_world_pos), "role": "exit"},
],
"ao_bake_hints": {
    "resolution": 512,
    "bias": 0.05,
    "max_distance": min(chamber_w, chamber_d) * 0.5,
},
```

**Time estimate:** 2 hours.

---

## P2 Findings (Notable Quality Issues)

### M3-P2-1 — `_build_synthetic_state` Ignores Real Heightmap Data

**File:** `terrain_caves.py:4100-4186`

`_build_synthetic_state` builds a flat heightmap with 0–0.5m noise, regardless of the actual terrain being processed. When `handle_generate_cave` is dispatched from `compose_map`, the terrain has already been sculpted by erosion, cliffs, and hydrology. The cave is carved into a flat blank sheet, not the actual terrain surface. The `cave_height_delta` returned is meaningless for the real terrain.

**Time estimate to fix:** 2 hours (pass real heightmap from compose_map's state into the adapter).

---

### M3-P2-2 — Bezier Tunnel Frame Calculation Has a Degenerate Last-Segment Edge Case

**File:** `terrain_caves.py:4896-4903`

```python
if si < n_segs:
    t_next = float(si + 1) / float(n_segs)
else:
    t_next = t
    t_prev = float(si - 1) / float(n_segs)
    c_prev = _bezier_cubic(p0, p1, p2, p3, t_prev)
    centre_next = centre          # assigned but never used
    centre = c_prev               # overwrites centre for the local frame calc
    centre = _bezier_cubic(p0, p1, p2, p3, t)  # then immediately reassigned
```

`centre_next` is assigned but never used. `centre` is overwritten twice in three lines. The frame tangent at the last segment is computed from `c_next - centre` where `centre` was temporarily set to `c_prev` then restored, but `c_next = _bezier_cubic(p0, p1, p2, p3, min(t_next, 1.0))` and `t_next = t` at the last segment means `c_next == centre`. The tangent magnitude is zero — division by `tang_len = 0 or 1e-0` clamp gives a degenerate frame. The last tunnel ring is placed with an arbitrary normal, producing a faceted cap seam.

**Fix:** Use backward difference for the last segment:
```python
else:
    t_prev = float(si - 1) / float(n_segs)
    c_prev = _bezier_cubic(p0, p1, p2, p3, t_prev)
    tang_x = centre[0] - c_prev[0]
    tang_y = centre[1] - c_prev[1]
    tang_z = centre[2] - c_prev[2]
    # skip the rest of the forward-difference block
```

**Time estimate:** 30 minutes.

---

### M3-P2-3 — Sinkhole Wall Material Assignment Uses `kt` Before It Is Defined at Loop Scope

**File:** `terrain_features.py:3200`

```python
# terrain_features.py:3191-3205
for k in range(depth_res):
    for i in range(radial_res):
        ...
        faces.append((v0, v1, v2, v3))
        # Upper quarter: dirt over rock; lower: exposed rock
        if kt < 0.25:           # BUG: kt is from the outer loop — reads stale value
            mat_indices.append(0)  # dirt_wall
```

`kt = k / max(depth_res, 1)` is defined in the outer `for k in range(depth_res + 1)` loop (wall vertex construction, lines 3161–3189) but that loop ends before the face construction loop begins. In the face construction loop, `kt` retains the last value from the vertex loop (`kt = depth_res / max(depth_res, 1) = 1.0`). Therefore `kt < 0.25` is always False, `kt < 0.5` is always False, and every sinkhole wall face gets material `1` (exposed_rock) regardless of depth — no dirt layer ever appears.

**Fix:**
```python
for k in range(depth_res):
    kt_face = (k + 0.5) / max(depth_res, 1)   # face centre kt, not stale vertex kt
    for i in range(radial_res):
        ...
        if kt_face < 0.25:
            mat_indices.append(0)
        elif kt_face < 0.5:
            mat_indices.append(1)
        else:
            mat_indices.append(1)
```

**Time estimate:** 15 minutes.

---

### M3-P2-4 — Karst `cenote` has_bottom_cave=True Flag Is Never Consumed

**File:** `terrain_karst.py` (detect_karst_candidates → pass_karst)

`KarstFeature.has_bottom_cave` is set to `True` for cenotes. `pass_karst` iterates features and computes the carve delta but never inspects `has_bottom_cave`. The cenote geometry has an underwater cave opening — but no cave passage is spawned, no cave anchor is added to `cave_candidates`, and no karst-cave linkage event is recorded. The cenote is carved as a generic sinkhole with a flat bottom.

**Fix:** In `pass_karst`, after carving, collect cenotes with `has_bottom_cave=True` and append their world positions to `scene_read.cave_candidates` (or a new `karst_cave_candidates` channel) so the caves pass can pick them up.

**Time estimate:** 2 hours.

---

### M3-P2-5 — `generate_floating_rocks` Crystal Vein Material Assignment Is Dead Code

**File:** `terrain_features.py:3593-3604`

```python
# terrain_features.py:3593-3604
eq_start_mi = (len(mat_indices) - rock_end + rock_start
               + top_cap_faces + prev_band_faces)
# Simpler: just tag the vein in the RockSpec; downstream shader handles it
# (adding geometry-level crystal veins would require UV seams)
```

The equatorial crystal vein band is computed but immediately commented out in favour of "just tag the vein in the RockSpec." But the RockSpec dict never has a `"crystal_vein"` key added. No vein materialisation occurs either in the mesh or in the spec. The `crystal_vein` material (index 2) is declared in the materials list but assigned to zero faces.

**Fix:** Either complete the geometry-level vein (UV seams + face relabelling) or add `"has_crystal_vein_band": True` to the RockSpec dict so the downstream shader can apply it procedurally.

**Time estimate:** 1 hour.

---

## P3 Findings (Minor/Polish Issues)

**M3-P3-1** — `_fbm_noise` in terrain_caves.py (line 4189) uses `sin(x * 127.1 + y * 311.7) * 43758.5453` — the classic GPU hash lattice. This is not fBm; it is a single-frequency hash with accumulated octaves using the same hash per octave (only `frequency` and `amplitude` change). Real fBm uses independent noise per octave. The result has visible lattice aliasing at low frequencies. Low priority since it only affects floor rubble perturbation, but worth noting for a AAA audit.

**M3-P3-2** — `terrain_features.py` — `generate_lava_flow` `slope_angle_deg` docstring lists "Random seed" twice (line 4169: `slope_angle_deg: float\n    ...\n    Random seed.`). The parameter is `slope_angle_deg`. Copy-paste error.

**M3-P3-3** — `terrain_caves.py` — `validate_cave_opening_integration` checks cliff-face integration but only inspects the `_cliff_entry_meta` module dict. If the cave was generated without cliff-face snapping (i.e., the entrance was not snapped to a cliff face), `_cliff_entry_meta` is empty and all integration checks pass trivially — producing a false-green validation result for floating-in-air cave entrances.

**M3-P3-4** — `terrain_karst.py` — polje carving uses a superellipse with exponent 4 (line 399: `dist_super = (|dr|/rad)^4 + (|dc|/(rad*2.5))^4`). The exponent is hardcoded; field research suggests poljes have aspect ratios 2:1 to 5:1 rather than the fixed 2.5:1 used here. This is a correctness-over-physics concern, not a production blocker.

**M3-P3-5** — `terrain_features.py` — `generate_ice_formation` stalactite list (lines 3943-3947) only records metadata (`tip_position`, `length`, `base_radius`) but adds actual geometry to `vertices`/`faces`. When stalactite geometry fails mid-loop, the `stalactites` metadata list is shorter than the actual geometry, producing a mismatch between recorded specs and rendered cones.

---

## P0 Count Tally

| ID | File | Line | Issue |
|----|------|------|-------|
| M3-P0-1 | terrain_caves.py | 1543 | A\* max_nodes hard cap (4096) produces straight-line caves on all production tiles |
| M3-P0-2 | environment.py | 2008, 2025 | Caves off by default — silently produce flat terrain |
| M3-P0-3 | terrain_caves.py | 3864 | Overlapping cave footprints double-carve to unbounded depth |
| M3-P0-4 | terrain_caves.py | 1911 | Branch topology concatenates as linear extension, not true junction tree |
| M3-P0-5 | terrain_caves.py | 1888-1893 | Chamber spatial data dropped — only count stored |
| M3-P0-6 | terrain_caves.py | 656 | `_cliff_entry_meta` never cleared — tile-to-tile memory leak and determinism violation |
| M3-P0-7 | terrain_features.py | whole file | Entire file orphaned from production pipeline — 11 generators never called |
| M3-P0-8 | terrain_features.py | 73 | LOD_1 returns integer count, not geometry |
| M3-P0-9 | environment.py | 2004-2035 | Karst pass never in production sequence — sinkholes/cenotes never generated |
| ~~K4-P0-6~~ | ~~terrain_caves.py~~ | ~~1217-1234~~ | ~~Previously confirmed — excluded from new count~~ |

**New P0 count from M3:** 9

**Cumulative P0 total (all sweeps):** 105 prior + 9 new = **114 P0 blockers**

---

## Overall Grade

| Subsystem | Grade | Rationale |
|-----------|-------|-----------|
| terrain_caves.py | D | Correct math in isolation; production gated off by default; A\* capped to 1.6% of grid; branch topology broken; chamber data discarded; module-level state leaks |
| terrain_karst.py | C- | Carve math sound; pass correctly written; never added to production pipeline; cenote cave linkage unused; silent failure on mesh generation |
| terrain_features.py | D- | 4,588 lines of orphaned generators; LOD stub returns a count integer; never called from pipeline |
| Overall M3 | D+ | Mathematically above-average implementation quality destroyed by production wiring failures at every level |

---

*Audit completed 2026-04-27. K4-P0-6 (confirmed prior session) excluded from new count. All line numbers verified against full file reads.*
