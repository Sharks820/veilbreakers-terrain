# VeilBreakers Terrain — Node Seaming Audit
**Date:** 2026-04-24  
**Auditor:** Claude Sonnet 4.6  
**Scope:** Tile boundary continuity, noise coordinate system, material seams, road/river cross-tile continuity, adjacency metadata, LOD transitions, GeoNodes potential.

---

## Executive Summary

The codebase has a **two-tier split personality**: `build_scene_v3.py` (the primary showcase build script) operates as a **fully isolated single-tile generator with zero seaming infrastructure**, while the deeper handler layer (`terrain_chunking.py`, `handle_stitch_terrain_edges`, `_terrain_noise.py`) has real, working seam machinery that is never called by the showcase scripts. The seaming code exists, is tested, and mostly passes — but is wired to a different entry path that the Blender scene-build pipeline never touches.

Three of the seven audit sections are outright failing at the build-script level. Two are partial. Only the LOD pipeline and GeoNodes bridge are clean.

---

## A. TILE BOUNDARY HEIGHT MATCHING — Grade: D

### Finding

`build_scene_v3.py` generates the heightmap entirely in **tile-local coordinates**. The `compose_heightmap()` function at line 89 constructs a 513×513 NumPy grid spanning `X_MIN=-512` to `X_MAX=+512`, then adds multi-octave sinusoidal fBm noise with random per-octave phase offsets (`ox`, `oy` drawn from `np.random.default_rng(SEED)`). There is no concept of a neighboring tile and no seam stitching before mesh construction.

**Key code — build_scene_v3.py:118–133:**
```python
def fbm(x, y, octaves=6, base_freq=0.008, ...):
    rng = np.random.default_rng(seed_val)
    ...
    for _ in range(octaves):
        ox = float(rng.uniform(0, 1000.0))   # random offset — NOT world-space
        oy = float(rng.uniform(0, 1000.0))
        wave = np.sin((x + ox) * freq) * np.cos((y + oy) * freq * 1.3) + ...
```

These `ox/oy` offsets come from an RNG seeded with `SEED = 0xAAA3`, not from world coordinates. If a second tile used a different seed (or even the same seed with a different tile origin) the phase would be wrong and heights at the shared boundary would be discontinuous.

**`build_terrain_mesh` — build_scene_v3.py:240–273:** Directly builds a 257×257 bmesh grid from the local heightmap. No border-row locking, no averaging, no import of neighbor edges.

### What the handler layer has

`terrain_chunking.py:592–647` (`_blend_locked_edges`) implements a 3-cell weighted blend (weights `[1.0, 0.6, 0.2]`) that forces a tile's border rows/cols to match provided neighbor edge values. `apply_seam_boundary_conditions` at line 650 calls it per-channel. `handle_stitch_terrain_edges` in `environment.py:3351` does a post-mesh vertex-Z averaging pass after two tiles exist in the Blender scene. `validate_tile_seams` in `terrain_chunking.py:857` checks agreement to 1e-4 tolerance.

**None of these are called by `build_scene_v3.py`, `build_aaa_node_v1.py`, or the `handle_generate_terrain_tile` path used by `build_scene_v3.py`.**

The sole exception is `build_aaa_node_v2.py:160–179`, which manually calls `_load_v1_heightmap()` and locks the south-edge first 3 rows to v1's north edge. This is a one-off hack for the v1→v2 adjacency only; it does not generalize to arbitrary tile grids.

### Required Fix

`compose_heightmap()` in `build_scene_v3.py` must accept `world_origin_x, world_origin_y` parameters and pass them into `fbm()` so that noise is sampled at world-space coordinates. After heightmap generation, if neighbor edge arrays are available they must be injected via `_blend_locked_edges`. Then `build_terrain_mesh()` must use the same world-origin offset for vertex X/Y positions so the mesh vertices at `X=+512` of tile A and `X=-512` of tile B are coincident.

```python
# Minimal fix skeleton — build_scene_v3.py compose_heightmap()
def compose_heightmap(world_origin_x=0.0, world_origin_y=0.0,
                      neighbor_edges: dict | None = None):
    xs = np.linspace(world_origin_x + X_MIN, world_origin_x + X_MAX, HM_RES)
    ys = np.linspace(world_origin_y + Y_MIN, world_origin_y + Y_MAX, HM_RES)
    X, Y = np.meshgrid(xs, ys, indexing="xy")
    # ... existing heightmap math using X, Y in world-space ...
    # DO NOT use random ox/oy offsets — use world-space coords directly
    # After construction:
    if neighbor_edges:
        from veilbreakers_terrain.handlers.terrain_chunking import _blend_locked_edges
        heightmap = _blend_locked_edges(
            heightmap,
            north_edge=neighbor_edges.get("north"),
            south_edge=neighbor_edges.get("south"),
            east_edge=neighbor_edges.get("east"),
            west_edge=neighbor_edges.get("west"),
        )
    return heightmap
```

---

## B. NOISE COORDINATE SYSTEM — Grade: C

### Finding

The situation is split across the codebase.

**BROKEN (build_scene_v3.py):** The `fbm()` function at line 118 uses random `ox/oy` offsets drawn from an RNG, not world-space coordinates. The X/Y arrays passed in are tile-local (ranging from -512 to +512). This guarantees mismatch at all edges.

**WORKING (_terrain_noise.py:1200–1298):** `generate_terrain_heightmap_array()` accepts `world_origin_x, world_origin_y, cell_size` and builds coordinate grids as:
```python
x_coords = (np.arange(sample_width) * cell_size + sample_origin_x) / scale
y_coords = (np.arange(sample_height) * cell_size + sample_origin_y) / scale
xs_base, ys_base = np.meshgrid(x_coords, y_coords)
```
This is correct world-space sampling. With `normalize=False` it preserves the raw world-space value range and the docstring explicitly notes "Tileable: world_origin offsets produce seamless multi-tile output."

The `normalize=True` path (default) applies a per-tile geological constraint pass and rescales to [0,1], which **breaks tileability** by compressing each tile's range independently.

**Root cause:** `build_scene_v3.py` does not use `generate_terrain_heightmap_array` at all — it implements its own `compose_heightmap()` with a different, non-world-space noise algorithm. The advanced handler layer's noise infrastructure is dead code from the perspective of the primary build pipeline.

### Required Fix

`build_scene_v3.py:compose_heightmap()` should call `generate_terrain_heightmap_array(width=HM_RES, height=HM_RES, ..., world_origin_x=..., world_origin_y=..., normalize=False)` instead of its bespoke sinusoidal fBm. If the v3-specific art (320m peak, river spring, waterfall) must be preserved, it should be layered on top of the world-space base noise as additive height deltas defined by world-space coordinates (not tile-local).

---

## C. MATERIAL SEAM BLENDING — Grade: C+

### Finding

The terrain material in `build_scene_v3.py:279–382` (`make_terrain_material`) uses Blender **world-space Position and Normal** for all its computations:

- Altitude ramp: `GeometryNode → "Position" → SeparateXYZ → Z → MapRange(0..320)` — this is world-space Z, continuous across tile boundaries as long as heights match.
- Slope ramp: `GeometryNode → "Normal" → SeparateXYZ → Z → Math(SUBTRACT from 1.0)` — world-space normal, continuous.
- Rock texture: `ShaderNodeTexNoise` driven by `geom.outputs["Position"]` — world-space, continuous.

**Conclusion:** The material shader is world-space correct. If two adjacent tiles share matching geometry at their borders, the material will blend correctly with no shader-level seam. The material is **not the problem**.

**However:** Because the underlying heights mismatch at tile edges (Section A), there will be visible color discontinuities at boundaries anyway — not because of shader logic, but because height-driven bands will be at different elevations on each side of the crack.

**Edge case failure:** The biome-band logic in `world_map.py` operates on abstract `map_size` Voronoi coordinates (0..2000m), not the actual terrain tile coordinate system (±512m). Biome region boundaries from `generate_world_map` are therefore not automatically aligned with tile borders, and biome color transitions will appear at arbitrary positions that could cross tile boundaries without continuity.

---

## D. ROAD AND RIVER CROSS-TILE CONTINUITY — Grade: F

### Finding

#### The two disconnected road systems

**System 1 — `_terrain_noise.py:generate_road_path_grid_legacy`:** A grid-space A* pathfinder operating on a normalized [0,1] heightmap. Deprecated, used as a disaster-recovery fallback. Road output is a list of grid cells, not world-space coordinates. No tile-edge metadata.

**System 2 — `road_network.py:compute_road_network` + `_astar_24dir`:** A full 24-directional A* with AASHTO cost function operating on the actual world-space heightmap. Produces `segments`, `nodes`, `bridges`. Called from `environment.py:handle_generate_road` via `_solve_road_path_with_network`.

These two systems coexist because `handle_generate_road` at line 5704 sets `road_routing_method = "legacy_grid"` and only promotes to System 2 via `_solve_road_path_with_network` (line 5706) if the heightmap and terrain bounds are available. If that call fails, it falls back to `generate_road_path_grid_legacy` (line 5734). The legacy path remains as a production fallback.

**Connection status:** System 2 calls System 1's world-grading pass (`_grade_road_path_in_world_space` at line 4159) on the points it produces, so they are loosely chained but architecturally separate with no unifying interface.

#### Cross-tile continuity: does not exist

Neither system stores exit-edge metadata. There is no data structure of the form:
```python
{"north_exit": {"world_x": 120.0, "angle_deg": 15.0, "road_type": "main"},
 "east_exit": None, ...}
```

`build_scene_v3.py` hardcodes river points as tile-local literals (e.g. `outflow_pts = [(100., -400.), (110., -470.), (120., -511.)]`) ending at Y=-511 (1 meter from the south tile boundary). There is no mechanism for the adjacent tile to pick up this exit at (120, -512) and continue the river.

`world_map.py:_build_connections` builds an MST of region centers and labels edges `"main"` or `"path"` but these are purely abstract graph edges between Voronoi region centers — they have no heightmap interaction and no tile-boundary intersection points.

### Required Fix

```python
# Tile edge manifest entry — add to seam_contract output of build_tile_seam_contract()
"edge_features": {
    "north": [
        {"type": "river", "world_x": 120.0, "width_m": 22.0, "depth_m": 5.0,
         "direction_deg": 355.0},
    ],
    "east": [],
    "south": [],
    "west": [],
}
```

`handle_generate_terrain_tile` must extract river/road polyline endpoints that are within `cell_size * 2` of each tile edge and write them into the seam contract. The adjacent tile's generation call must then receive these as `neighbor_edge_features` and spawn matching river/road entry points.

---

## E. ADJACENCY / NEIGHBOR METADATA — Grade: C

### Finding

**What exists:**

`terrain_chunking.py:build_tile_seam_contract()` at line 510 produces a rich per-tile seam contract:
```python
{
    "tile_key": "5,7",
    "neighbor_tiles": {"north": [5,6], "south": [5,8], "east": [6,7], "west": [4,7]},
    "edge_contracts": {
        "north": {"sha256": "...", "samples": [...], "sample_count": 513},
        ...
    },
    "corner_heights": {"north_west": ..., "north_east": ..., ...},
}
```

`validate_tile_seams()` at line 857 does bidirectional height matching to 1e-4 tolerance.

`apply_seam_boundary_conditions()` at line 650 can lock a tile's border rows to neighbor edge arrays.

`handle_stitch_terrain_edges` in `environment.py:3351` does a Blender-side post-mesh Z-averaging pass.

**What is missing:**

1. **The seam contract is only populated when `handle_generate_terrain_tile` is called** (the multi-tile batch path in `handle_generate_world_terrain`). The primary showcase pipeline (`build_scene_v3.py`) never calls this function and produces no seam contract.

2. **No tile registry / cache.** When generating tile (5,8), there is no lookup mechanism to retrieve the already-computed edge samples from tile (5,7). The seam contract is generated and returned in the response dict but not persisted to a shared registry accessible to subsequent tile generation calls.

3. **`_blend_locked_edges` is never called during heightmap generation** in `build_scene_v3.py`. It is only called from `apply_seam_boundary_conditions` which is called from `terrain_twelve_step.py:1306` — a different pipeline entirely.

### What a proper implementation looks like

```python
# Shared tile registry (could be a JSON file or in-memory dict keyed by tile coords)
TILE_REGISTRY: dict[tuple[int,int], dict] = {}

def generate_tile(tile_x: int, tile_y: int, ...):
    neighbor_edges = {}
    for direction, (nx, ny) in [
        ("north", (tile_x, tile_y+1)),
        ("south", (tile_x, tile_y-1)),
        ("east",  (tile_x+1, tile_y)),
        ("west",  (tile_x-1, tile_y)),
    ]:
        if (nx, ny) in TILE_REGISTRY:
            contract = TILE_REGISTRY[(nx, ny)]["seam_contract"]
            opposite = {"north":"south","south":"north","east":"west","west":"east"}[direction]
            neighbor_edges[direction] = np.array(
                contract["edge_contracts"][opposite]["samples"]
            )
    hm = compose_heightmap(world_origin_x=..., world_origin_y=...,
                           neighbor_edges=neighbor_edges)
    contract = build_tile_seam_contract(hm, tile_x, tile_y, ...)
    TILE_REGISTRY[(tile_x, tile_y)] = {"seam_contract": contract}
    return hm, contract
```

---

## F. LOD TRANSITIONS — Grade: B-

### Finding

`lod_pipeline.py:handle_generate_lods()` at line 1613 generates a LOD chain from a named mesh object using the `LOD_PRESETS` table. The decimation pipeline (`decimate_preserving_silhouette`) uses QEM (Quadric Error Metrics) with silhouette-importance weighting. This is architecturally sound for per-object LOD.

**Gap 1 — No terrain-specific LOD preset.** The `LOD_PRESETS` dict (line 36) lists `hero_character`, `standard_mob`, `building`, `prop_small`, `prop_medium`, `weapon`, `vegetation`, `furniture` — but **no `terrain` preset**. Terrain LOD requirements differ fundamentally: 4+ LOD levels, border-row preservation to prevent T-junctions, skirt mesh generation. The `handle_generate_lods` handler would require callers to pass `asset_type="prop_medium"` for terrain which is wrong ratios and wrong preservation strategy.

**Gap 2 — No T-junction crack prevention.** When LOD1 terrain (128×128) is placed adjacent to LOD0 terrain (256×256), each shared vertex on the LOD1 border has a corresponding T-junction in the LOD0 mesh. The pipeline has no skirt geometry generation and no border-row pinning for terrain meshes.

**Gap 3 — LOD selection is per-object, not per-tile.** There is no terrain-tile LOD group system that swaps the entire tile mesh at LOD boundaries (the UE5 World Partition model). The handler generates individual LOD meshes in the Blender scene but does not set up any LOD group driver for real-time switching.

### Required Fix

Add to `LOD_PRESETS`:
```python
"terrain_tile": {
    "ratios": [1.0, 0.25, 0.0625, 0.015625],  # 257→65→17→5 resolution
    "screen_percentages": [1.0, 0.5, 0.2, 0.05],
    "min_tris": [130000, 8000, 500, 50],
    "preserve_regions": ["border_north", "border_south", "border_east", "border_west"],
    "generate_skirts": True,
    "border_pin": True,   # Lock border row/col Z to prevent T-junctions
},
```

Border pinning: before QEM collapse, mark all border-row vertices with `importance = 1.0` (maximum, never collapse). Generate 4 skirt quads per border edge that drop 10m below the lowest border vertex so any residual height gap is hidden underground.

---

## G. GEOMETRY NODES vs PYTHON — Grade: B (infrastructure exists, unused for terrain)

### Finding

The infrastructure for Geometry Nodes exists and is wired:

- `blender_capability_bridge.py:547–681` implements `geometry_nodes_create_group`, `geometry_nodes_add_node`, `geometry_nodes_link_sockets`, `geometry_nodes_assign_to_object`, `geometry_nodes_dump`.
- These are registered in `COMMAND_HANDLERS` at `__init__.py:1123–1130` and aliased in `blender_server.py:159–163`.
- Tests in `test_blender_capability_bridge.py:304` exercise the full round-trip.

**However:** `build_scene_v3.py` does not use Geometry Nodes at all. Terrain geometry is built entirely in Python bmesh (lines 240–273). Trees, rocks, and grass use bmesh + particle systems. No Geometry Nodes modifier exists on any object in the v3 pipeline.

### What GeoNodes migration would specifically enable for this codebase

**1. World-space seaming without code changes.** A GeoNodes "Terrain Tile" node that accepts `world_origin_x/y` as inputs and feeds them into a Noise Texture node with `Vector → Combine XYZ → Add(world_origin)` would automatically produce world-space-continuous noise. Adjacent tiles would share the same noise evaluation and heights would match at borders as long as vertex positions align.

**2. Non-destructive scatter.** Currently `scatter_trees()` bakes 180 object instances at fixed positions (lines 854–905). With GeoNodes `Distribute Points on Faces → Instance on Points`, scatter density is a live parameter, density masks update in real time, and no vertex-group baking is required.

**3. Seam-pinned LOD via mesh attributes.** GeoNodes can read a `border_pinned` vertex attribute and feed it into a `Merge by Distance` or `Decimate` subgraph, enabling LOD reduction that automatically preserves border rows.

**4. Dynamic river/road carving.** River and road carving (`carve_river()` at lines 160–172) currently bakes into the heightmap irreversibly. A GeoNodes setup with spline inputs and a `Raycast + Attribute Transfer` carving node would allow live parameter adjustment without re-running `compose_heightmap()`.

**Migration path (incremental, not replace-all):**
```
Step 1: Replace terrain mesh build (build_terrain_mesh) with a GeoNodes Grid node
        that reads world_origin from object custom properties.
Step 2: Replace particle grass with GeoNodes scatter on the terrain mesh output.
Step 3: Port river carving to a GeoNodes spline-deform modifier.
Step 4: Add border-pin attribute for seam-safe LOD.
```

---

## Summary Table

| Section | Description | Grade | Primary File:Line | Blocker? |
|---------|-------------|-------|-------------------|----------|
| A | Tile boundary height matching | D | build_scene_v3.py:89–139 (compose_heightmap) | YES — visible height step at all tile edges |
| B | Noise coordinate system | C | build_scene_v3.py:118–133 vs _terrain_noise.py:1280–1298 | YES — world-space infra exists but not used by v3 |
| C | Material seam blending | C+ | build_scene_v3.py:279–382 | NO (shader is world-space) but blocked by A |
| D | Road and river cross-tile continuity | F | environment.py:57,76; build_scene_v3.py:174–180 | YES — no exit-point metadata exists |
| E | Adjacency / neighbor metadata | C | terrain_chunking.py:510, 857; environment.py:3351 | PARTIAL — contract exists, not used by v3 pipeline |
| F | LOD transitions | B- | lod_pipeline.py:36,1613 | NO — but T-junctions guaranteed without terrain preset |
| G | Geometry Nodes vs Python | B | blender_capability_bridge.py:547; build_scene_v3.py:240 | NO — GN bridge exists, migration would fix A/B/F |

---

## Ordered Remediation Priority

**P0 — Must fix before any multi-tile work:**

1. **build_scene_v3.py:compose_heightmap** — Add `world_origin_x/y` params, use them in coordinate grids, remove random phase offsets from `fbm()`, inject neighbor edge arrays via `_blend_locked_edges`. *(Files: build_scene_v3.py:89, _terrain_noise.py:1280)*

2. **Tile registry** — Implement a persistent tile registry (JSON file keyed by `"tile_x,tile_y"`) that stores seam contracts so adjacent tile generation can read neighbor edges. *(Files: new module or extension to terrain_chunking.py)*

**P1 — Fix before shipping any adjacent tiles:**

3. **River/road exit metadata** — Extend `build_tile_seam_contract()` to include `edge_features` with river/road exit points. Extend `handle_generate_terrain_tile` to read them from the neighbor tile's contract and spawn matching inlets. *(Files: terrain_chunking.py:510, environment.py:3351)*

4. **Terrain LOD preset** — Add `"terrain_tile"` to `LOD_PRESETS` with border-pin preservation and skirt generation. *(Files: lod_pipeline.py:36)*

**P2 — Quality / GeoNodes migration path:**

5. Migrate `build_terrain_mesh` to a GeoNodes grid that reads world_origin from object properties — resolves A, B, and F simultaneously.

6. Replace `scatter_trees / scatter_rocks / add_grass` particle system with GeoNodes Distribute Points on Faces — resolves density-field/scatter disconnect noted in memory.
