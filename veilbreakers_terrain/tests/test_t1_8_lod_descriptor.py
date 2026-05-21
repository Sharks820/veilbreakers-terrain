"""T1-8 regression — Unity LOD distance descriptor emission (Y04 v2-ord 25).

Before this PR, the Python descriptor builder
(``terrain_unity_export._build_unity_import_descriptor``) emitted NO
``lod0_distance_m`` / ``lod1_distance_m`` / ``lod2_distance_m`` keys, so
Unity's ``VbTerrainTileMetadata`` fell back to literal ``50f/150f/400f``
defaults in ``unity_plugin/VbTerrainTileMetadata.cs``. The
``aaa_open_world`` profile's ``lod_max_distance_m=2000.0`` was silently
discarded, capping the outer LOD ring at 400 m (5x too small — AAA-tier
terrain detail vanished a quarter of the way out from where it should).

This test file pins (PR #117 round-3, CHECKPOINT-4 V2; round-4 docstring
sweep):
1. All 3 keys are present in the emitted ``unity_import_descriptor.json``
   when a real quality profile resolves (aaa_open_world, high_fidelity,
   standard, mobile, and the legacy aliases preview/low/production/hero_shot).
2. The fan-out is exactly ``lod_max * (0.25, 0.75, 1.0)``.
3. The ``aaa_open_world`` profile yields ``lod2_distance_m == 2000.0``
   (the key regression in the audit).
4. When the profile is unresolved (None / empty / ``"default"`` / unknown
   name), the descriptor OMITS the keys entirely. The Python side never
   emits 50 / 150 / 400 m itself; those numbers are observable only on the
   C# side as the struct defaults in ``VbTerrainTileMetadata.cs:46-48``
   (``Lod0DistanceM=50f``, ``Lod1DistanceM=150f``, ``Lod2DistanceM=400f``).
   When the JSON keys are absent JsonUtility leaves the C# struct fields
   at those defaults, all pass the > 0f gate at
   ``VbTerrainImporter.cs:389-391``, and Unity binds the literal C# values
   — exactly matching pre-T1-8 behaviour. The Python and C# sides AGREE on
   the fallback by KEY ABSENCE on the JSON hop, not by Python mirroring
   the C# literals. Round-2 (8b0d9d43) regressed this by emitting
   100/300/400 m for the default profile via a 400 m sentinel fan-out
   ``400 * (0.25, 0.75, 1.0)``, doubling LOD0 (50→100) and LOD1 (150→300)
   ring distances. Round-3 deleted the sentinel; round-4 deleted the
   ``_LOD_LEGACY_FALLBACK_MAX_DISTANCE_M`` global (CodeQL unused-symbol).
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
    _resolve_lod_max_distance_m,
    export_unity_manifest,
)

# C# struct-default LOD distances are the canonical source of truth for the
# no-profile fallback path. They live in
# ``unity_plugin/VbTerrainTileMetadata.cs:46-48``
# (``Lod0DistanceM=50f``, ``Lod1DistanceM=150f``, ``Lod2DistanceM=400f``).
# Python never emits these numbers itself; the tests below assert key ABSENCE
# from the descriptor on the unresolved-profile path so that JsonUtility on
# the C# side falls through to these defaults. The literal is reproduced here
# only as a test-side proxy for the regression bound (e.g. the
# ``aaa_open_world`` ``lod2 == 5x C# default == 2000.0`` witness).
_CSHARP_LOD2_DEFAULT_M = 400.0


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

    def test_none_profile_returns_none(self) -> None:
        """PR #117 round-3: ``None`` → ``None`` so the descriptor builder
        OMITS the lod_*_distance_m keys and the C# importer falls back to
        literal 50/150/400 m. Round-2 returned 400.0 here which caused
        round-2 to emit 100/300/400 m, doubling LOD0 (50→100) and LOD1
        (150→300) ring distances (silent perf regression)."""
        assert _resolve_lod_max_distance_m(None) is None

    def test_empty_string_returns_none(self) -> None:
        """PR #117 round-3: empty string → ``None`` → keys omitted → C#
        literal 50/150/400 m fallback (pre-T1-8 behaviour preserved)."""
        assert _resolve_lod_max_distance_m("") is None

    def test_default_profile_name_returns_none(self) -> None:
        """PR #117 round-3: ``export_unity_manifest`` writes ``profile or
        "default"`` into the manifest; the resolver must treat ``"default"``
        as "no profile" and return ``None`` rather than crashing on the
        unknown key or — round-2 regression — returning the 400 m fallback
        and fan-out emitting 100/300/400 m."""
        assert _resolve_lod_max_distance_m("default") is None

    def test_unknown_profile_returns_none(self) -> None:
        """PR #117 round-3: an unknown profile name must NOT raise — Unity
        export is a production hot path. A profile-lookup miss returns
        ``None``, the descriptor builder omits the lod_*_distance_m keys,
        and the C# importer falls back to its literal 50/150/400 m
        defaults rather than failing the entire export."""
        assert _resolve_lod_max_distance_m("cinematic_2050_unknown") is None

    def test_legacy_fallback_sentinel_removed(self) -> None:
        """PR #117 round-4 (CodeQL ``py/unused-global-variable``): the
        historic ``_LOD_LEGACY_FALLBACK_MAX_DISTANCE_M = 400.0`` sentinel
        was removed because no production code path uses it after round-3
        deleted the 400 m fan-out. The C# struct defaults in
        ``unity_plugin/VbTerrainTileMetadata.cs:46-48`` (``Lod0DistanceM=50f``,
        ``Lod1DistanceM=150f``, ``Lod2DistanceM=400f``) are now the single
        source of truth for the no-profile fallback; the Python side
        expresses that fallback by key absence on the JSON hop, not by
        carrying a duplicate constant.

        Pin: the module MUST NOT re-introduce the sentinel (regression net
        for the CodeQL finding and for any future drift that would tempt
        a contributor to start emitting 50/150/400 from Python again)."""
        from veilbreakers_terrain.handlers import terrain_unity_export
        assert not hasattr(
            terrain_unity_export, "_LOD_LEGACY_FALLBACK_MAX_DISTANCE_M"
        ), (
            "PR #117 round-4 removed _LOD_LEGACY_FALLBACK_MAX_DISTANCE_M as "
            "dead code (CodeQL py/unused-global-variable). Reintroducing it "
            "risks Python re-emitting 50/150/400 m and drifting from the "
            "absence-of-keys contract documented in VbTerrainTileMetadata.cs:36-49."
        )

    # ------------------------------------------------------------------
    # PR #117 round-2 — legacy alias pins
    #
    # The ``_BUILTIN_PROFILES`` registry in ``terrain_quality_profiles``
    # exposes four legacy alias names that callers still hard-code in
    # configs / tests:
    #
    #     preview     -> mobile data  (extends=None directly)         -> 200 m
    #     low         -> mobile data  (extends=None directly)         -> 200 m
    #     production  -> standard data, extends="preview"             -> 500 m
    #     hero_shot   -> high_fidelity data, extends="production"     -> 1000 m
    #
    # These pins lock the alias-to-radius mapping that ``_resolve_lod_max
    # _distance_m`` depends on. If a future refactor of the alias chain
    # silently changes any of these values, the Unity LOD ring radius
    # changes underneath every legacy caller without breaking any other
    # test — exactly the silent-default regression class T1-8 was filed
    # to eliminate.
    #
    # Note ``production`` triggers ``DeprecationWarning`` in
    # ``load_quality_profile``. PR #117 round-2 narrowed the helper's
    # ``except`` to ``(ValueError, PresetLocked)`` so the warning is no
    # longer silently swallowed; under ``python -W error`` the alias
    # would now raise and propagate.
    # ------------------------------------------------------------------

    def test_legacy_alias_preview_resolves_to_200m(self) -> None:
        """Legacy alias ``preview`` shares mobile's data -> 200 m."""
        assert _resolve_lod_max_distance_m("preview") == 200.0

    def test_legacy_alias_low_resolves_to_200m(self) -> None:
        """Legacy alias ``low`` shares mobile's data -> 200 m."""
        assert _resolve_lod_max_distance_m("low") == 200.0

    def test_legacy_alias_production_resolves_to_500m(self) -> None:
        """Legacy alias ``production`` extends preview; inheritance merge
        keeps standard's 500 m (max of standard 500 and preview 200)."""
        # Filter the DeprecationWarning that load_quality_profile emits
        # for "production" so this assertion stays clean. The narrowed
        # except in the helper means the warning would otherwise propagate
        # under ``python -W error::DeprecationWarning``.
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            assert _resolve_lod_max_distance_m("production") == 500.0

    def test_legacy_alias_hero_shot_resolves_to_1000m(self) -> None:
        """Legacy alias ``hero_shot`` extends production; inheritance merge
        keeps high_fidelity's 1000 m (max of hf 1000 and production 500)."""
        import warnings
        with warnings.catch_warnings():
            # hero_shot recurses through production which triggers the
            # DeprecationWarning; filter only that warning, not real ones.
            warnings.simplefilter("ignore", DeprecationWarning)
            assert _resolve_lod_max_distance_m("hero_shot") == 1000.0


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
        # The bug-shape explicitly: descriptor lod2 must be 5x the C# struct
        # default (VbTerrainTileMetadata.cs:48 ``Lod2DistanceM=400f``) for the
        # AAA profile. PR #117 round-4 inlined the literal here after the
        # ``_LOD_LEGACY_FALLBACK_MAX_DISTANCE_M`` constant was removed as dead
        # code; the cross-language source of truth is the C# struct field.
        assert descriptor["lod2_distance_m"] == pytest.approx(
            _CSHARP_LOD2_DEFAULT_M * 5.0
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

    def test_no_profile_omits_keys_preserving_csharp_literal_fallback(self) -> None:
        """PR #117 round-3 (CHECKPOINT-4 V2 regression fix): when no profile
        is supplied, the descriptor MUST OMIT the ``lod{0,1,2}_distance_m``
        keys so the C# importer's literal-fallback path runs.

        Read-side wiring (validated):
        - ``unity_plugin/Editor/VbTerrainImporter.cs:78-80`` declares the
          struct fields with defaults ``50f / 150f / 400f``.
        - ``VbTerrainImporter.cs:389-391`` gate ``descriptor.lodN_distance_m
          > 0f`` — when JSON keys are absent, JsonUtility leaves the fields
          at their struct defaults (50/150/400), all > 0, so the gate
          passes through and ``metadata.LodNDistanceM`` ends up at the
          literal C# defaults from ``VbTerrainTileMetadata.cs:46-48``
          (also ``50f / 150f / 400f``). Exactly the pre-T1-8 behaviour.

        Round-2 (8b0d9d43) regressed this: ``_resolve_lod_max_distance_m``
        returned the 400 m legacy fallback, and the builder fanned out
        ``400 * (0.25, 0.75, 1.0) = 100/300/400`` into the descriptor —
        doubling LOD0 (50→100) and LOD1 (150→300) ring distances vs.
        pre-T1-8. Silent perf regression: more terrain rendered at
        LOD0/LOD1 detail than the C# defaults intended.
        """
        descriptor = _export_and_load_descriptor(None)
        assert "lod0_distance_m" not in descriptor, (
            "PR #117 round-3: lod0_distance_m must be ABSENT for unresolved "
            "profile so VbTerrainImporter.cs:389 falls back to literal 50f. "
            "Round-2 emitted 100.0 here (LOD0 ring doubled — silent regression)."
        )
        assert "lod1_distance_m" not in descriptor, (
            "PR #117 round-3: lod1_distance_m must be ABSENT for unresolved "
            "profile so VbTerrainImporter.cs:390 falls back to literal 150f. "
            "Round-2 emitted 300.0 here (LOD1 ring doubled — silent regression)."
        )
        assert "lod2_distance_m" not in descriptor, (
            "PR #117 round-3: lod2_distance_m must be ABSENT for unresolved "
            "profile so VbTerrainImporter.cs:391 falls back to literal 400f."
        )

    def test_default_profile_does_not_emit_keys_preserving_csharp_50_150_400_fallback(self) -> None:
        """PR #117 round-3: explicit absence-of-keys pin across every
        unresolved-profile spelling (None / "" / "default" / unknown).

        ``export_unity_manifest`` writes ``profile or "default"`` into the
        manifest; round-2 regressed all 4 spellings to emit 100/300/400 m
        via the 400 m sentinel fan-out. Round-3 must omit the keys in all
        4 cases so the C# importer (VbTerrainImporter.cs:389-391) sees
        the JSON keys missing, JsonUtility leaves the descriptor struct
        fields at their default 50/150/400, all pass the ``> 0f`` gate,
        and ``metadata.LodNDistanceM`` lands at the literal C# defaults.
        """
        for profile_arg in (None, "", "default", "cinematic_2050_unknown"):
            descriptor = _export_and_load_descriptor(profile_arg)
            for key in ("lod0_distance_m", "lod1_distance_m", "lod2_distance_m"):
                assert key not in descriptor, (
                    f"PR #117 round-3: profile={profile_arg!r} must NOT emit "
                    f"{key!r} so the C# importer falls back to the literal "
                    f"50/150/400 m defaults in VbTerrainTileMetadata.cs:46-48. "
                    f"Found key with value {descriptor.get(key)!r}."
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
