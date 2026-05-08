"""Phase D1 — URP backend-agnostic manifest schema tests.

Pins the four backend-agnostic dataclasses (water/sky/atmospheric/upscaler),
the :class:`UnityExportConfig` profiles, the rename of
``_pack_hdrp_mask_map`` → ``_pack_material_mask_map`` plus the legacy
filename opt-in, and the ``unity_urp`` manifest key wiring.

Spec: §17 Phase D1 of IMPLEMENTATION_FIX_GUIDE_2026_05_07_FINAL.
"""

from __future__ import annotations

import json
import pathlib
import tempfile

import numpy as np

from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack
from veilbreakers_terrain.handlers.terrain_unity_backends import (
    AtmosphericManifest,
    SkyManifest,
    UnityExportConfig,
    UpscalerManifest,
    WaterSurfaceManifest,
    build_unity_urp_manifest_section,
)
from veilbreakers_terrain.handlers.terrain_unity_export import (
    _pack_hdrp_mask_map,
    _pack_material_mask_map,
    export_unity_manifest,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_min_stack(H: int = 33, W: int = 33) -> TerrainMaskStack:
    stack = TerrainMaskStack(
        tile_size=H,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=np.zeros((H, W), dtype=np.float32),
    )
    # The mask-map writer fires only when terrain_ao or roughness_variation
    # are present.  Stage both so both legacy/canonical files can be checked.
    stack.set("terrain_ao", np.full((H, W), 0.5, dtype=np.float32), "test_phase_d1")
    stack.set(
        "roughness_variation",
        np.full((H, W), 0.4, dtype=np.float32),
        "test_phase_d1",
    )
    return stack


# ---------------------------------------------------------------------------
# 1. WaterSurfaceManifest round-trip + upgrade_compat invariance
# ---------------------------------------------------------------------------


def test_water_manifest_roundtrip_default():
    m = WaterSurfaceManifest()
    d = m.to_dict()
    m2 = WaterSurfaceManifest.from_dict(d)
    assert m2 == m
    # JSON-safety: dict must be JSON-serialisable round-trip.
    j = json.loads(json.dumps(d))
    m3 = WaterSurfaceManifest.from_dict(j)
    assert m3 == m


def test_water_manifest_default_backend_and_upgrade_compat_locked():
    m = WaterSurfaceManifest()
    assert m.backend == "boat_attack"
    # Pinned upgrade_compat — fail loudly if alternates regress.
    assert m.upgrade_compat == ("stylized_water_2", "crest_5", "hand_authored_urp")
    d = m.to_dict()
    assert "stylized_water_2" in d["upgrade_compat"]
    assert "crest_5" in d["upgrade_compat"]
    assert "hand_authored_urp" in d["upgrade_compat"]


def test_water_manifest_custom_field_overrides_persist():
    m = WaterSurfaceManifest(
        backend="crest_5",
        elevation_m=12.5,
        wave_amplitude_m=1.2,
        foam_threshold_normalized=0.6,
        shore_reaction_enabled=False,
    )
    d = m.to_dict()
    assert d["backend"] == "crest_5"
    assert d["elevation_m"] == 12.5
    assert d["wave_amplitude_m"] == 1.2
    assert d["foam_threshold_normalized"] == 0.6
    assert d["shore_reaction_enabled"] is False
    m2 = WaterSurfaceManifest.from_dict(d)
    assert m2 == m


# ---------------------------------------------------------------------------
# 2. SkyManifest round-trip + upgrade_compat invariance
# ---------------------------------------------------------------------------


def test_sky_manifest_roundtrip_default():
    m = SkyManifest()
    d = m.to_dict()
    m2 = SkyManifest.from_dict(d)
    assert m2 == m
    j = json.loads(json.dumps(d))
    m3 = SkyManifest.from_dict(j)
    assert m3 == m


def test_sky_manifest_default_backend_and_upgrade_compat_locked():
    m = SkyManifest()
    assert m.backend == "skybox_cubemap"
    # Pinned upgrade_compat alternates.
    assert m.upgrade_compat == ("volume_cloud_urp", "volumetric_clouds_native")


def test_sky_manifest_quaternion_roundtrip():
    m = SkyManifest(sun_rotation_quat=(0.1, 0.2, 0.3, 0.9))
    d = m.to_dict()
    assert d["sun_rotation_quat"] == [0.1, 0.2, 0.3, 0.9]
    m2 = SkyManifest.from_dict(d)
    assert m2.sun_rotation_quat == (0.1, 0.2, 0.3, 0.9)


# ---------------------------------------------------------------------------
# 3. AtmosphericManifest round-trip + upgrade_compat invariance
# ---------------------------------------------------------------------------


def test_atmospheric_manifest_roundtrip_default():
    m = AtmosphericManifest()
    d = m.to_dict()
    m2 = AtmosphericManifest.from_dict(d)
    assert m2 == m
    j = json.loads(json.dumps(d))
    m3 = AtmosphericManifest.from_dict(j)
    assert m3 == m


def test_atmospheric_manifest_default_backend_and_upgrade_compat_locked():
    m = AtmosphericManifest()
    assert m.backend == "urp_fog_volume_plus_cards"
    assert m.upgrade_compat == ("atmospheric_height_fog", "volumetric_fog_native")


def test_atmospheric_manifest_height_density_curve_roundtrip():
    curve = ((0.0, 1.0), (10.0, 0.7), (100.0, 0.2), (300.0, 0.0))
    m = AtmosphericManifest(height_density_curve=curve)
    d = m.to_dict()
    # JSON list-of-list form survives JSON round-trip.
    j = json.loads(json.dumps(d))
    m2 = AtmosphericManifest.from_dict(j)
    assert m2.height_density_curve == curve


# ---------------------------------------------------------------------------
# 4. UpscalerManifest round-trip + upgrade_compat invariance
# ---------------------------------------------------------------------------


def test_upscaler_manifest_roundtrip_default():
    m = UpscalerManifest()
    d = m.to_dict()
    m2 = UpscalerManifest.from_dict(d)
    assert m2 == m
    j = json.loads(json.dumps(d))
    m3 = UpscalerManifest.from_dict(j)
    assert m3 == m


def test_upscaler_manifest_default_backend_and_upgrade_compat_locked():
    m = UpscalerManifest()
    assert m.backend == "fsr_3_1"
    assert m.upgrade_compat == ("dlss_4_5", "stp_native", "off")
    assert m.quality == "balanced"
    assert m.mip_bias == -1.0


# ---------------------------------------------------------------------------
# 5. UnityExportConfig profiles
# ---------------------------------------------------------------------------


def test_unity_export_config_default_profile():
    cfg = UnityExportConfig.DEFAULT
    assert cfg.splatmap_max_layers == 4
    assert cfg.render_pipeline == "URP"
    assert cfg.render_pipeline_version == "17.3"
    assert cfg.water_backend == "boat_attack"
    assert cfg.sky_backend == "skybox_cubemap"
    assert cfg.fog_backend == "urp_fog_volume_plus_cards"
    assert cfg.upscaler_backend == "fsr_3_1"
    assert cfg.legacy_hdrp_filename is False


def test_unity_export_config_aaa_16gb_profile():
    cfg = UnityExportConfig.AAA_16GB
    assert cfg.splatmap_max_layers == 8
    # Same FREE URP backends — only the splatmap layer cap differs in v1.1.
    assert cfg.water_backend == "boat_attack"
    assert cfg.sky_backend == "skybox_cubemap"
    assert cfg.fog_backend == "urp_fog_volume_plus_cards"
    assert cfg.upscaler_backend == "fsr_3_1"


def test_unity_export_config_to_dict_contains_all_keys():
    cfg = UnityExportConfig()
    d = cfg.to_dict()
    expected = {
        "schema_version", "render_pipeline", "render_pipeline_version",
        "splatmap_max_layers",
        "water_backend", "sky_backend", "fog_backend", "upscaler_backend",
        "legacy_hdrp_filename",
    }
    assert expected <= set(d.keys())


# ---------------------------------------------------------------------------
# 6. Mask-map function: rename + deprecation alias
# ---------------------------------------------------------------------------


def test_pack_material_mask_map_exists_and_packs_rgba_correctly():
    """Function exists under canonical name and packs R/G/B/A in order."""
    metallic = np.full((4, 4), 0.1, dtype=np.float32)
    ao = np.full((4, 4), 0.2, dtype=np.float32)
    detail = np.full((4, 4), 0.3, dtype=np.float32)
    smoothness = np.full((4, 4), 0.4, dtype=np.float32)
    mask = _pack_material_mask_map(metallic, ao, detail, smoothness)
    assert mask.shape == (4, 4, 4)
    np.testing.assert_array_almost_equal(mask[..., 0], metallic)
    np.testing.assert_array_almost_equal(mask[..., 1], ao)
    np.testing.assert_array_almost_equal(mask[..., 2], detail)
    np.testing.assert_array_almost_equal(mask[..., 3], smoothness)


def test_pack_hdrp_mask_map_is_deprecation_alias():
    """Legacy ``_pack_hdrp_mask_map`` callers still resolve to the new function."""
    # Both names point at the same callable object — any future change to
    # ``_pack_material_mask_map`` is automatically reflected.
    assert _pack_hdrp_mask_map is _pack_material_mask_map


# ---------------------------------------------------------------------------
# 7. Legacy filename opt-in / opt-out at export time
# ---------------------------------------------------------------------------


def test_export_writes_only_material_mask_map_by_default():
    """Default config emits material_mask_map.raw and NOT hdrp_mask_map.raw."""
    stack = _make_min_stack()
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td)
        manifest = export_unity_manifest(
            stack,
            out,
            strict_unity_resolution=False,
            fail_on_validation_error=False,
        )

        material_path = out / "material_mask_map.raw"
        hdrp_path = out / "hdrp_mask_map.raw"

        assert material_path.is_file(), "material_mask_map.raw must always exist"
        assert not hdrp_path.is_file(), (
            "hdrp_mask_map.raw must NOT exist by default — legacy flag is off"
        )
        assert "material_mask_map.raw" in manifest["files"]
        assert "hdrp_mask_map.raw" not in manifest["files"]


def test_export_writes_legacy_hdrp_filename_when_opted_in():
    """legacy_hdrp_filename=True emits BOTH files, byte-identical."""
    stack = _make_min_stack()
    cfg = UnityExportConfig(legacy_hdrp_filename=True)
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td)
        manifest = export_unity_manifest(
            stack,
            out,
            strict_unity_resolution=False,
            fail_on_validation_error=False,
            unity_export_config=cfg,
        )

        material_path = out / "material_mask_map.raw"
        hdrp_path = out / "hdrp_mask_map.raw"

        assert material_path.is_file(), "canonical file must exist"
        assert hdrp_path.is_file(), (
            "legacy hdrp_mask_map.raw must exist when legacy_hdrp_filename=True"
        )
        # Byte-identical aliasing — Unity importers reading either name see
        # the same payload.
        assert material_path.read_bytes() == hdrp_path.read_bytes()
        assert "material_mask_map.raw" in manifest["files"]
        assert "hdrp_mask_map.raw" in manifest["files"]
        # The legacy entry self-identifies as an alias for downstream tooling.
        assert manifest["files"]["hdrp_mask_map.raw"].get("legacy_alias_of") == (
            "material_mask_map.raw"
        )


# ---------------------------------------------------------------------------
# 8. unity_urp manifest section wiring
# ---------------------------------------------------------------------------


def test_export_manifest_emits_unity_urp_section_with_all_four_backends():
    """Manifest carries unity_urp.{water,sky,atmospheric,upscaler}."""
    stack = _make_min_stack()
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td)
        manifest = export_unity_manifest(
            stack,
            out,
            strict_unity_resolution=False,
            fail_on_validation_error=False,
        )
        manifest_disk = json.loads((out / "manifest.json").read_text(encoding="utf-8"))

    for source in (manifest, manifest_disk):
        assert "unity_urp" in source, "unity_urp top-level key must be present"
        urp = source["unity_urp"]
        assert urp["schema_version"] == "1.0"
        assert urp["render_pipeline"] == {"type": "URP", "version": "17.3"}
        for slot in ("water", "sky", "atmospheric", "upscaler"):
            assert slot in urp, f"unity_urp missing required slot: {slot}"
            assert "backend" in urp[slot]
            assert "schema_version" in urp[slot]
            assert "upgrade_compat" in urp[slot]
            assert isinstance(urp[slot]["upgrade_compat"], list)
            assert len(urp[slot]["upgrade_compat"]) >= 1


def test_export_manifest_unity_urp_default_backends_match_phase_d1_decisions():
    """Default bake locks the four FREE URP backends specified in Phase D1."""
    stack = _make_min_stack()
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td)
        manifest = export_unity_manifest(
            stack,
            out,
            strict_unity_resolution=False,
            fail_on_validation_error=False,
        )
    urp = manifest["unity_urp"]
    assert urp["water"]["backend"] == "boat_attack"
    assert urp["sky"]["backend"] == "skybox_cubemap"
    assert urp["atmospheric"]["backend"] == "urp_fog_volume_plus_cards"
    assert urp["upscaler"]["backend"] == "fsr_3_1"


def test_export_manifest_accepts_overridden_backend_manifests():
    """Caller-supplied manifest dataclasses propagate into the unity_urp block."""
    stack = _make_min_stack()
    custom_water = WaterSurfaceManifest(
        backend="crest_5",
        elevation_m=42.0,
        wave_amplitude_m=2.5,
    )
    custom_sky = SkyManifest(
        backend="volumetric_clouds_native",
        cloud_density=0.6,
    )
    custom_atm = AtmosphericManifest(backend="volumetric_fog_native")
    custom_up = UpscalerManifest(backend="dlss_4_5", quality="quality")
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td)
        manifest = export_unity_manifest(
            stack,
            out,
            strict_unity_resolution=False,
            fail_on_validation_error=False,
            water_manifest=custom_water,
            sky_manifest=custom_sky,
            atmospheric_manifest=custom_atm,
            upscaler_manifest=custom_up,
        )
    urp = manifest["unity_urp"]
    assert urp["water"]["backend"] == "crest_5"
    assert urp["water"]["elevation_m"] == 42.0
    assert urp["water"]["wave_amplitude_m"] == 2.5
    assert urp["sky"]["backend"] == "volumetric_clouds_native"
    assert urp["sky"]["cloud_density"] == 0.6
    assert urp["atmospheric"]["backend"] == "volumetric_fog_native"
    assert urp["upscaler"]["backend"] == "dlss_4_5"
    assert urp["upscaler"]["quality"] == "quality"


def test_build_unity_urp_manifest_section_helper_uses_config_backend_strings():
    """``build_unity_urp_manifest_section`` honours the config's backend slots."""
    cfg = UnityExportConfig(
        water_backend="stylized_water_2",
        sky_backend="volume_cloud_urp",
        fog_backend="atmospheric_height_fog",
        upscaler_backend="stp_native",
    )
    section = build_unity_urp_manifest_section(config=cfg)
    assert section["water"]["backend"] == "stylized_water_2"
    assert section["sky"]["backend"] == "volume_cloud_urp"
    assert section["atmospheric"]["backend"] == "atmospheric_height_fog"
    assert section["upscaler"]["backend"] == "stp_native"


# ---------------------------------------------------------------------------
# 9. Backwards-compat with D25 splatmap test
# ---------------------------------------------------------------------------


def test_default_splatmap_max_layers_unchanged_from_d25():
    """Default cap stays at 4 — D25 truncation regression must keep passing."""
    cfg = UnityExportConfig()
    assert cfg.splatmap_max_layers == 4
