# Blender Agent Usage Guide (Phase J)

MCP dispatch vocabulary for the VeilBreakers terrain toolchain.
Every entry below can be invoked via:

```python
from veilbreakers_terrain.src.veilbreakers_mcp.blender_server import dispatch
result = dispatch("<location_key>", {...payload...})
# -> {"status": "ok", "location": ..., "command": ..., "result": ...}
```

Location keys are the short MCP vocabulary; command keys are the canonical
`COMMAND_HANDLERS` entries. Agents should prefer location keys.

All responses are dicts with `status: "ok"` on success or
`status: "error"` plus an `error` code on failure.

---

## 1. bmesh operations — `bmesh_op`

Low-level bmesh edit ops applied in place to a mesh object.

**Payload**

```json
{
  "object_name": "Terrain_Main",
  "op": "bevel | poke | triangulate | dissolve_edges | dissolve_faces | dissolve_verts | boolean",
  "offset": 0.05,
  "segments": 1,
  "angle_limit_deg": 30.0,
  "quad_method": "BEAUTY",
  "ngon_method": "BEAUTY",
  "use_verts": false,
  "other_object_name": "Cutter",
  "boolean_op": "DIFFERENCE | UNION | INTERSECT"
}
```

**Return** — `{ "status": "ok", "op", "object", "vertex_count", "face_count" }`.

Boolean falls back to a `BOOLEAN` modifier when `bmesh.ops.intersect_boolean`
is unavailable. Always guard dense meshes with `safety_boolean` first.

---

## 2. Modifier stack — `modifier_add` / `modifier_apply` / `modifier_remove` / `modifier_list`

Supported types: `SUBSURF`, `DECIMATE`, `ARRAY`, `MIRROR`, `SOLIDIFY`,
`DISPLACE`, `REMESH`, `CURVE`, `BOOLEAN`, `NODES`.

**Add**

```json
{
  "object_name": "Terrain_Main",
  "modifier_type": "DECIMATE",
  "name": "LOD1_decimate",
  "settings": {"ratio": 0.5, "decimate_type": "COLLAPSE"}
}
```

Unknown settings are reported in `unknown_settings`; known ones in
`applied_settings`.

**Apply / Remove** — both take `{object_name, modifier_name}`.

**List** — `{object_name}` → `{"status": "ok", "modifiers": [{"name", "type"}, ...]}`.

---

## 3. UV projection — `uv_project`

**Payload**

```json
{
  "object_name": "Terrain_Main",
  "method": "smart | cube | unwrap",
  "angle_limit_deg": 66.0,
  "island_margin": 0.02,
  "cube_size": 1.0,
  "correct_aspect": true
}
```

**Return** — `{"status": "ok", "method", "uv_layer": "<active layer name>"}`.

Agent enters Edit mode, selects all, runs the op, returns to Object mode —
mode is restored even on failure.

---

## 4. Render engine — `render_engine`

```json
{"engine": "BLENDER_EEVEE_NEXT | BLENDER_EEVEE | CYCLES | BLENDER_WORKBENCH"}
```

Blender 4.5's default engine identifier is `BLENDER_EEVEE_NEXT`.

---

## 5. Render still — `render_still`

```json
{
  "output_path": "/tmp/out.png",
  "width": 512,
  "height": 512,
  "mode": "render | opengl"
}
```

Width/height are clamped to `[64, 507]` by `terrain_blender_safety.clamp_screenshot_size`
to prevent Blender crashes on oversized OpenGL renders.

`mode=opengl` uses `bpy.ops.render.opengl(write_still=True)` (fast, viewport
shading). `mode=render` uses the active engine.

---

## 6. Collections — `collection_create` / `collection_link`

**Create**

```json
{"name": "vegetation_lod0", "parent": "world_root"}
```

If `parent` is omitted, links to the scene's root collection.

**Link object**

```json
{"object_name": "Tree_001", "collection_name": "vegetation_lod0"}
```

---

## 7. Parenting — `parent_set`

```json
{
  "child_name": "Rock_001",
  "parent_name": "Terrain_Chunk_05",
  "keep_transform": true
}
```

`keep_transform=true` preserves world-space transform by setting
`matrix_parent_inverse`.

---

## 8. Empty controllers — `empty_create`

```json
{
  "name": "water_ctrl",
  "location": [0.0, 0.0, 1.5],
  "display_type": "PLAIN_AXES | SPHERE | CUBE | CONE | ARROWS"
}
```

Returns `{"status": "ok", "name", "location", "display_type"}`.
Fails with `name_taken` if an object of that name already exists.

---

## 9. Geometry Nodes — round-trip surface

Five commands, together sufficient to build, assign, and inspect a Geometry
Nodes tree without leaving the MCP layer.

### 9.1 `gn_create_group`

```json
{"name": "gn_terrain_subdiv"}
```

Creates a `GeometryNodeTree` with default `Geometry` input/output sockets
and a straight-through link between the group's input and output nodes.

### 9.2 `gn_add_node`

```json
{
  "group_name": "gn_terrain_subdiv",
  "node_type": "GeometryNodeSubdivideMesh",
  "node_name": "subdiv_1",
  "location": [0.0, 0.0]
}
```

### 9.3 `gn_link_sockets`

```json
{
  "group_name": "gn_terrain_subdiv",
  "from_node": "Group Input",
  "from_socket": "Geometry",
  "to_node": "subdiv_1",
  "to_socket": "Mesh"
}
```

Socket identifiers accept socket names or positional indexes.

### 9.4 `gn_assign_object`

```json
{
  "object_name": "Terrain_Main",
  "group_name": "gn_terrain_subdiv",
  "modifier_name": "GeometryNodes"
}
```

Creates a `NODES` modifier if absent and assigns the node group.

### 9.5 `gn_dump`

```json
{"group_name": "gn_terrain_subdiv"}
```

Returns full tree state:

```json
{
  "status": "ok",
  "node_group": "gn_terrain_subdiv",
  "node_count": 3,
  "link_count": 2,
  "nodes": [{"name", "type", "location", "inputs": [...], "outputs": [...]}],
  "links": [{"from_node", "from_socket", "to_node", "to_socket"}]
}
```

This round-trips: `create → add → link → assign → dump` is the full build cycle.

---

## 10. Add-ons — `addon_enable` / `addon_disable`

Short-name keys: `ant_landscape`, `sapling`, `node_wrangler`. Any other
string is passed through as the raw Blender add-on module name.

```json
{"addon_key": "ant_landscape"}
```

---

## 11. Existing high-level handlers (recap)

These predate Phase J and remain the right tools for their domain.

| Location key | Command |
|---|---|
| `terrain_sculpt` | raise/lower/smooth/flatten/stamp brush (handlers/terrain_sculpt.py) |
| `paint_weights`, `paint_weights_uv`, `paint_blend` | vertex-paint offline math |
| `material_procedural` | procedural material creation |
| `terrain_biome_setup` | full biome material setup |
| `mesh_smooth` | Taubin smoothing |
| `terrain_lods` | Decimate-based LOD chain |
| `visual_setup_camera`, `visual_set_shading`, `visual_capture_screenshot` | QA camera/shading/screenshot |
| `scene_read`, `viewport_read`, `viewport_fresh`, `frustum_check` | scene/viewport observation |
| `addon_health`, `addon_stale`, `addon_reload` | add-on lifecycle |
| `safety_boolean`, `safety_convert_yup`, `safety_screenshot_size` | crash-prevention guards |

Prefer these over raw capability calls when a domain handler exists —
they apply VeilBreakers-specific validation and budgets.

---

## Error codes (union across all commands)

| error | meaning |
|---|---|
| `unknown_location` | location key not in `_LOC_HANDLERS` |
| `unknown_command` | location resolved but handler missing |
| `handler_exception` | handler raised — see `exception_type`, `message` |
| `invalid_params` | params wasn't a dict |
| `bpy_unavailable` | running outside Blender |
| `bmesh_unavailable` | bmesh module not importable |
| `object_not_found` / `not_a_mesh` | target object missing or wrong type |
| `unknown_op` / `unknown_uv_method` / `unsupported_modifier_type` / `unknown_engine` | enum guard rejected input |
| `modifier_not_found` | named modifier absent from stack |
| `modifier_create_failed` / `apply_failed` | Blender rejected the op |
| `node_group_not_found` / `node_not_found` / `socket_not_found` | geometry nodes targets missing |
| `name_taken` | empty_create collided with existing object |
| `parent_collection_not_found` | collection_create parent missing |

Agents should branch on `error` and retry with corrected params or fall
back to a different capability rather than treating all errors as fatal.
