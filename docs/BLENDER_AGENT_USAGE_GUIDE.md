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

## 1. Scene/object orientation and bounded edits

Use these as the safe VeilBreakers equivalent of generic Blender MCP scene
inspection and basic object authoring. Prefer them over arbitrary Python code.

| Location key | Purpose |
|---|---|
| `blender_scene_info` | compact object counts, active camera, optional object summaries |
| `blender_object_info` | detailed summary for one object |
| `object_create` | create bounded mesh primitive (`cube`, `plane`, `uv_sphere`, `ico_sphere`, `cylinder`, `cone`, `torus`) |
| `object_transform` | set location, rotation, and/or scale |
| `object_delete` | delete one named object |
| `material_basic` | create/update a simple Principled material and assign it |
| `material_inspect` | inspect assigned materials, shader nodes, UV layers, and terrain attributes |
| `light_setup` | create/update `AREA`, `POINT`, `SPOT`, or `SUN` light |
| `camera_setup` | create/update camera, optionally look at a target and set active |
| `camera_orbit_plan` | generate reusable hero/cardinal/top/closeup terrain camera shots |
| `camera_apply_shot` | create/update a Blender camera from one shot-list entry |
| `render_output_check` | verify a render file exists, is non-trivial, and optionally is PNG |
| `terrain_bridge_health` | check live Blender/bmesh availability and compact scene status |
| `terrain_heightfield_mesh` | build a terrain grid mesh from a height channel and named point attributes |
| `terrain_write_attribute` | write a scalar point attribute to an existing terrain mesh |
| `terrain_scene_validate` | verify required terrain objects/channels/camera before an agent mutates or exports |
| `terrain_editability_report` | confirm a terrain object is mesh-backed, unlocked, attributed, textured, and editable |

**Primitive payload**

```json
{
  "name": "VB_probe_cube",
  "primitive_type": "cube",
  "location": [0, 0, 1],
  "rotation_euler": [0, 0, 0],
  "scale": [1, 1, 1],
  "size": 1.0
}
```

**Material payload**

```json
{
  "object_name": "VB_probe_cube",
  "material_name": "VB_probe_moss",
  "base_color": [0.22, 0.38, 0.18, 1.0],
  "roughness": 0.8,
  "metallic": 0.0
}
```

**Terrain heightfield payload**

```json
{
  "name": "VB_Terrain_Main",
  "height": [[0.0, 0.4, 0.0], [0.2, 1.0, 0.2], [0.0, 0.3, 0.0]],
  "cell_size": 2.0,
  "attributes": {
    "wetness": [[0.0, 0.2, 0.0], [0.4, 1.0, 0.4], [0.0, 0.2, 0.0]],
    "flow_accumulation": [[0.0, 0.1, 0.0], [0.2, 0.8, 0.2], [0.0, 0.1, 0.0]]
  },
  "material_name": "VB_Terrain_Debug",
  "replace": true
}
```

Use `terrain_scene_validate` before follow-up operations:

```json
{
  "required_objects": ["VB_Terrain_Main"],
  "required_attributes": {
    "VB_Terrain_Main": ["height", "wetness", "flow_accumulation"]
  },
  "require_active_camera": false
}
```

Use the camera and render quality loop before visual claims:

```json
{
  "target": [0, 0, 0],
  "radius": 40,
  "include_top": true,
  "include_closeups": true
}
```

Pass one returned `shots[]` item into `camera_apply_shot`, render or capture,
then run `render_output_check` and `visual_compare_render` when a golden exists.

---

## 2. bmesh operations — `bmesh_op`

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

## 3. Modifier stack — `modifier_add` / `modifier_apply` / `modifier_remove` / `modifier_list`

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

## 4. UV projection — `uv_project`

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

## 5. Render engine — `render_engine`

```json
{"engine": "BLENDER_EEVEE_NEXT | BLENDER_EEVEE | CYCLES | BLENDER_WORKBENCH"}
```

Blender 4.5's default engine identifier is `BLENDER_EEVEE_NEXT`.

---

## 6. Render still — `render_still`

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

## 7. Collections — `collection_create` / `collection_link`

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

## 8. Parenting — `parent_set`

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

## 9. Empty controllers — `empty_create`

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

## 10. Geometry Nodes — round-trip surface

Five commands, together sufficient to build, assign, and inspect a Geometry
Nodes tree without leaving the MCP layer.

### 10.1 `gn_create_group`

```json
{"name": "gn_terrain_subdiv"}
```

Creates a `GeometryNodeTree` with default `Geometry` input/output sockets
and a straight-through link between the group's input and output nodes.

### 10.2 `gn_add_node`

```json
{
  "group_name": "gn_terrain_subdiv",
  "node_type": "GeometryNodeSubdivideMesh",
  "node_name": "subdiv_1",
  "location": [0.0, 0.0]
}
```

### 10.3 `gn_link_sockets`

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

### 10.4 `gn_assign_object`

```json
{
  "object_name": "Terrain_Main",
  "group_name": "gn_terrain_subdiv",
  "modifier_name": "GeometryNodes"
}
```

Creates a `NODES` modifier if absent and assigns the node group.

### 10.5 `gn_dump`

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

## 11. Add-ons — `addon_enable` / `addon_disable`

Short-name keys: `ant_landscape`, `sapling`, `node_wrangler`. Any other
string is passed through as the raw Blender add-on module name.

```json
{"addon_key": "ant_landscape"}
```

---

## 12. Existing high-level handlers (recap)

These predate Phase J and remain the right tools for their domain.

| Location key | Command |
|---|---|
| `terrain_sculpt` | raise/lower/smooth/flatten/stamp brush (handlers/terrain_sculpt.py) |
| `blender_scene_info`, `blender_object_info`, `object_create`, `object_transform`, `object_delete`, `material_basic`, `light_setup`, `camera_setup` | safe scene/object/modeling wrappers inspired by generic Blender MCP |
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
