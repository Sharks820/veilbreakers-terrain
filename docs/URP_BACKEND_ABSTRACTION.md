# URP Backend Abstraction — Plug-and-Play Architecture Spec

> Canonical design document for VeilBreakers' URP rendering-backend abstraction.
> Unity-side C# implementation work consults this spec when authoring the four
> backend interfaces and their concrete adapters.

---

## 1. Executive summary

VeilBreakers commits to **Universal Render Pipeline (URP) 17.3** for v1.0 ship.
The choice is locked because URP 17.3 is FREE, runs comfortably inside the
project's **8 GB VRAM hard constraint** (RTX 4060 Ti baseline), and continues
to receive Unity engineering attention while HDRP enters maintenance mode in
February 2026.

> **Reference scope.** The URP commitment was finalized via a 6-agent fleet
> audit + Unity batch-mode setup verification (memory note
> `project_urp_commitment_2026_05_07`, repo-external — lives in the
> author's user-memory store, not under version control).
> `docs/IMPLEMENTATION_FIX_GUIDE_2026_05_07_FINAL.md` contains the legacy
> HDRP-tied stack notes from before this commitment was made; **only the
> 8 GB VRAM hardware-constraint analysis there is still authoritative**
> (memory note `project_hardware_8gb_vram_2026_05_07`, also user-memory
> only). The HDRP-specific picks (MicroSplat HDRP, WaterSurface, DXR, etc.)
> in that older guide are SUPERSEDED by this URP spec — see §10 References
> for what to read and what to ignore.

URP, however, has feature gaps relative to HDRP — most notably in water,
volumetric clouds, height-fog, and high-quality temporal upscaling. Rather
than ship sub-AAA visuals or paint ourselves into a corner that blocks a
later upgrade, v1.0 introduces **four backend interfaces** that hide the
URP-specific implementation choices behind a stable contract:

1. `IWaterBackend`
2. `ISkyBackend`
3. `IFogBackend`
4. `IUpscalerBackend`

The bake side (Python, this repo) writes a deterministic JSON manifest
describing **what** the scene needs (water elevation, wave amplitude,
fog density curve, upscaler quality preset, etc.). The runtime side (Unity,
C#) selects the concrete backend matching the project's current Player
Settings define-symbol set and translates the manifest into backend-specific
calls.

**v1.1 upgrade cost = adding one C# adapter + flipping a define symbol.**
Zero bake-side changes. No regrade of asset libraries, terrain, foliage,
or any of the 26 fields of `VbTerrainTileMetadata`.

---

## 2. The 4 interfaces

All four interfaces share a small common base, `IBackend`, so generic
selection code can read `BackendId` / `IsAvailable` without `dynamic`:

```csharp
namespace VeilBreakers.Rendering.Backends
{
    public interface IBackend
    {
        bool   IsAvailable { get; }
        string BackendId   { get; }
    }
}
```

`IWaterBackend`, `ISkyBackend`, `IFogBackend`, and `IUpscalerBackend` each
extend `IBackend`. The members shown in the per-slot contracts below
(`IsAvailable`, `BackendId`) are inherited from `IBackend` and re-listed
for readability — implementers do not declare them twice.

### 2.1 `IWaterBackend`

**Today's implementation (v1.0 ship):** Boat Attack water (FREE Unity sample
asset, MIT licensed). Vertex-displacement Gerstner waves, planar reflection,
foam by mask, caustics by projector, shore reaction by SDF lookup.

**Future swap candidates:**
- Stylized Water 2 (paid asset, ~$45 — `[SKU TBD — search Asset Store
  before swap; verify the listed SKU and current price]`) — better
  stylized look for v1.1.
- Crest 5 — **paid only**, Asset Store SKU **268614**, $100-200 list
  (~$165 typical). The OSS GitHub `wave-harmonic/crest` (Crest 4) is
  **BIRP-only** and **not usable on URP**; it does not back-port to
  URP 17.3. Selecting `crest_5` requires the paid Asset Store license.
- `hand_authored_urp` `[FUTURE]` — placeholder for "we wrote our own URP
  shader", not a shipping product today. Reserved for the case where
  licensing or perf forces a custom write. Manifest writers SHOULD NOT
  emit this backend ID until v1.1+ ships an in-house implementation;
  runtime SHOULD reject `hand_authored_urp` as `not yet implemented`
  per §7 schema versioning.

**C# interface contract:**

```csharp
namespace VeilBreakers.Rendering.Backends
{
    public interface IWaterBackend : IBackend
    {
        // BackendId is one of: "boat_attack" / "stylized_water_2" / "crest_5" / "hand_authored_urp"
        // [FUTURE] markers: "hand_authored_urp" is reserved (not shipping today).
        void ApplyManifest(WaterSurfaceManifest manifest);
        void SetWaterPlaneElevation(float meters);
        void SetWaveSpec(float amplitude_m, float period_s);
        void SetFoamMask(Texture2D mask, float thresholdNormalized);
        void SetCausticsMask(Texture2D mask, float intensity);
        void SetShoreReaction(bool enabled, Texture2D shoreSDF);
    }
}
```

### 2.2 `ISkyBackend`

**Today's implementation (v1.0 ship):** Skybox cubemap. A baked HDR EXR
cubemap drives both reflection probes and the visible sky. Time-of-day is
authored as a discrete keyframe per scene (no real-time TOD blend in v1.0).

**Future swap candidates:**
- Volume Cloud URP (paid asset, `[SKU TBD — search Asset Store before
  swap]`) — drop-in volumetric clouds for v1.1.
- `volumetric_clouds_native` `[FUTURE]` — placeholder for Unity native
  URP volumetric clouds. **No public Unity roadmap commits to URP-native
  volumetric clouds as of URP 17.3** (HDRP-only as of writing). This
  backend ID is reserved against the future where Unity ships parity;
  runtime SHOULD reject `volumetric_clouds_native` as `not yet
  implemented` per §7 schema versioning until that happens.

**C# interface contract:**

```csharp
namespace VeilBreakers.Rendering.Backends
{
    public interface ISkyBackend : IBackend
    {
        // BackendId is one of: "skybox_cubemap" / "volume_cloud_urp" / "volumetric_clouds_native"
        // [FUTURE] markers: "volumetric_clouds_native" is reserved (no URP roadmap as of 17.3).
        void ApplyManifest(SkyManifest manifest);
        void SetCubemap(Texture cubemap);
        void SetTimeOfDay(float hour);                // 0.0 .. 24.0
        void SetSunRotation(Quaternion rotation);
        void SetCloudDensity(float density01);        // 0..1; 0.0 = clear sky
    }
}
```

### 2.3 `IFogBackend`

**Today's implementation (v1.0 ship):** URP Fog Volume + atmospheric cards.
Standard URP exponential / linear fog driven by a height-density curve plus
billboarded fog cards for hero pockets (mist clinging to riverbeds, etc.).

**Future swap candidates:**
- Atmospheric Height Fog (paid asset, `[SKU TBD — search Asset Store
  before swap]`) — proper height-fog with light scattering for v1.1.
- `volumetric_fog_native` `[FUTURE]` — placeholder for Unity native URP
  volumetric fog. **URP 17.3 has no native volumetric-fog module as of
  writing** (HDRP-only). This backend ID is reserved against future
  parity; runtime SHOULD reject `volumetric_fog_native` as `not yet
  implemented` per §7 schema versioning until URP ships it.

**C# interface contract:**

```csharp
namespace VeilBreakers.Rendering.Backends
{
    public interface IFogBackend : IBackend
    {
        // BackendId is one of: "urp_fog_volume_plus_cards" / "atmospheric_height_fog" / "volumetric_fog_native"
        // [FUTURE] markers: "volumetric_fog_native" is reserved (no URP-native module as of 17.3).
        void ApplyManifest(AtmosphericManifest manifest);
        void SetHeightDensityCurve(AnimationCurve curve);   // y in [0..1]; x = world meters
        void SetFogColorRamp(Texture2D ramp);
        void SetWindDirection(Vector3 windXYZ);
    }
}
```

### 2.4 `IUpscalerBackend`

**Today's implementation (v1.0 ship):** **STP 1.0** (Spatial-Temporal
Post-processing) — Unity's native temporal upscaler shipping in URP 17.3
out of the box (Upscaling Filter dropdown option, motion-vector-driven,
FREE). **FSR 1.0** (FidelityFX Super Resolution 1.0) is the in-the-box
spatial fallback dropdown choice (also FREE, also URP 17.3 native) for
scenes where STP ghosting on heavy alpha foliage forces a swap. Both
shipped FREE and native; both are real Upscaling Filter dropdown picks
in URP 17.3 (the in-box list is *Automatic / Bilinear / Nearest-Neighbor /
FSR 1.0 / STP 1.0*).

> **Why STP 1.0, not FSR 3.1.** Earlier drafts of this doc and the
> IMPLEMENTATION_FIX_GUIDE listed `fsr_3_1` as the v1.0 default. That was
> a doc-drift error — FSR 3.1 is **not** in URP 17.3's native Upscaling
> Filter dropdown. FSR 3.1 requires the external `FSR3-Unity-URP`
> AMD/community package; we treat it as a v1.1 IUpscalerBackend swap
> candidate, not the ship default. Source: URP 6000.0 manual >
> Universal Render Pipeline Asset > Quality > Upscaling Filter.

**Future swap candidates (all v1.1):**
- FSR 3.1 — AMD/community `FSR3-Unity-URP` package; gated on package availability
  and integration time (~1-2 weeks). Adds super-resolution + frame-gen.
- DLSS 4.5 — NVIDIA NGX SDK URP port; gated on either an official Unity
  package or a stable community wrapper (see §6.4 walkthrough — currently
  marked v1.1 deferred).
- Off — explicit no-upscale path for QA, screenshots, AAA-quality stills.

**C# interface contract:**

```csharp
namespace VeilBreakers.Rendering.Backends
{
    public interface IUpscalerBackend : IBackend
    {
        // BackendId is one of: "stp_1_0" / "fsr_1_0" / "fsr_3_1" / "dlss_4_5" / "off"
        // v1.0 ship default = "stp_1_0"; spatial fallback = "fsr_1_0".
        // v1.1 swaps = "fsr_3_1" (FSR3-Unity-URP package), "dlss_4_5" (NGX SDK URP port).
        void ApplyManifest(UpscalerManifest manifest);
        void SetQuality(string preset);      // "ultra_quality" / "quality" / "balanced" / "performance"
        void SetMipBias(float biasOffset);   // negative values sharpen at the cost of perf
        bool IsSupportedOnThisGPU();         // instance method — call after construction
    }
}
```

> **Capability detection convention.** `IsSupportedOnThisGPU()` is declared
> as an **instance method** so adapters can consult fields populated in
> their constructor (NGX init handle, FSR feature support flags, etc.).
> The bootstrap MUST construct the backend first and then call the
> instance method — never call it as a static. See §5.1 below.

---

## 3. Manifest schema reference

This is the **exact** JSON the bake side writes and the runtime side reads.
Each top-level section corresponds to one backend interface and carries an
independent `schema_version` so the four backends evolve out-of-step without
coupling.

```json
{
  "schema_version": "1.0",
  "render_pipeline": {"type": "URP", "version": "17.3"},
  "water": {
    "schema_version": "1.0",
    "backend": "boat_attack",
    "elevation_m": 12.0,
    "wave_amplitude_m": 0.6,
    "wave_period_s": 4.5,
    "foam_threshold_normalized": 0.3,
    "caustics_intensity": 0.7,
    "shore_reaction_enabled": true,
    "upgrade_compat": ["stylized_water_2", "crest_5", "hand_authored_urp"]
  },
  "sky": {
    "schema_version": "1.0",
    "backend": "skybox_cubemap",
    "cubemap_path": "skybox/sky_cubemap.exr",
    "time_of_day_hour": 14.5,
    "sun_rotation_quat": [0.0, 0.0, 0.0, 1.0],
    "cloud_density": 0.0,
    "upgrade_compat": ["volume_cloud_urp", "volumetric_clouds_native"]
  },
  "atmospheric": {
    "schema_version": "1.0",
    "backend": "urp_fog_volume_plus_cards",
    "height_density_curve": [[0.0, 0.8], [50.0, 0.4], [200.0, 0.05]],
    "fog_color_ramp_path": "atmospheric/fog_ramp.png",
    "wind_direction_xyz": [0.7, 0.0, 0.7],
    "upgrade_compat": ["atmospheric_height_fog", "volumetric_fog_native"]
  },
  "upscaler": {
    "schema_version": "1.0",
    "backend": "stp_1_0",
    "quality": "balanced",
    "mip_bias": -1.0,
    "upgrade_compat": ["fsr_1_0", "fsr_3_1", "dlss_4_5", "off"]
  }
}
```

> **Note on `[FUTURE]` backend IDs in `upgrade_compat`.** Three IDs above
> — `hand_authored_urp` (water), `volumetric_clouds_native` (sky),
> `volumetric_fog_native` (atmospheric) — are valid manifest values per
> §2 but are **not yet implemented** as of v1.0. They are reserved against
> the future where Unity ships URP-native parity (clouds/fog) or where
> VeilBreakers writes its own URP shader (water). Runtime SHOULD reject
> these IDs as `not yet implemented` until v1.1+ ships them — see §7
> schema versioning.
>
> **Note on `upscaler.backend = "stp_1_0"`.** v1.0 defaults to STP 1.0
> (URP 17.3 native, motion-vector-driven). FSR 1.0 is the in-the-box
> spatial fallback (also URP 17.3 native). FSR 3.1 and DLSS 4.5 are v1.1
> swap candidates listed in `upgrade_compat[]` so the abstraction can
> roll forward without a schema bump. See §2.4.

This schema has matching `@dataclass` definitions on the bake side at
`veilbreakers_terrain/handlers/terrain_unity_backends.py` (landed via
Phase D1 PR #49, merge `e97ae1c` 2026-05-08T14:25:11Z):

- `WaterSurfaceManifest`
- `SkyManifest`
- `AtmosphericManifest`
- `UpscalerManifest`

> **Status update (2026-05-08).** Phase D1 has merged. `terrain_unity_backends.py`
> is now present on `main`; the `@dataclass` definitions match this JSON
> schema and are pinned by `test_phase_d1_urp_manifest_schema.py`.

The bake side OWNS the schema. The runtime side is read-only.

### 3.5 ScriptableObject field schemas (runtime-side authoring)

Each backend slot is bound at edit-time through a **`ScriptableObject`
profile** that carries Unity-side asset references (Addressables,
Materials, Prefabs) which the JSON manifest cannot itself contain. The
bootstrap reads the profile, then overlays the JSON-manifest parameters
on top — assets come from the SO, parameters come from the manifest. The
SO field types below are the canonical authoring surface; backend
adapters MUST consume them through the typed accessors and never via
reflection.

```csharp
using UnityEngine;
using UnityEngine.AddressableAssets;

namespace VeilBreakers.Rendering.Backends
{
    [CreateAssetMenu(menuName = "VeilBreakers/Rendering/Water Backend Profile")]
    public sealed class WaterBackendProfile : ScriptableObject
    {
        // Maps to manifest.water.backend
        public string backendId = "boat_attack";

        // Addressable asset references — resolved at scene load.
        public AssetReferenceGameObject waterPrefab;     // e.g. Boat Attack water prefab
        public AssetReferenceTexture2D foamMask;
        public AssetReferenceTexture2D causticsMask;
        public AssetReferenceTexture2D shoreSDF;

        // Direct material reference for runtime parameter binding.
        public Material waterMaterial;

        // Parameter defaults (overlaid by WaterSurfaceManifest at runtime).
        public float waterPlaneElevationM = 12.0f;
        public float waveAmplitudeM       = 0.5f;
        public float wavePeriodS          = 4.5f;
        public float foamThresholdNorm    = 0.3f;
        public float causticsIntensity    = 0.7f;
        public bool  shoreReactionEnabled = true;
    }

    [CreateAssetMenu(menuName = "VeilBreakers/Rendering/Sky Backend Profile")]
    public sealed class SkyBackendProfile : ScriptableObject
    {
        // Maps to manifest.sky.backend
        public string backendId = "skybox_cubemap";

        // Cubemap asset (HDR EXR). Addressable so it streams.
        public AssetReferenceCubemap cubemap;

        // Optional volumetric-cloud component reference (used by v1.1 swaps).
        public AssetReferenceGameObject cloudComponentPrefab;

        // Parameter defaults (overlaid by SkyManifest at runtime).
        public float      timeOfDayHour = 14.5f;          // 0.0 .. 24.0
        public Quaternion sunRotation   = Quaternion.identity;
        public float      cloudDensity  = 0.0f;           // 0..1; 0.0 = clear sky
    }

    [CreateAssetMenu(menuName = "VeilBreakers/Rendering/Fog Backend Profile")]
    public sealed class FogBackendProfile : ScriptableObject
    {
        // Maps to manifest.atmospheric.backend
        public string backendId = "urp_fog_volume_plus_cards";

        // Curve and ramp authored in the editor (manifest provides numeric keyframes
        // that overlay these defaults).
        public AnimationCurve heightDensityCurve = AnimationCurve.Linear(0, 0.8f, 200, 0.05f);
        public Texture2D      fogColorRamp;

        // Atmospheric-card prefabs for hero pockets (mist clinging to riverbeds).
        public AssetReferenceGameObject[] fogCardPrefabs;

        // Parameter defaults (overlaid by AtmosphericManifest at runtime).
        public Vector3 windDirectionXYZ = new Vector3(0.7f, 0.0f, 0.7f);
    }

    [CreateAssetMenu(menuName = "VeilBreakers/Rendering/Upscaler Backend Profile")]
    public sealed class UpscalerBackendProfile : ScriptableObject
    {
        // Maps to manifest.upscaler.backend. v1.0 default = "stp_1_0".
        public string backendId = "stp_1_0";

        // Parameter defaults (overlaid by UpscalerManifest at runtime).
        public string qualityPreset = "balanced";  // "ultra_quality" / "quality" / "balanced" / "performance"
        public float  mipBias       = -1.0f;       // negative = sharper

        // Optional NGX init-handle reference for v1.1 DLSS swap; null on v1.0 ship.
        // Resolved by DLSS45UpscalerBackend at construction time when the
        // VB_UPSCALER_DLSS_4_5 define is active. See §6.4 [V1.1 DEFERRED] banner.
        public Object ngxInitHandleAsset;          // typed via reflection-free wrapper in v1.1
    }
}
```

> **Authoring → runtime contract.** The `BackendBootstrap` MUST resolve
> the profile SO first (via Addressables or a directly-injected
> reference), then call `ApplyManifest(...)` so JSON-manifest values
> overwrite the SO defaults. SO defaults exist only to keep the editor
> playable when the manifest is absent (e.g. a fresh scene with no bake
> output yet). Manifest values always win at runtime.

Each backend lives in its **own assembly definition** (`.asmdef`) so
unselected backends are fully compile-excluded. There is no runtime
reflection, no `Resources.Load`, and no string-keyed dispatch in the hot
path. The selection is a build-time decision driven by **scripting define
symbols**.

### 4.1 Folder layout

```
Assets/Scripts/Rendering/
├── Backends/
│   ├── VeilBreakers.Rendering.Backends.asmdef         # interfaces only
│   ├── IWaterBackend.cs
│   ├── ISkyBackend.cs
│   ├── IFogBackend.cs
│   ├── IUpscalerBackend.cs
│   └── BackendBootstrap.cs
├── Water/
│   ├── BoatAttack/
│   │   ├── VeilBreakers.Rendering.Water.BoatAttack.asmdef
│   │   │   (defineConstraints: VB_WATER_BOAT_ATTACK)
│   │   └── BoatAttackWaterBackend.cs
│   ├── StylizedWater2/
│   │   ├── VeilBreakers.Rendering.Water.StylizedWater2.asmdef
│   │   │   (defineConstraints: VB_WATER_STYLIZED_2)
│   │   └── StylizedWater2Backend.cs
│   └── Crest5/
│       ├── VeilBreakers.Rendering.Water.Crest5.asmdef
│       │   (defineConstraints: VB_WATER_CREST_5)
│       └── Crest5Backend.cs
├── Sky/
│   ├── SkyboxCubemap/
│   │   ├── VeilBreakers.Rendering.Sky.SkyboxCubemap.asmdef
│   │   │   (defineConstraints: VB_SKY_SKYBOX_CUBEMAP)
│   │   └── SkyboxCubemapBackend.cs
│   ├── VolumeCloudURP/
│   │   ├── VeilBreakers.Rendering.Sky.VolumeCloudURP.asmdef
│   │   │   (defineConstraints: VB_SKY_VOLUME_CLOUD_URP)
│   │   └── VolumeCloudURPBackend.cs
│   └── VolumetricCloudsNative/
│       ├── VeilBreakers.Rendering.Sky.VolumetricCloudsNative.asmdef
│       │   (defineConstraints: VB_SKY_VOLUMETRIC_CLOUDS_NATIVE)
│       └── VolumetricCloudsNativeBackend.cs
├── Fog/
│   ├── URPFogVolume/
│   │   ├── VeilBreakers.Rendering.Fog.URPFogVolume.asmdef
│   │   │   (defineConstraints: VB_FOG_URP_FOG_VOLUME)
│   │   └── URPFogVolumeBackend.cs
│   ├── AtmosphericHeightFog/
│   │   ├── VeilBreakers.Rendering.Fog.AtmosphericHeightFog.asmdef
│   │   │   (defineConstraints: VB_FOG_ATMOSPHERIC_HEIGHT_FOG)
│   │   └── AtmosphericHeightFogBackend.cs
│   └── VolumetricFogNative/
│       ├── VeilBreakers.Rendering.Fog.VolumetricFogNative.asmdef
│       │   (defineConstraints: VB_FOG_VOLUMETRIC_FOG_NATIVE)
│       └── VolumetricFogNativeBackend.cs
└── Upscaler/
    ├── STP10/                                 # v1.0 ship default (URP 17.3 native)
    │   ├── VeilBreakers.Rendering.Upscaler.STP10.asmdef
    │   │   (defineConstraints: VB_UPSCALER_STP_1_0)
    │   └── STP10UpscalerBackend.cs
    ├── FSR10/                                 # v1.0 spatial fallback (URP 17.3 native)
    │   ├── VeilBreakers.Rendering.Upscaler.FSR10.asmdef
    │   │   (defineConstraints: VB_UPSCALER_FSR_1_0)
    │   └── FSR10UpscalerBackend.cs
    ├── FSR31/                                 # v1.1 swap (FSR3-Unity-URP package)
    │   ├── VeilBreakers.Rendering.Upscaler.FSR31.asmdef
    │   │   (defineConstraints: VB_UPSCALER_FSR_3_1)
    │   └── FSR31UpscalerBackend.cs
    ├── DLSS45/                                # v1.1 swap (NGX SDK URP port)
    │   ├── VeilBreakers.Rendering.Upscaler.DLSS45.asmdef
    │   │   (defineConstraints: VB_UPSCALER_DLSS_4_5)
    │   └── DLSS45UpscalerBackend.cs
    └── Off/
        ├── VeilBreakers.Rendering.Upscaler.Off.asmdef
        │   (always enabled — no constraint)
        └── OffUpscalerBackend.cs
```

> **Asmdef field choice:** Unity's `versionDefines` is for package-version-based
> compile symbols (e.g. emit `VB_HAS_NEW_API` when `com.unity.foo >= 2.0.0`),
> while `defineConstraints` is what gates whether an assembly is compiled or
> referenced at all. Backend gating belongs in `defineConstraints` — a missing
> or paid adapter (Stylized Water 2, Crest 5, NGX SDK) must stay
> compile-excluded, not fail import. `versionDefines` is reserved here for
> package-presence symbols that the constraint evaluates against.

### 4.2 Define-symbol contract

| Slot     | v1.0 active symbol(s)                                  | v1.1 candidate symbols                                       |
|----------|--------------------------------------------------------|--------------------------------------------------------------|
| Water    | `VB_WATER_BOAT_ATTACK`                                 | `VB_WATER_STYLIZED_2`, `VB_WATER_CREST_5`                    |
| Sky      | `VB_SKY_SKYBOX_CUBEMAP`                                | `VB_SKY_VOLUME_CLOUD_URP`, `VB_SKY_VOLUMETRIC_CLOUDS_NATIVE` |
| Fog      | `VB_FOG_URP_FOG_VOLUME`                                | `VB_FOG_ATMOSPHERIC_HEIGHT_FOG`, `VB_FOG_VOLUMETRIC_FOG_NATIVE` |
| Upscaler | `VB_UPSCALER_STP_1_0` (primary) + `VB_UPSCALER_FSR_1_0` (fallback) | `VB_UPSCALER_FSR_3_1`, `VB_UPSCALER_DLSS_4_5`        |

**Exactly one** Water / Sky / Fog symbol is active at a time. **Multiple**
upscaler symbols MAY be active simultaneously — v1.0 ships with both
`VB_UPSCALER_STP_1_0` and `VB_UPSCALER_FSR_1_0` defined so the bootstrap
can pick STP 1.0 by default and fall back to FSR 1.0 if STP causes
ghosting on heavy alpha foliage. v1.1 swap symbols
(`VB_UPSCALER_FSR_3_1`, `VB_UPSCALER_DLSS_4_5`) MAY also be defined
alongside the v1.0 symbols when their adapters land — the bootstrap
chooses at runtime via `IsSupportedOnThisGPU()` and the manifest
preference order.

### 4.3 Switching backends — operator runbook

To swap from Boat Attack water to Stylized Water 2:

1. **Player Settings → Other Settings → Scripting Define Symbols** —
   replace `VB_WATER_BOAT_ATTACK` with `VB_WATER_STYLIZED_2`.
2. **Update `WaterBackendProfile` ScriptableObject** — change the
   `prefabReference` to point at the Stylized Water 2 prefab.
3. **Trigger a full asset re-import** — Unity recompiles, the Boat Attack
   asmdef is now compile-excluded, and the Stylized Water 2 asmdef is
   compile-included.
4. **Hit Play.** Done.

No bake-side change. No JSON-schema bump. No regenerated tile metadata.

---

## 5. Capability detection

### 5.1 `BackendBootstrap.SelectActive()` pseudocode

```csharp
namespace VeilBreakers.Rendering.Backends
{
    public sealed class BackendBootstrap
    {
        public IWaterBackend SelectWater(WaterSurfaceManifest manifest)
        {
            var available = new List<IWaterBackend>();
#if VB_WATER_BOAT_ATTACK
            available.Add(new BoatAttackWaterBackend());
#endif
#if VB_WATER_STYLIZED_2
            available.Add(new StylizedWater2Backend());
#endif
#if VB_WATER_CREST_5
            available.Add(new Crest5Backend());
#endif
            return PickBestMatch(available, manifest.backend, manifest.upgrade_compat);
        }

        public ISkyBackend SelectSky(SkyManifest manifest)
        {
            var available = new List<ISkyBackend>();
#if VB_SKY_SKYBOX_CUBEMAP
            available.Add(new SkyboxCubemapBackend());
#endif
#if VB_SKY_VOLUME_CLOUD_URP
            available.Add(new VolumeCloudURPBackend());
#endif
#if VB_SKY_VOLUMETRIC_CLOUDS_NATIVE
            available.Add(new VolumetricCloudsNativeBackend());
#endif
            return PickBestMatch(available, manifest.backend, manifest.upgrade_compat);
        }

        public IFogBackend SelectFog(AtmosphericManifest manifest)
        {
            var available = new List<IFogBackend>();
#if VB_FOG_URP_FOG_VOLUME
            available.Add(new URPFogVolumeBackend());
#endif
#if VB_FOG_ATMOSPHERIC_HEIGHT_FOG
            available.Add(new AtmosphericHeightFogBackend());
#endif
#if VB_FOG_VOLUMETRIC_FOG_NATIVE
            available.Add(new VolumetricFogNativeBackend());
#endif
            return PickBestMatch(available, manifest.backend, manifest.upgrade_compat);
        }

        public IUpscalerBackend SelectUpscaler(UpscalerManifest manifest)
        {
            var available = new List<IUpscalerBackend>();
#if VB_UPSCALER_STP_1_0
            // v1.0 ship default. URP 17.3 native; motion-vector-driven temporal upscaler.
            // Construct first, THEN call IsSupportedOnThisGPU() — instance method,
            // consults fields populated in the constructor.
            var stp = new STP10UpscalerBackend();
            if (stp.IsSupportedOnThisGPU())
                available.Add(stp);
#endif
#if VB_UPSCALER_FSR_1_0
            // v1.0 spatial fallback (URP 17.3 native).
            var fsr1 = new FSR10UpscalerBackend();
            if (fsr1.IsSupportedOnThisGPU())
                available.Add(fsr1);
#endif
#if VB_UPSCALER_FSR_3_1
            // v1.1 swap (FSR3-Unity-URP package).
            var fsr3 = new FSR31UpscalerBackend();
            if (fsr3.IsSupportedOnThisGPU())
                available.Add(fsr3);
#endif
#if VB_UPSCALER_DLSS_4_5
            // v1.1 swap (NGX SDK URP port — see §6.4 [V1.1 DEFERRED] banner).
            var dlss = new DLSS45UpscalerBackend();
            if (dlss.IsSupportedOnThisGPU())
                available.Add(dlss);
#endif
            available.Add(new OffUpscalerBackend());      // always available

            return PickBestMatch(available, manifest.backend, manifest.upgrade_compat);
        }

        // Pick first available matching manifest preference; fall back through
        // upgrade_compat[] in order; finally fall back to any available backend.
        // T : IBackend — no `dynamic`, no runtime reflection, AOT/IL2CPP-safe.
        private static T PickBestMatch<T>(List<T> available, string preferred, string[] fallbackChain)
            where T : IBackend
        {
            // 1. Exact match on preferred.
            foreach (var b in available)
                if (b.BackendId == preferred && b.IsAvailable)
                    return b;

            // 2. Walk upgrade_compat in declared order.
            foreach (var fallbackId in fallbackChain)
                foreach (var b in available)
                    if (b.BackendId == fallbackId && b.IsAvailable)
                        return b;

            // 3. Last resort — any available.
            foreach (var b in available)
                if (b.IsAvailable)
                    return b;

            throw new InvalidOperationException(
                $"No available backend for slot; preferred='{preferred}', fallback=[{string.Join(",", fallbackChain)}]");
        }
    }
}
```

### 5.2 Selection precedence

1. **Manifest preferred backend** (`manifest.backend`) — bake's first choice.
2. **`manifest.upgrade_compat[]` in declared order** — bake's pre-approved
   substitutes.
3. **Any available backend** in the slot — last-resort safety net.
4. **Throw `InvalidOperationException`** — fail loud if even the safety
   net is empty.

The bake side guarantees `upgrade_compat[]` lists only swap candidates that
are visually-and-functionally close enough to be acceptable substitutes.
Order matters: closer-substitute first.

---

## 6. Upgrade migration guides

Each subsection walks one full backend swap. **Every guide assumes zero
bake-side changes** — that is the entire point of the abstraction.

### 6.1 Boat Attack → Stylized Water 2

- **Estimated effort:** 1 engineer-day. New asmdef, port `IWaterBackend`
  methods to Stylized Water 2's `WaterObject` API, hand-tune wave preset
  to match `wave_amplitude_m` / `wave_period_s` ranges.
- **Expected visual delta:** softer, more stylized foam edges; better
  shore wetness; simpler caustics.
- **Manifest changes:** none. `wave_amplitude_m`, `wave_period_s`,
  `foam_threshold_normalized` map directly. `caustics_intensity` maps to
  Stylized Water 2's `causticsStrength` slider.
- **Rollback:** flip the define symbol back to `VB_WATER_BOAT_ATTACK`.
  No data migration. The bake-side manifest is identical.

### 6.2 Skybox Cubemap → Volume Cloud URP

- **Estimated effort:** 2 engineer-days. New asmdef wraps Volume Cloud
  URP's `VolumeCloudComponent`. `cloud_density` field (currently `0.0`
  in v1.0) drives the asset's density slider.
- **Expected visual delta:** dramatic — moving volumetric clouds, soft
  shadows on terrain, atmospheric depth. Largest single-feature visual
  upgrade in v1.1.
- **Manifest changes:** none. `cloud_density` is already in the schema
  and ignored by the v1.0 cubemap backend.
- **Rollback:** flip `VB_SKY_VOLUME_CLOUD_URP` back to
  `VB_SKY_SKYBOX_CUBEMAP`. The cubemap path is still present in the
  manifest and resumes driving sky reflection.

### 6.3 URP Fog Volume → Atmospheric Height Fog

- **Estimated effort:** 1 engineer-day. New asmdef wraps Atmospheric
  Height Fog's volume override. `height_density_curve` keyframes are
  remapped onto the asset's `densityFalloff` curve.
- **Expected visual delta:** light scattering through fog (god rays),
  smoother altitude falloff, better hero-shot composition.
- **Manifest changes:** none. The curve schema is the same.
  `wind_direction_xyz` already drives both backends.
- **Rollback:** flip `VB_FOG_ATMOSPHERIC_HEIGHT_FOG` back to
  `VB_FOG_URP_FOG_VOLUME`. v1.0 fog cards continue to provide hero
  pockets unchanged.

### 6.4 STP 1.0 → DLSS 4.5 (via NGX) `[V1.1 DEFERRED — gated on Unity NGX package or community wrapper]`

> **Banner.** As of URP 17.3 there is no official Unity NGX SDK package
> and no stable community wrapper that ships an NGX binding for URP.
> This walkthrough is **not executable today** — it is preserved for
> future readers as a recipe for the v1.1 swap once a Unity NGX package
> ships. Per §9, NGX SDK URP integration is explicitly out of scope for
> v1.0. Selecting `dlss_4_5` in the manifest is rejected by the runtime
> as `not yet implemented` until this banner is removed.

- **Estimated effort (when unblocked):** 3 engineer-days. New asmdef
  wraps NVIDIA NGX SDK binding (waiting on Unity package availability —
  see §9). Quality preset string (`"balanced"` etc.) maps directly to
  NGX's `NVSDK_NGX_PerfQuality_Value`.
- **Expected visual delta:** sharper temporal detail at the same
  internal resolution; slight VRAM increase (mitigated because we're not
  swapping the hardware target). NVIDIA-only.
- **Manifest changes:** none. `quality` and `mip_bias` map directly.
- **Rollback:** flip `VB_UPSCALER_DLSS_4_5` off; the v1.0 default
  (`VB_UPSCALER_STP_1_0`) and fallback (`VB_UPSCALER_FSR_1_0`) remain
  active because all four upscaler define symbols can coexist and the
  bootstrap selects via the manifest preference order +
  `IsSupportedOnThisGPU()`.

---

## 7. Schema versioning policy

The manifest schema follows a **semver-like rule** owned by the bake
side:

- **Minor bump** (`1.0` → `1.1`): additive fields only. Runtime tolerates
  unknown new fields by ignoring them.
- **Major bump** (`1.0` → `2.0`): breaking changes. Runtime hard-fails on
  major mismatch with a clear error message naming the offending section.
- **Forward-compat:** runtime ignores fields it does not recognize.
- **Backward-compat:** runtime defaults missing fields per the bake-side
  `@dataclass` defaults declared in `terrain_unity_backends.py`.
- **Per-section versions:** each of the four sub-manifests
  (`water`, `sky`, `atmospheric`, `upscaler`) carries an independent
  `schema_version`. The four backends evolve out-of-step.
- **The bake side OWNS the schema version. The runtime side READS only.**
- **`[FUTURE]` backend IDs are valid manifest values** — `hand_authored_urp`
  (water), `volumetric_clouds_native` (sky), `volumetric_fog_native`
  (atmospheric), and `dlss_4_5` (upscaler, NGX-gated per §6.4) all parse
  cleanly through `from_dict()` round-trip and are accepted in
  `upgrade_compat[]` arrays. Runtime SHOULD reject them at backend-bind
  time with a clear `BackendNotImplementedException("backend_id not yet
  implemented as of v1.0; reserved for v1.1+")` message naming the
  manifest section and offending ID. They MUST NOT trigger a schema
  major-bump. As each `[FUTURE]` ID's adapter ships, the rejection is
  removed without a schema bump.

Any runtime change that requires a schema-version bump is a design
mistake — the abstraction has leaked. File a P0 fix to push the change
back into the bake side or into the adapter, never the schema.

---

## 8. Test strategy

### 8.1 Bake-side (Python, in this repo)

The Phase D1 companion PR will add
`veilbreakers_terrain/tests/test_phase_d1_urp_manifest_schema.py` (not yet
present on this branch) pinning:

- manifest dataclass round-trips (write → JSON → read → equal).
- `upgrade_compat` arrays are non-empty and contain only canonical
  backend IDs.
- `schema_version` strings match the per-section dataclasses.
- Required fields are present after default construction.
- Determinism: same seeded scene → byte-identical manifest JSON.

### 8.2 Unity-side (C#, deferred to scene-build phase)

- C# unit tests using **NSubstitute** on each interface — verify each
  concrete adapter calls the expected underlying-asset API methods given
  a specific manifest input.
- **Integration tests** against scene fixtures — load a known scene,
  apply a known manifest, render to RT, compare against a golden image
  (within a perceptual tolerance).
- **Capability-detection tests** — mock GPU caps, verify
  `BackendBootstrap.SelectUpscaler` picks DLSS on NVIDIA, FSR on AMD,
  STP on Intel, and falls back to Off on unknown vendors.

---

## 9. Out of scope for v1.0 ship

The following are explicitly NOT delivered in v1.0 and have no blocking
effect on ship:

- **C# implementations of each backend.** Deferred to the Unity
  scene-build phase. v1.0 bake produces a manifest that v1.0 Unity reads
  with stub adapters that no-op cleanly when the scene has no water /
  sky-cloud / volumetric-fog content.
- **Custom DLSS NGX SDK port.** Waiting on either an official Unity
  package or a stable community wrapper (see §6.4 [V1.1 DEFERRED]
  banner). v1.0 ships **STP 1.0** as the primary upscaler with **FSR 1.0**
  as the in-the-box spatial fallback — both URP 17.3 native, both FREE.
  FSR 3.1 (FSR3-Unity-URP package) is a separate v1.1 swap, not the v1.0
  default.
- **Volumetric clouds asset purchase.** Cubemap is sufficient for the
  v1.0 mood-board target. v1.1 budget covers the asset.
- **Real-time time-of-day blending.** v1.0 uses discrete TOD keyframes
  per scene. The `time_of_day_hour` field in the manifest is forward-
  compatible with a v1.1 TOD blender.
- **HDRP fallback path.** Project committed to URP-only. There is no
  HDRP backend in any of the four slots and there will not be one in
  any v1.x release.

---

## 10. References

- `project_urp_commitment_2026_05_07` — **user-memory note** (not in repo)
  locking the URP 17.3 v1.0 commitment, including the 6-agent fleet audit
  and Unity batch-mode setup verification. Stored in the author's
  Claude-memory store, not under version control.
- `docs/IMPLEMENTATION_FIX_GUIDE_2026_05_07_FINAL.md` — **rewritten for URP**
  via Phase D2 PR #50 merge `694409e` (2026-05-08T15:16:24Z). §X URP
  Backend Abstraction now mirrors this doc's interface contract; §17.4
  Phase D plan now points at the canonical define-symbol set
  (`VB_SKY_SKYBOX_CUBEMAP`, `VB_FOG_URP_FOG_VOLUME`, `VB_UPSCALER_STP_1_0`,
  `VB_UPSCALER_FSR_1_0`). Use the guide for the 60-day plan and §X for
  the high-level abstraction; this doc remains the authority for asmdef
  layout, capability detection, schema versioning, and ScriptableObject
  field schemas.
- `veilbreakers_terrain/handlers/terrain_unity_backends.py` —
  **landed via Phase D1 PR #49** merge `e97ae1c` (2026-05-08T14:25:11Z).
  Bake-side `@dataclass` definitions for `WaterSurfaceManifest`,
  `SkyManifest`, `AtmosphericManifest`, `UpscalerManifest`,
  `UnityExportConfig`, plus `build_unity_urp_manifest_section`. Pinned
  by `test_phase_d1_urp_manifest_schema.py`.
- `project_hardware_8gb_vram_2026_05_07` — **user-memory note** (not in
  repo) documenting the 8 GB VRAM hard constraint that drove the URP
  commitment. The default-upscaler choice it records as
  "FSR-3.1-default" is **superseded** by the corrected v1.0 choice
  (STP 1.0 primary + FSR 1.0 fallback, both URP 17.3 native) — see §2.4
  and §6.4 in this doc.
- **URP 6000.0 manual > Universal Render Pipeline Asset > Quality >
  Upscaling Filter** — official source enumerating the in-box dropdown
  options (Automatic / Bilinear / Nearest-Neighbor / FSR 1.0 / STP 1.0).
  Confirms FSR 3.1 and DLSS are NOT in-box and require external packages
  (FSR3-Unity-URP for FSR 3.1, NGX SDK URP port for DLSS).
