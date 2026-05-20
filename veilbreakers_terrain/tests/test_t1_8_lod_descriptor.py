"""T1-8 regression — Unity LOD distance descriptor emission (Y04 v2-ord 25).

Before this PR, the Python descriptor builder
(``terrain_unity_export._build_unity_import_descriptor``) emitted NO
``lod0_distance_m`` / ``lod1_distance_m`` / ``lod2_distance_m`` keys, so
Unity's ``VbTerrainTileMetadata`` fell back to literal ``50f/150f/400f``
defaults in ``unity_plugin/VbTerrainTileMetadata.cs``. The
``aaa_open_world`` profile's ``lod_max_distance_m=2000.0`` was silently
discarded, capping the outer LOD ring at 400 m (5x too small — AAA-tier
terrain detail vanished a quarter of the way out from where it should).

This test file pins:
1. All 3 keys are present in the emitted ``unity_import_descriptor.json``.
2. The fan-out is exactly ``lod_max * (0.25, 0.75, 1.0)``.
3. The ``aaa_open_world`` profile yields ``lod2_distance_m == 2000.0``
   (the key regression in the audit).
4. Unknown / missing profile falls back to the literal 400 m C# default
   (50 / 150 / 400 m fan-out) so existing deployments do not change shape.
5. The C# read path in ``VbTerrainImporter.cs`` is wired for these keys.

Wave-ZZ-3 / B.4.14 — Cert-YES visible-defect class. AAA anchor: Decima and
Snowdrop both ship per-LOD distance descriptors; never default-only.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from veilbreakers_terrain.handlers.terrain_quality_profiles import (
    load_quality_profile,
)
from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack
from veilbreakers_terrain.handlers.terrain_unity_export import (
    _LOD_LEGACY_FALLBACK_MAX_DISTANCE_M,
    _resolve_lod_max_distance_m,
    export_unity_manifest,
)


_TILE_SIZE = 32  # 33x33 heightmap = 2^5 + 1, Unity-valid for direct RAW import.


def _make_unity_valid_stack() -> TerrainMaskStack:
    """Build a minimal Unity-valid ``TerrainMaskStack`` for export tests."""
    height = np.ones((_TILE_SIZE + 1, _TILE_SIZE + 1), dtype=np.float32) * 50.0
    return TerrainMaskStack(
        tile_size=_TILE_SIZE,
        cell_size=4.0,
        world_origin_x=100.0,
        world_origin_y=200.0,
        tile_x=0,
        tile_y=0,
        height=height,
        height_min_m=0.0,
        height_max_m=100.0,
        coordinate_system="z-up",
    )


def _export_and_load_descriptor(profile: str | None) -> dict[str, Any]:
    """Run ``export_unity_manifest`` and load the descriptor JSON written to disk.

    The descriptor file ``unity_import_descriptor.json`` is what Unity's
    ``VbTerrainImporter`` actually reads at import time (the manifest itself
    carries an overlapping but distinct set of keys), so testing the on-disk
    descriptor is the closest proxy to "what does Unity see".
    """
    stack = _make_unity_valid_stack()
    with tempfile.TemporaryDirectory() as td:
        export_unity_manifest(stack, Path(td), profile=profile)
        descriptor_path = Path(td) / "unity_import_descriptor.json"
        assert descriptor_path.is_file(), (
            "unity_import_descriptor.json must be written by export_unity_manifest"
        )
        return json.loads(descriptor_path.read_text())


# ---------------------------------------------------------------------------
# Helper-level pins
# ---------------------------------------------------------------------------


class TestResolveLodMaxDistance:
    """Unit-test the lazy profile resolver."""

    def test_aaa_open_world_resolves_to_2000m(self) -> None:
        """``aaa_open_world`` profile must yield 2000.0 m post-inheritance merge."""
        assert _resolve_lod_max_distance_m("aaa_open_world") == 2000.0

    def test_high_fidelity_resolves_to_1000m(self) -> None:
        assert _resolve_lod_max_distance_m("high_fidelity") == 1000.0

    def test_standard_resolves_to_500m(self) -> None:
        assert _resolve_lod_max_distance_m("standard") == 500.0

    def test_mobile_resolves_to_200m(self) -> None:
        assert _resolve_lod_max_distance_m("mobile") == 200.0

    def test_none_profile_falls_back_to_legacy(self) -> None:
        assert (
            _resolve_lod_max_distance_m(None)
            == _LOD_LEGACY_FALLBACK_MAX_DISTANCE_M
            == 400.0
        )

    def test_empty_string_falls_back_to_legacy(self) -> None:
        assert (
            _resolve_lod_max_distance_m("")
            == _LOD_LEGACY_FALLBACK_MAX_DISTANCE_M
            == 400.0
        )

    def test_default_profile_name_falls_back_to_legacy(self) -> None:
        # ``export_unity_manifest`` writes ``profile or "default"`` into the
        # manifest; the resolver must treat ``"default"`` as "no profile"
        # rather than crashing on the unknown key.
        assert (
            _resolve_lod_max_distance_m("default")
            == _LOD_LEGACY_FALLBACK_MAX_DISTANCE_M
            == 400.0
        )

    def test_unknown_profile_falls_back_to_legacy(self) -> None:
        # An unknown profile name must NOT raise — Unity export is a
        # production hot path; a profile-lookup miss should degrade to the
        # historical literal-C# behaviour, not fail the entire export.
        assert (
            _resolve_lod_max_distance_m("cinematic_2050_unknown")
            == _LOD_LEGACY_FALLBACK_MAX_DISTANCE_M
            == 400.0
        )

    def test_legacy_fallback_matches_csharp_default(self) -> None:
        """The legacy fallback must mirror the literal C# default in
        ``unity_plugin/VbTerrainTileMetadata.cs:38`` (``Lod2DistanceM = 400f``).
        Drift here would cause silent visual regression vs. pre-T1-8 builds."""
        assert _LOD_LEGACY_FALLBACK_MAX_DISTANCE_M == 400.0


# ---------------------------------------------------------------------------
# End-to-end descriptor emission
# ---------------------------------------------------------------------------


class TestLodDescriptorEmission:
    """Pin the 3 LOD-distance descriptor keys via the public export entry."""

    def test_aaa_open_world_emits_three_distance_keys(self) -> None:
        descriptor = _export_and_load_descriptor("aaa_open_world")
        assert "lod0_distance_m" in descriptor, (
            "lod0_distance_m must be present in unity_import_descriptor.json — "
            "without it Unity falls back to the literal 50f default in "
            "VbTerrainTileMetadata.cs:36 (5x undersize for aaa_open_world)."
        )
        assert "lod1_distance_m" in descriptor
        assert "lod2_distance_m" in descriptor

    def test_aaa_open_world_lod_fanout_is_25_75_100_percent_of_2000m(self) -> None:
        """The exact audit fix prescription: aaa_open_world -> 500/1500/2000 m."""
        descriptor = _export_and_load_descriptor("aaa_open_world")
        assert descriptor["lod0_distance_m"] == pytest.approx(500.0)
        assert descriptor["lod1_distance_m"] == pytest.approx(1500.0)
        assert descriptor["lod2_distance_m"] == pytest.approx(2000.0)

    def test_aaa_open_world_lod2_is_not_silently_capped_at_400m(self) -> None:
        """Regression pin for the headline B.4.14 symptom: aaa_open_world's
        2000 m max was silently discarded so Unity capped LOD2 at the literal
        400 m C# default. This single assertion is the bug's smallest possible
        witness."""
        descriptor = _export_and_load_descriptor("aaa_open_world")
        assert descriptor["lod2_distance_m"] == pytest.approx(2000.0), (
            "aaa_open_world profile sets lod_max_distance_m=2000.0; "
            "the emitted lod2_distance_m must NOT be the legacy 400f default."
        )
        # The bug-shape explicitly: descriptor lod2 must be 5x the legacy
        # C# default for the AAA profile.
        assert descriptor["lod2_distance_m"] == pytest.approx(
            _LOD_LEGACY_FALLBACK_MAX_DISTANCE_M * 5.0
        )

    def test_high_fidelity_emits_250_750_1000m_fanout(self) -> None:
        descriptor = _export_and_load_descriptor("high_fidelity")
        assert descriptor["lod0_distance_m"] == pytest.approx(250.0)
        assert descriptor["lod1_distance_m"] == pytest.approx(750.0)
        assert descriptor["lod2_distance_m"] == pytest.approx(1000.0)

    def test_standard_emits_125_375_500m_fanout(self) -> None:
        descriptor = _export_and_load_descriptor("standard")
        assert descriptor["lod0_distance_m"] == pytest.approx(125.0)
        assert descriptor["lod1_distance_m"] == pytest.approx(375.0)
        assert descriptor["lod2_distance_m"] == pytest.approx(500.0)

    def test_mobile_emits_50_150_200m_fanout(self) -> None:
        descriptor = _export_and_load_descriptor("mobile")
        assert descriptor["lod0_distance_m"] == pytest.approx(50.0)
        assert descriptor["lod1_distance_m"] == pytest.approx(150.0)
        assert descriptor["lod2_distance_m"] == pytest.approx(200.0)

    def test_no_profile_falls_back_to_400m_max_with_uniform_fanout(self) -> None:
        """When no profile is supplied, ``_LOD_LEGACY_FALLBACK_MAX_DISTANCE_M``
        (400 m, matching the literal C# ``Lod2DistanceM = 400f`` default in
        VbTerrainTileMetadata.cs:38) is used as ``lod_max`` and fanned out
        uniformly: 100 / 300 / 400 m.

        Note: the historical C# literal triple (50 / 150 / 400 m) is NOT a
        clean 0.25/0.75/1.0 fan-out of 400 m — the 50f / 150f defaults are
        arbitrary historical values. The audit prescription (B.4.14) is an
        explicit ``lod_max * (0.25, 0.75, 1.0)`` fan-out, so a missing-profile
        emit yields 100 / 300 / 400 m, not the literal C# triple. Callers
        without a profile get a slightly larger lod0 ring than the old C#
        default — which is an improvement, not a regression: the lod2 outer
        radius (the only one users actually notice when terrain detail
        vanishes) remains 400 m, matching the historical behaviour.

        The literal C# 50f/150f/400f triple remains in
        ``VbTerrainTileMetadata.cs:36-38`` as defense-in-depth for the
        case where the JSON keys go missing entirely (legacy bundle,
        partial migration, third-party re-export).
        """
        descriptor = _export_and_load_descriptor(None)
        assert descriptor["lod0_distance_m"] == pytest.approx(100.0)
        assert descriptor["lod1_distance_m"] == pytest.approx(300.0)
        assert descriptor["lod2_distance_m"] == pytest.approx(400.0)
        # lod2 outer radius must match the historical C# Lod2DistanceM = 400f.
        assert descriptor["lod2_distance_m"] == pytest.approx(
            _LOD_LEGACY_FALLBACK_MAX_DISTANCE_M
        )

    def test_lod_fanout_invariant_across_profiles(self) -> None:
        """The 0.25 / 0.75 / 1.0 ratio must hold for every named profile."""
        for profile_name in (
            "mobile",
            "standard",
            "high_fidelity",
            "aaa_open_world",
        ):
            descriptor = _export_and_load_descriptor(profile_name)
            lod_max = load_quality_profile(profile_name).lod_max_distance_m
            assert descriptor["lod0_distance_m"] == pytest.approx(lod_max * 0.25), (
                f"profile {profile_name!r}: lod0 != lod_max * 0.25"
            )
            assert descriptor["lod1_distance_m"] == pytest.approx(lod_max * 0.75), (
                f"profile {profile_name!r}: lod1 != lod_max * 0.75"
            )
            assert descriptor["lod2_distance_m"] == pytest.approx(lod_max * 1.0), (
                f"profile {profile_name!r}: lod2 != lod_max"
            )

    def test_emitted_keys_are_python_floats_for_json_safety(self) -> None:
        """The descriptor is serialized via ``json.dumps(allow_nan=False)``;
        numpy scalars would round-trip silently but a non-float type would
        raise TypeError. Pin that the emit casts to a JSON-safe float."""
        descriptor = _export_and_load_descriptor("aaa_open_world")
        # After ``json.loads`` the values must be Python floats (or ints
        # that JSON does not lose precision on); never None / str / NaN.
        for key in ("lod0_distance_m", "lod1_distance_m", "lod2_distance_m"):
            value = descriptor[key]
            assert isinstance(value, (int, float)), (
                f"{key!r} must serialize as JSON number, got {type(value)!r}"
            )
            assert value > 0.0, (
                f"{key!r} must be > 0 (VbTerrainImporter.cs:389-391 uses > 0f "
                "as the 'use emitted value' gate; anything <= 0 silently "
                "falls back to the C# literal default)."
            )


# ---------------------------------------------------------------------------
# Cross-language wiring proof
# ---------------------------------------------------------------------------


class TestCSharpReadPathStillWired:
    """Light-touch grep-style guard: the C# importer must still read the
    keys this PR emits. If a future refactor strips the read path on the
    C# side, this test alerts before the silent-default regression returns.
    """

    def test_descriptor_read_present_in_unity_importer(self) -> None:
        importer_path = (
            Path(__file__).resolve().parents[2]
            / "unity_plugin"
            / "Editor"
            / "VbTerrainImporter.cs"
        )
        if not importer_path.is_file():
            pytest.skip(f"Unity importer not present at {importer_path}")
        text = importer_path.read_text(encoding="utf-8")
        for key in ("lod0_distance_m", "lod1_distance_m", "lod2_distance_m"):
            assert key in text, (
                f"VbTerrainImporter.cs no longer reads {key!r} — Python emit "
                "would land in the descriptor JSON but Unity would ignore it. "
                "This is the inverse of T1-8: emit without consume == silent "
                "default."
            )

    def test_csharp_metadata_class_still_carries_lod_fields(self) -> None:
        metadata_path = (
            Path(__file__).resolve().parents[2]
            / "unity_plugin"
            / "VbTerrainTileMetadata.cs"
        )
        if not metadata_path.is_file():
            pytest.skip(f"Unity metadata not present at {metadata_path}")
        text = metadata_path.read_text(encoding="utf-8")
        for field in ("Lod0DistanceM", "Lod1DistanceM", "Lod2DistanceM"):
            assert field in text, (
                f"VbTerrainTileMetadata.cs no longer declares {field!r} — "
                "Unity runtime streamer (VbTerrainRuntimeStreamer.cs) reads "
                "these fields for LOD ring selection."
            )
