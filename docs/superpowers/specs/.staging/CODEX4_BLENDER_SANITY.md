# CODEX4 Blender 4.5 Export Sanity

Date: 2026-05-06
Scope: static sanity check for Blender 4.5 chunk mesh export/import risk. Production code was read-only.

## Existing Export Contract

`veilbreakers_terrain/handlers/terrain_unity_export.py` is not a Blender exporter. It has no `bpy` import and no `bpy.ops.export_scene.*` path. Current bake-side contract is Python/NumPy -> RAW/PNG/JSON/NPZ sidecars.

Core facts:

- Scale: `UNITY_SCALE_FACTOR = 0.85` at `veilbreakers_terrain/handlers/terrain_unity_export.py:44`; `_apply_unity_scale()` applies it to scalars/lists at `:65-69`. Inline comment says camera/clavicle conversion, not terrain mesh scale, at `:45-47`.
- Required stack fields: `height`, `tile_x`, `tile_y`, `tile_size`, `cell_size`, `world_origin_x`, `world_origin_y` at `:1842-1850`.
- Heightmap: `heightmap.raw`, `raw_u16_le`, no extra flip at write because `_quantize_heightmap()` pre-flips at `:286-299`, then `_write_raw_array(... flip_vertical=False)` at `:1927-1935`.
- Terrain normals: world/unit vectors go to `terrain_normals.bin` as `raw_vec3_f32_le` at `:1936-1948`.
- Tangent normal texture: `terrain_normals_tangent.png` is RGBA8, declared tangent-space, flipped vertically at `:1949-1961`.
- Splatmaps: `_write_splatmap_groups()` emits `splatmap_XX.raw` groups. Its contract says RGBA uint8 RAW, normalized weights, Y-flip via `_write_raw_array()` at `:1741-1764` and writes files at `:1812-1835`.
- Generic binary channels: dynamic `populated_by_pass` plus legacy channel set are written as `<channel>.bin` via `_binary_export_payload()` and `_write_raw_array()` at `:1977-2024`.
- Optional sidecars include `hdrp_mask_map.raw` at `:2062-2079`, `detail_density__*.raw` at `:2081-2092`, `wildlife_affinity__*.bin` at `:2094-2104`, and `decal_density__*.bin` at `:2106-2117`.
- JSON sidecars emitted in the baseline loop: `tree_instances.json`, `foliage_placement_manifest.json`, `audio_zones.json`, `gameplay_zones.json`, `wildlife_zones.json`, `decals.json`, `ecosystem_meta.json` at `:2172-2181`.
- Optional JSON sidecars: `atmospheric_volumes.json` at `:2182-2195`, `supplemental_mesh_specs.json` at `:2196-2202`, `particle_emitter_specs.json` at `:2203-2209`, `water_shader_manifest.json` always at `:2210-2217`, `light_placements.json` when lights exist at `:2218-2220`, and `probe_placements.json` always at `:2221`.
- Mesh attributes: `mesh_attributes.npz` written by `_write_unity_mesh_attributes()` at `:1501-1520`.
- Final descriptor files: `manifest.json` and `unity_import_descriptor.json` are built in memory, validation-gated, and atomically written at `:2468-2515`.

Manifest JSON shape:

- `manifest.json` top-level includes `schema_version`, `world_id`, `tile_x`, `tile_y`, scaled `cell_size`, scaled origins, source height min/max, scaled height min/max, `height_scale_factor`, `coordinate_system`, profile, heightmap flags, splatmap counts/layers, biome distribution, water fields, foliage manifest, lightmap hints, file index, populated channels, determinism hash, terrain-layer assets, seam contract, validation issues/status, and optional sidecar filename keys. Main construction starts at `terrain_unity_export.py:2337`.
- `unity_import_descriptor.json` includes terrain identity, scaled height range, heightmap descriptor, terrain normals, normal map, mesh attributes, splatmaps, terrain layers, detail layers, tree prototypes/instances, zone/decals/water/navmesh/foliage/supplemental sidecar paths, seam contract, validation status, and Unity asset paths. Builder starts at `terrain_unity_export.py:1523` and returns the dict at `:1579-1689`.

18-artifact note:

- The staging implementation guide defines an 18-artifact byte-identity matrix by artifact class, not by the exact current handler filenames: heightmap raw/bin, heightmap/normal/splat PNGs, water/macro/navmesh masks, foliage/decals/water/edges JSON, manifest/meta JSON, and render-preview PNGs. See `docs/superpowers/specs/.staging/2026-05-06_CE_FIXES_IMPLEMENTATION_GUIDE.md:564-575`.
- Current `terrain_unity_export.py` does not yet emit that exact fixed 18-file chunk contract. It emits a variable Unity bundle, keyed by live stack channels and optional sidecars.

## Blender 4.5 Binary-Format Incompatibilities

### 1. glTF Draco vertex-color corruption

Bake-side cite:

- Supplemental mesh contract exposes `"color": []`, not a populated per-vertex color stream, at `terrain_unity_export.py:977`.
- Tree instance JSON explicitly defers `vertex_color` to a future per-prototype baked vertex stream at `terrain_unity_export.py:3014`.
- Wind-bend color function returns numeric RGBA data at `terrain_unity_export.py:2873-2936`, but current tree export does not serialize this into a mesh file.

Failure mode:

- Blender/glTF Draco compression has a known vertex-color corruption class, historically tracked as the Blender T75550 / glTF-Blender-IO Draco vertex color issue family. If wind-bend, biome ID, AO, or material weights move into COLOR_0 and `export_draco_mesh_compression_enable=True`, color values can quantize/reorder/corrupt. Foliage wind then bends wrong, terrain blend IDs shift, or color data appears washed/out-of-range after Unity import.

Fix:

- For any GLB carrying semantic vertex colors, disable Draco: `export_draco_mesh_compression_enable=False`.
- Prefer named glTF attributes or UV channels for non-color data where Unity importer can consume them directly.
- Add Blender round-trip check: export GLB, import GLB, compare COLOR_0/COLOR_1 arrays exactly or within explicit tolerance. Keep Draco blocked until that passes in Blender 4.5 and Unity.

### 2. `tangent.w` handedness flip

Bake-side cite:

- Supplemental mesh tangents are hardcoded placeholders `[1.0, 0.0, 0.0, 1.0]` at `terrain_unity_export.py:953-956`.
- Serialized tangent keys use that placeholder at `terrain_unity_export.py:973-974`.

Failure mode:

- `tangent.w` is the bitangent sign. Axis conversion, negative scale, FBX/glTF importer transforms, or Unity recalculation can flip handedness. Hardcoding `w=1` hides mirrored islands and causes normal maps to light inside-out on cliff/cave chunks.

Fix:

- Compute tangents from final exported positions, normals, and UV0 using MikkTSpace after coordinate conversion.
- Assert `tangent.xyz` length, orthogonality to normal, and correct `w` sign after Blender export-import.
- If Unity recalculates tangents, remove placeholder tangents from sidecar and mark importer as authoritative. Do not ship fake tangents.

### 3. UV V-flip mismatch

Bake-side cite:

- `_flip_for_unity()` flips raster axis 0 at `terrain_unity_export.py:629-633`.
- `_write_raw_array()` defaults `flip_vertical=True` and records `flip_vertical` metadata at `terrain_unity_export.py:736-754`.
- `_write_rgba_png()` also flips PNG rows by default at `terrain_unity_export.py:796-824`.
- Supplemental mesh UVs are copied as-is from raw specs at `terrain_unity_export.py:938-950`, then emitted as `uv0`, `uv1`, and `uvs` at `:975-985`.

Failure mode:

- Textures/masks are vertically flipped for Unity row convention, but mesh UV V values are not flipped. A GLB/FBX chunk mesh using those UVs against exported masks samples upside-down splat/normal/flow/height textures.

Fix:

- Pick one convention per artifact family. For mesh exports, either write texture images unflipped for GLB/FBX use, or transform mesh UVs with `v = 1.0 - v` when paired with flipped Unity textures.
- Add export manifest fields: `uv_origin`, `texture_origin`, `uv_v_flipped`.
- Round-trip sanity must compare UV0/UV1 count and sampled corner colors, not just vertex count.

### 4. sRGB vs linear vertex colors

Bake-side cite:

- `_hex_to_rgb01()` divides hex bytes by 255 without linear conversion at `terrain_unity_export.py:1260-1269`.
- Terrain layer metadata records `base_color_rgb` from that function at `terrain_unity_export.py:1306-1307`.
- Tree instance colors are JSON floats, fixed white, at `terrain_unity_export.py:3026-3027`.

Failure mode:

- Blender stores and displays color attributes/material colors in color-managed space, while glTF and Unity shader semantics differ between base color and data channels. If semantic data is stored in COLOR_0 but imported as sRGB color, wind/weights/AO get gamma-transformed. If visual colors are exported as linear but interpreted as sRGB, layer tint shifts.

Fix:

- Split streams: visual color attributes get explicit sRGB/linear conversion; data attributes never use vertex color unless importer guarantees no color-space transform.
- Add metadata per stream: `semantic`, `color_space`, `normalized`, `domain`.
- For base colors, convert hex sRGB to linear before shader math, or explicitly declare `base_color_rgb_space: srgb`.

### 5. FBX axis-swap plus scaling mode

Bake-side cite:

- Current vector conversion is a simple Z-up to Unity Y-up reorder `(x, z, y)` at `terrain_unity_export.py:323-330`.
- Supplemental mesh vertices are scaled and converted before serialization at `terrain_unity_export.py:916-922`.
- Manifest and descriptor also carry scaled world/height fields at `terrain_unity_export.py:2343-2361` and `:1585-1591`.

Failure mode:

- FBX adds its own axis and unit transform layer. Blender 4.5 `bpy.ops.export_scene.fbx` exposes `axis_forward`, `axis_up`, `apply_unit_scale`, `apply_scale_options`, `use_space_transform`, and `bake_space_transform`. Mixing pre-swapped vertices with FBX axis conversion and `Apply Scaling=All Local` vs `FBX Units Scale` can double-rotate or double-scale chunks. Result: terrain meshes import at 0.85x, 1/0.85x, or rotated/mirrored relative to RAW heightmaps.

Fix:

- Do not pre-swap vertices for FBX if the FBX exporter is doing axis conversion.
- Canonical FBX preset for chunk mesh tests: `global_scale=1.0`, `apply_unit_scale=True`, one chosen `apply_scale_options` documented in the manifest, `axis_forward='-Z'`, `axis_up='Y'`, and a Unity import smoke test.
- For deterministic sanity, prefer GLB first because current handler contract is explicit Y-up JSON/RAW, not FBX scene units.

### 6. Scale factor 0.85 vs 1.0

Bake-side cite:

- `UNITY_SCALE_FACTOR = 0.85` at `terrain_unity_export.py:44`.
- Comment ties this to camera/clavicle height at `terrain_unity_export.py:45-47`.
- Manifest writes scaled `cell_size`, origins, height min/max, and `height_scale_factor` at `terrain_unity_export.py:2343-2361`.
- Descriptor consumes scaled `cell_size`, height range, and `height_scale_factor` at `terrain_unity_export.py:1585-1591`.
- Tree prototype width/height also uses `_apply_unity_scale()` at `terrain_unity_export.py:2247-2254`.

Failure mode:

- Memory note says 0.85 is a character-rig hack incorrectly applied to mesh export. For chunk meshes, scale must be 1 terrain meter = 1 Unity meter. Current contract shrinks terrain, water planes, foliage positions, and supplemental meshes together. If any Blender GLB/FBX export uses real meters while JSON sidecars use 0.85, chunk mesh no longer aligns to RAW terrain, water, navmesh, or foliage.

Fix:

- Split scale domains: `terrain_world_scale = 1.0`; `character_rig_scale = 0.85`.
- Do not apply character scale in `export_unity_manifest()` for terrain/chunk artifacts.
- Add a round-trip assertion: bounding box X/Z extent equals `(tile_size - 1) * cell_size` in Unity meters with tolerance <= 1e-6.

### 7. Missing MikkTSpace tangents

Bake-side cite:

- Code explicitly says full MikkTSpace tangents are deferred to Unity at `terrain_unity_export.py:953-955`.
- It still serializes placeholder tangents at `terrain_unity_export.py:956` and `:973-974`.

Failure mode:

- Blender, Unity, Unreal, Substance, and xNormal workflows assume MikkTSpace for normal mapped meshes. Placeholder or non-Mikk tangents make cliff/cave normal maps show seams, checkerboard flips, and specular discontinuities at UV islands.

Fix:

- Either compute MikkTSpace in Blender during mesh export and preserve it, or omit tangent streams and force Unity's MikkTSpace recalculation.
- Add sanity script check for tangent presence/sign only after Mikk path exists. Current documentation script checks vertex and UV preservation only.

### 8. Smooth shading at chunk seams

Bake-side cite:

- `_compute_face_area_weighted_normals()` accumulates only faces present in the local mesh at `terrain_unity_export.py:851-894`.
- Supplemental mesh normals are computed from local `vertices` and `faces` at `terrain_unity_export.py:946-952`.
- Staging chunk guidance requires halo normals and Mikk tangents at `docs/superpowers/specs/.staging/2026-05-06_CE_FIXES_IMPLEMENTATION_GUIDE.md:608-616`.

Failure mode:

- Adjacent chunks compute edge normals from different triangle sets. Even with bit-equal edge heights, normals differ across the border. HDRP deferred lighting shows black/shimmering chunk cracks, especially on slopes.

Fix:

- Generate a 1-vertex halo for each chunk, accumulate face normals including halo triangles, then drop halo vertices before export.
- Add edge test: east/west exported heights bit-equal and normals allclose with tolerance <= 1e-6.

### 9. Terrain normal computation without halo vertices

Bake-side cite:

- `_compute_terrain_normals_zup()` uses `np.gradient(... edge_order=1)` on only the local heightmap at `terrain_unity_export.py:315-320`.
- Export refresh computes normals from the local height array when missing at `terrain_unity_export.py:1906-1909`.

Failure mode:

- Boundary normals use one-sided gradients. Neighbor chunk boundary normals use the opposite one-sided gradient. Same height seam, different lighting seam.

Fix:

- Compute terrain normals from a merged field or chunk halo, then export only the inner chunk.
- Store `normal_source: halo_1_vertex` or `normal_source: local_gradient` in manifest and fail visual-quality gate for local-gradient chunk meshes.

### 10. Foliage prefab pivot offset

Bake-side cite:

- Tree positions are serialized from point rows, sampled terrain height, and scale at `terrain_unity_export.py:2978-3028`.
- Foliage mesh library only records `mesh_id`, `species_key`, render mode, and batch key at `terrain_unity_export.py:3044-3052`.
- Foliage instance payload records position, rotation, and scale, but no prefab pivot/bounds offset at `terrain_unity_export.py:3054-3069`.

Failure mode:

- Imported FBX/GLB tree prefabs often have origin at center, root, or authoring pivot. Without a declared pivot offset, placement point may land at trunk center, below terrain, or above terrain. Rotation around wrong pivot also causes visible sliding on slopes.

Fix:

- Require per-prototype metadata: `pivot_space`, `pivot_offset_m`, `bounds_min_m`, `bounds_max_m`, `root_anchor_m`.
- During Blender export, bake foliage prefab origin to root/base or emit the offset and make Unity importer apply it.
- Add sanity test: lowest vertex after placement is within tolerance of sampled terrain height.

### 11. Apply Modifiers before export

Bake-side cite:

- Production handler serializes raw mesh spec vertices directly at `terrain_unity_export.py:904-922`; there is no evaluated Blender mesh path.
- There is no `bpy.ops.export_scene.gltf` or `bpy.ops.export_scene.fbx` call in `terrain_unity_export.py`.

Failure mode:

- If chunk meshes are authored in Blender with displace/geometry-nodes/triangulate/weighted-normal modifiers and export runs with modifiers off, the GLB/FBX contains base mesh geometry. Heightmap-derived vertex count, UV channels, normals, and collision no longer match the authored/evaluated chunk.

Fix:

- For GLB sanity exports, use Blender 4.5 `bpy.ops.export_scene.gltf(..., export_apply=True, export_tangents=True, export_draco_mesh_compression_enable=False)`.
- For FBX, use `use_mesh_modifiers=True` and the canonical scale/axis preset.
- Test against evaluated mesh counts before export and imported mesh counts after re-import.

## Documentation Script

Added `scripts/codex_export_sanity.py`.

Purpose:

- Blender 4.5 headless documentation script.
- Synthesizes a small terrain chunk mesh from an in-memory heightmap.
- Adds UV0 and UV1.
- Exports GLB with modifiers applied, tangents enabled, Draco disabled.
- Re-imports GLB.
- Asserts vertex count and UV channel count match.

Do not treat this as executed proof. No Blender runtime was available or used in this task.

## External References

- Blender 4.5 Python API, glTF and FBX export/import operators: https://docs.blender.org/api/4.5/bpy.ops.export_scene.html and https://docs.blender.org/api/4.5/bpy.ops.import_scene.html
- Blender 4.5 glTF manual, vertex color export modes: https://docs.blender.org/manual/en/4.5/addons/import_export/scene_gltf2.html
- Draco vertex-color corruption public issue family: https://github.com/KhronosGroup/glTF-Blender-IO/issues/1019
