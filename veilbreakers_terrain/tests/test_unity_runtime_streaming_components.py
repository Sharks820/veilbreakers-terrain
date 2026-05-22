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


def test_unity_foliage_manifest_renderer_consumes_gpu_manifest_without_gameobject_spam():
    repo_root = Path(__file__).resolve().parents[2]
    source = (repo_root / "unity_plugin" / "VbFoliageManifestRenderer.cs").read_text(
        encoding="utf-8"
    )

    for token in (
        "foliage_placement_manifest.json",
        "VbFoliageManifestRenderer",
        "Graphics.DrawMeshInstanced",
        "MaterialPropertyBlock",
        "mesh_library",
        "instances",
        "position_world",
        "ConvertTerrainXzyToUnityXyz",
        "PositionsAreWorldSpace",
        # PR #127 review: gate _originOffset on world-space input to avoid
        # double-shifting positions that already moved via parent transform.
        "if (PositionsAreWorldSpace)",
        "transform.TransformPoint(position)",
        "MaximumInstances",
        "CullDistanceM",
        "1023",
        "SpeciesKey",
        "MeshId",
    ):
        assert token in source

    assert "new GameObject" not in source
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


def test_foliage_renderer_subscribes_to_floating_origin():
    """HOTFIX-7e: foliage manifest matrices were baked at export time in
    absolute world coords. After the first VbFloatingOrigin.ShiftWorld() call,
    terrain GameObject roots shift but GPU foliage stayed at the original
    world position, opening a 2km+ gap. This test pins token-level evidence
    that the renderer (a) subscribes to OnOriginMoved on OnEnable, (b)
    unsubscribes on OnDisable, and (c) applies the accumulated offset in the
    position pipeline. Acknowledged as non-behavioral token-presence guard
    until Unity batch-mode tests exist.
    """
    repo_root = Path(__file__).resolve().parents[2]
    source = (repo_root / "unity_plugin" / "VbFoliageManifestRenderer.cs").read_text(
        encoding="utf-8"
    )

    assert "OnOriginMoved" in source
    assert "OnEnable" in source or "Awake" in source
    assert "OnDisable" in source
    assert "HandleOriginShifted" in source
    assert "AddListener(HandleOriginShifted)" in source
    assert "RemoveListener(HandleOriginShifted)" in source
    # Offset must actually be applied to world positions, not just stored.
    assert "_originOffset" in source
    # PR #127 review fix: subtraction must be gated on PositionsAreWorldSpace,
    # else local-space inputs (which already pass through transform.TransformPoint
    # — and therefore the renderer's parent transform that ShiftRoots moves)
    # get the offset applied twice and foliage drifts away from terrain.
    assert "position - _originOffset" in source
    assert "if (PositionsAreWorldSpace)" in source
    # Fallback for runtime-discovered origins (per Verifier A no-singleton constraint).
    assert "FindObjectOfType<VbFloatingOrigin>" in source
    assert "BindFloatingOrigin" in source


def test_streamer_unloads_terrain_data():
    """HOTFIX-7f: tile.Terrain.gameObject.SetActive(false) leaves TerrainData
    resident in memory (heightmaps, splatmaps, tree prototypes, detail layers).
    64-tile worlds OOM on 8GB targets after one play session. This test pins
    that the streamer (a) tracks pending deactivations, (b) triggers
    Resources.UnloadUnusedAssets() after N deactivations, (c) rate-limits the
    unload to avoid stalling the main thread, and (d) explicitly documents
    why UnloadUnusedAssets is chosen over Resources.UnloadAsset(terrainData).
    Acknowledged as non-behavioral token-presence guard until Unity batch-mode
    tests exist.
    """
    repo_root = Path(__file__).resolve().parents[2]
    source = (repo_root / "unity_plugin" / "VbTerrainRuntimeStreamer.cs").read_text(
        encoding="utf-8"
    )

    # Either pattern is acceptable per task spec.
    assert "Resources.UnloadUnusedAssets" in source or "Object.Destroy(terrainData)" in source
    # Bookkeeping that proves the unload is wired to deactivation events.
    assert "_pendingDeactivationCount" in source
    assert "UnloadAfterDeactivations" in source
    assert "MinSecondsBetweenUnloads" in source
    assert "MaybeUnloadUnusedAssets" in source
    # Streaming loop must call the unload path after toggling tiles.
    assert "MaybeUnloadUnusedAssets()" in source
    # PR #127 review fix: UnloadUnusedAssets only reclaims assets that are no
    # longer strongly referenced. The Terrain component holds terrainData
    # through SetActive(false), so we must explicitly drop the reference on
    # deactivate and reattach it from a cached copy on reactivate.
    assert "CachedTerrainData" in source
    assert "TerrainDataDetached" in source
    assert "terrain.terrainData = null" in source or "Terrain.terrainData = null" in source


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
    assert "VbFoliageManifestRenderer" in doc
    assert "Terrain.SetNeighbors" in doc
    assert "VbTerrainRuntimeStreamer" in foliage_doc
    assert "VbFoliageManifestRenderer" in foliage_doc
