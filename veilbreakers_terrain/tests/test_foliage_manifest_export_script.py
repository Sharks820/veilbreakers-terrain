from __future__ import annotations

import json
import math
from pathlib import Path

from scripts import export_foliage_manifest as exporter


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_spec_from_points_preserves_engine_yaw_without_dcc_remap():
    yaw = math.radians(90.0)
    points = [
        {
            "position": [4.0, 8.0, 12.0],
            "orient": [0.0, 0.0, math.sin(yaw * 0.5), math.cos(yaw * 0.5)],
            "scale": [1.2, 1.2, 1.2],
            "species_id": "tree_veil_healthy",
            "lod_hint": 1,
        }
    ]

    spec = exporter.build_spec_from_points(points, biome="thornwood")

    placement = spec["placements"][0]
    assert placement["mesh_name"] == "tree_veil_healthy"
    assert math.isclose(placement["rotation"], 90.0)
    assert placement["scale"] == 1.2
    assert placement["lod_level"] == 1


def test_export_foliage_manifest_cli_writes_unity_gpu_schema(tmp_path: Path):
    scatter = tmp_path / "scatter_points.json"
    mesh_library = tmp_path / "mesh_library.json"
    out = tmp_path / "foliage_placement_manifest.json"
    _write_json(
        scatter,
        {
            "points": [
                {
                    "position": [10.0, 20.0, 30.0],
                    "yaw_rad": math.radians(45.0),
                    "scale": 1.1,
                    "species_id": "tree_veil_healthy",
                    "lod_level": 0,
                    "biome": "thornwood",
                    "moisture": 0.35,
                    "seed": 123,
                }
            ]
        },
    )
    _write_json(
        mesh_library,
        {
            "tree_veil_healthy": {
                "mesh_asset_path": "Assets/Foliage/Trees/veil_healthy.fbx",
                "category": "trees",
                "lod_meshes": ["Assets/Foliage/Trees/veil_healthy_lod1.fbx"],
                "unity_render_mode": "terrain_tree",
                "wind_color_baked": True,
                "physics_collider": "capsule",
            }
        },
    )

    rc = exporter.main(
        [
            "--input",
            str(scatter),
            "--mesh-library",
            str(mesh_library),
            "--output",
            str(out),
            "--biome",
            "thornwood",
            "--lod-distances",
            "15,35,60,200",
        ]
    )

    assert rc == 0
    manifest = json.loads(out.read_text(encoding="utf-8"))
    assert manifest["instance_count"] == 1
    assert manifest["mesh_library"][0]["unity_render_mode"] == "terrain_tree"
    assert manifest["instances"][0]["position_terrain_norm"]
    dumped = json.dumps(manifest).lower()
    assert "3ds" not in dumped
    assert "forest" not in dumped
    assert "maxscript" not in dumped
