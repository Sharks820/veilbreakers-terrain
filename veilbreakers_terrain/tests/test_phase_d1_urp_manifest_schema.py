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
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import pytest as _pytest_module

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


# ---------------------------------------------------------------------------
# Hardening PR B Fix #4 — backend / version / upgrade_compat strict validation
# ---------------------------------------------------------------------------


def test_invalid_backend_raises_at_construction():
    """Unknown backend strings die loudly at __post_init__ time."""
    import pytest as _pytest

    with _pytest.raises(ValueError, match="not in canonical registry"):
        WaterSurfaceManifest(backend="not_real")
    with _pytest.raises(ValueError, match="not in canonical registry"):
        SkyManifest(backend="HDRP_volumetric_clouds")
    with _pytest.raises(ValueError, match="not in canonical registry"):
        AtmosphericManifest(backend="HDRP_volumetric_fog")
    with _pytest.raises(ValueError, match="not in canonical registry"):
        UpscalerManifest(backend="DLSS_99")


def test_invalid_upgrade_compat_entry_raises():
    """Unknown upgrade_compat alts die loudly at __post_init__ time."""
    import pytest as _pytest

    with _pytest.raises(ValueError, match="upgrade_compat entry"):
        WaterSurfaceManifest(
            backend="boat_attack",
            upgrade_compat=("stylized_water_2", "made_up_water"),
        )
    with _pytest.raises(ValueError, match="upgrade_compat entry"):
        UpscalerManifest(
            backend="stp_1_0",
            upgrade_compat=("fsr_3_1", "made_up_upscaler"),
        )


def test_schema_version_major_mismatch_raises():
    """from_dict rejects a v2.x manifest because this build is v1.x only."""
    import pytest as _pytest

    base_dict = WaterSurfaceManifest().to_dict()
    base_dict["schema_version"] = "2.0"
    with _pytest.raises(ValueError, match="schema major mismatch"):
        WaterSurfaceManifest.from_dict(base_dict)

    sky_dict = SkyManifest().to_dict()
    sky_dict["schema_version"] = "9.5"
    with _pytest.raises(ValueError, match="schema major mismatch"):
        SkyManifest.from_dict(sky_dict)


def test_schema_version_minor_bump_accepted():
    """Forward-compat: v1.99 still loads on this v1.x build."""
    base_dict = WaterSurfaceManifest().to_dict()
    base_dict["schema_version"] = "1.99"
    m = WaterSurfaceManifest.from_dict(base_dict)
    assert m.schema_version == "1.99"
    # Round-trip preserves the bumped version string.
    assert m.to_dict()["schema_version"] == "1.99"


def test_direct_construction_rejects_v2_schema_version():
    """CodeRabbit round-2 fix: direct construction must enforce schema-major.

    Before the fix, ``_check_major`` only ran in ``from_dict``, so a literal
    like ``WaterSurfaceManifest(schema_version="2.0", ...)`` could bypass
    the v1-only guard and serialise unchanged.  After the fix, every
    manifest dataclass — and ``UnityExportConfig`` — calls
    ``_check_major(self.schema_version)`` in ``__post_init__`` so the
    write path is closed too.
    """
    import pytest as _pytest

    from veilbreakers_terrain.handlers.terrain_unity_backends import (
        UnityExportConfig,
    )

    with _pytest.raises(ValueError, match="schema major mismatch"):
        WaterSurfaceManifest(schema_version="2.0")
    with _pytest.raises(ValueError, match="schema major mismatch"):
        SkyManifest(schema_version="2.0")
    with _pytest.raises(ValueError, match="schema major mismatch"):
        AtmosphericManifest(schema_version="2.0")
    with _pytest.raises(ValueError, match="schema major mismatch"):
        UpscalerManifest(schema_version="2.0")
    with _pytest.raises(ValueError, match="schema major mismatch"):
        UnityExportConfig(schema_version="2.0")


def test_recursive_self_in_upgrade_compat_rejected():
    """A backend listing itself as an alt is a config bug — reject."""
    import pytest as _pytest

    with _pytest.raises(ValueError, match="recursive self-reference"):
        WaterSurfaceManifest(
            backend="crest_5",
            upgrade_compat=("crest_5", "stylized_water_2"),
        )


# Direct tests for the module-level helpers — names referenced explicitly so
# the verification matrix can match callable -> test by text-content scan
# (Hardening PR B follow-up to grade-status promotion).


def test_check_major_helper_accepts_v1_minor_and_rejects_v2():
    """Direct unit test for the ``_check_major`` schema-version helper."""
    import pytest as _pytest

    from veilbreakers_terrain.handlers.terrain_unity_backends import _check_major

    # v1.x family — must accept silently.
    _check_major("1.0")
    _check_major("1.99")
    _check_major("v1.0")  # leading-v tolerated

    # v2+ — must raise.
    with _pytest.raises(ValueError, match="schema major mismatch"):
        _check_major("2.0")
    with _pytest.raises(ValueError, match="schema major mismatch"):
        _check_major("9.0")


def test_validate_backend_helper_accepts_canonical_and_rejects_unknown():
    """Direct unit test for the ``_validate_backend`` registry helper."""
    import pytest as _pytest

    from veilbreakers_terrain.handlers.terrain_unity_backends import (
        _validate_backend,
    )

    # All canonical backends accepted.
    _validate_backend("water", "boat_attack")
    _validate_backend("sky", "skybox_cubemap")
    _validate_backend("fog", "urp_fog_volume_plus_cards")
    _validate_backend("upscaler", "stp_1_0")

    # Typos / unknown values rejected with the canonical-list hint.
    with _pytest.raises(ValueError, match="not in canonical registry"):
        _validate_backend("water", "not_a_real_backend")


def test_validate_upgrade_compat_helper_rejects_unknown_and_self_ref():
    """Direct unit test for the ``_validate_upgrade_compat`` helper."""
    import pytest as _pytest

    from veilbreakers_terrain.handlers.terrain_unity_backends import (
        _validate_upgrade_compat,
    )

    # OK case — alts are canonical and not self-referential.
    _validate_upgrade_compat(
        "water", "boat_attack", ("stylized_water_2", "crest_5")
    )

    # Unknown alt — rejected.
    with _pytest.raises(ValueError, match="upgrade_compat entry"):
        _validate_upgrade_compat("water", "boat_attack", ("not_real",))

    # Self-reference — rejected.
    with _pytest.raises(ValueError, match="recursive self-reference"):
        _validate_upgrade_compat(
            "water", "crest_5", ("crest_5", "stylized_water_2")
        )


def test_canonical_alt_order_is_permutation_of_backend_registry():
    """Codex review fix on Hardening PR B PR #52 thread 5.

    ``CANONICAL_ALT_ORDER`` must contain exactly the same set of backend
    strings as ``BACKEND_REGISTRY`` for every slot.  This is enforced at
    module import time by ``_validate_canonical_alt_order``; this test
    pins the contract so a future PR that adds a backend to one map and
    forgets the other fails fast.
    """
    from veilbreakers_terrain.handlers.terrain_unity_backends import (
        BACKEND_REGISTRY,
        CANONICAL_ALT_ORDER,
        _validate_canonical_alt_order,
    )

    # Same slot set in both maps.
    assert set(CANONICAL_ALT_ORDER.keys()) == set(BACKEND_REGISTRY.keys())
    # CodeRabbit round-2 fix: compare sorted sequences (multiset equality)
    # rather than sets so duplicate entries trip this guard.  A pure ``set``
    # comparison would silently accept a duplicated backend.
    for slot, registry in BACKEND_REGISTRY.items():
        assert sorted(CANONICAL_ALT_ORDER[slot]) == sorted(registry), (
            f"slot {slot!r} permutation mismatch: "
            f"CANONICAL_ALT_ORDER={CANONICAL_ALT_ORDER[slot]!r} vs "
            f"BACKEND_REGISTRY={registry!r}"
        )

    # The validator itself runs at import; calling it directly here
    # documents the failure mode for future readers and pins the helper
    # against accidental signature changes.
    _validate_canonical_alt_order()


def test_canonical_alt_order_validator_rejects_duplicate_entries(
    monkeypatch: "_pytest_module.MonkeyPatch",
) -> None:
    """CodeRabbit round-2 fix: a tuple with a duplicate backend must be rejected.

    Before the fix, ``set(canonical) == set(registry)`` would treat
    ``("a", "a", "b", "c")`` as equal to ``("a", "b", "c", "d")`` when
    sets dedup, missing both the duplicated ``a`` and the missing ``d``.
    The sorted-sequence comparison catches both cases.
    """
    import pytest as _pytest

    from veilbreakers_terrain.handlers import terrain_unity_backends as tub

    # Patch CANONICAL_ALT_ORDER so the upscaler slot has the same length
    # as the registry but contains a duplicated entry and is missing one.
    bad = dict(tub.CANONICAL_ALT_ORDER)
    bad["upscaler"] = ("stp_1_0", "stp_1_0", "fsr_1_0", "dlss_4_5", "off")
    monkeypatch.setattr(tub, "CANONICAL_ALT_ORDER", bad)

    with _pytest.raises(RuntimeError, match="not a permutation"):
        tub._validate_canonical_alt_order()


def test_canonical_alt_order_upscaler_substitution_priority_pinned():
    """Upscaler alt ordering is locked in substitution-priority order.

    The pinned default of ``UpscalerManifest.upgrade_compat`` is
    ``("fsr_3_1", "fsr_1_0", "dlss_4_5", "off")``.  The
    ``build_unity_urp_manifest_section`` helper must derive the SAME
    order (with the active backend filtered out) when no explicit
    manifest is supplied.  Pinning this avoids the regression Codex
    flagged on PR #52: registry order would yield
    ``("fsr_1_0", "fsr_3_1", "dlss_4_5", "off")`` — different priority.
    """
    from veilbreakers_terrain.handlers.terrain_unity_backends import (
        CANONICAL_ALT_ORDER,
        UpscalerManifest,
    )

    # CANONICAL_ALT_ORDER pins substitution priority WITH default first.
    assert CANONICAL_ALT_ORDER["upscaler"] == (
        "stp_1_0", "fsr_3_1", "fsr_1_0", "dlss_4_5", "off"
    )

    # UpscalerManifest pinned default upgrade_compat = priority order
    # WITH the default removed.
    assert UpscalerManifest().upgrade_compat == (
        "fsr_3_1", "fsr_1_0", "dlss_4_5", "off"
    )

    # build_unity_urp_manifest_section must emit the same order.
    section = build_unity_urp_manifest_section()
    assert section["upscaler"]["upgrade_compat"] == [
        "fsr_3_1", "fsr_1_0", "dlss_4_5", "off"
    ]


def test_water_manifest_custom_field_overrides_persist():
    # Hardening PR B Fix #2: when backend != default, supply an
    # upgrade_compat tuple that doesn't list the active backend (recursive
    # self-reference is now rejected at __post_init__).
    m = WaterSurfaceManifest(
        backend="crest_5",
        elevation_m=12.5,
        wave_amplitude_m=1.2,
        foam_threshold_normalized=0.6,
        shore_reaction_enabled=False,
        upgrade_compat=("boat_attack", "stylized_water_2", "hand_authored_urp"),
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
    # Pinned upgrade_compat alternates.  Hardening PR B Fix #9: dropped
    # ``volumetric_clouds_native`` because URP 17.3 has no native volumetric
    # cloud pass roadmap.
    assert m.upgrade_compat == ("volume_cloud_urp",)


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
    # Hardening PR B Fix #9: dropped ``volumetric_fog_native`` (URP 17.3
    # has no native volumetric fog roadmap).
    assert m.upgrade_compat == ("atmospheric_height_fog",)


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
    # Hardening PR B Fix #1 (VA + VD critical bug): default backend is now
    # ``stp_1_0`` (URP 17.3 native), not ``fsr_3_1`` (external package).
    assert m.backend == "stp_1_0"
    assert m.upgrade_compat == ("fsr_3_1", "fsr_1_0", "dlss_4_5", "off")
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
    # Hardening PR B Fix #1: URP-native STP 1.0 is the default upscaler.
    assert cfg.upscaler_backend == "stp_1_0"
    assert cfg.legacy_hdrp_filename is False


def test_unity_export_config_aaa_16gb_profile():
    cfg = UnityExportConfig.AAA_16GB
    assert cfg.splatmap_max_layers == 8
    # Same FREE URP backends — only the splatmap layer cap differs in v1.1.
    assert cfg.water_backend == "boat_attack"
    assert cfg.sky_backend == "skybox_cubemap"
    assert cfg.fog_backend == "urp_fog_volume_plus_cards"
    assert cfg.upscaler_backend == "stp_1_0"


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
    # Hardening PR B Fix #1: URP-native STP 1.0 default (was fsr_3_1 external).
    assert urp["upscaler"]["backend"] == "stp_1_0"


def test_export_manifest_accepts_overridden_backend_manifests():
    """Caller-supplied manifest dataclasses propagate into the unity_urp block."""
    stack = _make_min_stack()
    # Hardening PR B Fix #2: when overriding backend, supply a tailored
    # upgrade_compat that does NOT list the active backend (otherwise the
    # __post_init__ self-reference guard fires).
    custom_water = WaterSurfaceManifest(
        backend="crest_5",
        elevation_m=42.0,
        wave_amplitude_m=2.5,
        upgrade_compat=("boat_attack", "stylized_water_2", "hand_authored_urp"),
    )
    custom_sky = SkyManifest(
        backend="volume_cloud_urp",
        cloud_density=0.6,
        upgrade_compat=(),
    )
    custom_atm = AtmosphericManifest(
        backend="atmospheric_height_fog",
        upgrade_compat=(),
    )
    custom_up = UpscalerManifest(
        backend="dlss_4_5",
        quality="quality",
        upgrade_compat=("stp_1_0", "fsr_3_1", "fsr_1_0", "off"),
    )
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
    assert urp["sky"]["backend"] == "volume_cloud_urp"
    assert urp["sky"]["cloud_density"] == 0.6
    assert urp["atmospheric"]["backend"] == "atmospheric_height_fog"
    assert urp["upscaler"]["backend"] == "dlss_4_5"
    assert urp["upscaler"]["quality"] == "quality"


def test_build_unity_urp_manifest_section_helper_uses_config_backend_strings():
    """``build_unity_urp_manifest_section`` honours the config's backend slots."""
    cfg = UnityExportConfig(
        water_backend="stylized_water_2",
        sky_backend="volume_cloud_urp",
        fog_backend="atmospheric_height_fog",
        upscaler_backend="fsr_3_1",
    )
    section = build_unity_urp_manifest_section(config=cfg)
    assert section["water"]["backend"] == "stylized_water_2"
    assert section["sky"]["backend"] == "volume_cloud_urp"
    assert section["atmospheric"]["backend"] == "atmospheric_height_fog"
    assert section["upscaler"]["backend"] == "fsr_3_1"


# ---------------------------------------------------------------------------
# 9. Backwards-compat with D25 splatmap test
# ---------------------------------------------------------------------------


def test_default_splatmap_max_layers_unchanged_from_d25():
    """Default cap stays at 4 — D25 truncation regression must keep passing."""
    cfg = UnityExportConfig()
    assert cfg.splatmap_max_layers == 4
