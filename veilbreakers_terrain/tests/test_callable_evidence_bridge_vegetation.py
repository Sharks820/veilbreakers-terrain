"""Behavior evidence for bridge, vegetation, and Blender live-probe wrappers.

The word Blender is intentional: the verification matrix treats this as a
Blender/live probe file for wrappers that fail closed when bpy is unavailable.
"""

from __future__ import annotations

import math
import builtins
from types import SimpleNamespace

import pytest

from veilbreakers_terrain.handlers import _bridge_mesh as bridge
from veilbreakers_terrain.handlers import blender_capability_bridge as bcb
from veilbreakers_terrain.handlers import vegetation_lsystem as lsys
from veilbreakers_terrain.handlers import vegetation_system as veg


def test_bridge_mesh_helpers_generate_connected_swept_geometry():
    centerline = [(0.0, 0.0, 4.0), (6.0, 0.5, 4.8), (12.0, 3.0, 5.5)]

    assert bridge._resolved_bridge_style("wood", span=12.5, width=2.6) == "timber_beam"
    assert bridge._resolved_bridge_style("stone", span=32.0, width=5.0) == "stone_viaduct"
    assert "wood_rails" in bridge._bridge_material_slots("timber_beam")
    profile = bridge._bridge_profile(
        requested_style="stone",
        resolved_style="stone_viaduct",
        span=32.0,
        width=5.0,
    )
    assert profile["arch_count"] >= 2
    assert profile["approach_transition_m"] >= 2.0

    assert bridge._polyline_length(centerline) > 12.0
    samples = bridge._resample_centerline(centerline, spacing_m=2.0)
    assert samples[0] == centerline[0]
    assert samples[-1] == centerline[-1]
    assert len(samples) > len(centerline)

    tangent, normal = bridge._frame_at(samples, 1)
    assert math.isclose(math.hypot(tangent[0], tangent[1]), 1.0, rel_tol=1e-6)
    assert abs(tangent[0] * normal[0] + tangent[1] * normal[1]) < 1e-6

    verts, faces = bridge._oriented_box(
        samples[0],
        tangent,
        normal,
        half_width=1.5,
        half_height=0.2,
        half_length=0.75,
    )
    assert len(verts) == 8
    assert len(faces) == 6

    all_verts: list[tuple[float, float, float]] = []
    all_faces: list[tuple[int, ...]] = []
    bridge._append_part(all_verts, all_faces, (verts, faces))
    bridge._append_swept_rail(
        all_verts,
        all_faces,
        samples,
        side=1.0,
        side_offset=1.55,
        z_center=0.8,
        half_depth=0.08,
        half_height=0.12,
    )
    bridge._append_swept_tube(all_verts, all_faces, samples, radius=0.05, sides=6)
    assert len(all_verts) > len(verts)
    assert len(all_faces) > len(faces)

    spec = bridge._generate_swept_centerline_bridge_mesh(
        centerline=centerline,
        width=3.0,
        style="stone",
        support_foundation_z=0.0,
    )
    assert spec["vertices"]
    assert spec["faces"]
    meta = spec["metadata"]["bridge_profile"]
    assert meta["swept_centerline"] is True
    assert meta["has_side_walls"] is True
    assert meta["has_bottom"] is True

    rope = bridge._generate_swept_centerline_bridge_mesh(
        centerline=centerline,
        width=2.0,
        style="rope",
    )
    rope_profile = rope["metadata"]["bridge_profile"]
    assert rope_profile["resolved_style"] == "rope"
    assert rope_profile["unsupported_mid_control_points_ignored"] is True
    assert rope_profile["centerline_point_count"] == 2


def test_blender_capability_bridge_fails_closed_without_bpy_or_bmesh(monkeypatch):
    real_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name in {"bpy", "bmesh"}:
            raise ModuleNotFoundError(f"No module named '{name}'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    bpy_mod, bpy_error = bcb._require_bpy()
    assert bpy_mod is None
    assert bpy_error["error"] == "bpy_unavailable"

    bmesh_mod, bmesh_error = bcb._require_bmesh()
    assert bmesh_mod is None
    assert bmesh_error["error"] == "bmesh_unavailable"

    fake_bpy = SimpleNamespace(data=SimpleNamespace(objects={}))
    obj, err = bcb._get_mesh_object(fake_bpy, "missing")
    assert obj is None
    assert err == {"status": "error", "error": "object_not_found", "name": "missing"}

    assert bcb.set_render_engine("CYCLES")["error"] == "bpy_unavailable"
    assert bcb.collection_link_object("obj", "coll")["error"] == "bpy_unavailable"
    assert bcb.geometry_nodes_create_group("TerrainGN")["error"] == "bpy_unavailable"
    assert bcb.geometry_nodes_add_node("TerrainGN", "GeometryNodeSubdivideMesh")["error"] == "bpy_unavailable"
    assert bcb.geometry_nodes_link_sockets("TerrainGN", "A", "0", "B", "0")["error"] == "bpy_unavailable"
    assert bcb.geometry_nodes_assign_to_object("Terrain", "TerrainGN")["error"] == "bpy_unavailable"
    assert bcb.geometry_nodes_dump("TerrainGN")["error"] == "bpy_unavailable"


def test_lsystem_tree_pipeline_outputs_mesh_wind_impostor_and_gpu_payloads():
    expanded = lsys.expand_lsystem("F", {"F": "F[+F]"}, 2, seed=7)
    assert expanded.count("F") == 4
    rx, ry, rz = lsys._rotate_vector(1.0, 0.0, 0.0, 0.0, 0.0, 1.0, math.pi / 2.0)
    assert abs(rx) < 1e-6
    assert ry == pytest.approx(1.0)
    heading, right = lsys._reorthogonalize(0.0, 0.0, 2.0, 1.0, 0.0, 0.5)
    assert heading == pytest.approx((0.0, 0.0, 1.0))
    assert abs(sum(a * b for a, b in zip(heading, right))) < 1e-6

    segments = lsys.interpret_lsystem("F[+F][-F]", segment_length=0.5, seed=3)
    assert segments
    ring = lsys._generate_cylinder_ring((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 0.2, 8)
    assert len(ring) == 8
    mesh = lsys.branches_to_mesh(segments, ring_segments=6)
    assert mesh["vertex_count"] > 0
    assert mesh["face_count"] > 0

    roots = lsys.generate_roots((0.0, 0.0, 0.0), 0.4, num_roots=3, num_segments=3, seed=9)
    assert len(roots) == 9
    tree = lsys.generate_lsystem_tree(
        {"tree_type": "oak", "iterations": 2, "seed": 11, "ring_segments": 5}
    )
    assert tree["metadata"]["branch_segments"] > 0
    assert tree["vertex_count"] > 0

    tips = [
        {"position": pos, "direction": direction, "radius": radius}
        for pos, direction, radius in zip(
            tree["tip_positions"][:4],
            tree["tip_directions"][:4],
            tree["tip_radii"][:4],
        )
    ]
    leaves = lsys.generate_leaf_cards(tips, density=1.0, seed=5)
    assert leaves["cards_generated"] > 0

    winded = lsys.bake_wind_vertex_colors(dict(tree))
    assert len(winded["wind_colors"]) == winded["vertex_count"]

    views = lsys._compute_impostor_atlas_views(8, 3, 3)
    assert len(views) == 9
    assert lsys._quad_normal((0, 0, 0), (1, 0, 0), (1, 1, 0)) == pytest.approx((0, 0, 1))
    impostor = lsys.generate_billboard_impostor({"height": 5.0, "width": 2.0, "num_views": 8})
    assert impostor["impostor_spec"]["total_views"] == 9
    quat = lsys._euler_deg_to_quaternion(0.0, 0.0, 90.0)
    assert math.isclose(sum(v * v for v in quat), 1.0, rel_tol=1e-6)
    radius = lsys._compute_species_bounds_radius(
        [{"mesh_name": "oak", "uniform_scale": 2.0}],
        {"oak": 3.0},
    )
    assert radius == pytest.approx(6.0)
    gpu = lsys.prepare_gpu_instancing_export(
        {
            "instances": [
                {
                    "mesh_name": "oak",
                    "position": [1.0, 2.0, 3.0],
                    "rotation": [0.0, 0.0, 90.0],
                    "scale": 1.5,
                    "lod_level": 2,
                }
            ],
            "mesh_half_extents": {"oak": 2.0},
        }
    )
    assert gpu["status"] == "success"
    assert gpu["bounds_radius"]["oak"] == pytest.approx(3.0)


def test_vegetation_system_places_lod_instances_and_density_maps():
    vertices = [(float(x), float(y), (x + y) * 0.02) for x in range(6) for y in range(6)]
    normals = [(0.0, 0.0, 1.0) for _ in vertices]
    placements = veg.compute_vegetation_placement(
        vertices,
        [],
        normals,
        "grasslands",
        (0.0, 0.0, 5.0, 5.0),
        seed=13,
        min_distance=1.0,
        water_level=0.0,
        camera_position=(2.5, 2.5, 2.0),
        lod_distances=[2.0, 4.0, 8.0],
    )
    assert placements
    assert veg._max_slope_for_category("trees") < veg._max_slope_for_category("rocks")
    colors = veg.compute_wind_vertex_colors([(0, 0, 0), (1, 0, 2), (0, 1, 4)])
    assert len(colors) == 3
    assert all(0.0 <= channel <= 1.0 for color in colors for channel in color)
    winter = veg.get_seasonal_variant("tree", "winter")
    assert winter["affects_leaves"] is True
    assert winter["leaf_density"] < 1.0

    spec = veg.build_vegetation_placement_spec(
        placements[:5],
        "grasslands",
        lod_distances=[1.0, 3.0, 6.0],
        camera_position=(0.0, 0.0, 0.0),
    )
    assert spec["instance_count"] == len(spec["placements"])
    assert spec["species_density"]

    class Stack:
        def __init__(self) -> None:
            import numpy as np

            self.height = np.zeros((3, 3), dtype=np.float32)
            self._channels = {"biome_id": np.full((3, 3), 10, dtype=np.uint8)}
            self.writes = []

        def get(self, name):
            return self._channels.get(name)

        def set(self, name, value, source):
            self.writes.append((name, value, source))

    stack = Stack()
    density = veg.build_biome_density_map(stack, "grasslands")
    assert density
    assert stack.writes and stack.writes[0][0] == "detail_density"


def test_vegetation_placement_samples_regular_raster_by_world_axes(monkeypatch):
    from veilbreakers_terrain.handlers import _scatter_engine

    def _single_point(width, depth, min_distance, seed=0):
        return [(1.6, 2.1)]

    monkeypatch.setattr(_scatter_engine, "poisson_disk_sample", _single_point)
    monkeypatch.setitem(
        veg.BIOME_VEGETATION_SETS,
        "phase7_test",
        {
            "trees": [],
            "ground_cover": [
                {
                    "type": "probe_plant",
                    "density": 1.0,
                    "scale_range": (1.0, 1.0),
                    "min_altitude": 0.0,
                    "max_altitude": 1.0,
                }
            ],
            "rocks": [],
        },
    )

    vertices = [
        (float(x), float(y), float(y * 10 + x))
        for y in range(4)
        for x in range(4)
    ]
    vertices = list(reversed(vertices))
    normals = [(0.0, 0.0, 1.0) for _ in vertices]

    placements = veg.compute_vegetation_placement(
        vertices,
        [],
        normals,
        "phase7_test",
        (0.0, 0.0, 3.0, 3.0),
        seed=7,
        min_distance=0.5,
        water_level=0.0,
        camera_position=(1.6, 2.1, 5.0),
        lod_distances=[1.0, 2.0],
    )

    assert len(placements) == 1
    assert placements[0]["position"][:2] == pytest.approx((1.6, 2.1))
    assert placements[0]["position"][2] == pytest.approx(22.0)
