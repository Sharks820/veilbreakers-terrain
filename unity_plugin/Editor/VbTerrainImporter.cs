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
            public string terrain_normal_map_file = string.Empty;
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
            public string supplemental_mesh_specs_file = string.Empty;
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
            metadata.TileSize = descriptor.tile_size;
            metadata.CellSize = descriptor.cell_size;
            metadata.HeightMinMeters = descriptor.height_min_m;
            metadata.HeightMaxMeters = descriptor.height_max_m;
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
            metadata.BiomeId = descriptor.tile_biome_id;
            metadata.PrimaryBiomeName = descriptor.tile_biome_name ?? "dark_fantasy_default";
            metadata.ClimateZone = descriptor.climate_zone ?? "temperate";
            metadata.WaterPresent = descriptor.has_water_surface;
            metadata.WaterSurfaceElevationM = descriptor.water_level_unity_units;
            metadata.ScatterCount = descriptor.scatter_count;
            metadata.Lod0DistanceM = descriptor.lod0_distance_m > 0f ? descriptor.lod0_distance_m : 50f;
            metadata.Lod1DistanceM = descriptor.lod1_distance_m > 0f ? descriptor.lod1_distance_m : 150f;
            metadata.Lod2DistanceM = descriptor.lod2_distance_m > 0f ? descriptor.lod2_distance_m : 400f;
            metadata.SnowLineFactor = descriptor.snow_line_factor;

            CreateSupplementalMeshes(bundleDirectory, descriptor, terrainObject.transform);
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

            terrainData.heightmapResolution = Mathf.Max(33, descriptor.heightmap.width);
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

            var payloadPath = Path.Combine(bundleDirectory, descriptor.supplemental_mesh_specs_file);
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

            var payloadPath = Path.Combine(bundleDirectory, relativeFile);
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
            reference.JsonPayload = File.ReadAllText(payloadPath);
            reference.ByteSize = reference.JsonPayload.Length;
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

            var shader = Shader.Find("HDRP/TerrainLit");
            if (shader == null)
            {
                shader = Shader.Find("HDRP/Lit");
            }
            if (shader == null)
            {
                shader = Shader.Find("Universal Render Pipeline/Lit");
            }
            if (shader == null)
            {
                shader = Shader.Find("Standard");
            }
            if (shader == null)
            {
                shader = Shader.Find("Diffuse");
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

        private static string ImportTerrainNormalMapAsset(
            string bundleDirectory,
            TerrainBundleDescriptor descriptor
        )
        {
            if (descriptor == null || string.IsNullOrEmpty(descriptor.terrain_normal_map_file))
            {
                return string.Empty;
            }

            var sourcePath = Path.Combine(bundleDirectory, descriptor.terrain_normal_map_file);
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
                importer.filterMode = FilterMode.Bilinear;
                importer.SaveAndReimport();
            }

            return AssetDatabase.LoadAssetAtPath<Texture2D>(normalizedAssetPath);
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
                var shader = Shader.Find("HDRP/TerrainLit");
                if (shader == null)
                {
                    shader = Shader.Find("HDRP/Lit");
                }
                if (shader == null)
                {
                    shader = Shader.Find("Universal Render Pipeline/Lit");
                }
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
