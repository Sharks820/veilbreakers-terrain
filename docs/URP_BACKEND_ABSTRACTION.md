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
- Stylized Water 2 (paid asset, ~$45) — better stylized look for v1.1.
- Crest 5 (free / paid tiers) — full ocean simulation when v1.2 needs it.
- Hand-authored URP shader — last-resort if licensing or perf forces it.

**C# interface contract:**

```csharp
namespace VeilBreakers.Rendering.Backends
{
    public interface IWaterBackend : IBackend
    {
        // BackendId is one of: "boat_attack" / "stylized_water_2" / "crest_5" / "hand_authored_urp"
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
- Volume Cloud URP (paid asset) — drop-in volumetric clouds for v1.1.
- Volumetric Clouds Native (URP) — when Unity ships the native module
  outside the HDRP-only fence currently locking it.

**C# interface contract:**

```csharp
namespace VeilBreakers.Rendering.Backends
{
    public interface ISkyBackend : IBackend
    {
        // BackendId is one of: "skybox_cubemap" / "volume_cloud_urp" / "volumetric_clouds_native"
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
- Atmospheric Height Fog (paid asset) — proper height-fog with light
  scattering for v1.1.
- Volumetric Fog Native (URP) — when Unity ships the native volumetric
  module on URP, parity with HDRP.

**C# interface contract:**

```csharp
namespace VeilBreakers.Rendering.Backends
{
    public interface IFogBackend : IBackend
    {
        // BackendId is one of: "urp_fog_volume_plus_cards" / "atmospheric_height_fog" / "volumetric_fog_native"
        void ApplyManifest(AtmosphericManifest manifest);
        void SetHeightDensityCurve(AnimationCurve curve);   // y in [0..1]; x = world meters
        void SetFogColorRamp(Texture2D ramp);
        void SetWindDirection(Vector3 windXYZ);
    }
}
```

### 2.4 `IUpscalerBackend`

**Today's implementation (v1.0 ship):** AMD FSR 3.1 (FREE, vendor-neutral,
ships in URP 17.3 out of the box). Used at "balanced" quality to recover
8 GB VRAM headroom on the 4060 Ti baseline target.

**Future swap candidates:**
- DLSS 4.5 — needs NVIDIA NGX SDK port; gated on Unity package availability.
- STP (Spatio-Temporal Post-processing) — Unity native temporal upscaler
  when stable.
- Off — explicit no-upscale path for QA, screenshots, AAA-quality stills.

**C# interface contract:**

```csharp
namespace VeilBreakers.Rendering.Backends
{
    public interface IUpscalerBackend : IBackend
    {
        // BackendId is one of: "fsr_3_1" / "dlss_4_5" / "stp_native" / "off"
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
    "backend": "fsr_3_1",
    "quality": "balanced",
    "mip_bias": -1.0,
    "upgrade_compat": ["dlss_4_5", "stp_native", "off"]
  }
}
```

This schema **will** have matching `@dataclass` definitions on the bake side
at `veilbreakers_terrain/handlers/terrain_unity_backends.py` once the
**Phase D1 companion PR** lands (this is the Phase D3 design spec — D1 is
the bake-side implementation that mirrors the schema in Python):

- `WaterSurfaceManifest`
- `SkyManifest`
- `AtmosphericManifest`
- `UpscalerManifest`

> **Pending prerequisite.** As of this commit, `terrain_unity_backends.py`
> does not yet exist on this branch. Phase D1 introduces it; this Phase D3
> doc is the canonical schema specification it must conform to. Until D1
> merges, the JSON above is the single source of truth.

The bake side OWNS the schema. The runtime side is read-only.

---

## 4. Asmdef + define-symbol architecture

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
    ├── FSR31/
    │   ├── VeilBreakers.Rendering.Upscaler.FSR31.asmdef
    │   │   (defineConstraints: VB_UPSCALER_FSR_3_1)
    │   └── FSR31UpscalerBackend.cs
    ├── DLSS/
    │   ├── VeilBreakers.Rendering.Upscaler.DLSS.asmdef
    │   │   (defineConstraints: VB_UPSCALER_DLSS)
    │   └── DLSSUpscalerBackend.cs
    ├── STP/
    │   ├── VeilBreakers.Rendering.Upscaler.STP.asmdef
    │   │   (defineConstraints: VB_UPSCALER_STP)
    │   └── STPUpscalerBackend.cs
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

| Slot     | v1.0 active symbol         | v1.1 candidate symbols                                |
|----------|----------------------------|-------------------------------------------------------|
| Water    | `VB_WATER_BOAT_ATTACK`     | `VB_WATER_STYLIZED_2`, `VB_WATER_CREST_5`             |
| Sky      | `VB_SKY_SKYBOX_CUBEMAP`    | `VB_SKY_VOLUME_CLOUD_URP`, `VB_SKY_VOLUMETRIC_CLOUDS_NATIVE` |
| Fog      | `VB_FOG_URP_FOG_VOLUME`    | `VB_FOG_ATMOSPHERIC_HEIGHT_FOG`, `VB_FOG_VOLUMETRIC_FOG_NATIVE` |
| Upscaler | `VB_UPSCALER_FSR_3_1`      | `VB_UPSCALER_DLSS`, `VB_UPSCALER_STP`                 |

**Exactly one** Water / Sky / Fog symbol is active at a time. **Multiple**
upscaler symbols MAY be active simultaneously (DLSS available alongside FSR
on NVIDIA hardware) — the bootstrap chooses at runtime via `IsSupportedOnThisGPU()`.

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
#if VB_UPSCALER_DLSS
            // Construct first, THEN call the instance method — IsSupportedOnThisGPU()
            // consults fields populated in the constructor (NGX init handle, etc.).
            var dlss = new DLSSUpscalerBackend();
            if (dlss.IsSupportedOnThisGPU())
                available.Add(dlss);
#endif
#if VB_UPSCALER_FSR_3_1
            var fsr = new FSR31UpscalerBackend();
            if (fsr.IsSupportedOnThisGPU())
                available.Add(fsr);
#endif
#if VB_UPSCALER_STP
            var stp = new STPUpscalerBackend();
            if (stp.IsSupportedOnThisGPU())
                available.Add(stp);
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

### 6.4 FSR 3.1 → DLSS 4.5 (via NGX)

- **Estimated effort:** 3 engineer-days. New asmdef wraps NVIDIA NGX SDK
  binding (waiting on Unity package availability — see §9). Quality
  preset string (`"balanced"` etc.) maps directly to NGX's
  `NVSDK_NGX_PerfQuality_Value`.
- **Expected visual delta:** sharper temporal detail at the same
  internal resolution; slight VRAM increase (mitigated because we're not
  swapping the hardware target). NVIDIA-only.
- **Manifest changes:** none. `quality` and `mip_bias` map directly.
- **Rollback:** flip `VB_UPSCALER_DLSS` off; FSR 3.1 remains active
  because both define symbols can coexist and the bootstrap selects via
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
  package or a stable community wrapper. v1.0 ships FSR 3.1 only.
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
- `docs/IMPLEMENTATION_FIX_GUIDE_2026_05_07_FINAL.md` — **partially stale.**
  Use ONLY for: (a) hardware/VRAM analysis, (b) the AAA-quality bar
  rationale. **IGNORE** every HDRP-tied section (MicroSplat HDRP,
  WaterSurface, DXR/HDRP volumetrics, etc.) — those are superseded by
  this URP spec. The guide has not yet been rewritten for the URP
  commitment; this doc is the new authority for the rendering-stack
  decision.
- `veilbreakers_terrain/handlers/terrain_unity_backends.py` —
  **pending prerequisite.** Phase D1 companion PR will add the bake-side
  `@dataclass` definitions for `WaterSurfaceManifest`, `SkyManifest`,
  `AtmosphericManifest`, `UpscalerManifest`. Not present on this branch.
- `project_hardware_8gb_vram_2026_05_07` — **user-memory note** (not in
  repo) documenting the 8 GB VRAM hard constraint that drove the URP
  commitment and the FSR-3.1-default-upscaler choice.
