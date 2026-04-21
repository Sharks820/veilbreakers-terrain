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
    }
}
