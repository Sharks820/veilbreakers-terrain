using System;
using System.Collections.Generic;
using UnityEngine;

namespace VeilBreakers.TerrainImport
{
    /// <summary>
    /// Camera-aware runtime activation and quality controller for imported terrain tiles.
    /// Uses VbTerrainTileMetadata so Python export LOD distances survive into Unity play mode.
    /// </summary>
    public sealed class VbTerrainRuntimeStreamer : MonoBehaviour
    {
        private sealed class TileState
        {
            public VbTerrainTileMetadata Metadata;
            public Terrain Terrain;
            public Bounds Bounds;
            public float Distance;
            public bool InFrustum;
            public bool ShouldBeActive;
            // HOTFIX-7f refinement (PR #127 codex review): cache terrainData so we can
            // null the Terrain.terrainData reference on deactivate. Without this, the
            // inactive Terrain still holds a strong ref and Resources.UnloadUnusedAssets()
            // cannot reclaim the asset — the hotfix would have been a no-op.
            public TerrainData CachedTerrainData;
            public bool TerrainDataDetached;
        }

        [Tooltip("Only tiles with this world id are controlled. Empty means all imported worlds.")]
        public string WorldId = string.Empty;

        [Tooltip("Camera used for frustum priority and visibility. Defaults to Camera.main.")]
        public Camera ViewCamera;

        [Tooltip("Player or camera transform used for distance priority. Defaults to ViewCamera.")]
        public Transform ViewTarget;

        [Tooltip("Fallback load distance when tile metadata has no LOD distances.")]
        public float DefaultLoadDistanceM = 750.0f;

        [Tooltip("Maximum active terrain tiles. Zero means unlimited.")]
        public int MaxActiveTiles = 64;

        [Tooltip("Maximum tile active-state changes per frame.")]
        public int MaxTilesChangedPerFrame = 4;

        [Tooltip("Prefer in-frustum tiles when active tile budget is limited.")]
        public bool PreferFrustumTiles = true;

        [Tooltip("Reconnect Terrain.SetNeighbors after active set changes.")]
        public bool ReconnectNeighborsAfterActivation = true;

        [Tooltip("Seconds between full tile rescans.")]
        public float RescanIntervalSeconds = 2.0f;

        // HOTFIX-7f: terrain data unload knobs. Without these, SetActive(false)
        // leaves heightmaps + splatmaps + tree prototypes resident — 64-tile
        // worlds OOM on 8GB targets after a single play session.
        [Tooltip("Run Resources.UnloadUnusedAssets() after every N tile deactivations.")]
        public int UnloadAfterDeactivations = 10;

        [Tooltip("Minimum seconds between Resources.UnloadUnusedAssets() invocations.")]
        public float MinSecondsBetweenUnloads = 30.0f;

        public int KnownTileCount { get; private set; }
        public int ActiveTileCount { get; private set; }

        private readonly List<TileState> _tiles = new List<TileState>();
        private float _lastRescanTime = -9999.0f;
        private int _pendingDeactivationCount;
        private float _lastUnloadTime = -9999.0f;

        private void OnEnable()
        {
            RefreshTiles(force: true);
            UpdateStreamingState();
        }

        private void LateUpdate()
        {
            RefreshTiles(force: false);
            UpdateStreamingState();
        }

        public void RefreshTiles(bool force)
        {
            if (!force && Time.unscaledTime - _lastRescanTime < RescanIntervalSeconds)
            {
                return;
            }

            _lastRescanTime = Time.unscaledTime;
            _tiles.Clear();

            var metadataComponents = Resources.FindObjectsOfTypeAll<VbTerrainTileMetadata>();
            foreach (var metadata in metadataComponents)
            {
                if (!IsRuntimeSceneObject(metadata))
                {
                    continue;
                }

                if (!string.IsNullOrEmpty(WorldId)
                    && !string.Equals(metadata.WorldId, WorldId, StringComparison.Ordinal))
                {
                    continue;
                }

                var terrain = metadata.GetComponent<Terrain>();
                if (terrain == null || terrain.terrainData == null)
                {
                    continue;
                }

                _tiles.Add(new TileState
                {
                    Metadata = metadata,
                    Terrain = terrain,
                    Bounds = TerrainBounds(terrain),
                    CachedTerrainData = terrain.terrainData,
                    TerrainDataDetached = false,
                });
            }

            KnownTileCount = _tiles.Count;
        }

        public void UpdateStreamingState()
        {
            var target = ResolveTarget();
            if (target == null)
            {
                return;
            }

            var camera = ResolveCamera();
            var planes = camera != null ? GeometryUtility.CalculateFrustumPlanes(camera) : null;

            foreach (var tile in _tiles)
            {
                // HOTFIX-7f refinement: when terrainData is detached for unload,
                // the Terrain has no .size — use the bounds captured at refresh
                // time (which are correct because tile dimensions don't change).
                if (!tile.TerrainDataDetached && tile.Terrain != null && tile.Terrain.terrainData != null)
                {
                    tile.Bounds = TerrainBounds(tile.Terrain);
                }
                tile.Distance = Mathf.Sqrt(tile.Bounds.SqrDistance(target.position));
                tile.InFrustum = planes == null || GeometryUtility.TestPlanesAABB(planes, tile.Bounds);
            }

            _tiles.Sort(CompareTiles);

            var activeBudget = MaxActiveTiles <= 0 ? int.MaxValue : MaxActiveTiles;
            for (var index = 0; index < _tiles.Count; index++)
            {
                var tile = _tiles[index];
                var loadDistance = TileLoadDistance(tile.Metadata);
                tile.ShouldBeActive = index < activeBudget && tile.Distance <= loadDistance;
            }

            var changesRemaining = Mathf.Max(1, MaxTilesChangedPerFrame);
            foreach (var tile in _tiles)
            {
                if (changesRemaining <= 0)
                {
                    break;
                }

                if (tile.Terrain.gameObject.activeSelf == tile.ShouldBeActive)
                {
                    continue;
                }

                var wasActive = tile.Terrain.gameObject.activeSelf;

                // HOTFIX-7f refined (PR #127 codex/copilot review):
                // Re-attach terrainData BEFORE activating so the Terrain has a
                // valid asset on enable. Detach AFTER deactivating so the
                // GameObject still owns the asset graph through its disable
                // lifecycle, but the strong ref is dropped immediately after
                // — that lets Resources.UnloadUnusedAssets() actually reclaim
                // the heightmaps/splatmaps/details/tree prototypes.
                if (!wasActive && tile.ShouldBeActive)
                {
                    if (tile.TerrainDataDetached && tile.CachedTerrainData != null)
                    {
                        tile.Terrain.terrainData = tile.CachedTerrainData;
                        tile.TerrainDataDetached = false;
                    }
                }

                tile.Terrain.gameObject.SetActive(tile.ShouldBeActive);
                changesRemaining--;

                if (wasActive && !tile.ShouldBeActive)
                {
                    // Drop the strong ref so UnloadUnusedAssets can reclaim it.
                    // CachedTerrainData still keeps the asset alive in our list
                    // until the next reactivation reassigns it.
                    if (tile.Terrain != null && tile.CachedTerrainData == null)
                    {
                        tile.CachedTerrainData = tile.Terrain.terrainData;
                    }
                    if (tile.Terrain != null)
                    {
                        tile.Terrain.terrainData = null;
                    }
                    tile.TerrainDataDetached = true;
                    _pendingDeactivationCount++;
                }
            }

            ActiveTileCount = 0;
            foreach (var tile in _tiles)
            {
                if (tile.Terrain.gameObject.activeSelf)
                {
                    ActiveTileCount++;
                    ApplyTerrainQuality(tile);
                }
            }

            if (ReconnectNeighborsAfterActivation)
            {
                ConnectActiveNeighbors();
            }

            MaybeUnloadUnusedAssets();
        }

        /// <summary>
        /// HOTFIX-7f (refined per PR #127 codex/copilot review): free GPU + CPU
        /// memory held by deactivated TerrainData. The deactivation path above
        /// nulls Terrain.terrainData before this call so the asset graph
        /// (heightmap RT, splatmap textures, detail layers, tree prototypes) is
        /// no longer strongly referenced from the live scene. CachedTerrainData
        /// on TileState retains the asset until the next reactivation rebinds
        /// it. Without that detach step, Resources.UnloadUnusedAssets() would
        /// be a no-op because the inactive Terrain still pinned the asset.
        /// </summary>
        private void MaybeUnloadUnusedAssets()
        {
            if (UnloadAfterDeactivations <= 0)
            {
                return;
            }
            if (_pendingDeactivationCount < UnloadAfterDeactivations)
            {
                return;
            }
            if (Time.unscaledTime - _lastUnloadTime < MinSecondsBetweenUnloads)
            {
                return;
            }
            _pendingDeactivationCount = 0;
            _lastUnloadTime = Time.unscaledTime;
            // Resources.UnloadUnusedAssets reclaims terrain heightmaps, splatmaps,
            // and tree prototypes that lost their last reference when tiles
            // deactivated. Returns an AsyncOperation we intentionally drop —
            // streamer reactivations across multiple frames are safe.
            Resources.UnloadUnusedAssets();
        }

        private int CompareTiles(TileState left, TileState right)
        {
            if (PreferFrustumTiles && left.InFrustum != right.InFrustum)
            {
                return left.InFrustum ? -1 : 1;
            }

            return left.Distance.CompareTo(right.Distance);
        }

        private Camera ResolveCamera()
        {
            return ViewCamera != null ? ViewCamera : Camera.main;
        }

        private Transform ResolveTarget()
        {
            if (ViewTarget != null)
            {
                return ViewTarget;
            }

            var camera = ResolveCamera();
            return camera != null ? camera.transform : null;
        }

        private static bool IsRuntimeSceneObject(VbTerrainTileMetadata metadata)
        {
            return metadata != null
                && metadata.gameObject != null
                && metadata.gameObject.scene.IsValid()
                && !string.IsNullOrEmpty(metadata.gameObject.scene.name);
        }

        private static Bounds TerrainBounds(Terrain terrain)
        {
            var size = terrain.terrainData.size;
            return new Bounds(
                terrain.transform.position + new Vector3(size.x * 0.5f, size.y * 0.5f, size.z * 0.5f),
                size
            );
        }

        private float TileLoadDistance(VbTerrainTileMetadata metadata)
        {
            var tileDistance = Mathf.Max(metadata.Lod2DistanceM, metadata.Lod1DistanceM, metadata.Lod0DistanceM);
            return tileDistance > 0.0f ? tileDistance : DefaultLoadDistanceM;
        }

        private void ApplyTerrainQuality(TileState tile)
        {
            var terrain = tile.Terrain;
            var metadata = tile.Metadata;

            if (tile.Distance <= metadata.Lod0DistanceM)
            {
                terrain.heightmapPixelError = 4.0f;
                terrain.detailObjectDistance = 250.0f;
                terrain.treeDistance = 2000.0f;
                return;
            }

            if (tile.Distance <= metadata.Lod1DistanceM)
            {
                terrain.heightmapPixelError = 8.0f;
                terrain.detailObjectDistance = 140.0f;
                terrain.treeDistance = 1200.0f;
                return;
            }

            terrain.heightmapPixelError = 16.0f;
            terrain.detailObjectDistance = 80.0f;
            terrain.treeDistance = 650.0f;
        }

        private void ConnectActiveNeighbors()
        {
            var terrainsByKey = new Dictionary<string, Terrain>();
            foreach (var tile in _tiles)
            {
                if (!tile.Terrain.gameObject.activeSelf)
                {
                    continue;
                }

                terrainsByKey[TileKey(tile.Metadata)] = tile.Terrain;
            }

            foreach (var tile in _tiles)
            {
                if (!tile.Terrain.gameObject.activeSelf)
                {
                    continue;
                }

                var metadata = tile.Metadata;
                terrainsByKey.TryGetValue(TileKey(metadata.WorldId, metadata.TileX - 1, metadata.TileY), out var left);
                terrainsByKey.TryGetValue(TileKey(metadata.WorldId, metadata.TileX, metadata.TileY + 1), out var top);
                terrainsByKey.TryGetValue(TileKey(metadata.WorldId, metadata.TileX + 1, metadata.TileY), out var right);
                terrainsByKey.TryGetValue(TileKey(metadata.WorldId, metadata.TileX, metadata.TileY - 1), out var bottom);
                tile.Terrain.SetNeighbors(left, top, right, bottom);
            }
        }

        private static string TileKey(VbTerrainTileMetadata metadata)
        {
            return TileKey(metadata.WorldId, metadata.TileX, metadata.TileY);
        }

        private static string TileKey(string worldId, int tileX, int tileY)
        {
            return worldId + "::" + tileX + "::" + tileY;
        }
    }
}
