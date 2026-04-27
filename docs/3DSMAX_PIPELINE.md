# VeilBreakers — 3ds Max / Forest Pack Pro Integration Guide

**Last updated:** 2026-04-27  
**Target software:** 3ds Max 2025, Forest Pack Pro 9.x  
**Terrain pipeline:** Python / Blender 4.5, 1024 × 1024 m tiles  
**GPU constraint:** 8 GB VRAM, 32 GB RAM

---

## 1. When to Use Which Tool

| Task | Tool | Reason |
|---|---|---|
| Terrain height, erosion, rivers, cliffs, caves | **Blender** | Python-scriptable, parametric, source-of-truth |
| Water surfaces, foam, waterfalls | **Blender** | Custom shader/geometry nodes wired to terrain pipeline |
| Procedural cliff placement, path contour-following | **Blender** | Needs heightmap access at generation time |
| Dense vegetation scatter (thousands of trees/rocks) | **3ds Max + Forest Pack Pro** | GPU instancing, LOD, render-engine integration |
| Hero props, unique set-dressing, cutscene polish | **3ds Max** (manual or Forest Pack Custom Edit) | Artist-controlled per-object adjustment |
| Foliage mesh authoring (trees, shrubs, grass cards) | **TreeIt / GrowFX / SpeedTree** → FBX → 3ds Max | See Section 4 |
| Final lighting, V-Ray / Corona render | **3ds Max** | Production render engines |
| Quick iteration, in-engine preview | **Blender** or **Unity** (see unity_plugin/) | Faster round-trip |

**Rule of thumb:** Blender owns the *terrain data*; 3ds Max owns the *final scatter and render*.  
Never edit the terrain mesh in 3ds Max — always re-import from the Blender FBX export.

---

## 2. Pipeline Flow

```
Python terrain gen (veilbreakers_terrain/)
    │
    ├── Blender .blend file  (output/aaa_node_v4/terrain_aaa_node_v4.blend)
    │       Terrain mesh, water, cliffs, procedural detail
    │
    ├── Scatter point table  (output/aaa_node_v4/scatter_points.json)
    │       ScatterPointTable JSON — position, species_id, scale, orient, seed
    │
    └── scripts/export_3dsmax.py
            │
            ├── output/3dsmax/forest_pack_instances.csv  ← Forest Pack loads this
            ├── output/3dsmax/forest_pack_instances_manifest.json
            └── output/3dsmax/load_forest_pack_instances.ms  ← drop into Max Script Editor
```

### 2a. Export from the terrain pipeline

Run from the project root:

```bash
# Standard export (metres → cm, auto species map):
python scripts/export_3dsmax.py

# Custom input / output:
python scripts/export_3dsmax.py \
    --input  output/aaa_node_v4/scatter_points.json \
    --output output/3dsmax/forest_pack_instances.csv \
    --units  cm

# Test with grid placeholder (no scatter_points.json required):
python scripts/export_3dsmax.py --grid-fallback --grid-spacing 12

# Supply a hand-crafted species → mesh-index mapping:
python scripts/export_3dsmax.py --species-map assets/species_map.json
```

The `--species-map` JSON format:

```json
{
  "tree_oak":      { "mesh_index": 0, "label": "Oak Tree",    "lod_count": 3 },
  "tree_pine":     { "mesh_index": 1, "label": "Scots Pine",  "lod_count": 3 },
  "shrub_briar":   { "mesh_index": 2, "label": "Briar Shrub", "lod_count": 2 },
  "rock_small":    { "mesh_index": 3, "label": "Rock Small",  "lod_count": 1 },
  "fern_cluster":  { "mesh_index": 4, "label": "Fern Cluster","lod_count": 1 }
}
```

### 2b. Export FBX from Blender

Blender → File → Export → FBX (.fbx)

Recommended export settings:

| Setting | Value | Why |
|---|---|---|
| Scale | 1.0 | Export in metres; Max will convert on import |
| Apply Scalings | FBX All | Bakes object-level scales |
| Forward / Up | -Z Forward / Y Up | Matches 3ds Max Z-up convention after import |
| Apply Unit | ON | Embeds metre unit metadata |
| Mesh → Smoothing | Face | Avoids split-normal artefacts |
| Include → Armatures | OFF | Terrain has no rigs |
| Bake Animation | OFF | Unless exporting animated water |

On import into 3ds Max: **Customise → Units Setup → Metric → Metres** before importing, then switch back to centimetres after. This ensures the FBX unit metadata is respected and the terrain lands at the correct scale.

---

## 3. Forest Pack Pro Setup

### 3a. InstanceInfo CSV column specification

The CSV written by `export_3dsmax.py` uses these columns (all floats except MeshIndex/Seed):

| Column | Type | Description |
|---|---|---|
| `X` | float | Position X in cm (or m if `--units m`) |
| `Y` | float | Position Y in cm — **note: Blender Y is negated** (axis remap) |
| `Z` | float | Position Z in cm (height) |
| `RX` | float | Euler rotation X in degrees (3ds Max XYZ order) |
| `RY` | float | Euler rotation Y in degrees |
| `RZ` | float | Euler rotation Z in degrees (= yaw/heading for upright plants) |
| `SX` | float | Scale X (1.0 = no change) |
| `SY` | float | Scale Y |
| `SZ` | float | Scale Z |
| `MeshIndex` | int | 0-based index into the Forest Pack Geometry List |
| `Seed` | int | Per-instance seed (drives FP colour / animation variation) |

Forest Pack Pro does **not** natively read a CSV file through its UI — you load it via the companion MaxScript (`load_forest_pack_instances.ms`) which calls the Custom Edit MaxScript API.

### 3b. Loading via MaxScript

1. Open 3ds Max.
2. File → Import → FBX → select `output/3dsmax/terrain.fbx` (or the Blender FBX export).
3. Create a **Forest Pack Pro** object: Create → Geometry → itoosoft → ForestPack.
4. In the **Geometry List** rollout, add your species meshes **in MeshIndex order** (index 0 first).
5. In the **Items Editor** rollout, set Mode to **Custom Edit**.
6. Open the Script Editor (Scripting → New Script).
7. Open `output/3dsmax/load_forest_pack_instances.ms` and run it.
8. The script will parse the CSV and call `$.trees.create()` / `setPosition()` / `setRotation()` etc. for each row.

> **Performance note:** For tiles with > 50,000 instances, split the CSV by species first and run one FP object per species (or per biome zone). Forest Pack handles millions of instances at render time, but the MaxScript ingestion loop is slow above ~100 k rows. The `--grid-spacing 10` default (~10,000 instances/km²) is a safe starting point.

### 3c. Forest Pack LOD setup

For each species entry:

1. In the Geometry List, enable **LOD** for the item.
2. Set LOD distances to match your camera range (e.g. 0–20 m: high poly, 20–80 m: mid, 80–400 m: billboard).
3. Use **ForestLOD** (included with Forest Pack Pro) to generate LOD meshes automatically from high-poly FBX imports.

### 3d. Forest Pack Lite limitations

The free Lite version caps at **3 species** and **4 scatter areas**. For VeilBreakers (dark fantasy biome with 5+ species) you need **Forest Pack Pro** for the MaxScript Custom Edit API used here.

If budget is a constraint, the **MultiScatter** plugin (paid, cheaper than FP Pro) also supports Custom Edit mode via MaxScript with a compatible API.

---

## 4. Free Foliage Generators for 3ds Max

### 4a. TreeIt (Evolved Software) — Recommended for game-ready trees

- **Cost:** Free (no export restrictions, commercial use allowed)
- **Export:** FBX (ASCII — convert to binary with Autodesk FBX Converter), OBJ, X
- **Quality:** Adjustable LOD sliders, decent bark/leaf card setup; not AAA hero quality but fine for background scatter
- **Best for:** Pine, oak, birch, dead trees — broad variety
- **3ds Max workflow:** Export FBX → Import → assign VRay/Corona materials manually → add to Forest Pack Geometry List
- **Download:** https://www.evolved-software.com/treeit/treeit
- **VRAM:** Negligible during authoring (standalone Win app, no GPU requirement)

### 4b. GrowFX (ExLevel) — Best 3ds Max-native tree generator

- **Cost:** Paid (~$295), but has a **free 30-day trial with full export**
- **3ds Max native:** Runs inside Max, direct access to the scene, excellent MAXScript integration
- **Quality:** AAA-adjacent; produces the smooth trunk/branch Meta Mesh transitions used in high-end architectural visualisation
- **Best for:** Hero trees, bespoke dark fantasy twisted specimens
- **Compatibility:** 3ds Max 2013–2025
- **VRAM:** Mesh generation is CPU-side; final render cost = mesh complexity

### 4c. SpeedTree — Best mesh quality, significant cost/friction for free use

- **Learning Edition:** Free to download, **no mesh export** (saves in .SPL format, not openable in other software). Useful only for learning the tool.
- **Games Indie tier:** Paid subscription. Exports FBX/OBJ/SPM compatible with 3ds Max via the SpeedTree Engine plugin.
- **Free path:** SpeedTree models bundled with Unreal Engine / Unity can be exported as FBX from those engines if you have a licence, but re-distributing them requires checking the UE/Unity content licence.
- **Verdict for VeilBreakers:** Use SpeedTree if you have a subscription; otherwise use GrowFX (trial) or TreeIt for background scatter and hand-sculpt hero trees in Blender/ZBrush.

### 4d. EZ-Tree — Browser-based, GLB output

- **Cost:** Free, open-source (MIT)
- **URL:** https://github.com/dgreenheck/ez-tree
- **Export:** GLB → import into Blender → export FBX → 3ds Max
- **Quality:** Stylised, 10–40 k tris per tree, suitable for mid-ground scatter
- **Best for:** Rapid iteration / placeholders during early production

### 4e. Forest Pack built-in library

Forest Pack Pro ships with **430+ ready-to-use models** (trees, shrubs, rocks, grass). For dark fantasy you will likely re-texture them, but the geometry and LODs are production-quality. Use these as a baseline before investing in custom tree authoring.

---

## 5. VRAM-Safe Workflow (8 GB VRAM / 32 GB RAM)

| Concern | Guidance |
|---|---|
| Forest Pack viewport | Enable **Point Cloud** display mode (FP 9 default for Max 2017+). Keeps GPU load minimal in viewport; full geometry only at render time. |
| Texture budget | Cap tree textures at 2048×2048 for scatter background species; 4096 only for hero trees within camera focus. |
| GrowFX authoring | Disable real-time Meta Mesh while tweaking parameters; re-enable for export. |
| V-Ray / Corona render | Enable **Progressive rendering** + early stop at ~75% convergence for iteration. Full final renders will use system RAM spill (32 GB is adequate). |
| TreeIt FBX import | TreeIt ASCII FBX can bloat; convert with Autodesk FBX Converter 2013 (free) to binary before importing into Max. Binary FBX loads 5–10× faster. |
| Simultaneous tools | Don't run Hunyuan3D-2 (16–24 GB VRAM) and 3ds Max render simultaneously. Sequence them: generate assets → close Blender/Hunyuan → render in Max. |

---

## 6. Blender → 3ds Max Handoff Checklist

Before calling a terrain tile "ready for 3ds Max":

- [ ] Terrain mesh triangulated (Mesh → Triangulate in Blender, or enable in FBX export settings)
- [ ] All modifiers applied (no live Displace or Subdivision modifiers left unapplied)
- [ ] UV maps baked (splatmap_weights.exr present and matching FBX UV channel)
- [ ] Water plane(s) exported as separate mesh objects (not joined to terrain)
- [ ] Cliff proxy meshes exported if used for Forest Pack area masking
- [ ] `scatter_points.json` present in the same output directory
- [ ] `export_3dsmax.py` run: CSV + manifest + MaxScript all generated
- [ ] Manifest `species` block reviewed — mesh indices match the order you will add meshes to Forest Pack
- [ ] Forest Pack object named exactly `FP_Terrain_Scatter` (MaxScript targets this name)
- [ ] 3ds Max system units set to **Metric → Centimetres** before running the loader script
- [ ] Test render with a single species first to validate position/scale before loading all instances

---

## 7. Coordinate System Reference

```
Blender (Y-up, metres)      3ds Max (Z-up, centimetres)
─────────────────────        ────────────────────────────
     +Z (up)                        +Z (up)
      │                              │
      │                              │
      ├──── +Y (forward)             ├──── +X (right)
     /                              /
   +X (right)                     +Y (into scene)

Axis remap applied by export_3dsmax.py:
  Max_X =  Blender_X × 100
  Max_Y = -Blender_Y × 100   ← Y is negated
  Max_Z =  Blender_Z × 100
```

Rotation convention: quaternion orient from `ScatterPoint.orient` is converted to Euler XYZ (degrees) in 3ds Max space. The Y-axis negation is applied to the quaternion before decomposition so yaw directions are consistent.

---

## 8. Troubleshooting

**Instances appear mirrored / facing wrong direction**  
The Y-axis negation in `convert_position()` is required. If your FBX was exported without negating Y (e.g. using Blender's default +Y forward), you may need to flip the terrain mesh's Y in Max too. Keep the FBX export settings from Section 2b exactly as specified.

**All instances land at Z=0**  
The `scatter_points.json` position Z values are world-space metres from the terrain pipeline. If the terrain mesh was imported at a different vertical offset, shift the FP object to match, or re-run `export_3dsmax.py` after adjusting `height_m` values in the pipeline.

**MaxScript "Cannot open CSV" error**  
The path in `load_forest_pack_instances.ms` uses the path at generation time. If you moved the output folder, edit the `csvPath` variable at the top of the .ms file.

**Species MeshIndex out of range**  
Forest Pack silently ignores items with a MeshIndex that exceeds the Geometry List length. Verify the manifest JSON `species` block and ensure you added meshes in the correct order before running the script.

**Grid fallback produces flat Z values**  
The `--grid-fallback` mode does not sample a real heightmap; it generates random Z offsets of 0–5 m as a placeholder. Replace with real scatter_points.json output from the terrain pipeline for production.
