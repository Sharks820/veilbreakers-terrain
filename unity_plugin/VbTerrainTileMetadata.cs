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
    }
}
