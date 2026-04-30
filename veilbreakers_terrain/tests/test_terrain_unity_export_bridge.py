from __future__ import annotations

import json
import tempfile
from types import SimpleNamespace
from pathlib import Path

import numpy as np
import pytest

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


def _make_unity_valid_stack() -> TerrainMaskStack:
    height = np.linspace(10.0, 22.0, 33 * 33, dtype=np.float32).reshape(33, 33)
    stack = TerrainMaskStack(
        tile_size=32,
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
    splat = np.zeros((33, 33, 4), dtype=np.float32)
    splat[..., 0] = 0.6
    splat[..., 1] = 0.2
    splat[..., 2] = 0.1
    splat[..., 3] = 0.1
    stack.set("splatmap_weights_layer", splat, "test")
    return stack


def _set_channel(stack: TerrainMaskStack, channel: str, value):
    stack.set(channel, value, "test_fixture")
    return value


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
        manifest = mod.export_unity_manifest(
            stack,
            Path(td),
            strict_unity_resolution=False,
            fail_on_validation_error=False,
        )

    assert manifest["validation_status"] == "failed"
    assert manifest["validation_issue_count"] == 1
    assert manifest["validation_issues"][0]["code"] == "FAKE_VALIDATION_FAILURE"


def test_export_manifest_hard_validation_raises_by_default(monkeypatch):
    import veilbreakers_terrain.handlers.terrain_unity_export as mod

    stack = _make_unity_valid_stack()

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
        with pytest.raises(ValueError, match="FAKE_VALIDATION_FAILURE"):
            mod.export_unity_manifest(stack, Path(td), strict_unity_resolution=False)
        assert (Path(td) / "manifest.json").exists()
        assert not (Path(td) / "unity_import_descriptor.json").exists()


def test_unity_import_descriptor_written_with_layer_assets_and_base_height():
    from veilbreakers_terrain.handlers.terrain_unity_export import UNITY_SCALE_FACTOR, export_unity_manifest

    stack = _make_stack()

    with tempfile.TemporaryDirectory() as td:
        manifest = export_unity_manifest(stack, Path(td), strict_unity_resolution=False)
        descriptor = json.loads((Path(td) / "unity_import_descriptor.json").read_text())
        tangent_png_header = (Path(td) / "terrain_normals_tangent.png").read_bytes()[:4]

    assert descriptor["heightmap"]["file"] == "heightmap.raw"
    assert len(descriptor["terrain_layers"]) == 4
    assert descriptor["terrain_layers"][0]["terrain_layer_asset_path"].endswith(".terrainlayer")
    assert descriptor["validation_status"] == "passed"
    assert descriptor["unity_world_origin"][1] == 10.0 * UNITY_SCALE_FACTOR
    assert manifest["height_min_m"] == 10.0
    assert manifest["height_max_m"] == 22.0
    assert descriptor["height_min_m"] == 10.0 * UNITY_SCALE_FACTOR
    assert descriptor["height_max_m"] == 22.0 * UNITY_SCALE_FACTOR
    assert descriptor["terrain_normal_map_file"] == "terrain_normals_tangent.png"
    assert descriptor["mesh_attributes_file"] == "mesh_attributes.npz"
    assert set(manifest["mesh_attributes_present"]) == {
        "slope_angle",
        "flow_accumulation",
        "wetness",
        "biome_id",
        "cliff_mask",
        "protected_zone_id",
    }
    assert manifest["files"]["mesh_attributes.npz"]["encoding"] == "npz_named_arrays"
    assert manifest["files"]["terrain_normals_tangent.png"]["encoding"] == "png_rgba8_tangent_space_normal"
    assert tangent_png_header == b"\x89PNG"


def test_tangent_space_normal_map_packs_flat_heightfield():
    from veilbreakers_terrain.handlers.terrain_unity_export import _pack_tangent_space_normal_rgba

    packed = _pack_tangent_space_normal_rgba(np.zeros((3, 3), dtype=np.float32), 1.0)

    assert packed.shape == (3, 3, 4)
    assert packed.dtype == np.uint8
    assert packed[1, 1].tolist() == [128, 128, 255, 255]


def test_heightmap_raw_export_is_flipped_once(monkeypatch):
    import veilbreakers_terrain.handlers.terrain_unity_export as mod

    stack = TerrainMaskStack(
        tile_size=1,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32),
        height_min_m=1.0,
        height_max_m=4.0,
    )
    quantized = mod._quantize_heightmap(stack)
    assert quantized.tolist() == [[43690, 65535], [0, 21845]]

    captured = {}

    def _capture_write(path: Path, data: bytes) -> int:
        captured["path"] = path
        captured["data"] = data
        return len(data)

    monkeypatch.setattr(Path, "write_bytes", _capture_write)
    monkeypatch.setattr(Path, "stat", lambda _path: SimpleNamespace(st_size=len(captured["data"])))
    monkeypatch.setattr(mod, "_sha256", lambda _path: "sha256")

    files = {}
    mod._write_raw_array(
        files,
        Path("unused"),
        filename="heightmap.raw",
        channel="heightmap_raw_u16",
        arr=quantized,
        encoding="raw_u16_le",
        flip_vertical=False,
    )
    written = np.frombuffer(captured["data"], dtype="<u2").reshape(2, 2)
    np.testing.assert_array_equal(written, quantized)
    assert files["heightmap.raw"]["flip_vertical"] is False


def test_flat_heightmap_quantizes_to_zero():
    from veilbreakers_terrain.handlers.terrain_unity_export import _quantize_heightmap

    stack = TerrainMaskStack(
        tile_size=2,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=np.full((3, 3), 7.0, dtype=np.float32),
        height_min_m=7.0,
        height_max_m=7.0,
    )
    quantized = _quantize_heightmap(stack)
    assert quantized.dtype == np.uint16
    assert int(quantized.max()) == 0


def test_write_raw_array_scrubs_non_finite_float_values(tmp_path):
    from veilbreakers_terrain.handlers import terrain_unity_export as mod

    files = {}
    arr = np.array([[np.nan, np.inf], [-np.inf, 1.25]], dtype=np.float32)

    mod._write_raw_array(
        files,
        tmp_path,
        filename="finite.raw",
        channel="debug_float",
        arr=arr,
        encoding="raw_f32_le",
        flip_vertical=False,
    )

    written = np.frombuffer((tmp_path / "finite.raw").read_bytes(), dtype="<f4").reshape(2, 2)
    assert np.isfinite(written).all()
    np.testing.assert_array_equal(written, np.array([[0.0, 0.0], [0.0, 1.25]], dtype=np.float32))


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


def test_audio_zones_export_explicit_zone_list_without_reverb_raster():
    from veilbreakers_terrain.handlers.terrain_unity_export import _audio_zones_json

    stack = _make_unity_valid_stack()
    stack.set(
        "audio_zone_list",
        [
            {
                "id": "cave_000",
                "preset": "cave",
                "boundary_polygon": [(1, 1), (1, 3), (3, 3), (3, 1)],
                "rt60_seconds": 1.4,
                "echo_delay_ms": 28.0,
                "occlusion_weight": 0.8,
                "wet_send_default": 0.35,
                "class_id": 3,
                "cell_count": 9,
            }
        ],
        "test",
    )

    payload = _audio_zones_json(stack)

    assert payload["zones"][0]["zone_id"] == "cave_000"
    assert payload["zones"][0]["reverb_class"] == "cave"
    assert payload["zones"][0]["bounds"]["max"][1] > payload["zones"][0]["bounds"]["min"][1]


def test_export_manifest_rejects_non_unity_heightmap_resolution_by_default():
    from veilbreakers_terrain.handlers.terrain_unity_export import export_unity_manifest

    stack = _make_stack()
    _set_channel(stack, "height", np.ones((6, 6), dtype=np.float32))
    stack.set("splatmap_weights_layer", np.ones((6, 6, 1), dtype=np.float32), "test")

    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(ValueError, match="2\\^n\\+1"):
            export_unity_manifest(stack, Path(td))


def test_export_manifest_can_flag_non_unity_heightmap_resolution_for_diagnostics():
    from veilbreakers_terrain.handlers.terrain_unity_export import export_unity_manifest

    stack = _make_stack()
    _set_channel(stack, "height", np.ones((6, 6), dtype=np.float32))
    stack.set("splatmap_weights_layer", np.ones((6, 6, 1), dtype=np.float32), "test")

    with tempfile.TemporaryDirectory() as td:
        manifest = export_unity_manifest(stack, Path(td), strict_unity_resolution=False)

    assert manifest["direct_unity_heightmap_import_supported"] is False
    assert "2^n+1" in manifest["unity_heightmap_resolution_warning"]


def test_export_manifest_uses_water_elevation_depth_and_flow_contract_files():
    from veilbreakers_terrain.handlers.terrain_unity_export import UNITY_SCALE_FACTOR, export_unity_manifest

    stack = _make_stack()
    water_mask = np.zeros((5, 5), dtype=np.float32)
    water_mask[1:4, 1:4] = 1.0
    stack.set("water_surface_mask", water_mask, "test")
    stack.set("water_surface_elevation_m", np.full((5, 5), 123.0, dtype=np.float32), "test")
    stack.set("water_depth_m", np.full((5, 5), 4.0, dtype=np.float32), "test")
    stack.set("flow_direction", np.dstack([
        np.ones((5, 5), dtype=np.float32),
        np.zeros((5, 5), dtype=np.float32),
    ]), "test")
    stack.set("flow_accumulation", np.arange(25, dtype=np.float32).reshape(5, 5), "test")

    with tempfile.TemporaryDirectory() as td:
        manifest = export_unity_manifest(stack, Path(td), strict_unity_resolution=False)
        descriptor = json.loads((Path(td) / "unity_import_descriptor.json").read_text())

    assert manifest["water_surface_elevation_m"] == pytest.approx(123.0)
    assert descriptor["water_level_unity_units"] == pytest.approx(123.0 * UNITY_SCALE_FACTOR)
    assert descriptor["water_surface_elevation_file"] == "water_surface_elevation_m.bin"
    assert descriptor["water_depth_file"] == "water_depth_m.bin"
    assert descriptor["flow_direction_file"] == "flow_direction.bin"
    assert descriptor["flow_accumulation_file"] == "flow_accumulation.bin"
    for name in (
        "water_surface_elevation_m.bin",
        "water_depth_m.bin",
        "flow_direction.bin",
        "flow_accumulation.bin",
    ):
        assert name in manifest["files"]


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


def test_shadow_clipmap_contract_accepts_unity_bundle_raw_f32():
    from veilbreakers_terrain.handlers.terrain_unity_export_contracts import (
        UnityExportContract,
        validate_bit_depth_contract,
    )

    issues = validate_bit_depth_contract(
        UnityExportContract(),
        {
            "shadow_clipmap.bin": {
                "bit_depth": 32,
                "encoding": "raw_f32_le",
            }
        },
    )

    assert issues == []


def test_export_manifest_writes_phase6_array_channels():
    from veilbreakers_terrain.handlers.terrain_unity_export import export_unity_manifest

    stack = _make_stack()
    stack.set("grass_density_map", np.full((5, 5), 0.25, dtype=np.float32), "test")
    stack.set("terrain_displacement", np.full((5, 5), 0.1, dtype=np.float32), "test")
    stack.set("shadow_clipmap", np.full((5, 5), 0.75, dtype=np.float32), "test")
    stack.set("corruption_map", np.full((5, 5), 0.5, dtype=np.float32), "test")

    with tempfile.TemporaryDirectory() as td:
        manifest = export_unity_manifest(stack, Path(td), strict_unity_resolution=False)

    for filename in (
        "grass_density_map.bin",
        "terrain_displacement.bin",
        "shadow_clipmap.bin",
        "corruption_map.bin",
    ):
        assert filename in manifest["files"]
        assert manifest["files"][filename]["shape"] == [5, 5]

    assert manifest["validation_status"] == "passed"
    shadow_meta = manifest["files"]["shadow_clipmap.bin"]
    assert shadow_meta["dtype"] == "float32"
    assert shadow_meta["bit_depth"] == 32
    assert shadow_meta["encoding"] == "raw_f32_le"
    assert shadow_meta["precision_contract"] == "shadow_clipmap_32f"


def test_export_manifest_coerces_float_channels_to_unity_float32():
    from veilbreakers_terrain.handlers.terrain_unity_export import export_unity_manifest

    stack = _make_stack()
    stack.set("terrain_displacement", np.full((5, 5), 0.1, dtype=np.float64), "test")

    with tempfile.TemporaryDirectory() as td:
        manifest = export_unity_manifest(stack, Path(td), strict_unity_resolution=False)

    displacement_meta = manifest["files"]["terrain_displacement.bin"]
    assert displacement_meta["dtype"] == "float32"
    assert displacement_meta["bit_depth"] == 32
    assert displacement_meta["encoding"] == "raw_f32_le"


def test_export_manifest_records_tile_biome_distribution():
    from veilbreakers_terrain.handlers.terrain_unity_export import export_unity_manifest

    stack = _make_stack()
    stack.biome_names = ["forest", "swamp"]
    stack.set("biome_id", np.array(
        [
            [0, 0, 1, 1, 1],
            [0, 0, 1, 1, 1],
            [0, 0, 1, 1, 1],
            [0, 0, 1, 1, 1],
            [0, 0, 1, 1, 1],
        ],
        dtype=np.uint8,
    ), "test")

    with tempfile.TemporaryDirectory() as td:
        manifest = export_unity_manifest(stack, Path(td), strict_unity_resolution=False)

    assert manifest["tile_biome_id"] == 1
    assert manifest["tile_biome_name"] == "swamp"
    assert manifest["biome_distribution"][0]["cell_count"] == 15


def test_phase6_zone_json_contains_priority_z_radius_density_and_normal_rotation():
    from veilbreakers_terrain.handlers.terrain_unity_export import (
        _decals_json,
        _gameplay_zones_json,
        _wildlife_zones_json,
    )

    stack = _make_stack()
    gameplay = np.zeros((5, 5), dtype=np.int32)
    gameplay[1:3, 1:3] = 6
    gameplay[3:5, 3:5] = 1
    stack.set("gameplay_zone", gameplay, "test")
    wildlife = np.zeros((5, 5), dtype=np.float32)
    wildlife[1:4, 1:4] = 0.8
    stack.set("wildlife_affinity", {"wolf": wildlife}, "test")
    decal = np.zeros((5, 5), dtype=np.float32)
    decal[2, 2] = 1.0
    stack.set("decal_density", {"mud": decal}, "test")

    zones = _gameplay_zones_json(stack)["zones"]
    assert zones[0]["priority"] >= zones[-1]["priority"]
    assert zones[0]["z_max_m"] > zones[0]["z_min_m"]
    assert zones[0]["trigger_radius_m"] > 0.0

    volume = _wildlife_zones_json(stack)["volumes"][0]
    assert volume["area_m2"] == 9 * stack.cell_size ** 2
    assert volume["density_per_area_m2"] > 0.0

    placement = _decals_json(stack)["decals"]["mud"]["placements"][0]
    assert "rotation_euler_degrees" in placement
    assert len(placement["rotation_euler_degrees"]) == 3


def test_unity_plugin_metadata_and_descriptor_cover_phase6_files():
    repo_root = Path(__file__).resolve().parents[2]
    importer_source = (repo_root / "unity_plugin" / "Editor" / "VbTerrainImporter.cs").read_text(encoding="utf-8")
    metadata_source = (repo_root / "unity_plugin" / "VbTerrainTileMetadata.cs").read_text(encoding="utf-8")

    for token in (
        "audio_zones_file",
        "gameplay_zones_file",
        "wildlife_zones_file",
        "decals_file",
        "particle_emitter_specs_file",
        "water_shader_manifest_file",
        "water_surface_elevation_file",
        "water_depth_file",
        "flow_direction_file",
        "flow_accumulation_file",
        "atmospheric_volumes_file",
        "wind_field_descriptor",
        "cloud_shadow_descriptor",
        "navmesh_area_id_file",
        "navmesh_data_asset_path",
        "WarnUnhandledDescriptorKeys",
        "ExtractTopLevelJsonObjectKeys",
    ):
        assert token in importer_source

    for token in (
        "TileSize",
        "CellSize",
        "HeightMinMeters",
        "HeightMaxMeters",
        "HeightScaleFactor",
        "ValidationStatus",
        "ValidationIssueCount",
        "SeamContractWorldId",
        "TerrainNormalMapFile",
        "TerrainNormalMapAssetPath",
        "NavMeshAreaIdFile",
        "NavMeshDataAssetPath",
    ):
        assert token in metadata_source

    assert "ImportTerrainNormalMapAsset" in importer_source
    assert "TextureImporterType.NormalMap" in importer_source
    assert "terrain_normal_map_file" in importer_source
    assert "BuildNavMeshDataAsset" in importer_source
    assert "NavMeshBuilder.BuildNavMeshData" in importer_source


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
        "FindExistingTerrain",
        "ClearGeneratedChildren",
        ".SetHeights(",
        ".SetAlphamaps(",
        ".SetDetailLayer(",
        ".SetTreeInstances(",
        ".SetNeighbors(",
        "CreateSupplementalMeshes",
        "MeshFilter",
        "MeshRenderer",
        "VbTerrainTileMetadata",
        "CreateSidecarReferences",
        "VbTerrainSidecarReference",
        "AssetDatabase.LoadAssetAtPath<TerrainData>",
        "Shader.Find(\"HDRP/TerrainLit\")",
        "TryAppendSupplementalFaceTriangles",
        "TryEarClipSupplementalPolygon",
        "mesh.SetUVs(1, dripMask)",
        "RejectFailedDescriptor",
        "validation_status, \"failed\", StringComparison.OrdinalIgnoreCase",
        "NavMeshBuildSourceShape.Terrain",
        "NavMeshBuildSourceShape.ModifierBox",
        "IsUnityHeightmapResolution",
        "UnityOriginY",
        "water_level_unity_units - UnityOriginY",
        "WaterSurfaceElevation",
        "WaterDepth",
        "FlowDirection",
        "FlowAccumulation",
        "GeneratedTrees",
        "NavMeshDataAssetPath",
    ):
        assert token in source
    assert "new int[descriptor.height, descriptor.width]" in source
    assert "counts[y, x]" in source


def test_public_unity_export_handler_writes_bundle():
    from veilbreakers_terrain.handlers.environment import handle_export_unity_bundle

    stack = _make_unity_valid_stack()

    with tempfile.TemporaryDirectory() as td:
        result = handle_export_unity_bundle(
            {
                "mask_stack": stack,
                "output_dir": td,
                "profile": "aaa_open_world",
                "out_of_view_ok": True,
            }
        )

    assert result["validation_status"] == "passed"
    assert result["terrain_layer_asset_count"] == 4
    assert result["manifest"]["profile"] == "aaa_open_world"
    assert "unity_import_descriptor.json" in result["manifest"]["files"]


def test_public_unity_export_handler_enforces_protocol_boundary():
    from veilbreakers_terrain.handlers.environment import handle_export_unity_bundle
    from veilbreakers_terrain.handlers.terrain_protocol import ProtocolViolation

    stack = _make_stack()

    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(ProtocolViolation, match="placement_class"):
            handle_export_unity_bundle(
                {
                    "mask_stack": stack,
                    "output_dir": td,
                    "out_of_view_ok": True,
                    "placements": [
                        {"id": "bad_marker", "placement_class": "on_a_cliff"}
                    ],
                }
            )


def test_tree_instances_skip_out_of_bounds_points():
    from veilbreakers_terrain.handlers.terrain_unity_export import _tree_instances_json

    stack = _make_stack()
    _set_channel(stack, "tree_instance_points", np.array(
        [
            [101.0, 201.0, 15.0, 0.0, 1.0],
            [500.0, 800.0, 20.0, 45.0, 2.0],
        ],
        dtype=np.float64,
    ))

    payload = _tree_instances_json(stack)

    assert len(payload["trees"]) == 1
    assert payload["skipped_out_of_bounds"] == 1


def test_tree_instances_sample_height_when_row_z_is_zero():
    from veilbreakers_terrain.handlers.terrain_unity_export import _tree_instances_json

    stack = _make_stack()
    _set_channel(stack, "tree_instance_points", np.array(
        [[102.0, 202.0, 0.0, 0.0, 1.0]],
        dtype=np.float64,
    ))

    payload = _tree_instances_json(stack)

    assert payload["trees"][0]["position"][1] == 13.0 * 0.85


def test_mcp_unity_export_location_dispatches_to_public_handler():
    from veilbreakers_terrain.src.veilbreakers_mcp.blender_server import dispatch

    stack = _make_unity_valid_stack()

    with tempfile.TemporaryDirectory() as td:
        result = dispatch(
            "unity_export",
            {
                "mask_stack": stack,
                "output_dir": td,
                "out_of_view_ok": True,
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
        manifest = export_unity_manifest(stack, Path(td), strict_unity_resolution=False)

    assert "waterfall_velocity.bin" in manifest["files"]
    assert manifest["files"]["waterfall_velocity.bin"]["shape"] == [5, 5, 2]


def test_unity_import_descriptor_references_atmosphere_wind_cloud_and_navmesh_sidecars():
    from veilbreakers_terrain.handlers.terrain_unity_export import export_unity_manifest

    stack = _make_stack()
    stack.set("atmospheric_volumes", [{"volume_id": "mist_000"}], "test")
    stack.set("wind_field", np.ones((5, 5, 2), dtype=np.float32), "test")
    stack.set("cloud_shadow", np.full((5, 5), 0.5, dtype=np.float32), "test")
    stack.set("navmesh_area_id", np.ones((5, 5), dtype=np.uint16), "test")

    with tempfile.TemporaryDirectory() as td:
        manifest = export_unity_manifest(stack, Path(td), strict_unity_resolution=False)
        descriptor = json.loads((Path(td) / "unity_import_descriptor.json").read_text())
        ecosystem_meta = json.loads((Path(td) / "ecosystem_meta.json").read_text())

    assert ecosystem_meta["has_wind_field"] is True
    assert ecosystem_meta["has_cloud_shadow"] is True
    assert ecosystem_meta["has_navmesh"] is True
    assert manifest["atmospheric_volumes_file"] == "atmospheric_volumes.json"
    assert descriptor["atmospheric_volumes_file"] == "atmospheric_volumes.json"
    assert descriptor["wind_field_descriptor"] == "wind_field.bin"
    assert descriptor["cloud_shadow_descriptor"] == "cloud_shadow.bin"
    assert descriptor["navmesh_area_id_file"] == "navmesh_area_id.bin"
    assert descriptor["navmesh_data_asset_path"].endswith("/NavMeshData_3_7.asset")


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
        manifest = export_unity_manifest(stack, Path(td), strict_unity_resolution=False)
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
