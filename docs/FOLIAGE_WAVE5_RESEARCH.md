# Wave 5 Foliage Pipeline — Research

**Researched:** 2026-04-26
**Domain:** AAA foliage placement, manifest export, DCC offload (3ds Max 2027 / Maya 2027)
**Confidence:** HIGH on Forest Pack export path, Unity TreeInstance schema, XGen-to-cards. MEDIUM on AAA studio specifics (Decima paper requires PDF). HIGH on current `vegetation_system.py` interface.

---

## Summary

The fastest path to AAA-bar foliage in VeilBreakers is to stop trying to *generate plant geometry* in Python and stop trying to *render placements* in Python. We already place better than we generate. The right division of labour is:

- **Python (us)** — *decides* placement (positions, rotations, scales, species, LOD) and emits a manifest. We already do this in `compute_vegetation_placement` + `build_vegetation_placement_spec`.
- **3ds Max 2027 + Forest Pack 9.4** — consumes the manifest in *Reference Mode* and acts as the AAA scatter renderer / FBX baker for offline cinematic shots and as the FBX exporter for Unity. We do **not** ask Forest Pack to compute placement rules — Forest Pack's "Reference Mode" places one item per pivot point of helper objects, which is exactly the consumer side of our manifest.
- **Maya 2027 + XGen** — used **once per ground-cover species** to author moss/lichen/grass cards, then `Convert Interactive Groom to Polygons` into FBX cards plus baked albedo/normal/AO atlas. After that, XGen is offline; the cards are normal Unity meshes.
- **Bifrost 2.13** — *not for foliage in our pipeline.* Bifrost's `scatter_points` overlaps Forest Pack but lives in Maya, has no Unity export route, and sits behind a per-frame Maya runtime. Keep Bifrost reserved for water (already its scope per master guide).
- **Unity** — final consumer. The manifest's per-instance records map 1:1 to `TerrainData.SetTreeInstances(TreeInstance[], snapToHeightmap=true)` for terrain trees and to a custom GPU-instanced renderer (or GPU Resident Drawer / BatchRendererGroup in Unity 6) for ground cover.

**Primary recommendation:** Wire `vegetation_system.py` to (1) accept a `mesh_library` of pre-authored asset paths instead of resolving Python procedural generators, and (2) emit `foliage_placement_manifest.json` with a schema that is simultaneously valid as a `TreeInstance[]` rehydration source for Unity Terrain *and* as a Forest Pack reference-helper import (one Max helper per record). Build no Python tree generation. Build no Python rendering. Forest Pack and XGen replace 6,000+ lines of code we'd otherwise rebuild.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary | Rationale |
|---|---|---|---|
| Density / exclusion logic | Python (terrain stack) | — | Already implemented; consumes `slope`, `drainage`, `splatmap_weights_layer`, `biome_id`, `road_mask`, `cliff_mesh_specs`, `water_surface` — all live on `TerrainMaskStack`. |
| Poisson-disk blue noise | Python (`_scatter_engine.poisson_disk_sample`) | — | Already correct, AAA-bar Bridson sampler. |
| Per-instance placement decision (xyz, rot, scale, lod_hint, species) | Python | — | Currently in `compute_vegetation_placement`. Stays. |
| Manifest serialisation | Python | — | New: `build_foliage_placement_manifest` writes JSON. |
| Plant *geometry* authoring | Maya 2027 (XGen) + 3ds Max 2027 + artist hand modelling | Tripo for hero trees (existing) | Retired Python L-system per locked decision. |
| Cinematic / FBX bake of full scatter | 3ds Max 2027 + Forest Pack 9.4 (Reference Mode consuming manifest) | — | Forest Pack is the industry standard renderer-side scatter; Reference Mode reads our pivots. |
| Ground-cover atlas (moss/lichen/grass cards) | Maya 2027 + XGen (Convert to Polygons) → Arnold bake → Substance/xNormal | — | XGen owns groom; cards are flat polygon strips Unity reads as standard meshes. |
| Runtime instancing | Unity GPU Resident Drawer (URP/HDRP 6.x) | Unity Terrain `TreeInstance` for tree count > 5k | `SetTreeInstances` is the single canonical batch API; GPU Resident Drawer auto-batches everything else. |
| Water sim, foliage simulation | Bifrost (water only) | — | Bifrost stays scoped to water per master guide. |

---

## Standard Stack

### Core

| Component | Version | Purpose | Confidence |
|---|---|---|---|
| Forest Pack Pro | 9.4.0 | 3ds Max scatter renderer; Reference Mode consumes our manifest helpers; Unity export plugin emits `.forest` + `.fbx`. | HIGH (verified itoosoft.com/blog & docs.itoosoft.com 2026-04-26) |
| 3ds Max | 2027 | Forest Pack 9.4 host. Confirmed supported. | HIGH (toolfarm.com 2026-04-26 — "Forest Pack 9.4.0 and RailClone 7.3.0 Support 3ds Max 2027") |
| Maya | 2027 | XGen Interactive Grooming host. | HIGH (autodesk.com/products/maya) |
| XGen Interactive Grooming | Maya 2027 | Author moss/grass cards; `Generate > Convert Interactive Groom to Polygon`. | HIGH (Autodesk help 2024 docs, behaviour stable across 2024–2027) |
| Arnold | 7.5+ (Max), MtoA latest (Maya) | Bake XGen groom → texture before card conversion (fixes the "lost textures on convert" gotcha). | HIGH (toolfarm.com, polycount thread) |
| Unity | 6.x (6000.x) — currently 6000.2 / 6000.3 docs | Final runtime. `TerrainData.SetTreeInstances`, GPU Resident Drawer, BatchRendererGroup. | HIGH (docs.unity3d.com/6000.2) |
| Substance Painter / xNormal | latest | Texture transfer from converted XGen high-poly to card low-poly. | HIGH |

### Supporting

| Library | Use | Confidence |
|---|---|---|
| Forest Pack Unity Export Plugin (experimental, ITOOSOFT) | Drag-drop `.forest` + `.fbx` into Unity; uses Hybrid Renderer; FP 7+ / Unity 2018+. | HIGH (docs.itoosoft.com/forestpack/instantiating-and-exporting/exporting-to-unity) |
| GPU Instancer Pro (Asset Store, optional) | Alternative to GPU Resident Drawer for non-URP/HDRP, or for prefab-based scatter not on Unity Terrain. | MEDIUM (active 2026, Asset Store id 290293) |
| Unity Terrain Tools | Detail prototypes for grass billboards (`DetailPrototype`); tree prototypes for `TreeInstance`. | HIGH |

### Alternatives we explicitly do NOT use

| Considered | Rejected because |
|---|---|
| Bifrost `scatter_points` for foliage | Same conceptual node graph as Forest Pack but inside Maya. No Unity export plugin. Maya runtime cost. Forest Pack is strictly superior for this job. |
| Houdini scatter / SideFX Labs | Excellent but no licence assumed; user has Max + Maya, not Houdini. |
| L-Py / PlantGL inside our Python | Already evaluated in `project_foliage_stack_2026_04_26.md` — keep for *one-off* tree variant authoring at most, not as a scatter pipeline. |
| Unity Terrain "Mass Place Trees" | Random only, not biome-aware, not LOD-aware. We override via `SetTreeInstances`. |

---

## Pipeline Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         AUTHORING (one-time, per-asset)                  │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Maya 2027 + XGen ──► Generate > Convert Interactive Groom to Polygon    │
│        │                                                                 │
│        └──► Arnold groom bake (.png atlas: albedo / normal / AO)         │
│             └──► xNormal / Substance: transfer to card UVs               │
│                  └──► card_<species>.fbx + card_<species>_atlas.png      │
│                                                                          │
│  3ds Max 2027 / Tripo / hand-modelled ──► hero_tree_<style>.fbx          │
│                                                                          │
│  Output: Assets/Foliage/{trees,groundcover,rocks}/*.fbx + atlases        │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                  PLACEMENT (every terrain build, in Python)              │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   TerrainMaskStack channels we consume:                                  │
│     biome_id, slope, drainage, splatmap_weights_layer,                   │
│     road_mask, road_sdf_dist, cliff_label, cliff_mesh_specs,             │
│     water_surface, bathymetry, hero_exclusion, poi_mask                  │
│                                                                          │
│   ┌─────────────────────────────────────────┐                            │
│   │ vegetation_system.py                    │                            │
│   │  · build_biome_density_map() (exists)   │                            │
│   │  · compute_vegetation_placement()       │ ← already Poisson + LOD    │
│   │  · build_vegetation_placement_spec()    │   tiers + competition      │
│   │  · build_foliage_placement_manifest() ← NEW: writes JSON             │
│   │     · resolves species → mesh_library   │                            │
│   │     · stamps SDF exclusion (roads/      │                            │
│   │       cliffs/water edges)               │                            │
│   │     · normalises positions for Unity    │                            │
│   │       TerrainData (0..1 percentage)     │                            │
│   └─────────────────────────────────────────┘                            │
│                       │                                                  │
│                       ▼                                                  │
│   foliage_placement_manifest.json    ◄── single source of truth          │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                ┌───────────────────┴───────────────────┐
                ▼                                       ▼
┌─────────────────────────────────────┐   ┌─────────────────────────────────┐
│   CINEMATIC / OFFLINE BAKE PATH     │   │     UNITY RUNTIME PATH          │
├─────────────────────────────────────┤   ├─────────────────────────────────┤
│                                     │   │                                 │
│  MAXScript reader:                  │   │  Editor importer (C#) reads     │
│   manifest.json → spawn one         │   │   the same manifest.json:       │
│   PointHelper / Dummy per record    │   │                                 │
│   tagged by species, rot, scale.    │   │   for trees:                    │
│                                     │   │    TreeInstance[] →             │
│  Forest Pack object in              │   │    TerrainData.SetTreeInstances │
│   Reference Mode → distribute       │   │      (instances, snap=true)     │
│   FBX assets across helpers,        │   │                                 │
│   keyed by species tag + LOD group. │   │   for ground cover & rocks:     │
│                                     │   │    GameObject prefab + GPU      │
│  Forest Tools → export to Unity     │   │    Resident Drawer (URP/HDRP)   │
│   (.forest + .fbx + Hybrid          │   │    OR DetailPrototype layer for │
│   Renderer plugin) — alt path,      │   │    grass billboards.            │
│   for shots needing FP-quality      │   │                                 │
│   renders inside Unity.             │   │   LOD groups built from         │
│                                     │   │   manifest.lod_level field.     │
└─────────────────────────────────────┘   └─────────────────────────────────┘
```

**Trace one tree from input to output:**
1. `pass_water` writes `water_surface`; `pass_erosion` writes `slope`/`drainage`; `pass_materials` writes `splatmap_weights_layer`/`biome_id`; `pass_roads` writes `road_mask`/`road_sdf_dist`.
2. `compute_vegetation_placement` walks the LOD-tiered Poisson-disk samples, samples those masks at each candidate, applies SDF exclusions and density rolls, emits a placement record.
3. `build_foliage_placement_manifest` resolves each record's `(type, style)` to a mesh asset path from `mesh_library`, attaches LOD group, and writes one entry into the JSON manifest.
4. Unity importer reads the manifest, creates the `TreeInstance` (for trees) or instantiates / GPU-instances (for ground cover), snaps to terrain heightmap on import.
5. (Optional cinematic) MAXScript spawns dummies → Forest Pack scatters → render.

---

## Forest Pack 9.4 Integration Path (3ds Max 2027)

**Path A — manifest → Forest Pack (the consumer direction we want):** [HIGH]
- Forest Pack ships a *Reference Mode* distribution (docs.itoosoft.com/forestpack/forest-plugin/distribution/reference-mode). Reference Mode places one item per pivot of a helper object, optionally one-per-face for polygon helpers. It carries dynamic links — moving the helper updates the scatter.
- Workflow:
  1. Python writes `foliage_placement_manifest.json`.
  2. A small MAXScript (~50 lines) reads the JSON, loops records, creates `PointHelper` per record at world XYZ with `rotation_euler.z = manifest.rotation`. Sets a string user property `species` and float `scale`. Groups helpers by species into named layers.
  3. Artist creates one Forest Pack object per species, sets distribution to **Reference**, picks the species' helper layer, sets the FBX item, sets random scale ranges to `[1.0, 1.0]` (we already chose scale per-instance — set FP to read scale from helper user property if needed).
  4. Result: a fully scattered scene, AAA-bar shading, V-Ray / Arnold / Corona ready.
- Key Reference Mode capabilities verified (docs.itoosoft.com): per-marker random offset, material-ID filter, multiple references via Pin Stack — none of which we need to use because we've already done that work upstream, but good to know they exist if an artist wants to re-touch.

**Path B — Forest Pack → Unity (offline export for shots needing FP-quality):** [HIGH]
- Forest Pack 7+ has an experimental **Unity export plugin** (docs.itoosoft.com/forestpack/instantiating-and-exporting/exporting-to-unity) using Unity's Hybrid Renderer.
- Process:
  1. Select Forest objects in Max → Utilities panel → Forest Tools → Export.
  2. Forest Tools writes `.forest` (distribution data) + `.fbx` (source meshes).
  3. Drag both into a Unity 2018+ project; the plugin instantiates instances under Hybrid Renderer (DOTS-style instancing). On Unity 6, the Hybrid Renderer is superseded by Entities Graphics + GPU Resident Drawer; the plugin still produces FBX + transform data which we can rebind to a custom MonoBehaviour reader if the shipped plugin lags Unity 6.
- **Recommendation:** Path B is for cinematic / hero-shot scenes only. Production runtime uses our manifest directly through the Editor importer (next section) so we own the data path and stay version-portable.

**Path B failure mode to plan for:** ITOOSOFT's plugin is "experimental" and was last validated on Unity 2018-era Hybrid Renderer. If it doesn't load on Unity 6, fall back to: in Max, use Forest Pack's "Convert to Geometry" / FBX export of all instances → Unity reads as a giant FBX → script splits into instanced renderers. Works but loses FP per-LOD billboarding.

**Forest Pack 9 features useful to us (verified itoosoft.com/blog/forest-pack-8 + 9.0 release notes):**
- Built-in tinting & color variation per instance — we can drive from `manifest.tint` (per-record RGB) without baking.
- Spline-based scatter — we ignore this; we use Reference Mode.
- Surface-aligned distribution — we ignore; our manifest already snaps to terrain.

---

## Maya XGen 2027 — Moss / Grass / Lichen Card Workflow

**Goal:** XGen authors a procedural groom *once* per species; we extract polygon cards + a baked atlas; Unity instances those cards via the same manifest. Maya is *not* in the runtime path.

**Workflow (verified Autodesk help 2024 + polycount + community threads, behaviour stable across 2024–2027):** [HIGH]

1. **Author the groom.** Maya → XGen Interactive Grooming on a small representative patch of ground polygon. Sculpt density, length, direction.
2. **Bake textures via Arnold first** (this avoids the documented "lost textures on convert" pitfall). With the groom selected, Arnold render → utility AOVs (root, tip, normal, ID). Save as PNG atlas. Source: polycount thread "Looking for fur texture workflow ideas".
3. **Convert to polygon strips.** Modeling menu → `Generate > Convert Interactive Groom to Polygon`. Set strip count, twist (use the "twist brush with align to surface" option from the polycount workflow). Outputs flat ribbon meshes.
4. **Transfer textures.** Use Maya's Transfer Maps OR xNormal / Substance Painter to project the Arnold AOVs onto the strip UVs. (Transfer fails directly inside the convert step — that's the gotcha — so always go via baked maps.)
5. **Export FBX.** One mesh per LOD (LOD0 = 1x density, LOD1 = 0.5x, LOD2 = billboard quad with same atlas).
6. **Asset path lands in `mesh_library`** with key `(type='moss', style='hanging_moss')` etc. Manifest references it by `mesh_asset_path` field.

**What we don't try to do:**
- Don't ship XGen Interactive Groom directly — Unity has no XGen reader; UE5's Groom path is hair-only, not for ground cover.
- Don't bake at runtime; bake once per asset, version into `Assets/Foliage/groundcover/`.

**Per-species effort:** ~30–60 min in Maya for an experienced groom artist. Scales: bake 6–8 ground-cover species (moss/grass/lichen variants per biome), reuse across 14 biomes.

---

## Bifrost 2.13 — Foliage Use Case?

**Verdict:** Skip for foliage. Bifrost stays in its lane — water (per master guide).

**Why it looked tempting:** Bifrost has a `scatter_points` node (knowledge.autodesk.com/Bifrost-Common scatter-pack) with full procedural graph control, instancing onto particles/MPM/strands, native Arnold instancing.

**Why we don't use it:**
- No Unity export. Bifrost graphs are Maya-runtime structures; baking them out is via Alembic / FBX of the resulting instances, no better than what we already get from Forest Pack.
- Forest Pack does the same job and *also* has the experimental Unity Hybrid Renderer plugin. Pick one scatter renderer; pick the one with the export plugin.
- Maya licence overhead: every artist who wants to re-touch a scatter would need Maya open. Forest Pack scenes can ship to a 3ds Max-only artist.

**Where Bifrost stays:** water simulation per the master guide — splash, foam, mist particles. Untouched here.

---

## `foliage_placement_manifest.json` Schema

Designed to satisfy three consumers simultaneously:
1. Unity Editor importer → `TerrainData.SetTreeInstances(TreeInstance[], snapToHeightmap=true)`.
2. Unity GPU Resident Drawer / GameObject instantiator for ground cover.
3. MAXScript Reference-Mode helper writer for Forest Pack.

**Verified Unity TreeInstance fields** (docs.unity3d.com/ScriptReference/TreeInstance.html, 2026-04-26):
- `position : Vector3` — clamped 0..1, percentage of terrain extent.
- `prototypeIndex : int` — index into `TerrainData.treePrototypes`.
- `rotation : float` — radians, X-Z plane (read-only via property; settable via `SetTreeInstance`).
- `widthScale, heightScale : float` — relative to prototype.
- `color, lightmapColor : Color`.

### Schema (v1.0)

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-04-26T00:00:00Z",
  "terrain": {
    "tile_x": 0,
    "tile_y": 0,
    "tile_size": 1024,
    "cell_size": 1.0,
    "world_origin": [0.0, 0.0],
    "world_extent": [1024.0, 1024.0],
    "height_min_m": -25.0,
    "height_max_m": 412.0
  },
  "biome": "thornwood_forest",
  "season": "summer",
  "lod_distances_m": [15.0, 35.0, 60.0, 200.0],
  "camera_reference": [512.0, 512.0, 0.0],

  "mesh_library": [
    {
      "mesh_id": 0,
      "species_key": "tree_veil_healthy",
      "mesh_asset_path": "Assets/Foliage/trees/veil_healthy.fbx",
      "atlas_path": null,
      "lod_meshes": [
        "Assets/Foliage/trees/veil_healthy_lod0.fbx",
        "Assets/Foliage/trees/veil_healthy_lod1.fbx",
        "Assets/Foliage/trees/veil_healthy_lod2_billboard.fbx",
        "Assets/Foliage/trees/veil_healthy_lod3_impostor.fbx"
      ],
      "category": "trees",
      "unity_render_mode": "terrain_tree",
      "forestpack_reference_layer": "FP_REF_tree_veil_healthy",
      "wind_color_baked": true,
      "physics_collider": "capsule"
    },
    {
      "mesh_id": 1,
      "species_key": "moss_hanging_moss",
      "mesh_asset_path": "Assets/Foliage/groundcover/moss_hanging_moss_card.fbx",
      "atlas_path": "Assets/Foliage/groundcover/moss_hanging_moss_atlas.png",
      "lod_meshes": [
        "Assets/Foliage/groundcover/moss_hanging_moss_lod0.fbx",
        "Assets/Foliage/groundcover/moss_hanging_moss_lod1.fbx",
        "Assets/Foliage/groundcover/moss_hanging_moss_lod2_quad.fbx"
      ],
      "category": "ground_cover",
      "unity_render_mode": "gpu_instancer",
      "forestpack_reference_layer": "FP_REF_moss_hanging_moss",
      "authored_in": "maya_xgen",
      "physics_collider": "none"
    }
  ],

  "instances": [
    {
      "i": 0,
      "mesh_id": 0,
      "position_world": [123.4, 456.7, 28.9],
      "position_terrain_norm": [0.1205, 0.4460, 0.1267],
      "rotation_y_rad": 1.2566,
      "scale": 1.85,
      "scale_xyz": [1.85, 1.85, 1.85],
      "lod_level": 0,
      "lod_hint_sampler_tier": 0,
      "biome": "thornwood_forest",
      "category": "trees",
      "moisture": 0.71,
      "tint_rgb": [1.0, 1.0, 1.0],
      "color_variation_seed": 1234567
    }
  ],

  "instance_count": 4823,
  "species_density": {
    "tree_veil_healthy": 412,
    "moss_hanging_moss": 1860
  },
  "lod_distribution": {"0": 803, "1": 1442, "2": 1611, "3": 967},

  "exclusion_sources": {
    "road_sdf_min_m": 1.5,
    "cliff_sdf_min_m": 0.8,
    "water_edge_min_m": 0.5,
    "hero_exclusion_used": true,
    "poi_radius_used_m": 8.0
  }
}
```

**Field rationale & consumer mapping:**

| Field | Unity TerrainData consumer | Unity GPU Resident Drawer consumer | Forest Pack reader (MAXScript) |
|---|---|---|---|
| `position_world` | (used to compute terrain_norm) | `Matrix4x4.Translate` | `PointHelper.position` |
| `position_terrain_norm` | `TreeInstance.position` directly | (unused) | (unused) |
| `rotation_y_rad` | `TreeInstance.rotation` (radians) | `Matrix4x4.Rotate(Quat.Euler(0, deg, 0))` | `PointHelper.rotation.z = math.degrees(rad)` |
| `scale` (uniform) | `widthScale = heightScale = scale` | `Matrix4x4.Scale` | `PointHelper.userProp.scale` |
| `lod_level` | `prototypeIndex` (one prototype per LOD if needed) OR pre-LOD'd in mesh | LOD group selection | FP item-by-distance rule |
| `mesh_id` → `mesh_library[mesh_id]` | `prototypeIndex` (Editor importer matches `mesh_asset_path` to a `TreePrototype.prefab`) | Prefab pool key | FP item assignment per layer |
| `tint_rgb` | `TreeInstance.color` | Per-instance `MaterialPropertyBlock` | FP per-item color |

**Why uniform `scale` and a separate `scale_xyz`:** current `compute_vegetation_placement` outputs uniform scale. The schema reserves `scale_xyz` for future non-uniform scaling (wind-bent grass, etc.) without bumping schema_version.

**Why `position_terrain_norm` is precomputed:** Unity's `TreeInstance.position` is normalised 0..1 in terrain local space. Doing it once in Python keeps the importer dumb and avoids drift between offline cinematic (world coords) and runtime (norm coords).

**Backwards-compatibility rule:** new fields are additive only; consumers ignore unknown fields. `schema_version` bumps on breaking changes.

---

## What `vegetation_system.py` Needs to Implement

### Current interface (verified by reading the file 2026-04-26)

`scatter_biome_vegetation(params)` is the single entry point. It already:
- Computes Poisson-disk placements in 3 LOD tiers via `compute_vegetation_placement`.
- Enriches with LOD assignments via `build_vegetation_placement_spec`.
- Writes biome density to `stack.detail_density` via `build_biome_density_map`.
- Optionally creates Blender objects (Blender materializer mode) — **this is the part we deprecate** for Wave 5.
- Has a `spec_only=True` short-circuit that returns the spec dict — **this is the path we extend**.

It currently resolves species to a Blender mesh template via `_create_biome_vegetation_template` → `resolve_generator("vegetation", veg_type)` from `_mesh_bridge`. **This is what we replace with a `mesh_library` lookup.**

### Required changes (function signatures)

```python
# NEW — at module top
def load_mesh_library(library_path: str | Path) -> dict[str, dict[str, Any]]:
    """Load Assets/Foliage manifest of pre-authored mesh assets.

    Returns:
        dict keyed by species_key (e.g. "tree_veil_healthy") to:
          {
            "mesh_asset_path": str,
            "atlas_path": str | None,
            "lod_meshes": list[str],     # per-LOD asset paths
            "category": "trees" | "ground_cover" | "rocks",
            "unity_render_mode": "terrain_tree" | "gpu_instancer" | "detail_prototype",
            "wind_color_baked": bool,
            "physics_collider": str,
          }

    The library file is a JSON sidecar in the foliage assets directory
    that artists update when they add/remove FBX files. Keep one canonical
    library per project; merging is out of scope for Wave 5.
    """


# NEW — wraps existing build_vegetation_placement_spec
def build_foliage_placement_manifest(
    spec: dict[str, Any],
    mesh_library: dict[str, dict[str, Any]],
    stack: "TerrainMaskStack",
    *,
    biome_name: str,
    season: str | None = None,
    schema_version: str = "1.0",
    sdf_road_min_m: float = 1.5,
    sdf_cliff_min_m: float = 0.8,
    water_edge_min_m: float = 0.5,
) -> dict[str, Any]:
    """Convert placement spec → Unity/Forest Pack-compatible manifest.

    Steps:
      1. Build mesh_library section from species observed in spec["placements"].
         Drop placements whose species_key has no mesh_library entry (warn).
      2. For each placement:
         - Apply SDF exclusion using stack.road_sdf_dist (>= sdf_road_min_m)
           and a derived cliff SDF and water-surface edge SDF.
         - Normalise position to terrain local 0..1 using stack.world_origin /
           stack.tile_size * stack.cell_size and stack.height min/max.
         - Convert rotation degrees → radians.
         - Resolve mesh_id (index into mesh_library array).
      3. Aggregate species_density and lod_distribution.
      4. Return manifest dict ready for json.dump.

    Raises:
      ValueError if required stack channels (height, slope) are absent.
    """


# NEW — thin writer
def write_foliage_placement_manifest(
    manifest: dict[str, Any],
    out_path: str | Path,
) -> Path:
    """Atomic JSON write (tmp + rename). Returns the written Path."""


# MODIFIED — add manifest emission to the existing entry point.
def scatter_biome_vegetation(params: dict) -> dict:
    """[existing docstring] ... plus:

    NEW PARAMS for Wave 5:
      mesh_library_path (str, optional): Path to mesh_library.json.
          When set, writes foliage_placement_manifest.json next to it.
      manifest_out_path (str, optional): Override manifest output location.
      emit_manifest (bool, default False): When True, builds and writes
          foliage_placement_manifest.json. Implies spec_only behaviour for
          the placement computation (no Blender objects created).
    """
    # ... existing code path ...
    # AT THE END:
    if params.get("emit_manifest"):
        mesh_library = load_mesh_library(params["mesh_library_path"])
        manifest = build_foliage_placement_manifest(
            spec=spec_dict,                # the spec we already build
            mesh_library=mesh_library,
            stack=params.get("stack"),
            biome_name=biome_name,
            season=season,
        )
        out = params.get("manifest_out_path") or _default_manifest_path(stack)
        write_foliage_placement_manifest(manifest, out)
        result["manifest_path"] = str(out)
    return result
```

### Stack channels read for SDF exclusion

Verified present on `TerrainMaskStack` (handlers/terrain_semantics.py lines 232–430):

| Channel | Used for | Notes |
|---|---|---|
| `height` (required) | Z + norm-height | always populated |
| `slope` | already used by `_max_slope_for_category` | float32 (H, W), degrees |
| `drainage` | wetness modifier (existing moisture map alternative) | float32 (H, W) |
| `splatmap_weights_layer` | per-layer biome blend for ground cover | float32 (H, W, L) |
| `biome_id` | already used by `build_biome_density_map` | uint8 (H, W) |
| `road_mask` + `road_sdf_dist` | exclude foliage near roads | road_sdf_dist is the precomputed signed distance |
| `cliff_label` | exclude foliage on cliff faces | uint8 mask; derive SDF via scipy.ndimage.distance_transform_edt |
| `cliff_mesh_specs` | hero exclusion for cliff geometry override | list of dicts; each has bbox |
| `water_surface` | per-cell water elevation; foliage forbidden where height < water_surface | float32 (H, W) |
| `bathymetry` | depth below water | float32 (H, W); 0 = above water |
| `hero_exclusion` | union of POIs / hero meshes | bool/uint8 mask |
| `poi_mask` | POI proximity exclusion | bool/uint8 mask |

### SDF-based exclusion logic (deterministic, no new tools)

```python
# Pseudocode for the exclusion check inside build_foliage_placement_manifest
import numpy as np
from scipy.ndimage import distance_transform_edt

def _exclude_placement(p, stack, sdf_road_min_m, sdf_cliff_min_m, water_edge_min_m):
    wx, wy, wz = p["position"]
    ix, iy = world_to_cell(wx, wy, stack)  # using stack.world_origin + cell_size

    # 1. Road SDF: precomputed signed distance — fast path
    if stack.road_sdf_dist is not None:
        if stack.road_sdf_dist[iy, ix] < sdf_road_min_m:
            return True

    # 2. Cliff SDF: derive once per stack from cliff_label
    cliff_sdf = _cliff_sdf_cache.get(id(stack))
    if cliff_sdf is None and stack.cliff_label is not None:
        cliff_sdf = distance_transform_edt(stack.cliff_label == 0) * stack.cell_size
        _cliff_sdf_cache[id(stack)] = cliff_sdf
    if cliff_sdf is not None and cliff_sdf[iy, ix] < sdf_cliff_min_m:
        return True

    # 3. Water edge SDF: derive from bathymetry > 0 mask
    water_sdf = _water_sdf_cache.get(id(stack))
    if water_sdf is None and stack.bathymetry is not None:
        water_sdf = distance_transform_edt(stack.bathymetry == 0) * stack.cell_size
        _water_sdf_cache[id(stack)] = water_sdf
    if water_sdf is not None and water_sdf[iy, ix] < water_edge_min_m:
        return True

    # 4. Hero exclusion mask (categorical)
    if stack.hero_exclusion is not None and stack.hero_exclusion[iy, ix]:
        return True

    return False
```

This is the only SDF logic Wave 5 adds. The existing slope/moisture/biome filters in `compute_vegetation_placement` handle the other constraints.

---

## Don't Hand-Roll

| Problem | Don't build | Use instead | Why |
|---|---|---|---|
| Procedural tree geometry | A Python L-system replacement | Tripo + 3ds Max + artist hand-modelling | Locked decision. AAA tree silhouette is artist-driven; procedural is uncanny-valley. |
| Procedural moss / lichen | Anything | Maya XGen Interactive Grooming → Convert to Polygon | XGen is the industry-standard groom tool; cards are flat polys Unity already understands. |
| Big-scale instancing renderer | A custom GPU instancer | Unity 6 GPU Resident Drawer (auto) + `TerrainData.SetTreeInstances` for trees | Unity 6's GPU Resident Drawer auto-batches via BatchRendererGroup. We get it for free. |
| Wind / sway | Any new system | Existing `compute_wind_vertex_colors` + Unity wind shader | Already implemented; manifest field `wind_color_baked: true` flags which meshes have wind colours. |
| LOD generation | Any per-mesh LOD baker | Pre-author 4 LODs per species in DCC | LOD0–LOD2 in Max/Maya, LOD3 = Imposter (Unity Imposter Baker package or static billboard). |
| Distance-field SDFs from masks | bespoke chamfer algorithm | `scipy.ndimage.distance_transform_edt` | Already a transitive dependency via numpy stack. Exact Euclidean DT, fast. |
| Cinematic scatter rendering | Anything | Forest Pack 9.4 Reference Mode | THE industry standard; user already has it via Max 2027. |

**Key insight:** every piece of the foliage pipeline that is NOT "decide where things go" is already a solved problem in Forest Pack, XGen, or Unity. Our entire value-add is the placement decision, which we already do well. Wave 5 is plumbing, not algorithm.

---

## Common Pitfalls

### Pitfall 1: XGen "Convert to Polygon" loses textures

**What goes wrong:** Artist authors a textured XGen groom, runs Convert Interactive Groom to Polygon, gets untextured strips. (Documented multiple times in Autodesk forum thread `xgen-convert-interactive-groom-to-polygone-with-texture`.)
**Root cause:** Convert step does not transfer texture from groom material to strip UVs.
**Avoidance:** Bake AOVs via Arnold *first* (root, tip, normal, ID maps), convert second, then transfer maps onto the polygon strip UVs via xNormal or Substance Painter. Document this as the canonical workflow in `docs/FOLIAGE_AUTHORING_GUIDE.md`.
**Warning sign:** strip FBX renders pure white in Unity preview.

### Pitfall 2: Forest Pack Unity export plugin is "experimental" and Unity-2018-era

**What goes wrong:** Plugin doesn't load on Unity 6 (Hybrid Renderer was deprecated → Entities Graphics).
**Root cause:** ITOOSOFT plugin tagged "experimental" since FP 7; not actively updated.
**Avoidance:** Use Path A (manifest → Forest Pack) for cinematic shots only. Production runtime path bypasses the plugin entirely — we read our own manifest. The FP→Unity path is a *fallback*.
**Warning sign:** "DLL load failed" or missing Hybrid Renderer assemblies in Unity console.

### Pitfall 3: `TerrainData.treeInstances` direct assignment doesn't snap to heightmap

**What goes wrong:** Trees float above or sink into terrain after import.
**Root cause:** `terrainData.treeInstances = arr` performs no snapping; `SetTreeInstances(arr, snapToHeightmap=true)` does.
**Avoidance:** Always use `SetTreeInstances(instances, true)`. Verified docs.unity3d.com/ScriptReference/TerrainData.SetTreeInstances.html 2026-04-26.
**Warning sign:** trees clipping into terrain visible from low-angle camera.

### Pitfall 4: TreeInstance.position is normalised 0..1, not world coords

**What goes wrong:** Trees appear in a tiny clump near the origin.
**Root cause:** Authors assume position is world meters. It's percentage of terrain extent (X/Z) and percentage of `TerrainData.size.y` for Y.
**Avoidance:** Manifest precomputes `position_terrain_norm` so the importer is dumb.
**Warning sign:** all trees within the first cell of the terrain.

### Pitfall 5: Forest Pack Reference Mode treats one helper as one item

**What goes wrong:** A polygon-helper-as-reference creates one item per face, not per pivot. Density explodes.
**Root cause:** Reference Mode has both modes (per-pivot or per-face) configurable.
**Avoidance:** Use `PointHelper` / `Dummy` (zero-face) per record. Set FP Reference Mode to "Use Pivot Point". Documented at docs.itoosoft.com/forestpack/forest-plugin/distribution/reference-mode.

### Pitfall 6: Bifrost vs Forest Pack confusion

**What goes wrong:** Team builds a Bifrost scatter graph that overlaps Forest Pack work.
**Root cause:** Both tools have a `scatter_points`-style node.
**Avoidance:** Master guide says Bifrost = water only. Document this in our internal usage guide.

### Pitfall 7: `scipy.ndimage.distance_transform_edt` returns pixel distance not metres

**What goes wrong:** SDF threshold of 1.5 m blocks every cell because `distance_transform_edt` returns pixel counts.
**Avoidance:** Multiply by `stack.cell_size` (metres per cell). The pseudocode above does this.

---

## Code Examples

### Reading the manifest into Unity Terrain (Editor C# importer)

```csharp
// Source pattern: Unity 6 docs.unity3d.com/ScriptReference/TerrainData.SetTreeInstances.html
[MenuItem("VeilBreakers/Foliage/Import Manifest")]
public static void ImportFoliageManifest() {
    string path = EditorUtility.OpenFilePanel("Manifest", "", "json");
    var manifest = JsonUtility.FromJson<FoliageManifest>(File.ReadAllText(path));

    // Resolve TreePrototypes from mesh_library
    var terrain = Selection.activeGameObject.GetComponent<Terrain>();
    var prototypes = manifest.mesh_library
        .Where(m => m.unity_render_mode == "terrain_tree")
        .Select(m => new TreePrototype {
            prefab = AssetDatabase.LoadAssetAtPath<GameObject>(m.lod_meshes[0])
        }).ToArray();
    terrain.terrainData.treePrototypes = prototypes;

    // Build TreeInstance[]
    var trees = manifest.instances
        .Where(i => manifest.mesh_library[i.mesh_id].unity_render_mode == "terrain_tree")
        .Select(i => new TreeInstance {
            position = new Vector3(
                i.position_terrain_norm[0],
                i.position_terrain_norm[1],
                i.position_terrain_norm[2]),
            prototypeIndex = i.mesh_id,
            rotation = i.rotation_y_rad,
            widthScale = i.scale,
            heightScale = i.scale,
            color = new Color(i.tint_rgb[0], i.tint_rgb[1], i.tint_rgb[2]),
            lightmapColor = Color.white,
        }).ToArray();

    terrain.terrainData.SetTreeInstances(trees, snapToHeightmap: true);
}
```

### MAXScript helper writer for Forest Pack Reference Mode

```maxscript
-- Reads manifest.json, creates one PointHelper per instance grouped by species layer.
-- Forest Pack object then uses Reference Mode → species layer.
fn importFoliageManifest jsonPath = (
    local manifest = readJsonFile jsonPath
    for inst in manifest.instances do (
        local species = manifest.mesh_library[inst.mesh_id+1].species_key
        local layerName = "FP_REF_" + species
        local lyr = LayerManager.getLayerFromName layerName
        if lyr == undefined do lyr = LayerManager.newLayerFromName layerName

        local p = Point pos:[inst.position_world[1], inst.position_world[2], inst.position_world[3]]
        rotate p (eulerAngles 0 0 (degToRad inst.rotation_y_rad))
        setUserProp p "scale" inst.scale
        setUserProp p "lod_level" inst.lod_level
        lyr.addNode p
    )
)
```

---

## State of the Art

| Old approach | Current AAA approach (2026) | When changed | Impact |
|---|---|---|---|
| Hand-paint all foliage in DCC | GPU procedural placement (Decima / Horizon) + artist override layer | 2017 (HZD) → industry-wide by 2022 | We adopt the GPU-placement *style* in Python on the CPU; same conceptual pipeline. |
| Unity Tree Editor / SpeedTree only | Pre-authored FBX + GPU Resident Drawer + BatchRendererGroup | Unity 6 (2024) | We bypass Tree Editor entirely. SpeedTree optional. |
| Forest Pack scenes baked to massive FBX for game export | Forest Pack Unity export plugin (Hybrid Renderer) OR data-driven manifest | FP 7 (2018) for plugin; better path = manifest (current best) | We use manifest as primary, plugin as fallback for shot-specific exports. |
| XGen for hair only | XGen Interactive Grooming for ground cover cards | Maya 2017 + (Convert to Polygon shipped 2017) | Standard practice now for game ground-cover authoring. |
| Custom Python L-systems | Retired; replaced by Tripo + artist + XGen | This project, locked 2026-04-26 | Per master guide. |

**Deprecated / outdated:**
- Unity Hybrid Renderer (`com.unity.rendering.hybrid`) — deprecated, forwards to `com.unity.entities.graphics`. The Forest Pack Unity plugin built on this; verify on Unity 6 before relying.
- `TerrainData.treeInstances = arr` (no snap) — superseded by `SetTreeInstances(arr, true)`.

---

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|---|---|---|
| A1 | Forest Pack 9.4 Reference Mode behaves the same in 3ds Max 2027 as documented for FP 8/9 in the public docs site (which target Max 2023–2027). | Forest Pack section | LOW — itoosoft.com explicitly states 2027 support via FP 9.4.0 + RailClone 7.3.0. [VERIFIED: toolfarm.com news 2026] |
| A2 | The XGen "Convert Interactive Groom to Polygon" workflow in Maya 2027 matches the documented Maya 2024 workflow. | XGen section | LOW — feature has been stable since Maya 2017; Autodesk has not signalled changes. [ASSUMED across versions; verified for 2024 docs] |
| A3 | Unity 6.x `TerrainData.SetTreeInstances` API is unchanged from earlier `TerrainData.treeInstances`-era API. | Unity importer | LOW — `SetTreeInstances` has been stable since Unity 2019.3; both 6000.1 and 6000.2 docs show identical signature. [VERIFIED: docs.unity3d.com 2026-04-26] |
| A4 | The Forest Pack Unity export plugin still functions on Unity 6 despite Hybrid Renderer deprecation. | Forest Pack Path B | MEDIUM — ITOOSOFT marks the plugin "experimental" and last refresh appears to be Unity 2018 era. Treated as fallback path only. [ASSUMED — no FP release note confirms Unity 6 compatibility as of 2026-04-26] |
| A5 | `scipy.ndimage` is available in the runtime Python; if not, fall back to a numpy chamfer DT. | SDF exclusion | LOW — already a transitive dep of the terrain stack via existing numpy use. [ASSUMED — verify in `pyproject.toml` during planning] |
| A6 | Forest Pack 9.4's Reference Mode supports reading per-helper user-properties (scale, rotation) at distribute time, not just helper transform. | Forest Pack section | MEDIUM — docs confirm Reference Mode reads pivot+rotation from helpers; per-instance scale via user-prop is implied by FP's general per-item randomisation but not explicitly stated for Reference Mode. Workaround: bake scale into helper transform (`PointHelper.scale`) when writing the helpers. [ASSUMED with workaround] |
| A7 | We will author at most ~8 ground-cover species across all 14 biomes (moss variants, grass variants, lichen variants), not 14×8. | XGen workflow effort estimate | LOW — biome differentiation comes mostly from material tinting (already supported via `tint_rgb` field), not unique meshes. [ASSUMED — confirm with art direction] |

---

## Open Questions

1. **Does Forest Pack 9.4's Reference Mode read per-helper scale?**
   - What we know: helper *position* and *rotation* are dynamically linked. Per-item scale variation in FP normally comes from FP's own random-scale field.
   - What's unclear: whether a string user-property on the helper can drive per-instance scale.
   - Recommendation: write a 30-line MAXScript test that creates 5 helpers with different `scale` user-props, points an FP Reference object at the layer, and renders. If it doesn't work, bake scale into the helper's transform `scale` instead — Reference Mode definitely respects helper transform.

2. **Forest Pack Unity export plugin status on Unity 6.**
   - What we know: plugin is "experimental", FP 7+, Unity 2018+. Hybrid Renderer was deprecated in Unity 6.
   - What's unclear: whether the plugin actually loads + functions on a 6000.x project.
   - Recommendation: validate empirically before relying on Path B. Production path (manifest direct → Editor importer) does not depend on the plugin.

3. **Should ground-cover use Unity Terrain Detail layer (`DetailPrototype`) or GPU Resident Drawer?**
   - What we know: `DetailPrototype` is fast, billboard-only, density-painted via splatmap. GPU Resident Drawer handles full meshes with arbitrary instancing.
   - Trade-off: Detail layer is best for grass billboards; GPU Resident Drawer is best for moss cards we want to retain at multiple LODs and with full materials.
   - Recommendation: dual-mode — `unity_render_mode: "detail_prototype"` for billboard grass, `"gpu_instancer"` for everything else. Schema already supports this.

4. **How are imposters/billboards (LOD3) authored?**
   - What we know: Unity has an Imposter Baker package; alternative is a single quad with a baked atlas.
   - What's unclear: whether to bake imposters in Max via Forest Pack's billboard tools or via Unity's Imposter Baker.
   - Recommendation: Unity Imposter Baker — keeps the LOD3 atlas in the same format as runtime materials and avoids round-tripping. Out of scope for Wave 5 plumbing; tracked for Wave 6.

---

## Project Constraints (from CLAUDE.md / MEMORY.md)

The project's auto-memory locks these decisions for foliage work:

- **Master guide:** `docs/AAA_MASTER_IMPLEMENTATION_GUIDE_2026_04_26.md` — Foliage = D grade, **retire Python L-system**.
- **Foliage stack memo (2026-04-26):** `project_foliage_stack_2026_04_26.md` — L-Py + PlantGL noted as "best free headless"; Modular Tree, OpenScatter, Geo-Scatter listed as broken for BG scripting. *We supersede this with Forest Pack + XGen for Wave 5*; the L-Py path is now optional and kept only for one-off variant authoring outside the runtime path.
- **Audit strictness:** Compare to AAA studios, not technique names — the manifest must produce results indistinguishable from a Decima / Frostbite scatter at shipping resolution.
- **Don't commit during Codex verification.**
- **Blender 4.5 bpy API** — `vegetation_system.py` Blender materializer mode targets 4.5; no API change needed for Wave 5 since Wave 5 uses `spec_only` plus manifest emission, bypassing the Blender path.
- **Repo scope guard:** `procedural_meshes.py` flagged for relocation — do not extend foliage logic into that file.

---

## Validation Architecture

### Test framework

| Property | Value |
|---|---|
| Framework | pytest (existing — confirmed via `tests/test_callable_evidence_bridge_vegetation.py` and ~30 other test_*.py) |
| Quick run | `python -m pytest veilbreakers_terrain/tests/test_vegetation_system.py -x -q` |
| Full suite | `python -m pytest veilbreakers_terrain/tests/ -x -q` |

### Phase requirements → test map

| REQ | Behaviour | Test type | Command | File |
|---|---|---|---|---|
| W5-01 | `load_mesh_library` reads valid JSON, raises on missing fields | unit | `pytest tests/test_foliage_manifest.py::test_load_mesh_library -x` | NEW: `tests/test_foliage_manifest.py` |
| W5-02 | `build_foliage_placement_manifest` produces v1.0 schema with required keys | unit | `pytest tests/test_foliage_manifest.py::test_manifest_schema -x` | NEW |
| W5-03 | SDF exclusion drops placements within `sdf_road_min_m` of `road_mask` | unit | `pytest tests/test_foliage_manifest.py::test_road_sdf_exclusion -x` | NEW |
| W5-04 | SDF exclusion drops placements within `water_edge_min_m` of water (`bathymetry > 0`) | unit | `pytest tests/test_foliage_manifest.py::test_water_edge_exclusion -x` | NEW |
| W5-05 | `position_terrain_norm` is in [0, 1] for every instance | unit | `pytest tests/test_foliage_manifest.py::test_position_norm_range -x` | NEW |
| W5-06 | `mesh_id` resolves to a valid `mesh_library` entry for every instance | unit | `pytest tests/test_foliage_manifest.py::test_mesh_id_integrity -x` | NEW |
| W5-07 | Round-trip: write manifest → read back → identical instance count and species_density | unit | `pytest tests/test_foliage_manifest.py::test_roundtrip -x` | NEW |
| W5-08 | `scatter_biome_vegetation(emit_manifest=True)` writes file at expected path | integration | `pytest tests/integration/test_foliage_pipeline.py::test_emit_manifest -x` | NEW |
| W5-09 | Manifest produced from real `TerrainMaskStack` smoke fixture has > 0 instances | integration | `pytest tests/integration/test_foliage_pipeline.py::test_real_stack -x` | NEW |
| W5-10 | (manual) MAXScript reads manifest and creates correct helper count | manual | smoke run in Max 2027 | manual checklist |
| W5-11 | (manual) Unity Editor importer creates correct `TreeInstance` count | manual | smoke run in Unity 6 | manual checklist |

### Sampling rate

- **Per task commit:** unit tests (W5-01 to W5-07) — < 5 s
- **Per wave merge:** full suite — current crashes at 47% per memory; resolve as Wave 5 Wave-0 prereq
- **Phase gate:** all unit + integration tests pass; manual W5-10/W5-11 signed off in `docs/aaa-audit/`

### Wave 0 gaps

- [ ] `tests/test_foliage_manifest.py` — does not exist
- [ ] `tests/integration/test_foliage_pipeline.py` — extend existing `test_full_terrain_pipeline.py` or new file
- [ ] Mesh library fixture: `tests/fixtures/mesh_library_minimal.json` with 3 species
- [ ] Stack fixture with `road_sdf_dist`, `cliff_label`, `bathymetry`, `hero_exclusion` populated
- [ ] Resolve full-suite crash at 47% (memory note Wave 9 — pre-Wave-10 task)

---

## Security Domain

Not applicable — Wave 5 is offline asset pipeline plumbing. No auth, sessions, network, secrets, or user input. Manifest JSON is authored by the build system, consumed by the build system. ASVS not applicable.

---

## Sources

### Primary (HIGH confidence)
- [Unity TreeInstance API](https://docs.unity3d.com/ScriptReference/TreeInstance.html) — TreeInstance fields verified 2026-04-26
- [Unity TerrainData.SetTreeInstances](https://docs.unity3d.com/ScriptReference/TerrainData.SetTreeInstances.html) — signature + snapToHeightmap behaviour
- [Unity TerrainData (6000.1)](https://docs.unity3d.com/6000.1/Documentation/ScriptReference/TerrainData.html) — Unity 6 confirmation
- [Forest Pack — Reference Mode](https://docs.itoosoft.com/forestpack/forest-plugin/distribution/reference-mode) — reference-helper distribution behaviour
- [Forest Pack — Exporting to Unity](https://docs.itoosoft.com/forestpack/instantiating-and-exporting/exporting-to-unity) — `.forest` + `.fbx` export flow
- [Forest Pack 9.4 + Max 2027 support announcement (Toolfarm)](https://www.toolfarm.com/news/itoosoft-3ds-max-2027/) — version verification
- [Forest Pack 9 release announcement (CG Channel)](https://www.cgchannel.com/2024/09/itoo-software-releases-forest-pack-9-for-3ds-max/) — feature set
- [XGen Convert Interactive Groom to Polygon (Autodesk Maya 2024 help)](https://help.autodesk.com/view/MAYAUL/2024/ENU/?guid=GUID-5A38705B-3741-4B0D-B5DF-C8FFFB474822) — workflow stable across versions
- [Bifrost scatter_points reference](https://knowledge.autodesk.com/support/maya/learn-explore/caas/CloudHelp/cloudhelp/2022/ENU/Bifrost-Common/files/reference/scatter-pack/Bifrost-Common-reference-scatter-pack-scatter-points-html-html.html) — confirming overlap with FP, kept out of scope
- Source code: `veilbreakers_terrain/handlers/vegetation_system.py` (lines 1–1430), `veilbreakers_terrain/handlers/terrain_semantics.py` (lines 232–430) — read directly 2026-04-26

### Secondary (MEDIUM confidence)
- [Polycount: XGen fur texture workflows](https://polycount.com/discussion/205158/looking-for-fur-texture-workflow-ideas-possibilities-with-xgen-and-arnold) — Arnold-bake-first workaround for Convert-loses-textures pitfall
- [Autodesk forum: XGen convert with texture](https://forums.autodesk.com/t5/maya-forum/xgen-convert-interactive-groom-to-polygone-with-texture/td-p/10292475) — confirms pitfall is widely encountered
- [GPU Instancer Pro on Asset Store](https://assetstore.unity.com/packages/tools/utilities/gpu-instancer-pro-290293) — alternative to GPU Resident Drawer
- [Unity GPU Resident Drawer (URP)](https://docs.unity3d.com/6000.2/Documentation/Manual/urp/gpu-resident-drawer.html) — auto-batching path

### Tertiary (LOW confidence — flagged for validation)
- [Guerrilla Games — GPU-Based Procedural Placement in HZD](https://www.guerrilla-games.com/read/gpu-based-procedural-placement-in-horizon-zero-dawn) — only summary level via web; full PDF not fetched. Confirms the *approach* (graph-defined rules + GPU resolution) but not specific data formats. We are mirroring the *conceptual* design (rules in code, output in manifest), not the exact Decima format.

---

## Metadata

**Confidence breakdown:**
- Standard stack (Forest Pack, XGen, Unity APIs): **HIGH** — multi-source verified
- Forest Pack ↔ manifest integration (Reference Mode): **HIGH** — docs explicit
- Forest Pack → Unity plugin on Unity 6: **MEDIUM** — plugin is experimental, treated as fallback
- XGen card workflow: **HIGH** — Autodesk docs + community workflow consistent
- `vegetation_system.py` modification scope: **HIGH** — read source 2026-04-26
- TerrainMaskStack channel availability: **HIGH** — read source 2026-04-26
- AAA studio internal data formats (Decima): **LOW** — only conceptual, public details limited

**Research date:** 2026-04-26
**Valid until:** 2026-05-26 (30 days — stack is stable; revalidate FP plugin Unity 6 status sooner if it becomes critical-path)
