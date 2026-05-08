"""Phase D1 — backend-agnostic URP manifest dataclasses.

This module defines the bake-side schema for Unity URP runtime backends.  The
bake writes manifests using these versioned dataclasses; runtime adapters in
the Unity C# project translate the manifest fields into backend-specific
parameters (Boat Attack water material, skybox cubemap, STP 1.0 upscaler, etc).

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
  sky           skybox_cubemap         volume_cloud_urp
  fog           urp_fog_volume_plus_   atmospheric_height_fog
                cards
  upscaler      stp_1_0                fsr_3_1, fsr_1_0, dlss_4_5, off
  ============  =====================  =========================================

  The ``upscaler`` row's alternates are listed in **substitution priority
  order** (highest-quality replacement first) — this matches the pinned
  ``UpscalerManifest.upgrade_compat`` default and the per-slot canonical
  alt ordering used by ``build_unity_urp_manifest_section`` (Codex review
  fix on Hardening PR B).

Hardening PR B (2026-05-08): Default upscaler changed from ``fsr_3_1`` (which
is an external ``FSR3-Unity-URP`` package) to ``stp_1_0``, which ships
natively with URP 17.3.  ``volumetric_clouds_native`` and
``volumetric_fog_native`` were dropped from upgrade_compat because URP has no
roadmap for native volumetric anything as of 17.3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, Tuple


# ---------------------------------------------------------------------------
# BACKEND_REGISTRY (Hardening PR B Fix #2 — V2 finding)
# ---------------------------------------------------------------------------
# Module-level constants enumerate every backend string a manifest's
# ``backend`` field or ``upgrade_compat`` entry may legitimately hold.  Each
# manifest's ``__post_init__`` validates against the matching registry tuple.

WATER_BACKENDS: tuple[str, ...] = (
    "boat_attack",
    "stylized_water_2",
    "crest_5",
    "hand_authored_urp",
)
SKY_BACKENDS: tuple[str, ...] = (
    "skybox_cubemap",
    "volume_cloud_urp",
)
FOG_BACKENDS: tuple[str, ...] = (
    "urp_fog_volume_plus_cards",
    "atmospheric_height_fog",
)
UPSCALER_BACKENDS: tuple[str, ...] = (
    "stp_1_0",
    "fsr_1_0",
    "fsr_3_1",
    "dlss_4_5",
    "off",
)

BACKEND_REGISTRY: dict[str, tuple[str, ...]] = {
    "water": WATER_BACKENDS,
    "sky": SKY_BACKENDS,
    "fog": FOG_BACKENDS,
    "upscaler": UPSCALER_BACKENDS,
}


# ---------------------------------------------------------------------------
# Canonical alternate ordering (Codex review fix on Hardening PR B)
# ---------------------------------------------------------------------------
# ``BACKEND_REGISTRY`` orders entries with the bake-time default first
# (``stp_1_0`` before ``fsr_3_1`` for upscalers, etc).  That is correct for
# "what defaults exist" but WRONG for "if I have to substitute, what is the
# next-best choice?".  The registry order would yield
# ``("fsr_1_0", "fsr_3_1", "dlss_4_5", "off")`` for the upscaler slot when
# filtered against the active backend, which contradicts the pinned
# ``UpscalerManifest.upgrade_compat`` default of
# ``("fsr_3_1", "fsr_1_0", "dlss_4_5", "off")``.
#
# Substitution priority is dataclass-pinned per-slot below.  Each tuple is a
# permutation of the matching registry tuple — ``_validate_canonical_alt_order``
# enforces this at module import so the two stay in sync.
CANONICAL_ALT_ORDER: dict[str, tuple[str, ...]] = {
    "water": ("boat_attack", "stylized_water_2", "crest_5", "hand_authored_urp"),
    "sky": ("skybox_cubemap", "volume_cloud_urp"),
    "fog": ("urp_fog_volume_plus_cards", "atmospheric_height_fog"),
    # Substitution priority: highest-quality replacement first.  STP 1.0 is
    # the bake-time default; if it is unavailable at runtime we prefer FSR
    # 3.1 (best image quality), then FSR 1.0 (widest hardware), then DLSS
    # 4.5 (NVIDIA-only), then ``off`` (no upscaling).
    "upscaler": ("stp_1_0", "fsr_3_1", "fsr_1_0", "dlss_4_5", "off"),
}


def _validate_canonical_alt_order() -> None:
    """Assert each ``CANONICAL_ALT_ORDER`` entry is a permutation of the registry.

    Catches typos at import time so a divergence between
    ``BACKEND_REGISTRY`` and ``CANONICAL_ALT_ORDER`` surfaces immediately
    rather than silently producing a manifest whose ``upgrade_compat``
    omits a registered backend.

    CodeRabbit round-2 fix: ``set(canonical) == set(registry)`` would accept
    a tuple with a duplicated backend and no missing values (sets dedup
    silently).  Comparing the multisets via ``sorted(...)`` instead enforces
    true permutation semantics, so a duplicated entry trips the import-time
    guard before it can leak into emitted ``upgrade_compat`` tuples.
    """
    for slot, registry in BACKEND_REGISTRY.items():
        canonical = CANONICAL_ALT_ORDER.get(slot)
        if canonical is None:
            raise RuntimeError(
                f"CANONICAL_ALT_ORDER missing entry for slot {slot!r}; "
                "every BACKEND_REGISTRY slot needs a substitution-priority "
                "ordering."
            )
        if sorted(canonical) != sorted(registry):
            raise RuntimeError(
                f"CANONICAL_ALT_ORDER[{slot!r}] = {canonical!r} is not a "
                f"permutation of BACKEND_REGISTRY[{slot!r}] = {registry!r}; "
                "they must contain exactly the same backend strings with "
                "no duplicates and no omissions."
            )


_validate_canonical_alt_order()


# ---------------------------------------------------------------------------
# Schema version enforcement (Hardening PR B Fix #3 — V2 finding)
# ---------------------------------------------------------------------------
# Bake-side build understands schema_version major v1 only.  Future v2.x
# bakes must explicitly bump _SCHEMA_MAJOR_VERSION here AND every
# corresponding runtime adapter.  Minor bumps (1.0 → 1.99) are silently
# accepted to preserve forward-compat: a bake that reads a 1.99 manifest
# from a future release just reads only the v1.x fields it knows about.

_SCHEMA_MAJOR_VERSION = "1"


def _check_major(version: str) -> None:
    """Raise ValueError if ``version`` major component != ``_SCHEMA_MAJOR_VERSION``.

    Forward-compat is preserved: minor bumps within v1.x are accepted.  A
    leading ``v`` prefix is tolerated so callers may pass either ``"1.0"``
    or ``"v1.0"``.
    """
    cleaned = str(version).lstrip("v")
    major = cleaned.split(".", 1)[0]
    if major != _SCHEMA_MAJOR_VERSION:
        raise ValueError(
            f"manifest schema major mismatch: got v{major}, this build "
            f"understands v{_SCHEMA_MAJOR_VERSION}.x only"
        )


def _validate_backend(slot: str, backend: str) -> None:
    """Validate ``backend`` is in the canonical registry for ``slot``.

    ``slot`` is one of ``water``, ``sky``, ``fog``, ``upscaler``.  Raises
    ValueError on mismatch with the canonical list spelled out for clarity.
    """
    canonical = BACKEND_REGISTRY[slot]
    if backend not in canonical:
        raise ValueError(
            f"{slot} backend {backend!r} not in canonical registry "
            f"{canonical!r}; add to {slot.upper()}_BACKENDS in "
            "terrain_unity_backends.py and register a runtime adapter."
        )


def _validate_upgrade_compat(
    slot: str, backend: str, upgrade_compat: Tuple[str, ...]
) -> None:
    """Validate every upgrade_compat entry against the registry.

    Also rejects self-references (a backend listing itself as an alt is a
    bug — alts are by definition *other* backends).
    """
    canonical = BACKEND_REGISTRY[slot]
    for alt in upgrade_compat:
        if alt not in canonical:
            raise ValueError(
                f"{slot} upgrade_compat entry {alt!r} not in canonical "
                f"registry {canonical!r}"
            )
        if alt == backend:
            raise ValueError(
                f"{slot} upgrade_compat must not list the active backend "
                f"{backend!r} as its own alternate (recursive self-reference)"
            )


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

    def __post_init__(self) -> None:
        # Hardening PR B Fix #2 — V2 finding: validate backend + upgrade_compat
        # at construction time so wrong values die loudly here rather than
        # silently in the runtime adapter on the Unity side.
        #
        # CodeRabbit round-2 fix: ``_check_major`` previously only ran in
        # ``from_dict``; direct construction (e.g. ``WaterSurfaceManifest(
        # schema_version="2.0", ...)``) could bypass the schema-major guard
        # and emit a v2 manifest unchanged.  Validate here too so the write
        # path is closed.
        _check_major(self.schema_version)
        _validate_backend("water", self.backend)
        _validate_upgrade_compat("water", self.backend, self.upgrade_compat)

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
        """Reconstruct from a dict produced by :meth:`to_dict`.

        Hardening PR B Fix #3: rejects manifests whose schema_version's
        major component does not match this build's ``_SCHEMA_MAJOR_VERSION``.
        Minor bumps (1.0 → 1.99) are accepted (forward-compat).
        """
        version = str(d.get("schema_version", "1.0"))
        _check_major(version)
        return cls(
            schema_version=version,
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

    Fields are the intersection of skybox cubemap and the URP volumetric
    cloud component (Volume Cloud URP).  ``cloud_density`` is 0 for cubemap
    backends and >0 for volumetric cloud backends; the runtime adapter is
    responsible for mapping non-zero density to its preferred volumetric
    noise.

    Hardening PR B Fix #9 (V2 + VD finding): ``volumetric_clouds_native``
    was removed from upgrade_compat — URP has no native volumetric cloud
    pass roadmap as of 17.3 (only HDRP does).
    """

    schema_version: str = "1.0"
    backend: str = "skybox_cubemap"
    cubemap_path: str = ""
    time_of_day_hour: float = 14.0
    sun_rotation_quat: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    cloud_density: float = 0.0
    upgrade_compat: Tuple[str, ...] = (
        "volume_cloud_urp",
    )

    def __post_init__(self) -> None:
        # CodeRabbit round-2 fix: enforce schema-major on direct construction
        # too (not only from_dict), closing the write-path hole.
        _check_major(self.schema_version)
        _validate_backend("sky", self.backend)
        _validate_upgrade_compat("sky", self.backend, self.upgrade_compat)

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
        version = str(d.get("schema_version", "1.0"))
        _check_major(version)
        quat = d.get("sun_rotation_quat", (0.0, 0.0, 0.0, 1.0))
        quat_tuple: Tuple[float, float, float, float] = (
            float(quat[0]),
            float(quat[1]),
            float(quat[2]),
            float(quat[3]),
        )
        return cls(
            schema_version=version,
            backend=str(d.get("backend", "skybox_cubemap")),
            cubemap_path=str(d.get("cubemap_path", "")),
            time_of_day_hour=float(d.get("time_of_day_hour", 14.0)),
            sun_rotation_quat=quat_tuple,
            cloud_density=float(d.get("cloud_density", 0.0)),
            upgrade_compat=tuple(
                str(x) for x in d.get(
                    "upgrade_compat",
                    ("volume_cloud_urp",),
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

    Hardening PR B Fix #9 (V2 + VD finding): ``volumetric_fog_native`` was
    removed from upgrade_compat — URP has no native volumetric fog
    roadmap as of 17.3.
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
    )

    def __post_init__(self) -> None:
        # CodeRabbit round-2 fix: enforce schema-major on direct construction
        # too (not only from_dict), closing the write-path hole.
        _check_major(self.schema_version)
        _validate_backend("fog", self.backend)
        _validate_upgrade_compat("fog", self.backend, self.upgrade_compat)

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
        version = str(d.get("schema_version", "1.0"))
        _check_major(version)
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
            schema_version=version,
            backend=str(d.get("backend", "urp_fog_volume_plus_cards")),
            height_density_curve=curve_tuple,
            fog_color_ramp_path=str(d.get("fog_color_ramp_path", "")),
            wind_direction_xyz=wind_tuple,
            upgrade_compat=tuple(
                str(x) for x in d.get(
                    "upgrade_compat",
                    ("atmospheric_height_fog",),
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

    Hardening PR B Fix #1 (VA + VD critical bug): default backend changed
    from ``fsr_3_1`` (external ``FSR3-Unity-URP`` package) to ``stp_1_0``,
    which ships natively with URP 17.3.  FSR 3.1 / DLSS 4.5 are now
    upgrade-side alternates; FSR 1.0 is the legacy fallback.
    """

    schema_version: str = "1.0"
    backend: str = "stp_1_0"
    quality: str = "balanced"
    mip_bias: float = -1.0
    upgrade_compat: Tuple[str, ...] = (
        "fsr_3_1",
        "fsr_1_0",
        "dlss_4_5",
        "off",
    )

    def __post_init__(self) -> None:
        # CodeRabbit round-2 fix: enforce schema-major on direct construction
        # too (not only from_dict), closing the write-path hole.
        _check_major(self.schema_version)
        _validate_backend("upscaler", self.backend)
        _validate_upgrade_compat("upscaler", self.backend, self.upgrade_compat)

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
        version = str(d.get("schema_version", "1.0"))
        _check_major(version)
        return cls(
            schema_version=version,
            backend=str(d.get("backend", "stp_1_0")),
            quality=str(d.get("quality", "balanced")),
            mip_bias=float(d.get("mip_bias", -1.0)),
            upgrade_compat=tuple(
                str(x) for x in d.get(
                    "upgrade_compat",
                    ("fsr_3_1", "fsr_1_0", "dlss_4_5", "off"),
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
    # Hardening PR B Fix #1: default is now the URP-native STP 1.0, not
    # the external FSR3-Unity-URP package.
    upscaler_backend: str = "stp_1_0"

    # Legacy: emit hdrp_mask_map.raw alongside material_mask_map.raw so
    # existing Unity scenes that still read the old filename keep working.
    legacy_hdrp_filename: bool = False

    # Class-level preset slots — populated below the class definition so
    # they share the same dataclass type without becoming dataclass fields.
    # Using ClassVar tells both the dataclass machinery and pyright that
    # these are class attributes, not instance fields.
    DEFAULT: ClassVar["UnityExportConfig"]
    AAA_16GB: ClassVar["UnityExportConfig"]

    def __post_init__(self) -> None:
        # Hardening PR B Fix #2: validate per-slot backend strings against
        # BACKEND_REGISTRY so a typo in the bake config dies here rather
        # than silently producing an unloadable manifest.
        #
        # CodeRabbit round-2 fix: enforce schema-major on direct construction
        # too (not only from_dict), closing the write-path hole — a
        # ``UnityExportConfig(schema_version="2.0", ...)`` literal would
        # otherwise serialise unchanged.
        _check_major(self.schema_version)
        _validate_backend("water", self.water_backend)
        _validate_backend("sky", self.sky_backend)
        _validate_backend("fog", self.fog_backend)
        _validate_backend("upscaler", self.upscaler_backend)

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

    # Hardening PR B Fix #2: when the caller hasn't provided an explicit
    # manifest, instantiate the default for the chosen backend AND filter
    # the canonical upgrade_compat tuple so the active backend never
    # appears as its own alternate (recursive self-reference is rejected
    # by __post_init__).
    #
    # Codex review fix on Hardening PR B: source per-backend alternate
    # ordering from ``CANONICAL_ALT_ORDER`` rather than ``BACKEND_REGISTRY``
    # so the emitted ``upgrade_compat`` matches each manifest dataclass's
    # pinned canonical default exactly (substitution-priority order, not
    # default-first registry order).
    def _alts_for(slot: str, active: str) -> Tuple[str, ...]:
        return tuple(b for b in CANONICAL_ALT_ORDER[slot] if b != active)

    if water is not None:
        water_m = water
    else:
        water_m = WaterSurfaceManifest(
            backend=cfg.water_backend,
            upgrade_compat=_alts_for("water", cfg.water_backend),
        )
    if sky is not None:
        sky_m = sky
    else:
        sky_m = SkyManifest(
            backend=cfg.sky_backend,
            upgrade_compat=_alts_for("sky", cfg.sky_backend),
        )
    if atmospheric is not None:
        atmospheric_m = atmospheric
    else:
        atmospheric_m = AtmosphericManifest(
            backend=cfg.fog_backend,
            upgrade_compat=_alts_for("fog", cfg.fog_backend),
        )
    if upscaler is not None:
        upscaler_m = upscaler
    else:
        upscaler_m = UpscalerManifest(
            backend=cfg.upscaler_backend,
            upgrade_compat=_alts_for("upscaler", cfg.upscaler_backend),
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


# Re-export the unused ``field`` import path so future schema additions
# referencing ``dataclasses.field(default_factory=...)`` don't have to add a
# fresh import line.
_ = field


__all__ = [
    "WaterSurfaceManifest",
    "SkyManifest",
    "AtmosphericManifest",
    "UpscalerManifest",
    "UnityExportConfig",
    "BACKEND_REGISTRY",
    "CANONICAL_ALT_ORDER",
    "WATER_BACKENDS",
    "SKY_BACKENDS",
    "FOG_BACKENDS",
    "UPSCALER_BACKENDS",
    "build_unity_urp_manifest_section",
]
