from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np

from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack, ValidationIssue


def _make_stack() -> TerrainMaskStack:
    height = np.array(
        [
            [10.0, 12.0, 14.0, 16.0, 18.0],
            [11.0, 13.0, 15.0, 17.0, 19.0],
            [12.0, 14.0, 16.0, 18.0, 20.0],
            [13.0, 15.0, 17.0, 19.0, 21.0],
            [14.0, 16.0, 18.0, 20.0, 22.0],
        ],
        dtype=np.float32,
    )
    stack = TerrainMaskStack(
        tile_size=4,
        cell_size=2.0,
        world_origin_x=100.0,
        world_origin_y=200.0,
        tile_x=3,
        tile_y=7,
        height=height,
        height_min_m=10.0,
        height_max_m=22.0,
        coordinate_system="z-up",
    )
    splat = np.zeros((5, 5, 4), dtype=np.float32)
    splat[..., 0] = 0.6
    splat[..., 1] = 0.2
    splat[..., 2] = 0.1
    splat[..., 3] = 0.1
    stack.set("splatmap_weights_layer", splat, "test")
    return stack


def test_export_manifest_records_contract_failures(monkeypatch):
    import veilbreakers_terrain.handlers.terrain_unity_export as mod

    stack = _make_stack()

    def _fake_validate(contract, files):
        del contract, files
        return [
            ValidationIssue(
                code="FAKE_VALIDATION_FAILURE",
                severity="hard",
                affected_feature="heightmap.raw",
                message="forced failure",
            )
        ]

    monkeypatch.setattr(mod, "validate_bit_depth_contract", _fake_validate)

    with tempfile.TemporaryDirectory() as td:
        manifest = mod.export_unity_manifest(stack, Path(td))

    assert manifest["validation_status"] == "failed"
    assert manifest["validation_issue_count"] == 1
    assert manifest["validation_issues"][0]["code"] == "FAKE_VALIDATION_FAILURE"


def test_unity_import_descriptor_written_with_layer_assets_and_base_height():
    from veilbreakers_terrain.handlers.terrain_unity_export import UNITY_SCALE_FACTOR, export_unity_manifest

    stack = _make_stack()

    with tempfile.TemporaryDirectory() as td:
        export_unity_manifest(stack, Path(td))
        descriptor = json.loads((Path(td) / "unity_import_descriptor.json").read_text())

    assert descriptor["heightmap"]["file"] == "heightmap.raw"
    assert len(descriptor["terrain_layers"]) == 4
    assert descriptor["terrain_layers"][0]["terrain_layer_asset_path"].endswith(".terrainlayer")
    assert descriptor["validation_status"] == "passed"
    assert descriptor["unity_world_origin"][1] == 10.0 * UNITY_SCALE_FACTOR


def test_audio_zones_split_disconnected_components():
    from veilbreakers_terrain.handlers.terrain_unity_export import _audio_zones_json

    stack = _make_stack()
    audio = np.zeros((5, 5), dtype=np.int32)
    audio[0, 0] = 1
    audio[4, 4] = 1
    stack.set("audio_reverb_class", audio, "test")

    payload = _audio_zones_json(stack)
    forest_zones = [zone for zone in payload["zones"] if zone["reverb_class"] == "forest_dense"]

    assert len(forest_zones) == 2
    assert {zone["cell_count"] for zone in forest_zones} == {1}
    heights = {tuple(zone["bounds"]["min"]): zone["bounds"] for zone in forest_zones}
    first_bounds = next(iter(heights.values()))
    assert first_bounds["max"][1] > first_bounds["min"][1]


def test_export_manifest_flags_non_unity_heightmap_resolution():
    from veilbreakers_terrain.handlers.terrain_unity_export import export_unity_manifest

    stack = _make_stack()
    stack.height = np.ones((6, 6), dtype=np.float32)
    stack.set("splatmap_weights_layer", np.ones((6, 6, 1), dtype=np.float32), "test")

    with tempfile.TemporaryDirectory() as td:
        manifest = export_unity_manifest(stack, Path(td))

    assert manifest["direct_unity_heightmap_import_supported"] is False
    assert "2^n+1" in manifest["unity_heightmap_resolution_warning"]


def test_shadow_clipmap_contract_accepts_float32_npy():
    from veilbreakers_terrain.handlers.terrain_unity_export_contracts import (
        UnityExportContract,
        validate_bit_depth_contract,
    )

    issues = validate_bit_depth_contract(
        UnityExportContract(),
        {
            "shadow_clipmap.exr": {
                "bit_depth": 32,
                "encoding": "float32_npy",
            }
        },
    )

    assert issues == []


def test_unity_importer_bridge_files_exist_and_use_native_unity_terrain_api():
    repo_root = Path(__file__).resolve().parents[2]
    importer_path = repo_root / "unity_plugin" / "Editor" / "VbTerrainImporter.cs"
    metadata_path = repo_root / "unity_plugin" / "VbTerrainTileMetadata.cs"

    assert importer_path.exists()
    assert metadata_path.exists()

    source = importer_path.read_text(encoding="utf-8")
    for token in (
        "unity_import_descriptor.json",
        "Terrain.CreateTerrainGameObject",
        ".SetHeights(",
        ".SetAlphamaps(",
        ".SetDetailLayer(",
        ".SetTreeInstances(",
        ".SetNeighbors(",
        "CreateSupplementalMeshes",
        "MeshFilter",
        "MeshRenderer",
        "VbTerrainTileMetadata",
        "TryAppendSupplementalFaceTriangles",
        "TryEarClipSupplementalPolygon",
        "mesh.SetUVs(1, dripMask)",
    ):
        assert token in source
    assert "new int[descriptor.height, descriptor.width]" in source
    assert "counts[y, x]" in source


def test_public_unity_export_handler_writes_bundle():
    from veilbreakers_terrain.handlers.environment import handle_export_unity_bundle

    stack = _make_stack()

    with tempfile.TemporaryDirectory() as td:
        result = handle_export_unity_bundle(
            {
                "mask_stack": stack,
                "output_dir": td,
                "profile": "aaa_open_world",
            }
        )

    assert result["validation_status"] == "passed"
    assert result["terrain_layer_asset_count"] == 4
    assert result["manifest"]["profile"] == "aaa_open_world"
    assert "unity_import_descriptor.json" in result["manifest"]["files"]


def test_tree_instances_skip_out_of_bounds_points():
    from veilbreakers_terrain.handlers.terrain_unity_export import _tree_instances_json

    stack = _make_stack()
    stack.tree_instance_points = np.array(
        [
            [101.0, 201.0, 15.0, 0.0, 1.0],
            [500.0, 800.0, 20.0, 45.0, 2.0],
        ],
        dtype=np.float64,
    )

    payload = _tree_instances_json(stack)

    assert len(payload["trees"]) == 1
    assert payload["skipped_out_of_bounds"] == 1


def test_mcp_unity_export_location_dispatches_to_public_handler():
    from veilbreakers_terrain.src.veilbreakers_mcp.blender_server import dispatch

    stack = _make_stack()

    with tempfile.TemporaryDirectory() as td:
        result = dispatch(
            "unity_export",
            {
                "mask_stack": stack,
                "output_dir": td,
            },
        )

    assert result["status"] == "ok"
    assert result["command"] == "env_export_unity_bundle"
    assert result["result"]["validation_status"] == "passed"


def test_export_manifest_writes_waterfall_velocity_aux_channel():
    from veilbreakers_terrain.handlers.terrain_unity_export import export_unity_manifest

    stack = _make_stack()
    stack.set("waterfall_velocity", np.ones((5, 5, 2), dtype=np.float32), "test")

    with tempfile.TemporaryDirectory() as td:
        manifest = export_unity_manifest(stack, Path(td))

    assert "waterfall_velocity.bin" in manifest["files"]
    assert manifest["files"]["waterfall_velocity.bin"]["shape"] == [5, 5, 2]


def test_export_manifest_writes_supplemental_mesh_specs_for_unity_bridge():
    from veilbreakers_terrain.handlers.terrain_unity_export import (
        _apply_unity_scale,
        export_unity_manifest,
    )

    stack = _make_stack()
    stack.set("cliff_mesh_specs", [
        {
            "mesh_id": "cliff_overhang_000",
            "mesh_type": "cliff_overhang",
            "material_hint": "wet_cliff_drip",
            "tier": "hero",
            "vertices": [
                (100.0, 200.0, 12.0),
                (104.0, 200.0, 12.0),
                (104.0, 202.0, 12.0),
                (100.0, 202.0, 12.0),
            ],
            "faces": [(0, 1, 2, 3)],
        }
    ], "test")
    stack.set("cave_mesh_specs", [
        {
            "mesh_id": "cave_mouth_000",
            "mesh_type": "cave_mouth_surround",
            "material_hint": "cave_entry_ring",
            "tier": "secondary",
            "vertices": [
                (101.0, 201.0, 11.0),
                (102.0, 201.0, 11.0),
                (102.0, 201.0, 13.0),
            ],
            "faces": [(0, 1, 2)],
            "uvs": [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)],
        }
    ], "test")

    with tempfile.TemporaryDirectory() as td:
        manifest = export_unity_manifest(stack, Path(td))
        payload = json.loads((Path(td) / "supplemental_mesh_specs.json").read_text())
        descriptor = json.loads((Path(td) / "unity_import_descriptor.json").read_text())

    assert "supplemental_mesh_specs.json" in manifest["files"]
    assert descriptor["supplemental_mesh_specs_file"] == "supplemental_mesh_specs.json"
    assert len(payload["mesh_specs"]) == 2
    expected_first_vertex = _apply_unity_scale([100.0, 12.0, 200.0])
    assert payload["mesh_specs"][0]["vertices"][0] == {
        "x": expected_first_vertex[0],
        "y": expected_first_vertex[1],
        "z": expected_first_vertex[2],
    }
    assert payload["mesh_specs"][1]["uvs"][2] == {"x": 1.0, "y": 1.0}
