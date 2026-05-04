"""Tests for terrain_chunking handler."""

import json

import numpy as np

from veilbreakers_terrain.handlers.terrain_chunking import (
    build_tile_batch_manifest,
    build_tile_seam_contract,
    compute_chunk_lod,
    compute_streaming_distances,
    compute_terrain_chunks,
    export_chunks_metadata,
    validate_tile_seams,
)
from veilbreakers_terrain.handlers._terrain_world import validate_tile_seams as validate_world_tile_seams


# ---------------------------------------------------------------------------
# Helper: generate a simple heightmap
# ---------------------------------------------------------------------------

def _make_heightmap(rows: int, cols: int, value: float = 1.0) -> list[list[float]]:
    return [[value * (r + c) for c in range(cols)] for r in range(rows)]


# ---------------------------------------------------------------------------
# LOD downsample
# ---------------------------------------------------------------------------


class TestComputeChunkLod:
    def test_empty_heightmap(self):
        assert compute_chunk_lod([], 4) == 0

    def test_zero_target(self):
        assert compute_chunk_lod([[1, 2], [3, 4]], 0) == 0

    def test_already_below_target(self):
        hmap = [[1.0, 2.0], [3.0, 4.0]]
        result = compute_chunk_lod(hmap, 8)
        assert isinstance(result, int)
        assert result == 0

    def test_close_camera_keeps_full_detail(self):
        hmap = _make_heightmap(16, 16)
        result = compute_chunk_lod(hmap, 4, camera_distance=10.0)
        assert isinstance(result, int)
        assert result == 0

    def test_farther_camera_increases_lod(self):
        hmap = _make_heightmap(8, 8, value=1.0)
        close_lod = compute_chunk_lod(hmap, 2, camera_distance=10.0)
        far_lod = compute_chunk_lod(hmap, 2, camera_distance=500.0)
        assert far_lod >= close_lod

    def test_no_distance_defaults_to_lod_zero(self):
        hmap = [[0.0, 10.0], [10.0, 20.0]]
        result = compute_chunk_lod(hmap, 2)
        assert isinstance(result, int)
        assert result == 0


# ---------------------------------------------------------------------------
# Streaming distances
# ---------------------------------------------------------------------------


class TestStreamingDistances:
    def test_basic_distances(self):
        distances = compute_streaming_distances(64.0, 4)
        assert len(distances) == 4
        # LOD 0: 128, LOD 1: 256, LOD 2: 512, LOD 3: 1024
        assert distances[0] == 128.0
        assert distances[1] == 256.0
        assert distances[2] == 512.0
        assert distances[3] == 1024.0

    def test_distances_increase(self):
        distances = compute_streaming_distances(32.0, 3)
        for i in range(1, len(distances)):
            assert distances[i] > distances[i - 1]

    def test_single_lod(self):
        distances = compute_streaming_distances(100.0, 1)
        assert len(distances) == 1
        assert distances[0] == 200.0

    def test_reasonable_values(self):
        distances = compute_streaming_distances(64.0, 4)
        for lod, dist in distances.items():
            assert dist > 0
            assert dist < 100000  # Reasonable upper bound


# ---------------------------------------------------------------------------
# Main chunking pipeline
# ---------------------------------------------------------------------------


class TestComputeTerrainChunks:
    def test_empty_heightmap(self):
        result = compute_terrain_chunks([])
        assert result["chunks"] == []
        assert result["metadata"]["total_chunks"] == 0

    def test_empty_row(self):
        result = compute_terrain_chunks([[]])
        assert result["chunks"] == []

    def test_basic_chunking(self):
        hmap = _make_heightmap(128, 128)
        result = compute_terrain_chunks(hmap, chunk_size=64)
        assert len(result["chunks"]) == 4  # 2x2 grid
        assert result["metadata"]["grid_size"] == (2, 2)

    def test_chunk_has_required_fields(self):
        hmap = _make_heightmap(64, 64)
        result = compute_terrain_chunks(hmap, chunk_size=64)
        chunk = result["chunks"][0]
        assert "grid_x" in chunk
        assert "grid_y" in chunk
        assert "heightmap" in chunk
        assert "bounds" in chunk
        assert "lods" in chunk
        assert "neighbor_chunks" in chunk

    def test_lod_levels(self):
        hmap = _make_heightmap(64, 64)
        result = compute_terrain_chunks(hmap, chunk_size=64, lod_levels=3)
        chunk = result["chunks"][0]
        assert len(chunk["lods"]) == 3
        # Each LOD should have decreasing resolution
        for lod in chunk["lods"]:
            assert "lod_level" in lod
            assert "resolution" in lod
            assert "vertex_count" in lod

    def test_neighbor_references(self):
        hmap = _make_heightmap(128, 128)
        result = compute_terrain_chunks(hmap, chunk_size=64)
        # Corner chunk (0,0) should have no north/west
        corner = [c for c in result["chunks"] if c["grid_x"] == 0 and c["grid_y"] == 0][0]
        assert corner["neighbor_chunks"]["north"] is None
        assert corner["neighbor_chunks"]["west"] is None
        assert corner["neighbor_chunks"]["south"] is not None
        assert corner["neighbor_chunks"]["east"] is not None

    def test_metadata_well_formed(self):
        hmap = _make_heightmap(128, 128)
        result = compute_terrain_chunks(hmap, chunk_size=64, lod_levels=4)
        meta = result["metadata"]
        assert meta["total_chunks"] == 4
        assert meta["chunk_size_samples"] == 64
        assert meta["lod_levels"] == 4
        assert meta["heightmap_size"] == (128, 128)
        assert "streaming_distance_lod" in meta

    def test_world_scale(self):
        hmap = _make_heightmap(64, 64)
        result = compute_terrain_chunks(hmap, chunk_size=64, world_scale=2.0)
        meta = result["metadata"]
        assert meta["chunk_world_size"] == 128.0

    def test_world_origin_is_preserved(self):
        hmap = _make_heightmap(64, 64)
        result = compute_terrain_chunks(
            hmap,
            chunk_size=64,
            world_scale=2.0,
            world_origin=(512.0, 256.0),
        )
        meta = result["metadata"]
        assert meta["world_origin"] == (512.0, 256.0)
        chunk = result["chunks"][0]
        assert chunk["bounds"] == (512.0, 256.0, 640.0, 384.0)

    def test_bounds_with_overlap_uses_correct_axes(self):
        hmap = _make_heightmap(192, 192)
        result = compute_terrain_chunks(
            hmap,
            chunk_size=64,
            overlap=2,
            world_scale=2.0,
            world_origin=(100.0, 200.0),
        )
        interior = [c for c in result["chunks"] if c["grid_x"] == 1 and c["grid_y"] == 1][0]
        assert interior["bounds"] == (228.0, 328.0, 356.0, 456.0)
        assert interior["bounds_with_overlap"] == (224.0, 324.0, 360.0, 460.0)


# ---------------------------------------------------------------------------
# Metadata export
# ---------------------------------------------------------------------------


class TestExportMetadata:
    def test_export_json_valid(self):
        hmap = _make_heightmap(64, 64)
        result = compute_terrain_chunks(hmap, chunk_size=64)
        json_str = export_chunks_metadata(result)
        data = json.loads(json_str)
        assert "terrain_metadata" in data
        assert "chunks" in data

    def test_export_strips_heightmap_data(self):
        hmap = _make_heightmap(64, 64)
        result = compute_terrain_chunks(hmap, chunk_size=64)
        json_str = export_chunks_metadata(result)
        data = json.loads(json_str)
        for chunk in data["chunks"]:
            assert "heightmap" not in chunk

    def test_export_preserves_grid_info(self):
        hmap = _make_heightmap(128, 128)
        result = compute_terrain_chunks(hmap, chunk_size=64)
        json_str = export_chunks_metadata(result)
        data = json.loads(json_str)
        assert len(data["chunks"]) == 4
        grid_positions = [(c["grid_x"], c["grid_y"]) for c in data["chunks"]]
        assert (0, 0) in grid_positions

    def test_export_preserves_world_origin(self):
        hmap = _make_heightmap(64, 64)
        result = compute_terrain_chunks(
            hmap,
            chunk_size=64,
            world_origin=(1024.0, 2048.0),
        )
        json_str = export_chunks_metadata(result)
        data = json.loads(json_str)
        assert tuple(data["terrain_metadata"]["world_origin"]) == (1024.0, 2048.0)

    def test_export_includes_seam_manifest(self):
        hmap = _make_heightmap(128, 128)
        result = compute_terrain_chunks(hmap, chunk_size=64, overlap=1)
        json_str = export_chunks_metadata(result)
        data = json.loads(json_str)
        seam_manifest = data["seam_manifest"]
        assert seam_manifest["tile_count"] == 4
        assert seam_manifest["adjacency"]
        assert seam_manifest["frontier_tiles"]


class TestSeamContracts:
    def test_tile_seam_contract_includes_edges_and_neighbors(self):
        hmap = np.arange(9, dtype=np.float64).reshape(3, 3)
        contract = build_tile_seam_contract(
            hmap,
            tile_x=4,
            tile_y=7,
            cell_size=2.0,
            world_origin_x=100.0,
            world_origin_y=200.0,
            world_id="world_a",
            batch_id="batch_01",
        )

        assert contract["tile_coords"] == [4, 7]
        assert contract["neighbor_tiles"]["east"] == [5, 7]
        assert contract["world_bounds"] == {
            "min_x": 100.0,
            "min_y": 200.0,
            "max_x": 104.0,
            "max_y": 204.0,
        }
        assert contract["edge_contracts"]["east"]["sample_count"] == 3
        assert contract["corner_heights"]["south_east"] == [8.0]

    def test_tile_batch_manifest_reports_mismatch_and_frontier(self):
        left = build_tile_seam_contract(
            [[0.0, 1.0], [2.0, 3.0]],
            tile_x=0,
            tile_y=0,
            cell_size=1.0,
            world_origin_x=0.0,
            world_origin_y=0.0,
        )
        right = build_tile_seam_contract(
            [[99.0, 4.0], [99.0, 5.0]],
            tile_x=1,
            tile_y=0,
            cell_size=1.0,
            world_origin_x=1.0,
            world_origin_y=0.0,
        )

        manifest = build_tile_batch_manifest([left, right], world_id="world_a")

        assert manifest["tile_count"] == 2
        mismatch = [entry for entry in manifest["adjacency"] if entry["status"] == "mismatch"]
        assert mismatch
        assert {"tile_x": 0, "tile_y": 1} in manifest["frontier_tiles"]

    def test_tile_batch_manifest_frontier_includes_missing_north_and_west_neighbors(self):
        contract = build_tile_seam_contract(
            [[1.0, 2.0], [3.0, 4.0]],
            tile_x=1,
            tile_y=1,
            cell_size=1.0,
            world_origin_x=1.0,
            world_origin_y=1.0,
        )

        manifest = build_tile_batch_manifest([contract], world_id="world_a")

        assert {"tile_x": 1, "tile_y": 0} in manifest["frontier_tiles"]
        assert {"tile_x": 0, "tile_y": 1} in manifest["frontier_tiles"]


class TestValidateTileSeams:
    def test_east_west_tiles_match(self):
        left = [
            [0.0, 1.0, 2.0],
            [3.0, 4.0, 5.0],
            [6.0, 7.0, 8.0],
        ]
        right = [
            [2.0, 9.0, 10.0],
            [5.0, 11.0, 12.0],
            [8.0, 13.0, 14.0],
        ]
        result = validate_tile_seams(left, right, direction="east")
        assert result["match"] is True
        assert result["sample_count"] == 3

    def test_north_south_tiles_mismatch(self):
        top = [
            [0.0, 1.0, 2.0],
            [3.0, 4.0, 5.0],
            [6.0, 7.0, 8.0],
        ]
        bottom = [
            [6.5, 7.0, 8.0],
            [9.0, 10.0, 11.0],
            [12.0, 13.0, 14.0],
        ]
        result = validate_tile_seams(top, bottom, direction="south", tolerance=0.1)
        assert result["match"] is False
        assert result["max_delta"] == 0.5

    def test_world_tile_validator_returns_region_summary_shape(self):
        tiles = {
            (0, 0): [[0.0, 1.0], [2.0, 3.0]],
            (1, 0): [[1.0, 4.0], [3.0, 5.0]],
        }
        result = validate_world_tile_seams(tiles)
        assert set(result.keys()) == {"seam_ok", "max_edge_delta", "issues", "tile_count", "channel_count"}
        assert result["tile_count"] == 2

    def test_multichannel_tiles_report_per_channel_deltas(self):
        left = [
            [[0.0, 10.0], [1.0, 11.0]],
            [[2.0, 12.0], [3.0, 13.0]],
        ]
        right = [
            [[1.0, 11.0], [4.0, 14.0]],
            [[3.0, 13.2], [5.0, 15.2]],
        ]

        result = validate_tile_seams(left, right, direction="east", tolerance=0.1)

        assert result["match"] is False
        assert result["sample_count"] == 2
        assert result["channel_count"] == 2
        assert result["per_channel_max_delta"] == [0.0, 0.1999999999999993]

    def test_world_validator_accepts_multichannel_tiles(self):
        tiles = {
            (0, 0): np.array([[[0.0, 0.1], [1.0, 1.1]], [[2.0, 2.1], [3.0, 3.1]]], dtype=np.float64),
            (1, 0): np.array([[[1.0, 1.1], [4.0, 4.1]], [[3.0, 3.1], [5.0, 5.1]]], dtype=np.float64),
        }

        result = validate_world_tile_seams(tiles)

        assert result["seam_ok"] is True
        assert result["channel_count"] == 2
