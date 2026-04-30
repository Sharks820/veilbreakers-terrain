from __future__ import annotations

from pathlib import Path


def test_unity_runtime_streamer_closes_camera_lod_and_neighbor_gap():
    repo_root = Path(__file__).resolve().parents[2]
    source = (repo_root / "unity_plugin" / "VbTerrainRuntimeStreamer.cs").read_text(
        encoding="utf-8"
    )

    for token in (
        "VbTerrainTileMetadata",
        "Resources.FindObjectsOfTypeAll<VbTerrainTileMetadata>",
        "GeometryUtility.CalculateFrustumPlanes",
        "GeometryUtility.TestPlanesAABB",
        "MaxActiveTiles",
        "MaxTilesChangedPerFrame",
        "Terrain.SetNeighbors",
        "heightmapPixelError",
        "detailObjectDistance",
        "treeDistance",
        "Lod0DistanceM",
        "Lod1DistanceM",
        "Lod2DistanceM",
    ):
        assert token in source

    for retired_term in ("3ds" + " Max", "Forest" + " Pack"):
        assert retired_term not in source


def test_unity_floating_origin_shifts_roots_particles_and_exposes_offset_event():
    repo_root = Path(__file__).resolve().parents[2]
    source = (repo_root / "unity_plugin" / "VbFloatingOrigin.cs").read_text(
        encoding="utf-8"
    )

    for token in (
        "AccumulatedOffset",
        "ShiftRoots",
        "MaximumDistance",
        "OnOriginMoved",
        "ParticleSystem.Particle",
        "ParticleSystemSimulationSpace.World",
        "ReferenceTransform",
    ):
        assert token in source

    for retired_term in ("3ds" + " Max", "Forest" + " Pack"):
        assert retired_term not in source


def test_runtime_streaming_documentation_is_wired():
    repo_root = Path(__file__).resolve().parents[2]
    doc = (repo_root / "docs" / "UNITY_RUNTIME_TERRAIN_STREAMING.md").read_text(
        encoding="utf-8"
    )
    foliage_doc = (repo_root / "docs" / "FOLIAGE_MANIFEST_PIPELINE.md").read_text(
        encoding="utf-8"
    )

    assert "VbTerrainRuntimeStreamer" in doc
    assert "VbFloatingOrigin" in doc
    assert "Terrain.SetNeighbors" in doc
    assert "VbTerrainRuntimeStreamer" in foliage_doc
