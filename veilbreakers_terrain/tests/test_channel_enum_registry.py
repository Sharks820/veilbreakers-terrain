"""T0.5-1 regression net — typed Channel enum registry contract.

Y04 v3 §P.8.2 ord 0.5a: closes ZZ4-A6 R1 (Shape A elimination — silent
unit drift between producer and consumer).

This file pins the contract on the new ``Channel`` enum in
``veilbreakers_terrain.handlers._channels``:

1. Every enum value is the canonical string field name on
   ``TerrainMaskStack`` — so ``stack.get(Channel.X.value)`` works for
   migrated and unmigrated callers alike during the incremental migration.
2. Every enum member has a ``ChannelInfo`` with a canonical unit.
3. ``Channel.from_name`` is loud-at-source on unknown strings.
4. The unit set is closed: {m, rad, deg, dimensionless, id, count}.
5. Cross-check: every channel-info unit matches the assertion-site
   registry in ``terrain_golden_snapshots._CHANNEL_CANONICAL_UNITS``
   so the two registries do not drift.

Per FIX_PATTERN_v1.md §3 C4 (boundary contract / typed registry).
"""
from __future__ import annotations

import pytest


def test_channel_enum_values_are_strings() -> None:
    """Each Channel.value must be a string so legacy string-keyed callers
    can read ``Channel.X.value`` and pass it through transparently.
    """
    from veilbreakers_terrain.handlers._channels import Channel

    for ch in Channel:
        assert isinstance(ch.value, str), (
            f"Channel.{ch.name}.value is {type(ch.value).__name__}; must be str"
        )
        assert ch.value, f"Channel.{ch.name}.value is empty"


def test_channel_value_matches_terrain_mask_stack_field() -> None:
    """Every Channel.value should correspond to a real TerrainMaskStack
    field (or a documented export-side channel).

    A few channels (YAW_DEG, ROTATION_Y_RAD) live at export boundaries
    rather than directly on the stack — those are listed in the
    ``_EXPORT_SIDE_CHANNELS`` exemption set.
    """
    from dataclasses import fields

    from veilbreakers_terrain.handlers._channels import Channel
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    stack_fields = {f.name for f in fields(TerrainMaskStack)}
    _EXPORT_SIDE_CHANNELS = {
        Channel.YAW_DEG,
        Channel.ROTATION_Y_RAD,
    }

    for ch in Channel:
        if ch in _EXPORT_SIDE_CHANNELS:
            continue
        assert ch.value in stack_fields, (
            f"Channel.{ch.name} = {ch.value!r} is not a TerrainMaskStack "
            f"field. Either add it to the stack OR mark it export-side "
            f"in _EXPORT_SIDE_CHANNELS in this test."
        )


def test_every_channel_has_channel_info() -> None:
    """The module-level assert in _channels.py guarantees this at import
    time; this test pins it via the public API for forward compat.
    """
    from veilbreakers_terrain.handlers._channels import Channel, ChannelInfo

    for ch in Channel:
        info = ch.info
        assert isinstance(info, ChannelInfo), (
            f"Channel.{ch.name}.info is {type(info).__name__}; must be ChannelInfo"
        )
        assert info.unit, f"Channel.{ch.name}.info.unit is empty"
        assert info.description, (
            f"Channel.{ch.name}.info.description is empty"
        )


def test_canonical_unit_set_is_closed() -> None:
    """The unit string must be one of the closed set {m, rad, deg,
    dimensionless, id, count}. Any other unit is a typo or a new unit
    class that needs explicit consideration.
    """
    from veilbreakers_terrain.handlers._channels import Channel

    allowed = {"m", "rad", "deg", "dimensionless", "id", "count"}
    for ch in Channel:
        assert ch.info.unit in allowed, (
            f"Channel.{ch.name}.info.unit = {ch.info.unit!r} is not in the "
            f"closed unit set {allowed}. Add it explicitly if it's a new "
            f"unit class, OR fix the typo."
        )


def test_from_name_returns_correct_member() -> None:
    from veilbreakers_terrain.handlers._channels import Channel

    assert Channel.from_name("height") is Channel.HEIGHT
    assert Channel.from_name("water_depth_m") is Channel.WATER_DEPTH_M
    assert Channel.from_name("slope") is Channel.SLOPE_RAD
    assert Channel.from_name("yaw_degrees") is Channel.YAW_DEG


def test_from_name_raises_on_unknown_string() -> None:
    """``from_name`` is loud-at-source — typos must not silently succeed."""
    from veilbreakers_terrain.handlers._channels import Channel

    with pytest.raises(KeyError, match="not in the canonical Channel registry"):
        Channel.from_name("water_depth")  # missing _m suffix


def test_maybe_from_name_returns_none_on_unknown() -> None:
    from veilbreakers_terrain.handlers._channels import Channel

    assert Channel.maybe_from_name("water_depth") is None  # missing _m
    assert Channel.maybe_from_name("totally_made_up_channel") is None
    assert Channel.maybe_from_name("height") is Channel.HEIGHT


def test_channels_by_unit_lookup() -> None:
    """``CHANNELS_BY_UNIT`` returns a frozenset of all channels with a
    given canonical unit — useful for boundary validators that need to
    iterate "every meters-channel" or "every radians-channel".
    """
    from veilbreakers_terrain.handlers._channels import (
        CHANNELS_BY_UNIT,
        Channel,
    )

    assert Channel.HEIGHT in CHANNELS_BY_UNIT["m"]
    assert Channel.WATER_DEPTH_M in CHANNELS_BY_UNIT["m"]
    assert Channel.SLOPE_RAD in CHANNELS_BY_UNIT["rad"]
    assert Channel.YAW_DEG in CHANNELS_BY_UNIT["deg"]
    assert Channel.WETNESS in CHANNELS_BY_UNIT["dimensionless"]
    # Categorical IDs (BIOME_ID, NAVMESH_AREA_ID, TIDAL_ZONE_LABEL) are
    # tagged "dimensionless" to match T0.5-5 — they live in the
    # "dimensionless" bucket, not a separate "id" bucket.
    assert Channel.BIOME_ID in CHANNELS_BY_UNIT["dimensionless"]
    assert Channel.FLOW_ACCUMULATION in CHANNELS_BY_UNIT["count"]

    # Sets must be disjoint — a channel can only have one canonical unit.
    seen: set[Channel] = set()
    for _unit, channels in CHANNELS_BY_UNIT.items():
        for ch in channels:
            assert ch not in seen, (
                f"Channel.{ch.name} appears in multiple CHANNELS_BY_UNIT "
                f"buckets — units must be exclusive"
            )
            seen.add(ch)


def test_flow_direction_is_indexed_not_radians() -> None:
    """``flow_direction`` is D8 int8 indices (-1..7) per the producer
    contract in ``_water_network.pass_hydrology`` (which calls
    ``priority_flood_d8`` — see ``_water_network.py:705`` and the
    docstring at ``_water_network.py:296``).

    Pinning this prevents reintroducing the original Codex-P1 regression
    where the channel was misregistered as ``unit="rad"``. The angular
    representation (``flow_direction_rad``) only exists at per-lip
    granularity inside ``terrain_waterfalls.LipCandidate``; it is NOT
    a mask-stack channel.
    """
    from veilbreakers_terrain.handlers._channels import Channel

    assert Channel.FLOW_DIRECTION.value == "flow_direction"
    # MUST NOT be 'rad' — that was the Codex-P1 bug. The unit is tagged
    # 'dimensionless' to match T0.5-5 _CHANNEL_CANONICAL_UNITS; the
    # int8 D8 index-set semantics are documented inline at the registry
    # row in _channels.py and at the registry row in
    # terrain_golden_snapshots._CHANNEL_CANONICAL_UNITS.
    assert Channel.FLOW_DIRECTION.info.unit != "rad", (
        "Codex-P1 regression guard: flow_direction MUST NOT be tagged 'rad' — "
        "pass_hydrology emits D8 int8 indices (-1..7), not radians. "
        "See _water_network.py:705."
    )
    assert Channel.FLOW_DIRECTION.info.unit == "dimensionless", (
        f"Channel.FLOW_DIRECTION.info.unit = {Channel.FLOW_DIRECTION.info.unit!r}; "
        f"must be 'dimensionless' to match T0.5-5 "
        f"terrain_golden_snapshots._CHANNEL_CANONICAL_UNITS."
    )
    # The legacy misleading name must not be present on the enum.
    assert not hasattr(Channel, "FLOW_DIRECTION_RAD"), (
        "Channel.FLOW_DIRECTION_RAD is the misleading legacy name — it must "
        "stay removed. The mask-stack channel is integer-indexed; only "
        "LipCandidate.flow_direction_rad (a derived per-lip scalar) uses radians."
    )


def test_cross_registry_consistency_with_golden_snapshots() -> None:
    """The unit assigned to each channel in this enum must match the
    unit assigned in ``terrain_golden_snapshots._CHANNEL_CANONICAL_UNITS``
    (the T0.5-5 registry). Two registries cannot disagree about the same
    channel's unit — that would itself be a Shape C bug.

    Skips gracefully if the T0.5-5 registry isn't present (e.g. when this
    PR lands before PR #88 / T0.5-5).
    """
    import importlib
    from typing import Any, Mapping, cast

    from veilbreakers_terrain.handlers._channels import Channel

    try:
        golden_snapshots = importlib.import_module(
            "veilbreakers_terrain.handlers.terrain_golden_snapshots"
        )
        canonical_units = cast(
            Mapping[str, str],
            getattr(golden_snapshots, "_CHANNEL_CANONICAL_UNITS", None),
        )
    except ImportError:
        canonical_units = cast("Mapping[str, str] | None", None)

    if canonical_units is None:
        pytest.skip(
            "T0.5-5 _CHANNEL_CANONICAL_UNITS registry not present in this "
            "build — cross-registry check is moot. Will activate once PR "
            "#88 (T0.5-5) lands."
        )

    _unused: Any = canonical_units  # keep type checker calm pre-narrowing

    drifts: list[str] = []
    for ch in Channel:
        gs_unit = canonical_units.get(ch.value)
        if gs_unit is None:
            continue  # not yet registered in golden_snapshots — ok
        enum_unit = ch.info.unit
        # Golden-snapshots registry uses "m" / "rad" / "deg" / "dimensionless"
        # — our enum extends to "id" and "count". Both are non-overlapping
        # with the gs set so any drift is a real bug.
        if enum_unit != gs_unit:
            drifts.append(
                f"Channel.{ch.name} ({ch.value!r}): _channels says {enum_unit!r}, "
                f"golden_snapshots says {gs_unit!r}"
            )
    assert not drifts, (
        "Unit drift between _channels.Channel registry and "
        "terrain_golden_snapshots._CHANNEL_CANONICAL_UNITS:\n  "
        + "\n  ".join(drifts)
    )
