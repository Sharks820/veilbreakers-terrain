"""Phase C D34 — streaming mipmap memory budget cap tests.

Pins the new ``UnityExportConfig.streaming_mipmaps_memory_budget_mb`` field
plus its presence in the emitted manifest's ``unity_urp.quality_settings``
block.  The Unity-side ``URPSceneBootstrap`` (forthcoming) reads this field
and applies it via ``QualitySettings.streamingMipmapsMemoryBudget`` at scene
load to prevent the v1.0 8 GB ship config from blowing past 3 GB of texture
streaming on consumer GPUs.

Spec reference: §17 Phase C D34 of
``docs/IMPLEMENTATION_FIX_GUIDE_2026_05_07_FINAL.md`` (PRs #43 + #44).

  * 8 GB ship config (DEFAULT) = 3072 MB.
  * 16 GB target hardware (AAA_16GB) = 6144 MB.
"""

from __future__ import annotations

import json
import pathlib
import tempfile

import numpy as np
import pytest

from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack
from veilbreakers_terrain.handlers.terrain_unity_backends import (
    UnityExportConfig,
    build_unity_urp_manifest_section,
)
from veilbreakers_terrain.handlers.terrain_unity_export import (
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
    stack.set("terrain_ao", np.full((H, W), 0.5, dtype=np.float32), "test_phase_c_d34")
    stack.set(
        "roughness_variation",
        np.full((H, W), 0.4, dtype=np.float32),
        "test_phase_c_d34",
    )
    return stack


# ---------------------------------------------------------------------------
# 1. UnityExportConfig defaults (DEFAULT + AAA_16GB)
# ---------------------------------------------------------------------------


def test_default_streaming_mipmaps_memory_budget_is_3072_mb():
    """8 GB ship config locks streaming budget at exactly 3 GB."""
    cfg = UnityExportConfig.DEFAULT
    assert cfg.streaming_mipmaps_memory_budget_mb == 3072
    # Streaming must be ON by default — Unity's QualitySettings.streamingMipmapsActive
    # gates whether the budget is even applied.
    assert cfg.streaming_mipmaps_active is True


def test_aaa_16gb_streaming_mipmaps_memory_budget_is_6144_mb():
    """16 GB target hardware bumps the cap to 6 GB."""
    cfg = UnityExportConfig.AAA_16GB
    assert cfg.streaming_mipmaps_memory_budget_mb == 6144
    assert cfg.streaming_mipmaps_active is True


def test_unity_export_config_default_init_matches_default_preset():
    """Bare-init UnityExportConfig() lines up with DEFAULT preset on D34 fields."""
    cfg = UnityExportConfig()
    assert cfg.streaming_mipmaps_memory_budget_mb == 3072
    assert cfg.streaming_mipmaps_active is True


# ---------------------------------------------------------------------------
# 2. __post_init__ plausibility validation
# ---------------------------------------------------------------------------


def test_streaming_budget_zero_rejected():
    """Zero is not a plausible streaming budget (Unity refuses it too)."""
    with pytest.raises(ValueError, match="out of plausible range"):
        UnityExportConfig(streaming_mipmaps_memory_budget_mb=0)


def test_streaming_budget_negative_rejected():
    """Negative budgets are config bugs."""
    with pytest.raises(ValueError, match="out of plausible range"):
        UnityExportConfig(streaming_mipmaps_memory_budget_mb=-512)


def test_streaming_budget_overflow_rejected():
    """No shipping consumer GPU is above 16 GB in v1.x — reject 999999."""
    with pytest.raises(ValueError, match="out of plausible range"):
        UnityExportConfig(streaming_mipmaps_memory_budget_mb=999999)


def test_streaming_budget_below_floor_rejected():
    """255 MB is below the documented [256, 16384] floor."""
    with pytest.raises(ValueError, match="out of plausible range"):
        UnityExportConfig(streaming_mipmaps_memory_budget_mb=255)


def test_streaming_budget_above_ceiling_rejected():
    """16385 MB is above the documented [256, 16384] ceiling."""
    with pytest.raises(ValueError, match="out of plausible range"):
        UnityExportConfig(streaming_mipmaps_memory_budget_mb=16385)


def test_streaming_budget_at_floor_accepted():
    """Floor and ceiling values are inclusive."""
    cfg = UnityExportConfig(streaming_mipmaps_memory_budget_mb=256)
    assert cfg.streaming_mipmaps_memory_budget_mb == 256


def test_streaming_budget_at_ceiling_accepted():
    cfg = UnityExportConfig(streaming_mipmaps_memory_budget_mb=16384)
    assert cfg.streaming_mipmaps_memory_budget_mb == 16384


def test_streaming_budget_non_int_rejected():
    """Floats / strings / None die loudly at __post_init__ time."""
    with pytest.raises(ValueError, match="must be int"):
        UnityExportConfig(streaming_mipmaps_memory_budget_mb=3072.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be int"):
        UnityExportConfig(streaming_mipmaps_memory_budget_mb="3072")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be int"):
        UnityExportConfig(streaming_mipmaps_memory_budget_mb=None)  # type: ignore[arg-type]


def test_streaming_budget_bool_rejected():
    """``isinstance(True, int)`` is True in Python — reject explicitly so a
    typo'd ``streaming_mipmaps_memory_budget_mb=True`` doesn't silently
    yield budget = 1 MB.
    """
    with pytest.raises(ValueError, match="must be int"):
        UnityExportConfig(streaming_mipmaps_memory_budget_mb=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be int"):
        UnityExportConfig(streaming_mipmaps_memory_budget_mb=False)  # type: ignore[arg-type]


def test_streaming_active_non_bool_rejected():
    """Codex review: dynamic configs that ship ``streaming_mipmaps_active``
    as a string (``"False"`` / ``"0"``) or int (``0`` / ``1``) must die at
    __post_init__ time, otherwise ``bool(non_empty_str)`` silently flips an
    explicit opt-out back to True before it reaches the manifest.
    """
    with pytest.raises(ValueError, match="must be bool"):
        UnityExportConfig(streaming_mipmaps_active="False")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be bool"):
        UnityExportConfig(streaming_mipmaps_active="0")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be bool"):
        UnityExportConfig(streaming_mipmaps_active="True")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be bool"):
        UnityExportConfig(streaming_mipmaps_active=0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be bool"):
        UnityExportConfig(streaming_mipmaps_active=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be bool"):
        UnityExportConfig(streaming_mipmaps_active=None)  # type: ignore[arg-type]


def test_streaming_active_bool_accepted():
    """True and False round-trip cleanly through __post_init__ and to_dict()."""
    cfg_on = UnityExportConfig(streaming_mipmaps_active=True)
    assert cfg_on.streaming_mipmaps_active is True
    assert cfg_on.to_dict()["streaming_mipmaps_active"] is True
    cfg_off = UnityExportConfig(streaming_mipmaps_active=False)
    assert cfg_off.streaming_mipmaps_active is False
    assert cfg_off.to_dict()["streaming_mipmaps_active"] is False


# ---------------------------------------------------------------------------
# 3. UnityExportConfig.to_dict() includes the D34 fields
# ---------------------------------------------------------------------------


def test_unity_export_config_to_dict_contains_d34_fields():
    cfg = UnityExportConfig()
    d = cfg.to_dict()
    assert "streaming_mipmaps_memory_budget_mb" in d
    assert d["streaming_mipmaps_memory_budget_mb"] == 3072
    assert "streaming_mipmaps_active" in d
    assert d["streaming_mipmaps_active"] is True


def test_unity_export_config_to_dict_aaa_16gb_serializes_6144():
    cfg = UnityExportConfig.AAA_16GB
    d = cfg.to_dict()
    assert d["streaming_mipmaps_memory_budget_mb"] == 6144


# ---------------------------------------------------------------------------
# 4. build_unity_urp_manifest_section emits quality_settings block
# ---------------------------------------------------------------------------


def test_unity_urp_manifest_section_includes_quality_settings_default():
    """The ``unity_urp`` block must carry ``quality_settings`` with both fields."""
    section = build_unity_urp_manifest_section()
    assert "quality_settings" in section
    qs = section["quality_settings"]
    assert qs["streaming_mipmaps_memory_budget_mb"] == 3072
    assert qs["streaming_mipmaps_active"] is True


def test_unity_urp_manifest_section_quality_settings_aaa_16gb():
    """AAA_16GB preset propagates 6144 MB into the manifest."""
    section = build_unity_urp_manifest_section(config=UnityExportConfig.AAA_16GB)
    qs = section["quality_settings"]
    assert qs["streaming_mipmaps_memory_budget_mb"] == 6144
    assert qs["streaming_mipmaps_active"] is True


def test_unity_urp_manifest_section_quality_settings_overrides():
    """Custom config (e.g. low-spec 1024 MB) propagates into the manifest."""
    cfg = UnityExportConfig(
        streaming_mipmaps_memory_budget_mb=1024,
        streaming_mipmaps_active=False,
    )
    section = build_unity_urp_manifest_section(config=cfg)
    qs = section["quality_settings"]
    assert qs["streaming_mipmaps_memory_budget_mb"] == 1024
    assert qs["streaming_mipmaps_active"] is False


def test_unity_urp_manifest_section_quality_settings_json_safe():
    """``quality_settings`` round-trips through json.dumps/json.loads."""
    section = build_unity_urp_manifest_section()
    j = json.loads(json.dumps(section))
    qs = j["quality_settings"]
    assert qs["streaming_mipmaps_memory_budget_mb"] == 3072
    assert qs["streaming_mipmaps_active"] is True


# ---------------------------------------------------------------------------
# 5. End-to-end: full export_unity_manifest path emits quality_settings
# ---------------------------------------------------------------------------


def test_export_unity_manifest_includes_quality_settings_block():
    """Full bake path writes the quality_settings block both in-memory and on disk."""
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
        urp = source["unity_urp"]
        assert "quality_settings" in urp, (
            "unity_urp.quality_settings block must be present (Phase C D34)"
        )
        qs = urp["quality_settings"]
        assert qs["streaming_mipmaps_memory_budget_mb"] == 3072
        assert qs["streaming_mipmaps_active"] is True


def test_export_unity_manifest_aaa_16gb_emits_6144_budget():
    """AAA_16GB profile passed through the export pipeline emits 6144 MB."""
    stack = _make_min_stack()
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td)
        manifest = export_unity_manifest(
            stack,
            out,
            strict_unity_resolution=False,
            fail_on_validation_error=False,
            unity_export_config=UnityExportConfig.AAA_16GB,
        )
    qs = manifest["unity_urp"]["quality_settings"]
    assert qs["streaming_mipmaps_memory_budget_mb"] == 6144


# ---------------------------------------------------------------------------
# 6. Schema version stays in v1.x (this is an additive minor bump)
# ---------------------------------------------------------------------------


def test_schema_version_remains_v1_x_after_d34_additive_change():
    """D34 is an additive field — schema_version major must stay at 1.

    The ``_check_major`` policy on each manifest dataclass rejects only
    cross-major bumps (1.x → 2.x); within-major minor bumps (1.0 → 1.99)
    pass.  D34 adds new fields without breaking any existing v1.x reader,
    so by policy this stays in the v1.x family.
    """
    cfg = UnityExportConfig()
    # major component must be "1"
    assert str(cfg.schema_version).lstrip("v").split(".", 1)[0] == "1"
    # And the manifest section's schema_version inherits the same major.
    section = build_unity_urp_manifest_section()
    assert str(section["schema_version"]).lstrip("v").split(".", 1)[0] == "1"


def test_d1_regression_export_unity_urp_default_backends_still_intact():
    """D1 regression — the four FREE URP backends and core fields still emit."""
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
    assert urp["upscaler"]["backend"] == "stp_1_0"
    # All four upgrade_compat tuples present.
    for slot in ("water", "sky", "atmospheric", "upscaler"):
        assert isinstance(urp[slot]["upgrade_compat"], list)
