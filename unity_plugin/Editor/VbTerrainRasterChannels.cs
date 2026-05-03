using UnityEngine;

namespace VeilBreakers.TerrainImport
{
    /// <summary>
    /// FIX-12-38: Holds deserialized raster-channel arrays loaded from the raw binary
    /// sidecar files exported by the Python terrain pipeline.  Attached to the terrain
    /// GameObject during import so runtime systems can sample water, flow, wave, wind
    /// and cloud-shadow data without re-reading the bundle files at play-time.
    ///
    /// All float[] arrays use row-major (y*width+x) addressing and match the raster
    /// dimensions stored in <see cref="RasterWidth"/> / <see cref="RasterHeight"/>.
    /// Arrays are null when the corresponding sidecar file was absent from the bundle.
    /// </summary>
    public sealed class VbTerrainRasterChannels : MonoBehaviour
    {
        /// <summary>Water surface elevation in world-space metres (raw_f32_le).</summary>
        public float[] WaterSurfaceElevation;

        /// <summary>Water depth in metres at each raster cell (raw_f32_le).</summary>
        public float[] WaterDepth;

        /// <summary>Flow direction encoded as a float angle in radians (raw_f32_le).</summary>
        public float[] FlowDirection;

        /// <summary>Flow accumulation (upstream contributing area) per cell (raw_f32_le).</summary>
        public float[] FlowAccumulation;

        /// <summary>Wave-energy proxy per cell, 0–1 normalised (raw_f32_le).</summary>
        public float[] WaveEnergy;

        /// <summary>Wind-field magnitude/direction packed as float (raw_f32_le).</summary>
        public float[] WindField;

        /// <summary>Cloud-shadow intensity per cell, 0–1 normalised (raw_f32_le).</summary>
        public float[] CloudShadow;

        /// <summary>Atmospheric density scalar per cell (raw_f32_le).</summary>
        public float[] AtmosphericDensity;

        /// <summary>Horizontal cell count of all raster arrays.</summary>
        public int RasterWidth;

        /// <summary>Vertical cell count of all raster arrays.</summary>
        public int RasterHeight;
    }
}
