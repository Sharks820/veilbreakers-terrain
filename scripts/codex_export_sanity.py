"""Blender 4.5 GLB export/import sanity script for documentation.

Do not run from normal Python. Intended command shape:

    blender --background --python scripts/codex_export_sanity.py -- /tmp/vb_chunk_sanity.glb

The script synthesizes a small chunk mesh from a heightmap, exports GLB,
re-imports it, and asserts vertex count plus UV channel count survive.
"""

from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path

import bpy


GRID_SIZE = 9
CELL_SIZE_M = 2.0
EXPECTED_UV_CHANNELS = 2


def _clear_scene() -> None:
    """Remove every object from the active Blender scene."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def _height_at(row: int, col: int) -> float:
    """Return the synthetic heightmap value at ``(row, col)``."""
    x = col / float(GRID_SIZE - 1)
    y = row / float(GRID_SIZE - 1)
    return 1.25 * math.sin(x * math.pi) * math.cos(y * math.pi * 0.5)


def _build_chunk_mesh() -> tuple[bpy.types.Object, int, int]:
    """Build a synthetic chunk mesh; return ``(obj, vertex_count, uv_channels)``."""
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []

    for row in range(GRID_SIZE):
        for col in range(GRID_SIZE):
            x = col * CELL_SIZE_M
            y = row * CELL_SIZE_M
            z = _height_at(row, col)
            vertices.append((x, y, z))

    for row in range(GRID_SIZE - 1):
        for col in range(GRID_SIZE - 1):
            i0 = row * GRID_SIZE + col
            i1 = i0 + 1
            i2 = i0 + GRID_SIZE
            i3 = i2 + 1
            faces.append((i0, i2, i1))
            faces.append((i1, i2, i3))

    mesh = bpy.data.meshes.new("VB_SynthChunkMesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)

    uv0 = mesh.uv_layers.new(name="UV0")
    uv1 = mesh.uv_layers.new(name="UV1")
    for poly in mesh.polygons:
        for loop_index in poly.loop_indices:
            vert_index = mesh.loops[loop_index].vertex_index
            row = vert_index // GRID_SIZE
            col = vert_index % GRID_SIZE
            u = col / float(GRID_SIZE - 1)
            v = row / float(GRID_SIZE - 1)
            uv0.data[loop_index].uv = (u, v)
            uv1.data[loop_index].uv = (u, v)

    color_attr = mesh.color_attributes.new(
        name="VB_DebugColor",
        type="FLOAT_COLOR",
        domain="CORNER",
    )
    for poly in mesh.polygons:
        for loop_index in poly.loop_indices:
            vert_index = mesh.loops[loop_index].vertex_index
            row = vert_index // GRID_SIZE
            col = vert_index % GRID_SIZE
            color_attr.data[loop_index].color = (
                col / float(GRID_SIZE - 1),
                row / float(GRID_SIZE - 1),
                0.25,
                1.0,
            )

    mesh.validate(clean_customdata=False)
    mesh.update(calc_edges=True)

    obj = bpy.data.objects.new("VB_SynthChunk", mesh)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    for poly in mesh.polygons:
        poly.use_smooth = True

    return obj, len(vertices), EXPECTED_UV_CHANNELS


def _export_glb(path: Path) -> None:
    """Export the active selection to ``path`` as a GLB with UVs and tangents."""
    bpy.ops.export_scene.gltf(
        filepath=str(path),
        export_format="GLB",
        use_selection=True,
        export_texcoords=True,
        export_normals=True,
        export_tangents=True,
        export_apply=True,
        export_yup=True,
        export_vertex_color="ACTIVE",
        export_all_vertex_colors=True,
        export_active_vertex_color_when_no_material=True,
        export_draco_mesh_compression_enable=False,
    )


def _import_glb(path: Path) -> bpy.types.Object:
    """Re-import the GLB at ``path`` and return the single mesh object loaded."""
    _clear_scene()
    bpy.ops.import_scene.gltf(
        filepath=str(path),
        merge_vertices=False,
        import_shading="NORMALS",
        import_pack_images=False,
        import_select_created_objects=True,
    )
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if len(meshes) != 1:
        raise AssertionError(f"expected 1 mesh after import, got {len(meshes)}")
    return meshes[0]


def main() -> int:
    """Run the build/export/import sanity round-trip and assert vertex/UV parity."""
    if "--" in sys.argv:
        args = sys.argv[sys.argv.index("--") + 1 :]
    else:
        args = []

    if args:
        glb_path = Path(args[0]).resolve()
    else:
        glb_path = Path(tempfile.gettempdir()) / "vb_chunk_export_sanity.glb"

    _clear_scene()
    _obj, expected_vertices, expected_uv_channels = _build_chunk_mesh()
    glb_path.parent.mkdir(parents=True, exist_ok=True)
    _export_glb(glb_path)
    imported = _import_glb(glb_path)

    imported_mesh = imported.data
    actual_vertices = len(imported_mesh.vertices)
    actual_uv_channels = len(imported_mesh.uv_layers)

    if actual_vertices != expected_vertices:
        raise AssertionError(
            f"vertex count mismatch: expected {expected_vertices}, got {actual_vertices}"
        )
    if actual_uv_channels != expected_uv_channels:
        raise AssertionError(
            "UV channel count mismatch: "
            f"expected {expected_uv_channels}, got {actual_uv_channels}"
        )

    print(
        "PASS codex_export_sanity: "
        f"{actual_vertices} vertices, {actual_uv_channels} UV channels, {glb_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
