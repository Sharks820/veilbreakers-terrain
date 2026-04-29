using UnityEngine;

namespace VeilBreakers.TerrainImport
{
    /// <summary>
    /// Keeps terrain export sidecar JSON attached to the imported tile so
    /// gameplay/audio/wildlife/decal systems can bind it after import.
    /// </summary>
    public sealed class VbTerrainSidecarReference : MonoBehaviour
    {
        public string PayloadType = string.Empty;
        public string RelativeFile = string.Empty;
        [TextArea(3, 20)]
        public string JsonPayload = string.Empty;
        public int ByteSize;
    }
}
