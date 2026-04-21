using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;
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
            public HeightmapDescriptor heightmap = new HeightmapDescriptor();
            public string terrain_normals_file = string.Empty;
            public SplatmapDescriptor[] splatmaps = Array.Empty<SplatmapDescriptor>();
            public TerrainLayerDescriptor[] terrain_layers = Array.Empty<TerrainLayerDescriptor>();
            public DetailLayerDescriptor[] detail_layers = Array.Empty<DetailLayerDescriptor>();
            public TreePrototypeDescriptor[] tree_prototypes = Array.Empty<TreePrototypeDescriptor>();
            public string tree_instances_file = "tree_instances.json";
            public SeamContractPayload seam_contract = new SeamContractPayload();
            public string validation_status = "unknown";
            public int validation_issue_count;
            public string game_object_name = "VB_Terrain";
            public string terrain_data_asset_path = "Assets/VeilBreakersTerrain/Imported/TerrainData.asset";
            public string tile_metadata_asset_path = "Assets/VeilBreakersTerrain/Imported/TerrainTile.asset";
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
            var descriptorPath = Path.Combine(bundleDirectory, ImportDescriptorName);
            if (!File.Exists(descriptorPath))
            {
                throw new FileNotFoundException(
                    $"Missing {ImportDescriptorName} in bundle directory {bundleDirectory}"
                );
            }

            var descriptor = JsonUtility.FromJson<TerrainBundleDescriptor>(
                File.ReadAllText(descriptorPath)
            );
            if (descriptor == null)
            {
                throw new InvalidOperationException("Failed to parse Unity import descriptor.");
            }

            var terrainData = CreateTerrainData(bundleDirectory, descriptor);
            var terrainObject = Terrain.CreateTerrainGameObject(terrainData);
            terrainObject.name = string.IsNullOrEmpty(descriptor.game_object_name)
                ? $"VB_{descriptor.world_id}_{descriptor.tile_x}_{descriptor.tile_y}"
                : descriptor.game_object_name;
            terrainObject.transform.position = ToVector3(descriptor.unity_world_origin);

            var terrain = terrainObject.GetComponent<Terrain>();
            if (terrain == null)
            {
                throw new InvalidOperationException("Terrain.CreateTerrainGameObject returned no Terrain component.");
            }

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

        private static TerrainData CreateTerrainData(
            string bundleDirectory,
            TerrainBundleDescriptor descriptor
        )
        {
            var assetPath = AssetDatabase.GenerateUniqueAssetPath(descriptor.terrain_data_asset_path);
            EnsureAssetFolder(Path.GetDirectoryName(assetPath)?.Replace("\\", "/"));

            var terrainData = new TerrainData
            {
                heightmapResolution = Mathf.Max(33, descriptor.heightmap.width),
                alphamapResolution = descriptor.splatmaps != null && descriptor.splatmaps.Length > 0
                    ? Mathf.Max(16, descriptor.splatmaps[0].width)
                    : 16,
                baseMapResolution = 1024,
                size = new Vector3(
                    Mathf.Max(descriptor.terrain_size_x_m, descriptor.tile_size * descriptor.cell_size),
                    Mathf.Max(descriptor.height_max_m - descriptor.height_min_m, 1.0f),
                    Mathf.Max(descriptor.terrain_size_z_m, descriptor.tile_size * descriptor.cell_size)
                ),
                wavingGrassStrength = 0.4f,
                wavingGrassSpeed = 0.5f,
                wavingGrassAmount = 0.5f,
                wavingGrassTint = Color.white
            };

            ApplyHeightmap(bundleDirectory, descriptor, terrainData);
            ApplyTerrainLayers(bundleDirectory, descriptor, terrainData);
            ApplySplatmaps(bundleDirectory, descriptor, terrainData);
            ApplyDetailLayers(bundleDirectory, descriptor, terrainData);
            ApplyTreeInstances(bundleDirectory, descriptor, terrainData);

            AssetDatabase.CreateAsset(terrainData, assetPath);
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
                Path.Combine(bundleDirectory, descriptor.heightmap.file),
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
                var bytes = File.ReadAllBytes(Path.Combine(bundleDirectory, splatmap.file));
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
                    Path.Combine(bundleDirectory, descriptor.detail_layers[index].file),
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

            var treeInstancesPath = Path.Combine(bundleDirectory, descriptor.tree_instances_file);
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

            layer.diffuseTexture = GetOrCreateSolidTexture(diffusePath, color);
            layer.normalMapTexture = GetOrCreateSolidTexture(
                normalPath,
                new Color(0.5f, 0.5f, 1.0f, 1.0f)
            );
            layer.maskMapTexture = GetOrCreateSolidTexture(
                maskPath,
                new Color(
                    0.0f,
                    1.0f,
                    Mathf.Clamp01(descriptor.height_blend_factor),
                    smoothness
                )
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
            var assetPath = prefabAssetPath.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase)
                ? prefabAssetPath
                : prefabAssetPath + ".prefab";
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
                var shader = Shader.Find("Universal Render Pipeline/Lit");
                if (shader == null)
                {
                    shader = Shader.Find("Standard");
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

            var counts = new int[descriptor.width, descriptor.height];
            for (var y = 0; y < descriptor.height; y++)
            {
                var srcY = descriptor.flip_vertical ? descriptor.height - 1 - y : y;
                for (var x = 0; x < descriptor.width; x++)
                {
                    var offset = (srcY * descriptor.width + x) * 2;
                    var value = (ushort)(bytes[offset] | (bytes[offset + 1] << 8));
                    counts[x, y] = Mathf.Clamp(value, 0, descriptor.max_density_per_cell);
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
