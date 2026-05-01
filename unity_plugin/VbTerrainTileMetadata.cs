using UnityEngine;

namespace VeilBreakers.TerrainImport
{
    /// <summary>
    /// Scene-side identity for imported terrain tiles so neighbor hookup can
    /// reconnect explicit tile coordinates after import.
    /// </summary>
    public sealed class VbTerrainTileMetadata : MonoBehaviour
    {
        public string WorldId = "unknown";
        public int TileX;
        public int TileY;
        public int TileSize;
        public float CellSize;
        public float HeightMinMeters;
        public float HeightMaxMeters = 1.0f;
        public float HeightScaleFactor = 0.85f;
        public string CoordinateSystem = "y-up";
        public string SourceCoordinateSystem = "z-up";
        public string ValidationStatus = "unknown";
        public int ValidationIssueCount;
        public string SeamContractWorldId = "unknown";
        public string TerrainNormalsFile = string.Empty;
        public string TerrainNormalMapFile = string.Empty;
        public string TerrainNormalMapAssetPath = string.Empty;
        public string NavMeshAreaIdFile = string.Empty;
        public string NavMeshDataAssetPath = string.Empty;

        // Extended fields (D-1)
        public int BiomeId;
        public string ClimateZone = "temperate";
        public bool WaterPresent;
        public float WaterSurfaceElevationM;
        public int ScatterCount;
        public float Lod0DistanceM = 50f;
        public float Lod1DistanceM = 150f;
        public float Lod2DistanceM = 400f;
        public float SnowLineFactor;
        public string PrimaryBiomeName = "dark_fantasy_default";

        [System.Serializable]
        public struct ChannelBound
        {
            public string Name;
            public float Min;
            public float Max;
        }
        public ChannelBound[] ChannelBounds = System.Array.Empty<ChannelBound>();
    }
}
