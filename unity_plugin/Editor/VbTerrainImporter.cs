using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;
using UnityEngine.AI;
using VeilBreakers.TerrainImport;

namespace VeilBreakers.TerrainImport.Editor
{
    /// <summary>
    /// Imports a VeilBreakers terrain export bundle into native Unity TerrainData,
    /// TerrainLayer assets, optional detail layers, optional trees, and explicit
    /// scene-neighbor connectivity.
    /// </summary>
    public static class VbTerrainImporter
    {
        private const string ImportDescriptorName = "unity_import_descriptor.json";

        [Serializable]
        private sealed class TerrainBundleDescriptor
        {
            public string schema_version = "1.0";
            public string world_id = "unknown";
            public int tile_x;
            public int tile_y;
            public int tile_size;
            public float cell_size = 1.0f;
            public float[] unity_world_origin = Array.Empty<float>();
            public float terrain_size_x_m;
            public float terrain_size_z_m;
            public float height_min_m;
            public float height_max_m = 1.0f;
            public float height_scale_factor = 0.85f;
            public string coordinate_system = "y-up";
            public string source_coordinate_system = "z-up";
            public HeightmapDescriptor heightmap = new HeightmapDescriptor();
            public string terrain_normals_file = string.Empty;
            public string terrain_normal_map_file = string.Empty;
            public string mesh_attributes_file = string.Empty;
            public SplatmapDescriptor[] splatmaps = Array.Empty<SplatmapDescriptor>();
            public TerrainLayerDescriptor[] terrain_layers = Array.Empty<TerrainLayerDescriptor>();
            public DetailLayerDescriptor[] detail_layers = Array.Empty<DetailLayerDescriptor>();
            public TreePrototypeDescriptor[] tree_prototypes = Array.Empty<TreePrototypeDescriptor>();
            public string tree_instances_file = "tree_instances.json";
            public string audio_zones_file = "audio_zones.json";
            public string gameplay_zones_file = "gameplay_zones.json";
            public string wildlife_zones_file = "wildlife_zones.json";
            public string decals_file = "decals.json";
            public string particle_emitter_specs_file = string.Empty;
            public string water_shader_manifest_file = "water_shader_manifest.json";
            public string water_surface_elevation_file = string.Empty;
            public string water_depth_file = string.Empty;
            public string flow_direction_file = string.Empty;
            public string flow_accumulation_file = string.Empty;
            public string atmospheric_volumes_file = string.Empty;
            public string wind_field_descriptor = string.Empty;
            public string cloud_shadow_descriptor = string.Empty;
            public string navmesh_area_id_file = string.Empty;
            public string navmesh_data_asset_path = string.Empty;
            public string supplemental_mesh_specs_file = string.Empty;
            public string foliage_placement_manifest_file = string.Empty;
            public string light_placements_file = string.Empty;
            public string probe_placements_file = "probe_placements.json";
            public SeamContractPayload seam_contract = new SeamContractPayload();
            public string validation_status = "unknown";
            public int validation_issue_count;
            public string game_object_name = "VB_Terrain";
            public string terrain_data_asset_path = "Assets/VeilBreakersTerrain/Imported/TerrainData.asset";
            public string tile_metadata_asset_path = "Assets/VeilBreakersTerrain/Imported/TerrainTile.asset";
            // Extended metadata fields (D-1)
            public int tile_biome_id;
            public string tile_biome_name = "dark_fantasy_default";
            public string climate_zone = "temperate";
            public float water_level_unity_units;
            public bool has_water_surface;
            public int scatter_count;
            public float lod0_distance_m = 50f;
            public float lod1_distance_m = 150f;
            public float lod2_distance_m = 400f;
            public float snow_line_factor;
        }

        [Serializable]
        private sealed class HeightmapDescriptor
        {
            public string file = "heightmap.raw";
            public int width;
            public int height;
            public int bit_depth = 16;
            public string encoding = "raw_u16_le";
            public bool flip_vertical = true;
            public string endianness = "little";
        }

        [Serializable]
        private sealed class SplatmapDescriptor
        {
            public string file = string.Empty;
            public int width;
            public int height;
            public int channels = 4;
            public int bit_depth = 8;
            public string encoding = "raw_rgba_u8";
            public bool flip_vertical = true;
            public int layer_start;
            public int layer_end = -1;
            public string[] terrain_layer_assets = Array.Empty<string>();
        }

        [Serializable]
        private sealed class TerrainLayerDescriptor
        {
            public int layer_index;
            public string layer_id = string.Empty;
            public string terrain_layer_asset_path = string.Empty;
            public float uv_scale_meters = 4.0f;
            public float normal_map_intensity = 1.0f;
            public float roughness = 0.8f;
            public float roughness_multiplier = 1.0f;
            public float smoothness = 0.2f;
            public float height_blend_factor = 0.1f;
            public string base_color_hex = "#808080";
            public float[] base_color_rgb = Array.Empty<float>();
            public string diffuse_texture_file = string.Empty;
            public string normal_texture_file = string.Empty;
            public string mask_texture_file = string.Empty;
            public bool triplanar;
        }

        [Serializable]
        private sealed class DetailLayerDescriptor
        {
            public string kind = string.Empty;
            public string file = string.Empty;
            public int width;
            public int height;
            public int bit_depth = 16;
            public string encoding = "raw_u16_le_detail_count";
            public bool flip_vertical = true;
            public int max_density_per_cell = 16;
            public string placeholder_texture_asset_path = string.Empty;
        }

        [Serializable]
        private sealed class TreePrototypeDescriptor
        {
            public int prototype_id;
            public string prefab_asset = string.Empty;
            public float bend_factor = 1.0f;
            public float width = 5.0f;
            public float height = 10.0f;
        }

        [Serializable]
        private sealed class SeamContractPayload
        {
            public string world_id = string.Empty;
        }

        [Serializable]
        private sealed class TreeInstanceCollection
        {
            public TreeInstanceEntry[] trees = Array.Empty<TreeInstanceEntry>();
        }

        [Serializable]
        private sealed class TreeInstanceEntry
        {
            public float[] position = Array.Empty<float>();
            public float yaw_degrees;
            public int prototype_id;
            public float width_scale = 1.0f;
            public float height_scale = 1.0f;
            public ColorPayload color = new ColorPayload();
            public ColorPayload lightmap_color = new ColorPayload();
        }

        [Serializable]
        private sealed class ColorPayload
        {
            public float r = 1.0f;
            public float g = 1.0f;
            public float b = 1.0f;
            public float a = 1.0f;
        }

        [Serializable]
        private sealed class SupplementalMeshCollection
        {
            public SupplementalMeshSpec[] mesh_specs = Array.Empty<SupplementalMeshSpec>();
        }

        [Serializable]
        private sealed class SupplementalMeshSpec
        {
            public string mesh_id = string.Empty;
            public string mesh_type = string.Empty;
            public string material_hint = string.Empty;
            public string tier = string.Empty;
            public Vector3Payload[] vertices = Array.Empty<Vector3Payload>();
            public FacePayload[] faces = Array.Empty<FacePayload>();
            public Vector2Payload[] uvs = Array.Empty<Vector2Payload>();
            public int[] drip_edge_indices = Array.Empty<int>();
        }

        [Serializable]
        private sealed class Vector3Payload
        {
            public float x;
            public float y;
            public float z;
        }

        [Serializable]
        private sealed class Vector2Payload
        {
            public float x;
            public float y;
        }

        [Serializable]
        private sealed class FacePayload
        {
            public int[] indices = Array.Empty<int>();
        }

        [Serializable]
        private sealed class WaterShaderManifest
        {
            public WaterMaterialDescriptor[] materials = Array.Empty<WaterMaterialDescriptor>();
        }

        [Serializable]
        private sealed class WaterMaterialDescriptor
        {
            public string material_id = "water";
            public float[] base_color = Array.Empty<float>();
            public float[] deep_color = Array.Empty<float>();
            public float fog_distance_m = 8.0f;
            public float caustic_strength = 0.5f;
            public float normal_scale = 1.0f;
        }

        [Serializable]
        private sealed class LightPlacementCollection
        {
            public LightPlacement[] lights = Array.Empty<LightPlacement>();
        }

        [Serializable]
        private sealed class LightPlacement
        {
            public string light_type = "point";
            public string source_prop = string.Empty;
            public float[] position = Array.Empty<float>();
            public float[] color = Array.Empty<float>();
            public float energy = 50.0f;
            public float radius = 6.0f;
            public bool shadow = true;
            public float[] direction = Array.Empty<float>();
            public float spot_angle = 0.7853982f;
        }

        [Serializable]
        private sealed class ProbePlacementCollection
        {
            public ProbePlacement[] probes = Array.Empty<ProbePlacement>();
        }

        [Serializable]
        private sealed class ProbePlacement
        {
            public int probe_index;
            public float[] position = Array.Empty<float>();
            public float score;
        }

        [MenuItem("VeilBreakers/Terrain/Import Bundle Directory")]
        private static void ImportBundleDirectoryMenu()
        {
            var bundleDirectory = EditorUtility.OpenFolderPanel(
                "Select VeilBreakers Terrain Bundle",
                string.Empty,
                string.Empty
            );
            if (string.IsNullOrEmpty(bundleDirectory))
            {
                return;
            }

            try
            {
                ImportBundleDirectory(bundleDirectory);
            }
            catch (Exception exc)
            {
                Debug.LogError($"VeilBreakers terrain import failed: {exc}");
            }
        }

        [MenuItem("VeilBreakers/Terrain/Connect Imported Neighbors")]
        private static void ConnectImportedNeighborsMenu()
        {
            ConnectImportedNeighbors(null);
        }

        public static Terrain ImportBundleDirectory(string bundleDirectory)
        {
            var descriptorPath = SafePathCombine(bundleDirectory, ImportDescriptorName);
            if (!File.Exists(descriptorPath))
            {
                throw new FileNotFoundException(
                    $"Missing {ImportDescriptorName} in bundle directory {bundleDirectory}"
                );
            }

            var descriptorText = File.ReadAllText(descriptorPath);
            WarnUnhandledDescriptorKeys(descriptorText);
            var descriptor = JsonUtility.FromJson<TerrainBundleDescriptor>(descriptorText);
            if (descriptor == null)
            {
                throw new InvalidOperationException("Failed to parse Unity import descriptor.");
            }
            RejectFailedDescriptor(descriptor);

            var terrainData = CreateTerrainData(bundleDirectory, descriptor);
            var terrain = FindExistingTerrain(descriptor);
            var terrainObject = terrain != null
                ? terrain.gameObject
                : Terrain.CreateTerrainGameObject(terrainData);
            terrainObject.name = string.IsNullOrEmpty(descriptor.game_object_name)
                ? $"VB_{descriptor.world_id}_{descriptor.tile_x}_{descriptor.tile_y}"
                : descriptor.game_object_name;
            terrainObject.transform.position = ToVector3(descriptor.unity_world_origin);

            terrain = terrainObject.GetComponent<Terrain>();
            if (terrain == null)
            {
                throw new InvalidOperationException("Terrain.CreateTerrainGameObject returned no Terrain component.");
            }
            terrain.terrainData = terrainData;

            terrain.drawInstanced = true;
            terrain.allowAutoConnect = false;
            terrain.groupingID = 0;
            terrain.heightmapPixelError = 4.0f;
            terrain.basemapDistance = 1500.0f;
            terrain.Flush();

            var metadata = terrainObject.GetComponent<VbTerrainTileMetadata>();
            if (metadata == null)
            {
                metadata = terrainObject.AddComponent<VbTerrainTileMetadata>();
            }

            metadata.WorldId = descriptor.world_id;
            metadata.TileX = descriptor.tile_x;
            metadata.TileY = descriptor.tile_y;
            metadata.TileSize = descriptor.tile_size;
            metadata.CellSize = descriptor.cell_size;
            metadata.HeightMinMeters = descriptor.height_min_m;
            metadata.HeightMaxMeters = descriptor.height_max_m;
            metadata.HeightScaleFactor = descriptor.height_scale_factor;
            metadata.CoordinateSystem = descriptor.coordinate_system ?? "y-up";
            metadata.SourceCoordinateSystem = descriptor.source_coordinate_system ?? "z-up";
            metadata.ValidationStatus = descriptor.validation_status;
            metadata.ValidationIssueCount = descriptor.validation_issue_count;
            metadata.SeamContractWorldId = descriptor.seam_contract != null
                ? descriptor.seam_contract.world_id
                : descriptor.world_id;
            metadata.TerrainNormalsFile = descriptor.terrain_normals_file ?? string.Empty;
            metadata.TerrainNormalMapFile = descriptor.terrain_normal_map_file ?? string.Empty;
            metadata.TerrainNormalMapAssetPath = ImportTerrainNormalMapAsset(
                bundleDirectory,
                descriptor
            );
            metadata.NavMeshAreaIdFile = descriptor.navmesh_area_id_file ?? string.Empty;
            metadata.NavMeshDataAssetPath = BuildNavMeshDataAsset(bundleDirectory, terrain, descriptor);
            metadata.BiomeId = descriptor.tile_biome_id;
            metadata.PrimaryBiomeName = descriptor.tile_biome_name ?? "dark_fantasy_default";
            metadata.ClimateZone = descriptor.climate_zone ?? "temperate";
            metadata.WaterPresent = descriptor.has_water_surface;
            var waterSurfaceLocalUnityUnits = WaterLevelLocalUnityUnits(descriptor);
            metadata.WaterSurfaceElevationM = descriptor.height_scale_factor > 1e-6f
                ? waterSurfaceLocalUnityUnits / descriptor.height_scale_factor
                : waterSurfaceLocalUnityUnits;
            metadata.ScatterCount = descriptor.scatter_count;
            metadata.Lod0DistanceM = descriptor.lod0_distance_m > 0f ? descriptor.lod0_distance_m : 50f;
            metadata.Lod1DistanceM = descriptor.lod1_distance_m > 0f ? descriptor.lod1_distance_m : 150f;
            metadata.Lod2DistanceM = descriptor.lod2_distance_m > 0f ? descriptor.lod2_distance_m : 400f;
            metadata.SnowLineFactor = descriptor.snow_line_factor;

            ClearGeneratedChildren(terrainObject.transform);
            CreateSupplementalMeshes(bundleDirectory, descriptor, terrainObject.transform);
            CreateWaterSurfaces(bundleDirectory, descriptor, terrainObject.transform);
            CreateLightPlacements(bundleDirectory, descriptor, terrainObject.transform);
            CreateProbePlacements(bundleDirectory, descriptor, terrainObject.transform);
            AttachFoliageManifestRenderer(bundleDirectory, descriptor, terrainObject);
            CreateSidecarReferences(bundleDirectory, descriptor, terrainObject.transform);

            EditorUtility.SetDirty(terrainData);
            EditorUtility.SetDirty(terrain);
            EditorUtility.SetDirty(metadata);
            AssetDatabase.SaveAssets();
            ConnectImportedNeighbors(descriptor.world_id);
            Debug.Log(
                $"Imported VeilBreakers terrain tile {descriptor.world_id} [{descriptor.tile_x},{descriptor.tile_y}] " +
                $"with validation_status={descriptor.validation_status} issues={descriptor.validation_issue_count}."
            );
            return terrain;
        }

        private static void RejectFailedDescriptor(TerrainBundleDescriptor descriptor)
        {
            if (descriptor.validation_issue_count > 0 &&
                string.Equals(descriptor.validation_status, "failed", StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException(
                    $"VeilBreakers terrain descriptor failed export validation " +
                    $"({descriptor.validation_issue_count} issues). Regenerate the bundle before import."
                );
            }
        }

        private static Terrain FindExistingTerrain(TerrainBundleDescriptor descriptor)
        {
            var metadataComponents = UnityEngine.Object.FindObjectsOfType<VbTerrainTileMetadata>();
            foreach (var metadata in metadataComponents)
            {
                if (metadata == null)
                {
                    continue;
                }
                if (!string.Equals(metadata.WorldId, descriptor.world_id, StringComparison.Ordinal) ||
                    metadata.TileX != descriptor.tile_x ||
                    metadata.TileY != descriptor.tile_y)
                {
                    continue;
                }

                var terrain = metadata.GetComponent<Terrain>();
                if (terrain != null)
                {
                    return terrain;
                }
            }

            if (!string.IsNullOrEmpty(descriptor.game_object_name))
            {
                var named = GameObject.Find(descriptor.game_object_name);
                if (named != null)
                {
                    return named.GetComponent<Terrain>();
                }
            }

            return null;
        }

        private static void ClearGeneratedChildren(Transform parent)
        {
            for (var index = parent.childCount - 1; index >= 0; index--)
            {
                var child = parent.GetChild(index);
                if (child == null)
                {
                    continue;
                }

                if (IsGeneratedChild(child))
                {
                    UnityEngine.Object.DestroyImmediate(child.gameObject);
                }
            }
        }

        private static bool IsGeneratedChild(Transform child)
        {
            if (child.GetComponent<VbTerrainSidecarReference>() != null)
            {
                return true;
            }

            if (child.GetComponent("MarkGenerated") != null)
            {
                return true;
            }

            var name = child.name ?? string.Empty;
            if (name.StartsWith("VB_", StringComparison.Ordinal) ||
                name.IndexOf("vb_generated", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                return true;
            }

            return string.Equals(child.gameObject.tag, "VbGenerated", StringComparison.Ordinal);
        }

        private static VbTerrainSidecarReference MarkGenerated(
            GameObject go,
            string payloadType,
            string relativeFile = ""
        )
        {
            var reference = go.GetComponent<VbTerrainSidecarReference>();
            if (reference == null)
            {
                reference = go.AddComponent<VbTerrainSidecarReference>();
            }
            reference.PayloadType = payloadType;
            reference.RelativeFile = relativeFile ?? string.Empty;
            return reference;
        }

        private static string BuildNavMeshDataAsset(
            string bundleDirectory,
            Terrain terrain,
            TerrainBundleDescriptor descriptor
        )
        {
            if (terrain == null || terrain.terrainData == null ||
                string.IsNullOrEmpty(descriptor.navmesh_area_id_file))
            {
                return string.Empty;
            }

            var assetPath = descriptor.navmesh_data_asset_path;
            if (string.IsNullOrEmpty(assetPath))
            {
                assetPath = Path.ChangeExtension(descriptor.terrain_data_asset_path, ".navmesh.asset");
            }

            EnsureAssetFolder(Path.GetDirectoryName(assetPath)?.Replace("\\", "/"));

            var areaGrid = ReadNavMeshAreaGrid(bundleDirectory, descriptor);
            var dominantArea = DominantNavMeshArea(areaGrid);
            var source = new NavMeshBuildSource
            {
                shape = NavMeshBuildSourceShape.Terrain,
                sourceObject = terrain.terrainData,
                transform = terrain.transform.localToWorldMatrix,
                area = dominantArea
            };
            var sources = new List<NavMeshBuildSource> { source };
            AddNavMeshAreaModifierSources(sources, terrain, areaGrid, dominantArea);

            var terrainSize = terrain.terrainData.size;
            var bounds = new Bounds(
                terrainSize * 0.5f,
                terrainSize
            );
            var settings = NavMesh.GetSettingsByID(0);
            var navMeshData = NavMeshBuilder.BuildNavMeshData(
                settings,
                sources,
                bounds,
                terrain.transform.position,
                terrain.transform.rotation
            );
            if (navMeshData == null)
            {
                throw new InvalidOperationException(
                    "Unity NavMeshBuilder returned null for imported VeilBreakers terrain."
                );
            }
            navMeshData.name = Path.GetFileNameWithoutExtension(assetPath);

            var existing = AssetDatabase.LoadAssetAtPath<NavMeshData>(assetPath);
            if (existing != null)
            {
                EditorUtility.CopySerialized(navMeshData, existing);
                EditorUtility.SetDirty(existing);
            }
            else
            {
                AssetDatabase.CreateAsset(navMeshData, assetPath);
            }

            return assetPath;
        }

        private static ushort[,] ReadNavMeshAreaGrid(
            string bundleDirectory,
            TerrainBundleDescriptor descriptor
        )
        {
            if (string.IsNullOrEmpty(descriptor.navmesh_area_id_file))
            {
                return null;
            }

            var payloadPath = string.IsNullOrEmpty(bundleDirectory)
                ? descriptor.navmesh_area_id_file
                : SafePathCombine(bundleDirectory, descriptor.navmesh_area_id_file);
            if (!File.Exists(payloadPath))
            {
                return null;
            }

            var bytes = File.ReadAllBytes(payloadPath);
            if (bytes.Length < 2 || bytes.Length % 2 != 0)
            {
                return null;
            }

            var cellCount = bytes.Length / 2;
            var side = Mathf.RoundToInt(Mathf.Sqrt(cellCount));
            var rows = side;
            var cols = side;
            if (rows * cols != cellCount)
            {
                rows = Mathf.Max(1, descriptor.tile_size + 1);
                cols = rows > 0 ? cellCount / rows : 0;
                if (rows * cols != cellCount)
                {
                    rows = Mathf.Max(1, descriptor.tile_size);
                    cols = rows > 0 ? cellCount / rows : 0;
                }
            }
            if (rows <= 0 || cols <= 0 || rows * cols != cellCount)
            {
                Debug.LogWarning($"VeilBreakers navmesh area map has unsupported cell count: {cellCount}");
                return null;
            }

            var grid = new ushort[rows, cols];
            for (var index = 0; index < cellCount; index++)
            {
                var offset = index * 2;
                grid[index / cols, index % cols] = (ushort)(bytes[offset] | (bytes[offset + 1] << 8));
            }
            return grid;
        }

        private static int DominantNavMeshArea(ushort[,] areaGrid)
        {
            if (areaGrid == null)
            {
                return 0;
            }

            var counts = new Dictionary<int, int>();
            foreach (var raw in areaGrid)
            {
                var area = Mathf.Clamp(raw, 0, 31);
                counts[area] = counts.TryGetValue(area, out var count) ? count + 1 : 1;
            }

            var dominantArea = 0;
            var dominantCount = -1;
            foreach (var kvp in counts)
            {
                if (kvp.Value > dominantCount)
                {
                    dominantArea = kvp.Key;
                    dominantCount = kvp.Value;
                }
            }
            return dominantArea;
        }

        private static bool IsUnityHeightmapResolution(int resolution)
        {
            if (resolution < 33 || resolution > 4097)
            {
                return false;
            }

            var n = resolution - 1;
            return n > 0 && (n & (n - 1)) == 0;
        }

        private static float UnityOriginY(TerrainBundleDescriptor descriptor)
        {
            return descriptor.unity_world_origin != null && descriptor.unity_world_origin.Length >= 2
                ? descriptor.unity_world_origin[1]
                : descriptor.height_min_m;
        }

        private static float WaterLevelLocalUnityUnits(TerrainBundleDescriptor descriptor)
        {
            return descriptor.water_level_unity_units - UnityOriginY(descriptor);
        }

        private static Vector3 ToUnityLocalPosition(float[] unityWorldPosition, TerrainBundleDescriptor descriptor)
        {
            return ToVector3(unityWorldPosition) - ToVector3(descriptor.unity_world_origin);
        }

        private static void AddNavMeshAreaModifierSources(
            List<NavMeshBuildSource> sources,
            Terrain terrain,
            ushort[,] areaGrid,
            int dominantArea
        )
        {
            if (areaGrid == null || terrain == null || terrain.terrainData == null)
            {
                return;
            }

            var rows = areaGrid.GetLength(0);
            var cols = areaGrid.GetLength(1);
            if (rows <= 0 || cols <= 0)
            {
                return;
            }

            const int maxModifierSources = 16384;
            var terrainSize = terrain.terrainData.size;
            var cellX = terrainSize.x / cols;
            var cellZ = terrainSize.z / rows;
            var height = Mathf.Max(terrainSize.y + 20.0f, 20.0f);
            var y = terrain.transform.position.y + height * 0.5f;
            var modifierCount = 0;

            for (var row = 0; row < rows; row++)
            {
                var col = 0;
                while (col < cols)
                {
                    var area = Mathf.Clamp(areaGrid[row, col], 0, 31);
                    var start = col;
                    while (col < cols && Mathf.Clamp(areaGrid[row, col], 0, 31) == area)
                    {
                        col++;
                    }

                    if (area == dominantArea)
                    {
                        continue;
                    }

                    var widthCells = col - start;
                    var center = terrain.transform.position + new Vector3(
                        (start + widthCells * 0.5f) * cellX,
                        y - terrain.transform.position.y,
                        (row + 0.5f) * cellZ
                    );
                    sources.Add(new NavMeshBuildSource
                    {
                        shape = NavMeshBuildSourceShape.ModifierBox,
                        transform = Matrix4x4.TRS(center, Quaternion.identity, Vector3.one),
                        size = new Vector3(Mathf.Max(cellX * widthCells, 0.01f), height, Mathf.Max(cellZ, 0.01f)),
                        area = area
                    });
                    modifierCount++;
                    if (modifierCount >= maxModifierSources)
                    {
                        Debug.LogWarning(
                            $"VeilBreakers navmesh area map generated {modifierCount} modifier sources; " +
                            "remaining runs were skipped. Simplify or tile the area map for import-time baking."
                        );
                        return;
                    }
                }
            }
        }

        private static TerrainData CreateTerrainData(
            string bundleDirectory,
            TerrainBundleDescriptor descriptor
        )
        {
            var assetPath = descriptor.terrain_data_asset_path;
            EnsureAssetFolder(Path.GetDirectoryName(assetPath)?.Replace("\\", "/"));

            var terrainData = AssetDatabase.LoadAssetAtPath<TerrainData>(assetPath);
            var createAsset = terrainData == null;
            if (terrainData == null)
            {
                terrainData = new TerrainData();
            }

            if (descriptor.heightmap.width != descriptor.heightmap.height ||
                !IsUnityHeightmapResolution(descriptor.heightmap.width))
            {
                throw new InvalidDataException(
                    "Unity Terrain heightmap resolution must be square 2^n+1; " +
                    $"got {descriptor.heightmap.width}x{descriptor.heightmap.height}."
                );
            }
            terrainData.heightmapResolution = descriptor.heightmap.width;
            terrainData.alphamapResolution = descriptor.splatmaps != null && descriptor.splatmaps.Length > 0
                ? Mathf.Max(16, descriptor.splatmaps[0].width)
                : 16;
            terrainData.baseMapResolution = 1024;
            terrainData.size = new Vector3(
                Mathf.Max(descriptor.terrain_size_x_m, descriptor.tile_size * descriptor.cell_size),
                Mathf.Max(descriptor.height_max_m - descriptor.height_min_m, 1.0f),
                Mathf.Max(descriptor.terrain_size_z_m, descriptor.tile_size * descriptor.cell_size)
            );
            terrainData.wavingGrassStrength = 0.4f;
            terrainData.wavingGrassSpeed = 0.5f;
            terrainData.wavingGrassAmount = 0.5f;
            terrainData.wavingGrassTint = Color.white;

            ApplyHeightmap(bundleDirectory, descriptor, terrainData);
            ApplyTerrainLayers(bundleDirectory, descriptor, terrainData);
            ApplySplatmaps(bundleDirectory, descriptor, terrainData);
            ApplyDetailLayers(bundleDirectory, descriptor, terrainData);
            ApplyTreeInstances(bundleDirectory, descriptor, terrainData);

            if (createAsset)
            {
                AssetDatabase.CreateAsset(terrainData, assetPath);
            }
            EditorUtility.SetDirty(terrainData);
            AssetDatabase.SaveAssets();
            AssetDatabase.Refresh();
            return terrainData;
        }

        private static void ApplyHeightmap(
            string bundleDirectory,
            TerrainBundleDescriptor descriptor,
            TerrainData terrainData
        )
        {
            var heights = ReadHeightmap01(
                SafePathCombine(bundleDirectory, descriptor.heightmap.file),
                descriptor.heightmap
            );
            terrainData.SetHeights(0, 0, heights);
        }

        private static void ApplyTerrainLayers(
            string bundleDirectory,
            TerrainBundleDescriptor descriptor,
            TerrainData terrainData
        )
        {
            if (descriptor.terrain_layers == null || descriptor.terrain_layers.Length == 0)
            {
                return;
            }

            var layers = new TerrainLayer[descriptor.terrain_layers.Length];
            for (var index = 0; index < descriptor.terrain_layers.Length; index++)
            {
                layers[index] = GetOrCreateTerrainLayer(
                    bundleDirectory,
                    descriptor.terrain_layers[index]
                );
            }

            terrainData.terrainLayers = layers;
        }

        private static void ApplySplatmaps(
            string bundleDirectory,
            TerrainBundleDescriptor descriptor,
            TerrainData terrainData
        )
        {
            if (descriptor.splatmaps == null || descriptor.splatmaps.Length == 0)
            {
                return;
            }

            var height = descriptor.splatmaps[0].height;
            var width = descriptor.splatmaps[0].width;
            var layerCount = descriptor.terrain_layers != null ? descriptor.terrain_layers.Length : 0;
            if (height <= 0 || width <= 0 || layerCount <= 0)
            {
                return;
            }

            var alphamaps = new float[height, width, layerCount];
            foreach (var splatmap in descriptor.splatmaps)
            {
                var bytes = File.ReadAllBytes(SafePathCombine(bundleDirectory, splatmap.file));
                var expected = splatmap.width * splatmap.height * splatmap.channels;
                if (bytes.Length != expected)
                {
                    throw new InvalidDataException(
                        $"Unexpected splatmap size for {splatmap.file}: expected {expected}, got {bytes.Length}"
                    );
                }

                for (var y = 0; y < splatmap.height; y++)
                {
                    var srcY = splatmap.flip_vertical ? splatmap.height - 1 - y : y;
                    for (var x = 0; x < splatmap.width; x++)
                    {
                        var pixelOffset = (srcY * splatmap.width + x) * splatmap.channels;
                        for (var channel = 0; channel < splatmap.channels; channel++)
                        {
                            var layerIndex = splatmap.layer_start + channel;
                            if (layerIndex < 0 || layerIndex > splatmap.layer_end || layerIndex >= layerCount)
                            {
                                continue;
                            }

                            alphamaps[y, x, layerIndex] = bytes[pixelOffset + channel] / 255.0f;
                        }
                    }
                }
            }

            for (var y = 0; y < height; y++)
            {
                for (var x = 0; x < width; x++)
                {
                    var sum = 0.0f;
                    for (var layerIndex = 0; layerIndex < layerCount; layerIndex++)
                    {
                        sum += alphamaps[y, x, layerIndex];
                    }

                    if (sum <= 1e-5f)
                    {
                        alphamaps[y, x, 0] = 1.0f;
                        continue;
                    }

                    for (var layerIndex = 0; layerIndex < layerCount; layerIndex++)
                    {
                        alphamaps[y, x, layerIndex] /= sum;
                    }
                }
            }

            terrainData.SetAlphamaps(0, 0, alphamaps);
        }

        private static void ApplyDetailLayers(
            string bundleDirectory,
            TerrainBundleDescriptor descriptor,
            TerrainData terrainData
        )
        {
            if (descriptor.detail_layers == null || descriptor.detail_layers.Length == 0)
            {
                return;
            }

            var detailResolution = Mathf.Max(8, descriptor.detail_layers[0].width);
            terrainData.SetDetailResolution(detailResolution, 16);

            var prototypes = new DetailPrototype[descriptor.detail_layers.Length];
            for (var index = 0; index < descriptor.detail_layers.Length; index++)
            {
                var detailLayer = descriptor.detail_layers[index];
                var detailTexture = GetOrCreateSolidTexture(
                    detailLayer.placeholder_texture_asset_path,
                    DetailColor(detailLayer.kind)
                );
                prototypes[index] = new DetailPrototype
                {
                    prototypeTexture = detailTexture,
                    renderMode = DetailRenderMode.GrassBillboard,
                    minWidth = 0.75f,
                    maxWidth = 1.25f,
                    minHeight = 0.75f,
                    maxHeight = 1.35f,
                    healthyColor = Color.white,
                    dryColor = new Color(0.85f, 0.8f, 0.65f, 1.0f),
                    noiseSpread = 0.1f,
                };
            }

            terrainData.detailPrototypes = prototypes;

            for (var index = 0; index < descriptor.detail_layers.Length; index++)
            {
                var counts = ReadDetailCounts(
                    SafePathCombine(bundleDirectory, descriptor.detail_layers[index].file),
                    descriptor.detail_layers[index]
                );
                terrainData.SetDetailLayer(0, 0, index, counts);
            }
        }

        private static void ApplyTreeInstances(
            string bundleDirectory,
            TerrainBundleDescriptor descriptor,
            TerrainData terrainData
        )
        {
            if (descriptor.tree_prototypes == null || descriptor.tree_prototypes.Length == 0)
            {
                return;
            }

            var treeInstancesPath = SafePathCombine(bundleDirectory, descriptor.tree_instances_file);
            if (!File.Exists(treeInstancesPath))
            {
                return;
            }

            var payload = JsonUtility.FromJson<TreeInstanceCollection>(
                File.ReadAllText(treeInstancesPath)
            );
            if (payload == null || payload.trees == null || payload.trees.Length == 0)
            {
                return;
            }

            var prototypeById = new Dictionary<int, int>();
            var prototypes = new TreePrototype[descriptor.tree_prototypes.Length];
            for (var index = 0; index < descriptor.tree_prototypes.Length; index++)
            {
                var source = descriptor.tree_prototypes[index];
                prototypeById[source.prototype_id] = index;
                prototypes[index] = new TreePrototype
                {
                    prefab = GetOrCreateTreePrefab(source.prefab_asset),
                    bendFactor = source.bend_factor,
                };
            }

            terrainData.treePrototypes = prototypes;

            var terrainOrigin = ToVector3(descriptor.unity_world_origin);
            var terrainSize = terrainData.size;
            var instances = new List<TreeInstance>(payload.trees.Length);
            foreach (var tree in payload.trees)
            {
                if (tree.position == null || tree.position.Length < 3)
                {
                    continue;
                }

                if (!prototypeById.TryGetValue(tree.prototype_id, out var prototypeIndex))
                {
                    continue;
                }

                var normalizedPosition = new Vector3(
                    terrainSize.x > 1e-5f
                        ? Mathf.Clamp01((tree.position[0] - terrainOrigin.x) / terrainSize.x)
                        : 0.0f,
                    terrainSize.y > 1e-5f
                        ? Mathf.Clamp01((tree.position[1] - terrainOrigin.y) / terrainSize.y)
                        : 0.0f,
                    terrainSize.z > 1e-5f
                        ? Mathf.Clamp01((tree.position[2] - terrainOrigin.z) / terrainSize.z)
                        : 0.0f
                );

                instances.Add(
                    new TreeInstance
                    {
                        position = normalizedPosition,
                        prototypeIndex = prototypeIndex,
                        widthScale = Mathf.Max(0.1f, tree.width_scale),
                        heightScale = Mathf.Max(0.1f, tree.height_scale),
                        color = ToColor(tree.color),
                        lightmapColor = ToColor(tree.lightmap_color),
                    }
                );
            }

            if (instances.Count > 0)
            {
                terrainData.SetTreeInstances(instances.ToArray(), true);
            }
        }

        private static void CreateSupplementalMeshes(
            string bundleDirectory,
            TerrainBundleDescriptor descriptor,
            Transform parent
        )
        {
            if (string.IsNullOrEmpty(descriptor.supplemental_mesh_specs_file))
            {
                return;
            }

            var payloadPath = SafePathCombine(bundleDirectory, descriptor.supplemental_mesh_specs_file);
            if (!File.Exists(payloadPath))
            {
                return;
            }

            var payload = JsonUtility.FromJson<SupplementalMeshCollection>(
                File.ReadAllText(payloadPath)
            );
            if (payload == null || payload.mesh_specs == null || payload.mesh_specs.Length == 0)
            {
                return;
            }

            var materialCache = new Dictionary<string, Material>(StringComparer.Ordinal);
            foreach (var spec in payload.mesh_specs)
            {
                var mesh = BuildSupplementalMesh(spec, parent.position);
                if (mesh == null)
                {
                    continue;
                }

                var go = new GameObject(
                    string.IsNullOrEmpty(spec.mesh_id) ? "VB_SupplementalMesh" : spec.mesh_id
                );
                MarkGenerated(go, "SupplementalMesh", descriptor.supplemental_mesh_specs_file);
                go.transform.SetParent(parent, false);
                go.transform.localPosition = Vector3.zero;
                go.transform.localRotation = Quaternion.identity;
                go.transform.localScale = Vector3.one;

                var filter = go.AddComponent<MeshFilter>();
                filter.sharedMesh = mesh;

                var renderer = go.AddComponent<MeshRenderer>();
                renderer.sharedMaterial = GetOrCreateSupplementalMaterial(
                    spec.material_hint,
                    materialCache
                );
            }
        }

        private static void CreateWaterSurfaces(
            string bundleDirectory,
            TerrainBundleDescriptor descriptor,
            Transform parent
        )
        {
            if (!descriptor.has_water_surface || string.IsNullOrEmpty(descriptor.water_shader_manifest_file))
            {
                return;
            }

            if (!HasWaterRasterContract(bundleDirectory, descriptor))
            {
                Debug.LogWarning(
                    "VeilBreakers terrain import skipped water mesh creation: " +
                    "water_surface_elevation_file, water_depth_file, and flow_direction_file are required."
                );
                return;
            }

            var payloadPath = SafePathCombine(bundleDirectory, descriptor.water_shader_manifest_file);
            if (!File.Exists(payloadPath))
            {
                Debug.LogWarning($"VeilBreakers terrain import missing water shader manifest: {descriptor.water_shader_manifest_file}");
                return;
            }

            var payload = JsonUtility.FromJson<WaterShaderManifest>(File.ReadAllText(payloadPath));
            if (payload == null || payload.materials == null || payload.materials.Length == 0)
            {
                Debug.LogWarning($"VeilBreakers terrain import missing water material payload: {descriptor.water_shader_manifest_file}");
                return;
            }

            Debug.LogWarning(
                "VeilBreakers terrain import skipped raster-backed water mesh creation: " +
                "full-tile placeholder planes are disabled until water raster meshing is implemented."
            );
        }

        private static bool HasWaterRasterContract(
            string bundleDirectory,
            TerrainBundleDescriptor descriptor
        )
        {
            return File.Exists(SafePathCombine(bundleDirectory, descriptor.water_surface_elevation_file ?? string.Empty))
                && File.Exists(SafePathCombine(bundleDirectory, descriptor.water_depth_file ?? string.Empty))
                && File.Exists(SafePathCombine(bundleDirectory, descriptor.flow_direction_file ?? string.Empty));
        }

        private static Mesh BuildWaterPlaneMesh(float width, float depth, string id)
        {
            var mesh = new Mesh { name = "VB_WaterPlane_" + id };
            mesh.vertices = new[]
            {
                new Vector3(-width * 0.5f, 0.0f, -depth * 0.5f),
                new Vector3(width * 0.5f, 0.0f, -depth * 0.5f),
                new Vector3(-width * 0.5f, 0.0f, depth * 0.5f),
                new Vector3(width * 0.5f, 0.0f, depth * 0.5f),
            };
            mesh.uv = new[]
            {
                new Vector2(0.0f, 0.0f),
                new Vector2(1.0f, 0.0f),
                new Vector2(0.0f, 1.0f),
                new Vector2(1.0f, 1.0f),
            };
            mesh.triangles = new[] { 0, 2, 1, 2, 3, 1 };
            mesh.RecalculateNormals();
            mesh.RecalculateBounds();
            return mesh;
        }

        private static Material GetOrCreateWaterMaterial(
            TerrainBundleDescriptor descriptor,
            WaterMaterialDescriptor materialDescriptor
        )
        {
            var folder = Path.GetDirectoryName(descriptor.terrain_data_asset_path)?.Replace("\\", "/");
            if (string.IsNullOrEmpty(folder))
            {
                folder = "Assets/VeilBreakersTerrain/Imported";
            }
            EnsureAssetFolder(folder);

            var materialId = string.IsNullOrEmpty(materialDescriptor.material_id)
                ? "water"
                : materialDescriptor.material_id;
            var assetPath = $"{folder}/Water_{materialId}.mat";
            var material = AssetDatabase.LoadAssetAtPath<Material>(assetPath);
            if (material == null)
            {
                material = new Material(ResolveLitShader()) { name = "Water_" + materialId };
                AssetDatabase.CreateAsset(material, assetPath);
            }

            var baseColor = ToColor(materialDescriptor.base_color, "#1A4D66");
            baseColor.a = Mathf.Clamp01(0.35f + 0.08f * Mathf.Max(0.0f, materialDescriptor.caustic_strength));
            material.color = baseColor;
            if (material.HasProperty("_BaseColor"))
            {
                material.SetColor("_BaseColor", baseColor);
            }
            if (material.HasProperty("_Smoothness"))
            {
                material.SetFloat("_Smoothness", 0.88f);
            }
            if (material.HasProperty("_Metallic"))
            {
                material.SetFloat("_Metallic", 0.0f);
            }
            EditorUtility.SetDirty(material);
            return material;
        }

        private static void CreateLightPlacements(
            string bundleDirectory,
            TerrainBundleDescriptor descriptor,
            Transform parent
        )
        {
            if (string.IsNullOrEmpty(descriptor.light_placements_file))
            {
                return;
            }

            var payloadPath = SafePathCombine(bundleDirectory, descriptor.light_placements_file);
            if (!File.Exists(payloadPath))
            {
                return;
            }

            var payload = JsonUtility.FromJson<LightPlacementCollection>(File.ReadAllText(payloadPath));
            if (payload == null || payload.lights == null || payload.lights.Length == 0)
            {
                return;
            }

            var parentGo = new GameObject("VB_LightPlacements");
            MarkGenerated(parentGo, "LightPlacements", descriptor.light_placements_file);
            parentGo.transform.SetParent(parent, false);
            parentGo.transform.localPosition = Vector3.zero;
            parentGo.transform.localRotation = Quaternion.identity;
            parentGo.transform.localScale = Vector3.one;

            for (var index = 0; index < payload.lights.Length; index++)
            {
                var placement = payload.lights[index];
                if (placement == null)
                {
                    continue;
                }

                var go = new GameObject($"VB_Light_{index:000}_{placement.source_prop}");
                go.transform.SetParent(parentGo.transform, false);
                go.transform.localPosition = ToUnityLocalPosition(placement.position, descriptor);
                var light = go.AddComponent<Light>();
                light.type = ToLightType(placement.light_type);
                light.color = ToColor(placement.color, "#FFD08A");
                light.intensity = Mathf.Max(0.0f, placement.energy);
                light.range = Mathf.Max(0.1f, placement.radius);
                light.shadows = placement.shadow ? LightShadows.Soft : LightShadows.None;
                if (light.type == LightType.Spot)
                {
                    light.spotAngle = Mathf.Clamp(placement.spot_angle * Mathf.Rad2Deg, 1.0f, 179.0f);
                    var direction = ToVector3(placement.direction);
                    if (direction.sqrMagnitude > 1e-6f)
                    {
                        go.transform.rotation = Quaternion.LookRotation(direction.normalized, Vector3.up);
                    }
                }
            }
        }

        private static void CreateProbePlacements(
            string bundleDirectory,
            TerrainBundleDescriptor descriptor,
            Transform parent
        )
        {
            if (string.IsNullOrEmpty(descriptor.probe_placements_file))
            {
                return;
            }

            var payloadPath = SafePathCombine(bundleDirectory, descriptor.probe_placements_file);
            if (!File.Exists(payloadPath))
            {
                return;
            }

            var payload = JsonUtility.FromJson<ProbePlacementCollection>(File.ReadAllText(payloadPath));
            if (payload == null || payload.probes == null || payload.probes.Length == 0)
            {
                return;
            }

            var go = new GameObject("VB_LightProbeGroup");
            MarkGenerated(go, "ProbePlacements", descriptor.probe_placements_file);
            go.transform.SetParent(parent, false);
            go.transform.localPosition = Vector3.zero;
            go.transform.localRotation = Quaternion.identity;
            go.transform.localScale = Vector3.one;
            var group = go.AddComponent<LightProbeGroup>();
            var positions = new Vector3[payload.probes.Length];
            for (var index = 0; index < payload.probes.Length; index++)
            {
                positions[index] = ToUnityLocalPosition(payload.probes[index].position, descriptor);
            }
            group.probePositions = positions;
        }

        private static bool HasRenderableFoliagePrototypes(VbFoliageManifestRenderer renderer)
        {
            if (renderer == null || renderer.Prototypes == null)
            {
                return false;
            }

            foreach (var prototype in renderer.Prototypes)
            {
                if (
                    prototype != null
                    && prototype.Material != null
                    && prototype.LodMeshes != null
                    && prototype.LodMeshes.Length > 0
                    && (
                        prototype.MeshId >= 0 ||
                        !string.IsNullOrEmpty(prototype.SpeciesKey)
                    )
                )
                {
                    return true;
                }
            }

            return false;
        }

        private static void AttachFoliageManifestRenderer(
            string bundleDirectory,
            TerrainBundleDescriptor descriptor,
            GameObject terrainObject
        )
        {
            if (string.IsNullOrEmpty(descriptor.foliage_placement_manifest_file))
            {
                return;
            }

            var payloadPath = SafePathCombine(bundleDirectory, descriptor.foliage_placement_manifest_file);
            if (!File.Exists(payloadPath))
            {
                Debug.LogWarning($"VeilBreakers terrain import missing foliage placement manifest: {descriptor.foliage_placement_manifest_file}");
                return;
            }

            var renderer = terrainObject.GetComponent<VbFoliageManifestRenderer>();
            if (renderer == null)
            {
                renderer = terrainObject.AddComponent<VbFoliageManifestRenderer>();
            }

            var assetFolder = Path.GetDirectoryName(descriptor.terrain_data_asset_path)?.Replace("\\", "/");
            if (string.IsNullOrEmpty(assetFolder))
            {
                assetFolder = "Assets/VeilBreakersTerrain/Imported";
            }
            EnsureAssetFolder(assetFolder);

            var assetPath = $"{assetFolder}/{Path.GetFileName(descriptor.foliage_placement_manifest_file)}";
            File.Copy(payloadPath, assetPath, true);
            AssetDatabase.ImportAsset(assetPath, ImportAssetOptions.ForceUpdate);
            var manifestAsset = AssetDatabase.LoadAssetAtPath<TextAsset>(assetPath);

            renderer.ManifestJson = manifestAsset;
            renderer.ConvertTerrainXzyToUnityXyz = false;
            renderer.PositionsAreWorldSpace = true;
            renderer.CullDistanceM = Mathf.Max(150.0f, descriptor.lod2_distance_m);
            if (!HasRenderableFoliagePrototypes(renderer))
            {
                Debug.LogWarning(
                    "VeilBreakers terrain import attached foliage manifest, but " +
                    "VbFoliageManifestRenderer.Prototypes has no renderable mesh/material entries yet."
                );
            }
            EditorUtility.SetDirty(renderer);
        }

        private static void CreateSidecarReferences(
            string bundleDirectory,
            TerrainBundleDescriptor descriptor,
            Transform parent
        )
        {
            CreateSidecarReference(bundleDirectory, parent, "AudioZones", descriptor.audio_zones_file);
            CreateSidecarReference(bundleDirectory, parent, "GameplayZones", descriptor.gameplay_zones_file);
            CreateSidecarReference(bundleDirectory, parent, "WildlifeZones", descriptor.wildlife_zones_file);
            CreateSidecarReference(bundleDirectory, parent, "Decals", descriptor.decals_file);
            CreateSidecarReference(bundleDirectory, parent, "ParticleEmitters", descriptor.particle_emitter_specs_file);
            CreateSidecarReference(bundleDirectory, parent, "WaterShaderManifest", descriptor.water_shader_manifest_file);
            CreateSidecarReference(bundleDirectory, parent, "WaterSurfaceElevation", descriptor.water_surface_elevation_file);
            CreateSidecarReference(bundleDirectory, parent, "WaterDepth", descriptor.water_depth_file);
            CreateSidecarReference(bundleDirectory, parent, "FlowDirection", descriptor.flow_direction_file);
            CreateSidecarReference(bundleDirectory, parent, "FlowAccumulation", descriptor.flow_accumulation_file);
            CreateSidecarReference(bundleDirectory, parent, "MeshAttributes", descriptor.mesh_attributes_file);
            CreateSidecarReference(bundleDirectory, parent, "AtmosphericVolumes", descriptor.atmospheric_volumes_file);
            CreateSidecarReference(bundleDirectory, parent, "WindField", descriptor.wind_field_descriptor);
            CreateSidecarReference(bundleDirectory, parent, "CloudShadow", descriptor.cloud_shadow_descriptor);
            CreateSidecarReference(bundleDirectory, parent, "NavmeshAreaId", descriptor.navmesh_area_id_file);
            CreateSidecarReference(bundleDirectory, parent, "FoliagePlacementManifest", descriptor.foliage_placement_manifest_file);
            CreateSidecarReference(bundleDirectory, parent, "LightPlacements", descriptor.light_placements_file);
            CreateSidecarReference(bundleDirectory, parent, "ProbePlacements", descriptor.probe_placements_file);
        }

        private static void CreateSidecarReference(
            string bundleDirectory,
            Transform parent,
            string payloadType,
            string relativeFile
        )
        {
            if (string.IsNullOrEmpty(relativeFile))
            {
                return;
            }

            var payloadPath = SafePathCombine(bundleDirectory, relativeFile);
            if (!File.Exists(payloadPath))
            {
                Debug.LogWarning($"VeilBreakers terrain import missing {payloadType} sidecar: {relativeFile}");
                return;
            }

            var go = new GameObject($"VB_{payloadType}");
            go.transform.SetParent(parent, false);
            go.transform.localPosition = Vector3.zero;
            go.transform.localRotation = Quaternion.identity;
            go.transform.localScale = Vector3.one;

            var reference = go.AddComponent<VbTerrainSidecarReference>();
            reference.PayloadType = payloadType;
            reference.RelativeFile = relativeFile;
            var bytes = File.ReadAllBytes(payloadPath);
            reference.ByteSize = bytes.Length;
            if (string.Equals(Path.GetExtension(relativeFile), ".json", StringComparison.OrdinalIgnoreCase))
            {
                reference.JsonPayload = File.ReadAllText(payloadPath);
            }
        }

        private static void WarnUnhandledDescriptorKeys(string descriptorText)
        {
            var handled = new HashSet<string>(StringComparer.Ordinal)
            {
                "schema_version",
                "world_id",
                "tile_x",
                "tile_y",
                "tile_size",
                "cell_size",
                "unity_world_origin",
                "terrain_size_x_m",
                "terrain_size_z_m",
                "height_min_m",
                "height_max_m",
                "height_scale_factor",
                "coordinate_system",
                "source_coordinate_system",
                "heightmap",
                "terrain_normals_file",
                "terrain_normal_map_file",
                "mesh_attributes_file",
                "splatmaps",
                "terrain_layers",
                "detail_layers",
                "tree_prototypes",
                "tree_instances_file",
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
                "supplemental_mesh_specs_file",
                "foliage_placement_manifest_file",
                "light_placements_file",
                "probe_placements_file",
                "seam_contract",
                "validation_status",
                "validation_issue_count",
                "game_object_name",
                "terrain_data_asset_path",
                "tile_metadata_asset_path",
                "tile_biome_id",
                "tile_biome_name",
                "climate_zone",
                "water_level_unity_units",
                "has_water_surface",
                "scatter_count",
                "lod0_distance_m",
                "lod1_distance_m",
                "lod2_distance_m",
                "snow_line_factor",
            };

            foreach (var key in ExtractTopLevelJsonObjectKeys(descriptorText))
            {
                if (!handled.Contains(key))
                {
                    Debug.LogWarning($"VeilBreakers terrain import descriptor has unhandled key: {key}");
                }
            }
        }

        private static List<string> ExtractTopLevelJsonObjectKeys(string json)
        {
            var keys = new List<string>();
            var depth = 0;
            var inString = false;
            var escape = false;
            var expectingKey = false;
            var keyStart = -1;
            for (var i = 0; i < json.Length; i++)
            {
                var ch = json[i];
                if (inString)
                {
                    if (escape)
                    {
                        escape = false;
                        continue;
                    }
                    if (ch == '\\')
                    {
                        escape = true;
                        continue;
                    }
                    if (ch == '"')
                    {
                        if (keyStart >= 0)
                        {
                            keys.Add(json.Substring(keyStart, i - keyStart));
                            keyStart = -1;
                        }
                        inString = false;
                    }
                    continue;
                }

                if (ch == '"')
                {
                    inString = true;
                    keyStart = depth == 1 && expectingKey ? i + 1 : -1;
                    continue;
                }
                if (ch == '{')
                {
                    depth += 1;
                    if (depth == 1)
                    {
                        expectingKey = true;
                    }
                    continue;
                }
                if (ch == '}')
                {
                    depth = Math.Max(0, depth - 1);
                    expectingKey = false;
                    continue;
                }
                if (depth == 1 && ch == ',')
                {
                    expectingKey = true;
                    continue;
                }
                if (depth == 1 && ch == ':')
                {
                    expectingKey = false;
                }
            }

            return keys;
        }

        private static Mesh BuildSupplementalMesh(
            SupplementalMeshSpec spec,
            Vector3 terrainOrigin
        )
        {
            if (spec == null || spec.vertices == null || spec.vertices.Length < 3)
            {
                return null;
            }
            if (spec.faces == null || spec.faces.Length == 0)
            {
                return null;
            }

            var vertices = new Vector3[spec.vertices.Length];
            for (var index = 0; index < spec.vertices.Length; index++)
            {
                var source = spec.vertices[index];
                vertices[index] = new Vector3(
                    source.x - terrainOrigin.x,
                    source.y - terrainOrigin.y,
                    source.z - terrainOrigin.z
                );
            }

            var triangles = new List<int>();
            foreach (var face in spec.faces)
            {
                if (face == null || face.indices == null || face.indices.Length < 3)
                {
                    continue;
                }
                if (!TryAppendSupplementalFaceTriangles(face.indices, vertices, triangles))
                {
                    Debug.LogWarning(
                        $"VeilBreakers terrain import skipped invalid supplemental face on {spec.mesh_id}."
                    );
                }
            }

            if (triangles.Count < 3)
            {
                return null;
            }

            var mesh = new Mesh
            {
                name = string.IsNullOrEmpty(spec.mesh_id) ? "VB_SupplementalMesh" : spec.mesh_id
            };
            mesh.SetVertices(vertices);
            mesh.SetTriangles(triangles, 0);

            if (spec.uvs != null && spec.uvs.Length == vertices.Length)
            {
                var uv = new Vector2[spec.uvs.Length];
                for (var index = 0; index < spec.uvs.Length; index++)
                {
                    uv[index] = new Vector2(spec.uvs[index].x, spec.uvs[index].y);
                }
                mesh.SetUVs(0, uv);
            }
            if (spec.drip_edge_indices != null && spec.drip_edge_indices.Length > 0)
            {
                var dripMask = new List<Vector4>(vertices.Length);
                var dripVertexFlags = new bool[vertices.Length];
                foreach (var dripIndex in spec.drip_edge_indices)
                {
                    if (dripIndex >= 0 && dripIndex < dripVertexFlags.Length)
                    {
                        dripVertexFlags[dripIndex] = true;
                    }
                }

                for (var index = 0; index < vertices.Length; index++)
                {
                    dripMask.Add(new Vector4(dripVertexFlags[index] ? 1.0f : 0.0f, 0.0f, 0.0f, 0.0f));
                }
                mesh.SetUVs(1, dripMask);
            }

            mesh.RecalculateNormals();
            mesh.RecalculateBounds();
            return mesh;
        }

        private static bool TryAppendSupplementalFaceTriangles(
            int[] faceIndices,
            Vector3[] vertices,
            List<int> triangles
        )
        {
            if (faceIndices == null || faceIndices.Length < 3)
            {
                return false;
            }

            var polygon = new List<int>(faceIndices.Length);
            foreach (var rawIndex in faceIndices)
            {
                if (rawIndex < 0 || rawIndex >= vertices.Length)
                {
                    return false;
                }
                if (polygon.Count == 0 || polygon[polygon.Count - 1] != rawIndex)
                {
                    polygon.Add(rawIndex);
                }
            }

            if (polygon.Count >= 2 && polygon[0] == polygon[polygon.Count - 1])
            {
                polygon.RemoveAt(polygon.Count - 1);
            }

            if (polygon.Count == 3)
            {
                triangles.Add(polygon[0]);
                triangles.Add(polygon[1]);
                triangles.Add(polygon[2]);
                return true;
            }

            if (polygon.Count < 3)
            {
                return false;
            }

            return TryEarClipSupplementalPolygon(polygon, vertices, triangles);
        }

        private static bool TryEarClipSupplementalPolygon(
            List<int> polygon,
            Vector3[] vertices,
            List<int> triangles
        )
        {
            var projected = ProjectSupplementalPolygon(vertices, polygon);
            if (projected.Count != polygon.Count)
            {
                return false;
            }

            var working = new List<int>(polygon);
            var projectedByIndex = new Dictionary<int, Vector2>(polygon.Count);
            for (var i = 0; i < polygon.Count; i++)
            {
                projectedByIndex[polygon[i]] = projected[i];
            }

            if (ComputeSignedArea(projected) < 0.0f)
            {
                working.Reverse();
            }

            var guard = working.Count * working.Count;
            while (working.Count > 3 && guard-- > 0)
            {
                var earFound = false;
                for (var i = 0; i < working.Count; i++)
                {
                    var prevIndex = working[(i - 1 + working.Count) % working.Count];
                    var currIndex = working[i];
                    var nextIndex = working[(i + 1) % working.Count];

                    var a = projectedByIndex[prevIndex];
                    var b = projectedByIndex[currIndex];
                    var c = projectedByIndex[nextIndex];
                    if (Cross2D(a, b, c) <= 1e-5f)
                    {
                        continue;
                    }

                    var containsOther = false;
                    for (var test = 0; test < working.Count; test++)
                    {
                        var candidate = working[test];
                        if (candidate == prevIndex || candidate == currIndex || candidate == nextIndex)
                        {
                            continue;
                        }

                        if (PointInTriangle(projectedByIndex[candidate], a, b, c))
                        {
                            containsOther = true;
                            break;
                        }
                    }

                    if (containsOther)
                    {
                        continue;
                    }

                    triangles.Add(prevIndex);
                    triangles.Add(currIndex);
                    triangles.Add(nextIndex);
                    working.RemoveAt(i);
                    earFound = true;
                    break;
                }

                if (!earFound)
                {
                    return AppendFanTriangles(working, triangles);
                }
            }

            if (working.Count == 3)
            {
                triangles.Add(working[0]);
                triangles.Add(working[1]);
                triangles.Add(working[2]);
                return true;
            }

            return false;
        }

        private static List<Vector2> ProjectSupplementalPolygon(
            Vector3[] vertices,
            List<int> polygon
        )
        {
            var normal = Vector3.zero;
            for (var i = 0; i < polygon.Count; i++)
            {
                var current = vertices[polygon[i]];
                var next = vertices[polygon[(i + 1) % polygon.Count]];
                normal.x += (current.y - next.y) * (current.z + next.z);
                normal.y += (current.z - next.z) * (current.x + next.x);
                normal.z += (current.x - next.x) * (current.y + next.y);
            }

            var ax = Mathf.Abs(normal.x);
            var ay = Mathf.Abs(normal.y);
            var az = Mathf.Abs(normal.z);
            var projected = new List<Vector2>(polygon.Count);

            foreach (var vertexIndex in polygon)
            {
                var vertex = vertices[vertexIndex];
                if (ax >= ay && ax >= az)
                {
                    projected.Add(new Vector2(vertex.y, vertex.z));
                }
                else if (ay >= ax && ay >= az)
                {
                    projected.Add(new Vector2(vertex.x, vertex.z));
                }
                else
                {
                    projected.Add(new Vector2(vertex.x, vertex.y));
                }
            }

            return projected;
        }

        private static float ComputeSignedArea(List<Vector2> polygon)
        {
            var area = 0.0f;
            for (var i = 0; i < polygon.Count; i++)
            {
                var current = polygon[i];
                var next = polygon[(i + 1) % polygon.Count];
                area += (current.x * next.y) - (next.x * current.y);
            }

            return area * 0.5f;
        }

        private static float Cross2D(Vector2 a, Vector2 b, Vector2 c)
        {
            return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
        }

        private static bool PointInTriangle(Vector2 point, Vector2 a, Vector2 b, Vector2 c)
        {
            var w0 = Cross2D(a, b, point);
            var w1 = Cross2D(b, c, point);
            var w2 = Cross2D(c, a, point);
            var hasNegative = w0 < -1e-5f || w1 < -1e-5f || w2 < -1e-5f;
            var hasPositive = w0 > 1e-5f || w1 > 1e-5f || w2 > 1e-5f;
            return !(hasNegative && hasPositive);
        }

        private static bool AppendFanTriangles(List<int> polygon, List<int> triangles)
        {
            if (polygon.Count < 3)
            {
                return false;
            }

            var baseIndex = polygon[0];
            for (var i = 1; i < polygon.Count - 1; i++)
            {
                triangles.Add(baseIndex);
                triangles.Add(polygon[i]);
                triangles.Add(polygon[i + 1]);
            }

            return true;
        }

        private static Material GetOrCreateSupplementalMaterial(
            string materialHint,
            Dictionary<string, Material> cache
        )
        {
            var key = string.IsNullOrEmpty(materialHint) ? "terrain_rock" : materialHint;
            if (cache.TryGetValue(key, out var existing))
            {
                return existing;
            }

            // T1-1 fix (Y04 v3 / 2026-05-19): project is URP 17.3 per
            // project_urp_commitment_2026_05_07; HDRP shader references were
            // vestigial and caused every URP/HDRP-clean Unity build to paint
            // gray-flat terrain. Resolution order is now URP-first; if URP
            // is missing we raise loud rather than silently falling back to
            // Standard/Diffuse (which produces a flat default-grey material).
            var shader = Shader.Find("Universal Render Pipeline/Terrain/Lit");
            if (shader == null)
            {
                shader = Shader.Find("Universal Render Pipeline/Lit");
            }
            if (shader == null)
            {
                throw new System.InvalidOperationException(
                    "VbTerrainImporter: URP Terrain Lit / Universal Render Pipeline/Lit " +
                    "shader not found. Project must have URP 17.3 installed; HDRP fallback " +
                    "was removed per Y04 v3 T1-1 (URP commitment 2026-05-07).");
            }

            var material = new Material(shader)
            {
                name = $"VB_{key}"
            };
            if (key.Contains("wet", StringComparison.OrdinalIgnoreCase))
            {
                material.color = new Color(0.26f, 0.28f, 0.30f, 1.0f);
            }
            else if (key.Contains("cave", StringComparison.OrdinalIgnoreCase))
            {
                material.color = new Color(0.22f, 0.20f, 0.18f, 1.0f);
            }
            else
            {
                material.color = new Color(0.42f, 0.40f, 0.38f, 1.0f);
            }

            cache[key] = material;
            return material;
        }

        private static TerrainLayer GetOrCreateTerrainLayer(
            string bundleDirectory,
            TerrainLayerDescriptor descriptor
        )
        {
            var assetPath = descriptor.terrain_layer_asset_path;
            var layer = AssetDatabase.LoadAssetAtPath<TerrainLayer>(assetPath);
            if (layer != null)
            {
                return layer;
            }

            EnsureAssetFolder(Path.GetDirectoryName(assetPath)?.Replace("\\", "/"));
            layer = new TerrainLayer();

            var color = ToColor(descriptor.base_color_rgb, descriptor.base_color_hex);
            var smoothness = Mathf.Clamp01(descriptor.smoothness);
            var diffusePath = assetPath.Replace(".terrainlayer", "_Diffuse.asset");
            var normalPath = assetPath.Replace(".terrainlayer", "_Normal.asset");
            var maskPath = assetPath.Replace(".terrainlayer", "_Mask.asset");

            layer.diffuseTexture = ResolveLayerTexture(
                bundleDirectory,
                descriptor.diffuse_texture_file,
                diffusePath,
                false,
                color,
                descriptor,
                "diffuse"
            );
            layer.normalMapTexture = ResolveLayerTexture(
                bundleDirectory,
                descriptor.normal_texture_file,
                normalPath,
                true,
                new Color(0.5f, 0.5f, 1.0f, 1.0f),
                descriptor,
                "normal"
            );
            layer.maskMapTexture = ResolveLayerTexture(
                bundleDirectory,
                descriptor.mask_texture_file,
                maskPath,
                false,
                new Color(
                    0.0f,
                    1.0f,
                    Mathf.Clamp01(descriptor.height_blend_factor),
                    smoothness
                ),
                descriptor,
                "mask"
            );
            layer.tileSize = new Vector2(
                Mathf.Max(1.0f, descriptor.uv_scale_meters),
                Mathf.Max(1.0f, descriptor.uv_scale_meters)
            );
            layer.tileOffset = Vector2.zero;
            layer.normalScale = Mathf.Max(0.0f, descriptor.normal_map_intensity);
            layer.metallic = 0.0f;
            layer.smoothness = smoothness;

            AssetDatabase.CreateAsset(layer, assetPath);
            EditorUtility.SetDirty(layer);
            AssetDatabase.SaveAssets();
            return layer;
        }

        private static Texture2D ResolveLayerTexture(
            string bundleDirectory,
            string relativeTextureFile,
            string generatedAssetPath,
            bool normalMap,
            Color fallbackColor,
            TerrainLayerDescriptor descriptor,
            string channel
        )
        {
            if (!string.IsNullOrEmpty(relativeTextureFile))
            {
                var sourcePath = SafePathCombine(bundleDirectory, relativeTextureFile);
                if (!File.Exists(sourcePath))
                {
                    throw new FileNotFoundException(
                        $"Terrain layer '{descriptor.layer_id}' declares {channel} texture " +
                        $"'{relativeTextureFile}' but the file is missing from the export bundle."
                    );
                }

                var extension = Path.GetExtension(relativeTextureFile);
                var assetPath = generatedAssetPath.Replace(".asset", string.IsNullOrEmpty(extension) ? ".png" : extension);
                return ImportTextureAsset(sourcePath, assetPath, normalMap);
            }

            return GetOrCreateProceduralLayerTexture(
                generatedAssetPath,
                fallbackColor,
                descriptor,
                channel,
                normalMap
            );
        }

        private static string ImportTerrainNormalMapAsset(
            string bundleDirectory,
            TerrainBundleDescriptor descriptor
        )
        {
            if (descriptor == null || string.IsNullOrEmpty(descriptor.terrain_normal_map_file))
            {
                return string.Empty;
            }

            var sourcePath = SafePathCombine(bundleDirectory, descriptor.terrain_normal_map_file);
            if (!File.Exists(sourcePath))
            {
                Debug.LogWarning(
                    $"VeilBreakers terrain import missing normal-map texture: {descriptor.terrain_normal_map_file}"
                );
                return string.Empty;
            }

            var assetFolder = Path.GetDirectoryName(descriptor.terrain_data_asset_path)?.Replace("\\", "/");
            if (string.IsNullOrEmpty(assetFolder))
            {
                assetFolder = "Assets/VeilBreakersTerrain/Generated";
            }

            var assetPath = $"{assetFolder}/{Path.GetFileName(descriptor.terrain_normal_map_file)}";
            var texture = ImportTextureAsset(sourcePath, assetPath, normalMap: true);
            return texture != null ? assetPath : string.Empty;
        }

        private static Texture2D ImportTextureAsset(
            string sourcePath,
            string assetPath,
            bool normalMap
        )
        {
            var normalizedAssetPath = assetPath.Replace("\\", "/");
            EnsureAssetFolder(Path.GetDirectoryName(normalizedAssetPath)?.Replace("\\", "/"));

            var sourceFullPath = Path.GetFullPath(sourcePath);
            var destinationFullPath = Path.GetFullPath(normalizedAssetPath);
            if (!string.Equals(sourceFullPath, destinationFullPath, StringComparison.OrdinalIgnoreCase))
            {
                File.Copy(sourceFullPath, destinationFullPath, true);
            }

            AssetDatabase.ImportAsset(normalizedAssetPath, ImportAssetOptions.ForceUpdate);
            var importer = AssetImporter.GetAtPath(normalizedAssetPath) as TextureImporter;
            if (importer != null)
            {
                importer.textureType = normalMap ? TextureImporterType.NormalMap : TextureImporterType.Default;
                importer.sRGBTexture = !normalMap;
                importer.mipmapEnabled = true;
                importer.wrapMode = TextureWrapMode.Repeat;
                // T1-22 fix (Y04 v3 / 2026-05-19): every imported terrain
                // texture routed through ImportTextureAsset — terrain layer
                // diffuse/albedo textures AND terrain normal maps (via
                // ImportTerrainNormalMapAsset, which delegates here with
                // normalMap: true) — needs trilinear filtering + anisoLevel 16
                // to avoid moire / shimmer at grazing angles when the agent
                // walks across terrain. Snowdrop and Anvil both default
                // terrain textures to aniso 8-16 + trilinear. Previously
                // this was Bilinear + default anisoLevel=1, producing
                // visible aliasing in motion.
                //
                // CHECKPOINT-OPUS-ULTRA V5 followup (2026-05-19): bumped 8 -> 16
                // to hit hero-AAA bar. Witcher 3 / Snowdrop / Anvil ship ground
                // textures at 16; Unity max is 16
                // (https://docs.unity3d.com/ScriptReference/Texture-anisoLevel.html);
                // modern desktop GPUs (PS5 / XSX / RTX) have no perf cost for
                // 16 vs 8 on terrain. aniso 8 was mobile-AAA bar.
                //
                // PR #115 round-2 (copilot thread T115-2): scope reworded to
                // reflect that this importer is shared between layer and
                // normal-map paths, not just terrain-layer textures.
                importer.filterMode = FilterMode.Trilinear;
                importer.anisoLevel = 16;
                importer.SaveAndReimport();
            }

            return AssetDatabase.LoadAssetAtPath<Texture2D>(normalizedAssetPath);
        }

        private static Texture2D GetOrCreateProceduralLayerTexture(
            string assetPath,
            Color baseColor,
            TerrainLayerDescriptor descriptor,
            string channel,
            bool normalMap
        )
        {
            var texture = AssetDatabase.LoadAssetAtPath<Texture2D>(assetPath);
            if (texture != null)
            {
                return texture;
            }

            EnsureAssetFolder(Path.GetDirectoryName(assetPath)?.Replace("\\", "/"));
            const int size = 256;
            texture = new Texture2D(size, size, TextureFormat.RGBA32, true, !normalMap)
            {
                name = Path.GetFileNameWithoutExtension(assetPath),
                wrapMode = TextureWrapMode.Repeat,
                filterMode = FilterMode.Trilinear
            };

            var pixels = new Color[size * size];
            var seed = Mathf.Abs((descriptor.layer_id ?? "layer").GetHashCode());
            var roughness = Mathf.Clamp01(descriptor.roughness);
            var smoothness = Mathf.Clamp01(descriptor.smoothness);
            for (var y = 0; y < size; y++)
            {
                for (var x = 0; x < size; x++)
                {
                    var nx = (x + (seed & 255)) / 37.0f;
                    var ny = (y + ((seed >> 8) & 255)) / 41.0f;
                    var macro = Mathf.PerlinNoise(nx, ny);
                    var detail = Mathf.PerlinNoise(nx * 4.7f + 19.0f, ny * 4.7f + 11.0f);
                    var grain = Mathf.PerlinNoise(nx * 15.0f + 3.0f, ny * 15.0f + 7.0f);
                    var n = Mathf.Clamp01(0.55f * macro + 0.30f * detail + 0.15f * grain);

                    if (normalMap)
                    {
                        var dx = Mathf.PerlinNoise(nx + 0.05f, ny) - Mathf.PerlinNoise(nx - 0.05f, ny);
                        var dy = Mathf.PerlinNoise(nx, ny + 0.05f) - Mathf.PerlinNoise(nx, ny - 0.05f);
                        var normal = new Vector3(-dx * descriptor.normal_map_intensity, -dy * descriptor.normal_map_intensity, 1.0f).normalized;
                        pixels[y * size + x] = new Color(normal.x * 0.5f + 0.5f, normal.y * 0.5f + 0.5f, normal.z * 0.5f + 0.5f, 1.0f);
                    }
                    else if (string.Equals(channel, "mask", StringComparison.OrdinalIgnoreCase))
                    {
                        pixels[y * size + x] = new Color(
                            0.0f,
                            Mathf.Lerp(0.78f, 1.0f, n),
                            Mathf.Clamp01(descriptor.height_blend_factor + (n - 0.5f) * 0.12f),
                            Mathf.Clamp01(smoothness + (n - 0.5f) * Mathf.Lerp(0.03f, 0.12f, roughness))
                        );
                    }
                    else
                    {
                        var shade = Mathf.Lerp(0.78f, 1.22f, n);
                        pixels[y * size + x] = new Color(
                            Mathf.Clamp01(baseColor.r * shade),
                            Mathf.Clamp01(baseColor.g * shade),
                            Mathf.Clamp01(baseColor.b * shade),
                            1.0f
                        );
                    }
                }
            }

            texture.SetPixels(pixels);
            texture.Apply(true, true);
            AssetDatabase.CreateAsset(texture, assetPath);
            return texture;
        }

        private static Texture2D GetOrCreateSolidTexture(string assetPath, Color color)
        {
            var texture = AssetDatabase.LoadAssetAtPath<Texture2D>(assetPath);
            if (texture != null)
            {
                return texture;
            }

            EnsureAssetFolder(Path.GetDirectoryName(assetPath)?.Replace("\\", "/"));
            texture = new Texture2D(4, 4, TextureFormat.RGBA32, false, true)
            {
                name = Path.GetFileNameWithoutExtension(assetPath),
                wrapMode = TextureWrapMode.Repeat,
                filterMode = FilterMode.Bilinear
            };

            var pixels = new Color[16];
            for (var index = 0; index < pixels.Length; index++)
            {
                pixels[index] = color;
            }

            texture.SetPixels(pixels);
            texture.Apply(false, true);
            AssetDatabase.CreateAsset(texture, assetPath);
            return texture;
        }

        private static GameObject GetOrCreateTreePrefab(string prefabAssetPath)
        {
            var normalizedPath = string.IsNullOrEmpty(prefabAssetPath)
                ? "Assets/VeilBreakersTerrain/GeneratedTrees/Prototype.prefab"
                : prefabAssetPath.Replace("\\", "/");
            if (!normalizedPath.StartsWith("Assets/", StringComparison.Ordinal))
            {
                normalizedPath = "Assets/VeilBreakersTerrain/GeneratedTrees/" + normalizedPath.TrimStart('/');
            }
            var assetPath = normalizedPath.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase)
                ? normalizedPath
                : normalizedPath + ".prefab";
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(assetPath);
            if (prefab != null)
            {
                return prefab;
            }

            EnsureAssetFolder(Path.GetDirectoryName(assetPath)?.Replace("\\", "/"));
            var materialPath = assetPath.Replace(".prefab", "_Mat.mat");
            var material = AssetDatabase.LoadAssetAtPath<Material>(materialPath);
            if (material == null)
            {
                // T1-1 fix (Y04 v3 / 2026-05-19): URP-first lookup with loud
                // failure on miss; removes vestigial HDRP references and the
                // Standard-shader silent fallback that produced gray-flat
                // prefab materials. See project_urp_commitment_2026_05_07.
                var shader = Shader.Find("Universal Render Pipeline/Lit");
                if (shader == null)
                {
                    throw new System.InvalidOperationException(
                        "VbTerrainImporter: Universal Render Pipeline/Lit shader not " +
                        "found. URP 17.3 is required (Y04 v3 T1-1).");
                }

                material = new Material(shader)
                {
                    color = new Color(0.28f, 0.22f, 0.14f, 1.0f)
                };
                AssetDatabase.CreateAsset(material, materialPath);
            }

            var root = GameObject.CreatePrimitive(PrimitiveType.Capsule);
            root.name = Path.GetFileNameWithoutExtension(assetPath);
            var renderer = root.GetComponent<Renderer>();
            if (renderer != null)
            {
                renderer.sharedMaterial = material;
            }

            prefab = PrefabUtility.SaveAsPrefabAsset(root, assetPath);
            UnityEngine.Object.DestroyImmediate(root);
            return prefab;
        }

        private static float[,] ReadHeightmap01(string filePath, HeightmapDescriptor descriptor)
        {
            var bytes = File.ReadAllBytes(filePath);
            var expectedBytes = descriptor.width * descriptor.height * (descriptor.bit_depth / 8);
            if (bytes.Length != expectedBytes)
            {
                throw new InvalidDataException(
                    $"Unexpected heightmap size for {descriptor.file}: expected {expectedBytes}, got {bytes.Length}"
                );
            }

            var heights = new float[descriptor.height, descriptor.width];
            if (descriptor.bit_depth == 16)
            {
                for (var y = 0; y < descriptor.height; y++)
                {
                    var srcY = descriptor.flip_vertical ? descriptor.height - 1 - y : y;
                    for (var x = 0; x < descriptor.width; x++)
                    {
                        var offset = (srcY * descriptor.width + x) * 2;
                        var value = (ushort)(bytes[offset] | (bytes[offset + 1] << 8));
                        heights[y, x] = value / 65535.0f;
                    }
                }
            }
            else
            {
                for (var y = 0; y < descriptor.height; y++)
                {
                    var srcY = descriptor.flip_vertical ? descriptor.height - 1 - y : y;
                    for (var x = 0; x < descriptor.width; x++)
                    {
                        var offset = srcY * descriptor.width + x;
                        heights[y, x] = bytes[offset] / 255.0f;
                    }
                }
            }

            return heights;
        }

        private static int[,] ReadDetailCounts(string filePath, DetailLayerDescriptor descriptor)
        {
            var bytes = File.ReadAllBytes(filePath);
            var expectedBytes = descriptor.width * descriptor.height * 2;
            if (bytes.Length != expectedBytes)
            {
                throw new InvalidDataException(
                    $"Unexpected detail map size for {descriptor.file}: expected {expectedBytes}, got {bytes.Length}"
                );
            }

            var counts = new int[descriptor.height, descriptor.width];
            for (var y = 0; y < descriptor.height; y++)
            {
                var srcY = descriptor.flip_vertical ? descriptor.height - 1 - y : y;
                for (var x = 0; x < descriptor.width; x++)
                {
                    var offset = (srcY * descriptor.width + x) * 2;
                    var value = (ushort)(bytes[offset] | (bytes[offset + 1] << 8));
                    counts[y, x] = Mathf.Clamp(value, 0, descriptor.max_density_per_cell);
                }
            }

            return counts;
        }

        private static void ConnectImportedNeighbors(string worldId)
        {
            var metadataComponents = UnityEngine.Object.FindObjectsOfType<VbTerrainTileMetadata>();
            var terrainsByKey = new Dictionary<string, Terrain>();
            foreach (var metadata in metadataComponents)
            {
                if (metadata == null)
                {
                    continue;
                }

                if (!string.IsNullOrEmpty(worldId) && !string.Equals(metadata.WorldId, worldId, StringComparison.Ordinal))
                {
                    continue;
                }

                var terrain = metadata.GetComponent<Terrain>();
                if (terrain == null)
                {
                    continue;
                }

                terrainsByKey[TileKey(metadata.WorldId, metadata.TileX, metadata.TileY)] = terrain;
            }

            foreach (var metadata in metadataComponents)
            {
                if (metadata == null)
                {
                    continue;
                }

                if (!string.IsNullOrEmpty(worldId) && !string.Equals(metadata.WorldId, worldId, StringComparison.Ordinal))
                {
                    continue;
                }

                var terrain = metadata.GetComponent<Terrain>();
                if (terrain == null)
                {
                    continue;
                }

                terrainsByKey.TryGetValue(TileKey(metadata.WorldId, metadata.TileX - 1, metadata.TileY), out var left);
                terrainsByKey.TryGetValue(TileKey(metadata.WorldId, metadata.TileX, metadata.TileY + 1), out var top);
                terrainsByKey.TryGetValue(TileKey(metadata.WorldId, metadata.TileX + 1, metadata.TileY), out var right);
                terrainsByKey.TryGetValue(TileKey(metadata.WorldId, metadata.TileX, metadata.TileY - 1), out var bottom);

                terrain.SetNeighbors(left, top, right, bottom);
                EditorUtility.SetDirty(terrain);
            }
        }

        private static string TileKey(string worldId, int tileX, int tileY)
        {
            return worldId + "::" + tileX + "::" + tileY;
        }

        private static Shader ResolveLitShader()
        {
            // T1-1 fix (Y04 v3 / 2026-05-19): URP-first resolution; raise
            // loud when URP is missing rather than silently substituting
            // Standard or Diffuse (which produced unlit gray-flat terrain in
            // URP-clean Unity builds). Project commitment: URP 17.3 per
            // project_urp_commitment_2026_05_07.
            var shader = Shader.Find("Universal Render Pipeline/Terrain/Lit");
            if (shader == null)
            {
                shader = Shader.Find("Universal Render Pipeline/Lit");
            }
            if (shader == null)
            {
                throw new System.InvalidOperationException(
                    "VbTerrainImporter.ResolveLitShader: URP Terrain Lit / Universal " +
                    "Render Pipeline/Lit shader not found. URP 17.3 required (Y04 v3 T1-1).");
            }
            return shader;
        }

        private static LightType ToLightType(string lightType)
        {
            switch ((lightType ?? "point").ToLowerInvariant())
            {
                case "spot":
                case "god_ray":
                    return LightType.Spot;
                case "area":
                case "portal":
                case "sky_bounce":
                    return LightType.Area;
                case "directional":
                case "sun":
                    return LightType.Directional;
                default:
                    return LightType.Point;
            }
        }

        /// <summary>
        /// CWE-22 path-traversal containment guard (Verifier A 2026-05-21 #17).
        /// Resolves <paramref name="parts"/> against <paramref name="baseDir"/> via
        /// <see cref="Path.GetFullPath"/> and throws <see cref="System.Security.SecurityException"/>
        /// when the resolved path does not start with the canonical bundle directory.
        /// All reads from manifest-controlled file paths MUST go through this helper.
        /// </summary>
        private static string SafePathCombine(string baseDir, params string[] parts)
        {
            var baseFullPath = Path.GetFullPath(baseDir);
            // Ensure canonical form ends with separator so "bundleDirExtra/..." is not a false match.
            if (!baseFullPath.EndsWith(Path.DirectorySeparatorChar.ToString(), StringComparison.Ordinal) &&
                !baseFullPath.EndsWith(Path.AltDirectorySeparatorChar.ToString(), StringComparison.Ordinal))
            {
                baseFullPath += Path.DirectorySeparatorChar;
            }

            var allParts = new string[parts.Length + 1];
            allParts[0] = baseDir;
            parts.CopyTo(allParts, 1);
            var combined = Path.Combine(allParts);
            var fullPath = Path.GetFullPath(combined);

            if (!fullPath.StartsWith(baseFullPath, StringComparison.OrdinalIgnoreCase))
            {
                throw new System.Security.SecurityException(
                    $"VbTerrainImporter: refused to access '{combined}' — resolves outside bundle " +
                    $"directory '{baseFullPath}' (CWE-22 path traversal guard)"
                );
            }
            return fullPath;
        }

        private static void EnsureAssetFolder(string assetFolder)
        {
            if (string.IsNullOrEmpty(assetFolder) || AssetDatabase.IsValidFolder(assetFolder))
            {
                return;
            }

            var parts = assetFolder.Split('/');
            if (parts.Length == 0 || parts[0] != "Assets")
            {
                throw new ArgumentException($"Asset folder must start with Assets/: {assetFolder}");
            }

            var current = parts[0];
            for (var index = 1; index < parts.Length; index++)
            {
                var next = current + "/" + parts[index];
                if (!AssetDatabase.IsValidFolder(next))
                {
                    AssetDatabase.CreateFolder(current, parts[index]);
                }

                current = next;
            }
        }

        private static Vector3 ToVector3(float[] values)
        {
            if (values == null || values.Length < 3)
            {
                return Vector3.zero;
            }

            return new Vector3(values[0], values[1], values[2]);
        }

        private static Color ToColor(float[] rgbValues, string hexFallback)
        {
            if (rgbValues != null && rgbValues.Length >= 3)
            {
                return new Color(rgbValues[0], rgbValues[1], rgbValues[2], 1.0f);
            }

            if (ColorUtility.TryParseHtmlString(hexFallback, out var parsed))
            {
                parsed.a = 1.0f;
                return parsed;
            }

            return Color.gray;
        }

        private static Color ToColor(ColorPayload payload)
        {
            if (payload == null)
            {
                return Color.white;
            }

            return new Color(payload.r, payload.g, payload.b, payload.a);
        }

        private static Color DetailColor(string kind)
        {
            switch (kind)
            {
                case "canopy":
                    return new Color(0.26f, 0.42f, 0.20f, 1.0f);
                case "ground_cover":
                    return new Color(0.42f, 0.48f, 0.24f, 1.0f);
                case "grass":
                    return new Color(0.34f, 0.56f, 0.22f, 1.0f);
                default:
                    return new Color(0.55f, 0.65f, 0.38f, 1.0f);
            }
        }
    }
}
