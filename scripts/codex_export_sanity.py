"""Blender 4.5 GLB export/import sanity script for documentation.

Do not run from normal Python. Intended command shape:

    blender --background --python scripts/codex_export_sanity.py -- /tmp/vb_chunk_sanity.glb

The script synthesizes a small chunk mesh from a heightmap, exports GLB,
re-imports it, and asserts a strict round-trip:
    - vertex count parity
    - UV channel count parity
    - per-loop UV coordinate parity (catches glTF V-flip drift)
    - per-loop vertex-color RGBA parity (catches Draco color corruption)

This file is excluded from `pyrightconfig.strict.json` because it can only
run inside Blender's bundled Python (the `bpy` module is not pip-installable
and `bpy.ops.*` calls would otherwise trip every strict member-type check).
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

# Tolerances tuned for glTF lossy round-trip (float32 quantization on UVs;
# 8-bit color channels go through float→u8→float so quantize at 1/255).
UV_EPS = 1e-5
COLOR_EPS = 1.5 / 255.0  # one-LSB tolerance after 8-bit quantization
COLOR_ATTR_NAME = "VB_DebugColor"


def _clear_scene() -> None:
    """Remove every object from the active Blender scene."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def _height_at(row: int, col: int) -> float:
    """Return the synthetic heightmap value at ``(row, col)``."""
    x = col / float(GRID_SIZE - 1)
    y = row / float(GRID_SIZE - 1)
    return 1.25 * math.sin(x * math.pi) * math.cos(y * math.pi * 0.5)


def _build_chunk_mesh() -> tuple[bpy.types.Object, int, int, dict[str, list[tuple[float, ...]]]]:
    """Build a synthetic chunk mesh.

    Returns ``(obj, vertex_count, uv_channels, snapshots)`` where ``snapshots``
    captures pre-export per-loop UV and color data so the round-trip caller
    can compare against the imported mesh and detect glTF V-flip / Draco
    color corruption.
    """
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
        name=COLOR_ATTR_NAME,
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

    # Snapshot per-loop UV + color for round-trip comparison. Order is stable
    # within Blender's loop indexing so the post-import indices align 1:1.
    loop_count = len(mesh.loops)
    snapshots: dict[str, list[tuple[float, ...]]] = {
        "uv0": [tuple(uv0.data[i].uv) for i in range(loop_count)],
        "uv1": [tuple(uv1.data[i].uv) for i in range(loop_count)],
        "color": [tuple(color_attr.data[i].color) for i in range(loop_count)],
    }

    obj = bpy.data.objects.new("VB_SynthChunk", mesh)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    for poly in mesh.polygons:
        poly.use_smooth = True

    return obj, len(vertices), EXPECTED_UV_CHANNELS, snapshots


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


def _assert_uv_round_trip(
    layer_name: str,
    pre_uvs: list[tuple[float, ...]],
    post_layer: bpy.types.MeshUVLoopLayer,
) -> None:
    """Compare pre-export UVs to post-import UVs; surface V-flip explicitly.

    glTF's spec inverts V relative to Blender's convention; the Blender
    exporter normally compensates, but a regression there or in a downstream
    consumer would manifest as ``post_v ≈ 1.0 - pre_v``. We detect that
    pattern explicitly to give a clearer assertion than a generic drift error.
    """
    if len(post_layer.data) != len(pre_uvs):
        raise AssertionError(
            f"{layer_name}: loop count drift — expected {len(pre_uvs)}, got {len(post_layer.data)}"
        )

    flip_hits = 0
    for loop_idx, (pre_u, pre_v) in enumerate(pre_uvs):
        post_u, post_v = post_layer.data[loop_idx].uv
        if abs(pre_u - post_u) > UV_EPS:
            raise AssertionError(
                f"{layer_name} U drift at loop {loop_idx}: pre={pre_u:.6f}, post={post_u:.6f}"
            )
        if abs(pre_v - post_v) > UV_EPS:
            if abs((1.0 - pre_v) - post_v) < UV_EPS:
                flip_hits += 1
            else:
                raise AssertionError(
                    f"{layer_name} V drift at loop {loop_idx}: "
                    f"pre={pre_v:.6f}, post={post_v:.6f} "
                    f"(not consistent with V-flip)"
                )
    if flip_hits:
        raise AssertionError(
            f"{layer_name}: detected V-flip on {flip_hits}/{len(pre_uvs)} loops "
            f"(post_v == 1 - pre_v); glTF Y-flip compensation regressed"
        )


def _assert_color_round_trip(
    pre_colors: list[tuple[float, ...]],
    imported_mesh: bpy.types.Mesh,
) -> None:
    """Compare per-loop COLOR_0 RGBA pre-export vs post-import.

    Draco compression can quantize or strip vertex colors; a count-only
    check would miss that. We assert per-channel parity within COLOR_EPS.
    """
    color_attr = imported_mesh.color_attributes.get(COLOR_ATTR_NAME)
    if color_attr is None and len(imported_mesh.color_attributes) > 0:
        # Some glTF importers rename the active color layer to COLOR_0/Color.
        color_attr = imported_mesh.color_attributes[0]
    if color_attr is None:
        raise AssertionError(
            f"imported_mesh has no color attribute (expected {COLOR_ATTR_NAME!r}); "
            f"Draco compression may have stripped vertex colors"
        )
    if len(color_attr.data) != len(pre_colors):
        raise AssertionError(
            f"COLOR_0 loop count drift — expected {len(pre_colors)}, got {len(color_attr.data)}"
        )
    for loop_idx, pre_rgba in enumerate(pre_colors):
        post_rgba = tuple(color_attr.data[loop_idx].color)
        for ch_idx, (pre_v, post_v) in enumerate(zip(pre_rgba, post_rgba)):
            if abs(pre_v - post_v) > COLOR_EPS:
                raise AssertionError(
                    f"COLOR_0 channel {ch_idx} drift at loop {loop_idx}: "
                    f"pre={pre_v:.4f}, post={post_v:.4f} "
                    f"(tolerance {COLOR_EPS:.4f})"
                )


def main() -> int:
    """Run the build/export/import sanity round-trip and assert vertex/UV/color parity."""
    if "--" in sys.argv:
        args = sys.argv[sys.argv.index("--") + 1 :]
    else:
        args = []

    if args:
        glb_path = Path(args[0]).resolve()
    else:
        glb_path = Path(tempfile.gettempdir()) / "vb_chunk_export_sanity.glb"

    _clear_scene()
    _obj, expected_vertices, expected_uv_channels, pre_snapshots = _build_chunk_mesh()
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

    _assert_uv_round_trip("UV0", pre_snapshots["uv0"], imported_mesh.uv_layers[0])
    _assert_uv_round_trip("UV1", pre_snapshots["uv1"], imported_mesh.uv_layers[1])
    _assert_color_round_trip(pre_snapshots["color"], imported_mesh)

    print(
        "PASS codex_export_sanity: "
        f"{actual_vertices} vertices, {actual_uv_channels} UV channels, "
        f"COLOR_0 + UV0/UV1 round-trip parity verified -- {glb_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
