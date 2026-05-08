"""Phase D1 — backend-agnostic URP manifest dataclasses.

This module defines the bake-side schema for Unity URP runtime backends.  The
bake writes manifests using these versioned dataclasses; runtime adapters in
the Unity C# project translate the manifest fields into backend-specific
parameters (Boat Attack water material, skybox cubemap, FSR 3.1 upscaler, etc).

Plug-and-play architecture:

  * Each manifest carries a ``schema_version`` and a ``backend`` selector plus
    an ``upgrade_compat`` tuple listing other backends whose adapter can
    consume the same fields.  Swapping water from Boat Attack to Stylized
    Water 2 needs only a new C# adapter — no bake-side or schema changes.
  * The fields chosen are the **intersection** of features supported by the
    candidate backends, so any compatible backend can ingest the manifest
    without losing critical data.  Backend-specific extras (e.g. Crest 5
    spectrum parameters) are out of scope for the bake-side schema and live
    in the runtime adapter as backend defaults.

Phase D1 of the §17 60-day plan locks four FREE URP-default backends:

  ============  =====================  =========================================
  Slot          Default backend        Compatible alternates (upgrade_compat)
  ============  =====================  =========================================
  water         boat_attack            stylized_water_2, crest_5, hand_authored_urp
  sky           skybox_cubemap         volume_cloud_urp, volumetric_clouds_native
  fog           urp_fog_volume_plus_   atmospheric_height_fog,
                cards                  volumetric_fog_native
  upscaler      fsr_3_1                dlss_4_5, stp_native, off
  ============  =====================  =========================================
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Dict, Tuple


# ---------------------------------------------------------------------------
# WaterSurfaceManifest
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WaterSurfaceManifest:
    """Backend-agnostic water surface manifest.

    Fields are the intersection of Boat Attack, Stylized Water 2, Crest 5,
    and a hand-authored URP shader graph.  Each backend's runtime adapter
    consumes this manifest and maps fields onto its own material exposed
    properties.
    """

    schema_version: str = "1.0"
    backend: str = "boat_attack"
    elevation_m: float = 0.0
    wave_amplitude_m: float = 0.5
    wave_period_s: float = 4.0
    foam_threshold_normalized: float = 0.3
    caustics_intensity: float = 0.5
    shore_reaction_enabled: bool = True
    upgrade_compat: Tuple[str, ...] = (
        "stylized_water_2",
        "crest_5",
        "hand_authored_urp",
    )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-safe dict (tuples become lists)."""
        return {
            "schema_version": self.schema_version,
            "backend": self.backend,
            "elevation_m": float(self.elevation_m),
            "wave_amplitude_m": float(self.wave_amplitude_m),
            "wave_period_s": float(self.wave_period_s),
            "foam_threshold_normalized": float(self.foam_threshold_normalized),
            "caustics_intensity": float(self.caustics_intensity),
            "shore_reaction_enabled": bool(self.shore_reaction_enabled),
            "upgrade_compat": list(self.upgrade_compat),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "WaterSurfaceManifest":
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        return cls(
            schema_version=str(d.get("schema_version", "1.0")),
            backend=str(d.get("backend", "boat_attack")),
            elevation_m=float(d.get("elevation_m", 0.0)),
            wave_amplitude_m=float(d.get("wave_amplitude_m", 0.5)),
            wave_period_s=float(d.get("wave_period_s", 4.0)),
            foam_threshold_normalized=float(d.get("foam_threshold_normalized", 0.3)),
            caustics_intensity=float(d.get("caustics_intensity", 0.5)),
            shore_reaction_enabled=bool(d.get("shore_reaction_enabled", True)),
            upgrade_compat=tuple(
                str(x) for x in d.get(
                    "upgrade_compat",
                    ("stylized_water_2", "crest_5", "hand_authored_urp"),
                )
            ),
        )


# ---------------------------------------------------------------------------
# SkyManifest
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SkyManifest:
    """Backend-agnostic sky manifest.

    Fields are the intersection of skybox cubemap, URP volumetric cloud
    component (Volume Cloud URP), and the native URP 17 volumetric cloud
    pass.  ``cloud_density`` is 0 for cubemap backends and >0 for
    volumetric cloud backends; the runtime adapter is responsible for
    mapping non-zero density to its preferred volumetric noise.
    """

    schema_version: str = "1.0"
    backend: str = "skybox_cubemap"
    cubemap_path: str = ""
    time_of_day_hour: float = 14.0
    sun_rotation_quat: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    cloud_density: float = 0.0
    upgrade_compat: Tuple[str, ...] = (
        "volume_cloud_urp",
        "volumetric_clouds_native",
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "backend": self.backend,
            "cubemap_path": str(self.cubemap_path),
            "time_of_day_hour": float(self.time_of_day_hour),
            "sun_rotation_quat": list(self.sun_rotation_quat),
            "cloud_density": float(self.cloud_density),
            "upgrade_compat": list(self.upgrade_compat),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SkyManifest":
        quat = d.get("sun_rotation_quat", (0.0, 0.0, 0.0, 1.0))
        quat_tuple: Tuple[float, float, float, float] = (
            float(quat[0]),
            float(quat[1]),
            float(quat[2]),
            float(quat[3]),
        )
        return cls(
            schema_version=str(d.get("schema_version", "1.0")),
            backend=str(d.get("backend", "skybox_cubemap")),
            cubemap_path=str(d.get("cubemap_path", "")),
            time_of_day_hour=float(d.get("time_of_day_hour", 14.0)),
            sun_rotation_quat=quat_tuple,
            cloud_density=float(d.get("cloud_density", 0.0)),
            upgrade_compat=tuple(
                str(x) for x in d.get(
                    "upgrade_compat",
                    ("volume_cloud_urp", "volumetric_clouds_native"),
                )
            ),
        )


# ---------------------------------------------------------------------------
# AtmosphericManifest
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AtmosphericManifest:
    """Backend-agnostic atmospheric (fog) manifest.

    ``height_density_curve`` is a list of (altitude_m, density) breakpoints
    that the runtime adapter samples to drive the URP Fog Volume override
    or an Atmospheric Height Fog billboard pass.  ``fog_color_ramp_path``
    is an optional reference to a 1D LUT texture asset baked separately.
    """

    schema_version: str = "1.0"
    backend: str = "urp_fog_volume_plus_cards"
    height_density_curve: Tuple[Tuple[float, float], ...] = (
        (0.0, 0.8),
        (50.0, 0.4),
        (200.0, 0.05),
    )
    fog_color_ramp_path: str = ""
    wind_direction_xyz: Tuple[float, float, float] = (0.7, 0.0, 0.7)
    upgrade_compat: Tuple[str, ...] = (
        "atmospheric_height_fog",
        "volumetric_fog_native",
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "backend": self.backend,
            "height_density_curve": [
                [float(altitude), float(density)]
                for altitude, density in self.height_density_curve
            ],
            "fog_color_ramp_path": str(self.fog_color_ramp_path),
            "wind_direction_xyz": list(self.wind_direction_xyz),
            "upgrade_compat": list(self.upgrade_compat),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AtmosphericManifest":
        curve_raw = d.get(
            "height_density_curve",
            [[0.0, 0.8], [50.0, 0.4], [200.0, 0.05]],
        )
        curve_tuple: Tuple[Tuple[float, float], ...] = tuple(
            (float(point[0]), float(point[1])) for point in curve_raw
        )
        wind = d.get("wind_direction_xyz", (0.7, 0.0, 0.7))
        wind_tuple: Tuple[float, float, float] = (
            float(wind[0]),
            float(wind[1]),
            float(wind[2]),
        )
        return cls(
            schema_version=str(d.get("schema_version", "1.0")),
            backend=str(d.get("backend", "urp_fog_volume_plus_cards")),
            height_density_curve=curve_tuple,
            fog_color_ramp_path=str(d.get("fog_color_ramp_path", "")),
            wind_direction_xyz=wind_tuple,
            upgrade_compat=tuple(
                str(x) for x in d.get(
                    "upgrade_compat",
                    ("atmospheric_height_fog", "volumetric_fog_native"),
                )
            ),
        )


# ---------------------------------------------------------------------------
# UpscalerManifest
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UpscalerManifest:
    """Backend-agnostic upscaler manifest.

    ``quality`` is one of ``off, performance, balanced, quality, native``.
    ``mip_bias`` matches the FSR / DLSS recommendation of -1.0 to keep
    texture detail crisp under upscaling.  Runtime adapters translate the
    quality string to backend-specific render-scale ratios (FSR 3.1 native
    AA = 1.0, balanced = 0.59, etc).
    """

    schema_version: str = "1.0"
    backend: str = "fsr_3_1"
    quality: str = "balanced"
    mip_bias: float = -1.0
    upgrade_compat: Tuple[str, ...] = (
        "dlss_4_5",
        "stp_native",
        "off",
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "backend": self.backend,
            "quality": str(self.quality),
            "mip_bias": float(self.mip_bias),
            "upgrade_compat": list(self.upgrade_compat),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "UpscalerManifest":
        return cls(
            schema_version=str(d.get("schema_version", "1.0")),
            backend=str(d.get("backend", "fsr_3_1")),
            quality=str(d.get("quality", "balanced")),
            mip_bias=float(d.get("mip_bias", -1.0)),
            upgrade_compat=tuple(
                str(x) for x in d.get(
                    "upgrade_compat",
                    ("dlss_4_5", "stp_native", "off"),
                )
            ),
        )


# ---------------------------------------------------------------------------
# UnityExportConfig
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UnityExportConfig:
    """Bake-side configuration knobs for the Unity URP export.

    Two preset profiles are exposed:
      * :attr:`DEFAULT` — 8 GB shipping config (4 splat layers, FREE URP
        backends).
      * :attr:`AAA_16GB` — v1.1 16 GB AAA upgrade profile (8 splat layers,
        same FREE URP backends — backend swaps are independent of the
        splatmap layer cap).
    """

    schema_version: str = "1.0"
    render_pipeline: str = "URP"
    render_pipeline_version: str = "17.3"

    # Splatmap layer cap (Unity Terrain RGBA splatmap textures hold 4
    # layers each; 8 GB ship locks effective layers per pixel to 4).
    splatmap_max_layers: int = 4

    # Backend selection — bake-time defaults.  Runtime can pick different
    # backends as long as they accept the same manifest fields (see
    # ``upgrade_compat`` arrays on each manifest dataclass).
    water_backend: str = "boat_attack"
    sky_backend: str = "skybox_cubemap"
    fog_backend: str = "urp_fog_volume_plus_cards"
    upscaler_backend: str = "fsr_3_1"

    # Legacy: emit hdrp_mask_map.raw alongside material_mask_map.raw so
    # existing Unity scenes that still read the old filename keep working.
    legacy_hdrp_filename: bool = False

    # Class-level preset slots — populated below the class definition so
    # they share the same dataclass type without becoming dataclass fields.
    # Using ClassVar tells both the dataclass machinery and pyright that
    # these are class attributes, not instance fields.
    DEFAULT: ClassVar["UnityExportConfig"]
    AAA_16GB: ClassVar["UnityExportConfig"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "render_pipeline": self.render_pipeline,
            "render_pipeline_version": self.render_pipeline_version,
            "splatmap_max_layers": int(self.splatmap_max_layers),
            "water_backend": self.water_backend,
            "sky_backend": self.sky_backend,
            "fog_backend": self.fog_backend,
            "upscaler_backend": self.upscaler_backend,
            "legacy_hdrp_filename": bool(self.legacy_hdrp_filename),
        }


# Module-level preset constants — assigned to the class via setattr because
# ``frozen=True`` dataclasses forbid in-class default-value mutation, but
# the ``ClassVar`` declarations above tell pyright the attributes exist.
# Public access is ``UnityExportConfig.DEFAULT`` and ``UnityExportConfig.AAA_16GB``.
UnityExportConfig.DEFAULT = UnityExportConfig()
UnityExportConfig.AAA_16GB = UnityExportConfig(splatmap_max_layers=8)


def build_unity_urp_manifest_section(
    *,
    config: UnityExportConfig | None = None,
    water: WaterSurfaceManifest | None = None,
    sky: SkyManifest | None = None,
    atmospheric: AtmosphericManifest | None = None,
    upscaler: UpscalerManifest | None = None,
) -> Dict[str, Any]:
    """Assemble the ``unity_urp`` manifest section.

    Each backend slot defaults to its FREE URP option when the caller does
    not supply an override.  ``config`` controls the render-pipeline header
    fields; defaults to :attr:`UnityExportConfig.DEFAULT`.
    """
    cfg = config if config is not None else UnityExportConfig()
    water_m = water if water is not None else WaterSurfaceManifest(backend=cfg.water_backend)
    sky_m = sky if sky is not None else SkyManifest(backend=cfg.sky_backend)
    atmospheric_m = (
        atmospheric if atmospheric is not None
        else AtmosphericManifest(backend=cfg.fog_backend)
    )
    upscaler_m = (
        upscaler if upscaler is not None
        else UpscalerManifest(backend=cfg.upscaler_backend)
    )
    return {
        "schema_version": cfg.schema_version,
        "render_pipeline": {
            "type": cfg.render_pipeline,
            "version": cfg.render_pipeline_version,
        },
        "water": water_m.to_dict(),
        "sky": sky_m.to_dict(),
        "atmospheric": atmospheric_m.to_dict(),
        "upscaler": upscaler_m.to_dict(),
    }


__all__ = [
    "WaterSurfaceManifest",
    "SkyManifest",
    "AtmosphericManifest",
    "UpscalerManifest",
    "UnityExportConfig",
    "build_unity_urp_manifest_section",
]
