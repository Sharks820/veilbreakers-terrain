# Coastal Biome — AAA Perfection Audit Checklist

**Purpose:** Lockable per-pass guardrails that gate advancement. Every Coastal pass MUST pass every applicable gate before the next pass starts. After Coastal locks, this template carries forward to **Mountain + Forest** and **Grassland**.

**Goal**: render side-by-side with real AAA coastal references and defend the comparison without caveats.

**AAA references** (the bar to clear):
- Red Dead Redemption 2 — Sea of Coronado, Saint Denis Bay
- Witcher 3: Wild Hunt — Skellige isles
- Kingdom Come Deliverance 2 — Trosky / coastal cliffs
- Assassin's Creed Valhalla — Norwegian fjord coast
- Ghost of Tsushima — Iki Island coast
- Sea of Thieves — open-sea + island shelf

---

## Universal gates (every pass)

| Gate | Pass criterion |
|------|---------------|
| Render manifest written | `renders/coastal/<unit>/RENDER_MANIFEST.json` exists with all 3 cameras |
| All renders non-black | `nonblack_ratio ≥ 0.005` for every PNG |
| Render byte size ≥ 50 KB | every PNG passes the silent-no-write trap |
| 3 named cameras | `VB_CORRECT_COASTAL_FULL_NODE_CAMERA`, `_SHORE_CAMERA`, `_PLAYER_CAMERA` |
| Multi-angle proof when geometry-relevant | + `shore_close_oblique_30`, `bluff_close_oblique_45` |
| Determinism | re-run with same seed produces byte-identical heightfield |
| Test suite | new `test_<module>.py` ≥ 10 cases; all pass |
| AAA-reference composite | side-by-side committed to `renders/coastal/_aaa_comparison/<pass>/` |

## Pass-specific gates

### U1 — Render-Proof Harness ✓ (locked)
- [x] Bypasses `mcp__blender__.get_viewport_screenshot`
- [x] Pre-flights camera names (no late failures)
- [x] Absolute forward-slash filepath (defeats `--background` silent no-write)
- [x] Nonblack + min-byte assertion
- [x] 13 tests pass

### U3 — Bezier-SDF Shoreline ✓ (locked)
- [x] Tessellate→KDTree→signed-by-tangent
- [x] Sign convention: left-of-traversal = positive = land
- [x] Far-east on default shore reads as land (sd > 0)
- [x] Far-west on default shore reads as sea (sd < 0)
- [x] Polyline smoothness: max segment-step < 1% tile size
- [x] 256² grid sampling completes in seconds
- [x] 15 tests pass
- [ ] **Visual gate (pending render)**: shore camera at 50 m shows continuous mesh, no jagged grid triangles

### U4 — Authored Landform Zones (in progress)
- [x] 5 zones implemented (low beach / backshore / headland / gullies / inland ridge)
- [x] Zone weights in [0, 1]
- [x] Composition associative
- [x] Seed-deterministic (3 seeds verified)
- [x] Sea-side change < 5 m far from shore
- [x] Relief spread > 40 m on flat base
- [x] Poisson-disk min-dist respected
- [x] 14 tests pass
- [ ] **Visual gate**: player camera shows visible relief; Z-spread > 80 m on framed area
- [ ] **Visual gate**: bluff close-camera shows headland silhouette > 40 px tall

### U5 — AAA Terrain PBR Shader (queued)
- [ ] 4-6 layers (sand / wet sand / grass / moss / rock / cliff)
- [ ] Brucks height-blend formula verified
- [ ] Triplanar with per-axis tangent reconstruction (no diagonal pinstripes)
- [ ] Slope-driven cliff blend
- [ ] Wet-sand band aligned with SD=0
- [ ] Elevation-driven grass→moss transition
- [ ] No grid pattern in materials at 1 m close camera
- [ ] `TerrainTextureLayerStack` populated (albedo / normal / roughness / AO arrays)
- [ ] **Visual gate**: shore close-camera shows distinct sand/wet-sand band along SD=0
- [ ] **Visual gate**: bluff close-camera shows slope-driven cliff material; smooth transition to grass

### U6 — Animated Water Shader (queued)
- [ ] 4-wave Gerstner via Geometry Nodes (wavelengths 80/50/30/20 m)
- [ ] Water plane subdivided 512² (Nyquist for 20 m)
- [ ] Animation: frame 1, 30, 60 visibly different
- [ ] Foam from `1 − smoothstep(0, foam_dist, scene_depth − water_depth)` + curl-noise UV
- [ ] Foam aligned with SD=0 line
- [ ] Eevee Next: Refraction BSDF + Raytraced Transmission + Screen + Light Probes
- [ ] No water/terrain boundary visible
- [ ] **Visual gate**: shore camera shows foam at SD=0 contact, no foam in deep water
- [ ] **Visual gate**: refraction visible at headland/cove water (light bends through into bathymetry)

### U7 — Lighting / Atmosphere (queued)
- [ ] Nishita sun + sky world shader
- [ ] Volumetric mist (density 0.002, anisotropy 0.4)
- [ ] Horizon fog (distance-based exponential)
- [ ] Color grade preset (filmic-compatible)
- [ ] Irradiance volume + plane reflection probe baked
- [ ] 3 TOD presets: morning, overcast_noon, golden_hour
- [ ] **Visual gate**: full_node camera shows atmospheric perspective on distant features
- [ ] **Visual gate**: shore camera shows readable horizon (not blown out), sun-direction shadows on bluffs

### U8 — Vegetation Stack (queued, vetted free/OS only)

**Approved tools** (research locks before U8 starts):
- Modular Tree v5.5.1 GoodPie fork — GitHub `GoodPie/modular_tree`, GPL-3, Pivot Painter 2.0 baked in
- L-Py + PlantGL — OpenAlea `openalea3` channel, CeCILL-C, headless
- OpenScatter v1.0.7 — GitHub `GitMay3D/OpenScatter`, GPL, Blender 4.5 OK
- Blender Sapling Tree Gen — built-in 4.5 addon, free, fully scriptable
- BlenderProc procedural plants (`DLR-RM/BlenderProc`) — Apache-2.0
- Real Grass FOSS / Grass Free / `realgrass-freebie` style FOSS scatter alternates

**Blocked**: BlenderKit (background-disabled), Botaniq (GUI-only), Geo-Scatter (EULA), SpeedTree (no Blender bridge).

- [ ] Vegetation tool stack research doc committed
- [ ] L-Py installed via `mamba` (conda-forge openalea3)
- [ ] Modular Tree GoodPie addon installed via `blender --background --python` script
- [ ] OpenScatter addon installed via headless script
- [ ] 4 dark-fantasy coastal tree variants (twisted oak, dead pine, mangrove, gnarled hawthorn)
- [ ] 4 grass species + 2 shrub species
- [ ] LOD0 (< 5 k tris) + LOD1 (< 1 k tris)
- [ ] Manifest: `species_for_biome("coastal")` returns 10 species
- [ ] **Visual gate**: species swatch render shows 10 distinct silhouettes
- [ ] **Visual gate**: scatter on coastal tile produces > 0 placements (post-biome-registry alignment)

### U9 — Wind Animation (queued)
- [ ] Pivot Painter 2.0 vertex data baked (UV2 + 16-bit EXR)
- [ ] Geometry Nodes wind preview shader
- [ ] Frame 1 vs 30 vs 60 — pixel diff > 1 % in foliage
- [ ] **Visual gate**: animated 60-frame loop shows believable grass sway

### U10 — Hunyuan3D-2.1 Hero Props (queued)
- [ ] 3 driftwood, 4 boulders, 3 reeds, 2 shrubs, 5 foam decals
- [ ] Each LOD0 ≤ 20 k tris, LOD1 ≤ 5 k tris
- [ ] Manifest entries with placement rules (SD range, slope range, density)
- [ ] **Visual gate**: shore camera shows driftwood at human scale; boulder silhouettes legible

### U11 — Adaptive Mesh + Cliff Hero Meshes (queued)
- [ ] Curve-conforming shoreline strip welded into terrain (no T-junctions)
- [ ] Cliff hero meshes for headlands > 60 m / slope > 50°
- [ ] **Visual gate**: shore close-oblique 30° shows continuous mesh at strip-terrain join
- [ ] **Visual gate**: bluff close shows cliff hero detail not in base terrain

### U12 — Unity Round-Trip (queued)
- [ ] RAW16 heightmap (1025², uint16-LE, `.raw` extension)
- [ ] Splatmap weights from `stack.splatmap_weights_layer`
- [ ] Water JSON (surface elevation, depth, flow, shoreline mask)
- [ ] GLBs (terrain + strip + cliffs + props + foliage)
- [ ] `veilbreakers-unity-export-check` passes
- [ ] **Visual gate**: Blender vs Unity side-by-side at 3 cameras, < 10 % pixel diff post-color-grade

### U13 — Coastal Best-Practices Doc (queued)
- [ ] `docs/biome-best-practices/COASTAL.md` published
- [ ] `docs/biome-best-practices/_TEMPLATE_BIOME_PERFECTION.md` published
- [ ] All `docs/solutions/` entries from U1/U3/U4/U5/U6/U9/U12 exist
- [ ] AAA reference composite gallery committed
- [ ] **Final visual gate**: every camera + every pass + AAA reference all signed off

---

## AAA Comparison gate

For each major pass that changes appearance (U3, U5, U6, U7, U8, U9, U10), commit a side-by-side composite to `renders/coastal/_aaa_comparison/<pass>/SIDE_BY_SIDE.png`:

```
[ Our Coastal pass | RDR2 reference | Witcher 3 ref | KCD2 ref ]
```

The pass cannot advance until **at least 2 of 3 references** are visually peer-level on the dimension that pass owns (shoreline geometry, materials, water animation, lighting, foliage, props).

## Self-audit cadence

After each pass commit:
1. Re-run all biome tests (`pytest veilbreakers_terrain/tests/test_*coastal*.py`).
2. Run live-Blender render proof (`scripts/render_coastal_camera_proof.py --unit-id u<NN>_<slug> ...`).
3. Generate AAA-reference composite.
4. Update this checklist (check the gate boxes).
5. Commit with `feat(coastal): <Uxx> <slug> — pass <gate> visual proof + manifest`.

If any gate fails, **iterate on that pass before moving on**. Do not advance with open gates.
