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
    dimensionless, id, count, unit_normal_xyz}. Any other unit is a typo
    or a new unit class that needs explicit consideration.

    UT-C1 (CHECKPOINT-OPUS-ULTRA hotfix): added ``unit_normal_xyz`` for
    the strata_orientation channel which is a (H, W, 3) direction-cosine
    field, not radians. Adding the unit explicitly here keeps the
    closed-set invariant intact while welcoming the new class.
    """
    from veilbreakers_terrain.handlers._channels import Channel

    allowed = {
        "m", "rad", "deg", "dimensionless", "id", "count",
        "unit_normal_xyz",
    }
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

    PR #88 (_CHANNEL_CANONICAL_UNITS) has landed; the skip path is now
    a hard import-error guard, not a graceful pre-#88 fallback.
    """
    from veilbreakers_terrain.handlers._channels import Channel
    from veilbreakers_terrain.handlers.terrain_golden_snapshots import (
        _CHANNEL_CANONICAL_UNITS,
    )

    drifts: list[str] = []
    for ch in Channel:
        gs_unit = _CHANNEL_CANONICAL_UNITS.get(ch.value)
        if gs_unit is None:
            continue  # not yet registered in golden_snapshots — bidirectional
            # test below catches this side; this loop only validates
            # unit-agreement for the symmetric subset.
        enum_unit = ch.info.unit
        # Golden-snapshots registry uses "m" / "rad" / "deg" / "dimensionless" /
        # "count" — enum uses the same set. Any disagreement is a real bug.
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


def test_all_channels_have_canonical_unit() -> None:
    """Forward-direction cross-registry walk: every Channel enum value
    must have a unit declaration in ``_CHANNEL_CANONICAL_UNITS``.

    Closes the enum-only side of the V4-reported asymmetry surface
    (CHECKPOINT-OPUS-ULTRA P1-CCU-A1). Channels added to ``Channel``
    without a matching ``_CHANNEL_CANONICAL_UNITS`` entry would
    silently bypass the unit-drift gate at the assertion site
    (``_channel_unit_mismatch`` returns None for unregistered keys).

    Pinning this prevents reintroduction of the 8 enum-only channels
    reported in the V4 audit: tidal_zone_label, water_surface_mask,
    cave_candidate, flow_accumulation, erosion_amount,
    deposition_amount, curvature, bank_instability.
    """
    from veilbreakers_terrain.handlers._channels import Channel
    from veilbreakers_terrain.handlers.terrain_golden_snapshots import (
        _CHANNEL_CANONICAL_UNITS,
    )

    missing_in_units = [
        c.value for c in Channel if c.value not in _CHANNEL_CANONICAL_UNITS
    ]
    assert not missing_in_units, (
        f"Cross-registry drift: {missing_in_units} are in Channel enum "
        "but NOT in _CHANNEL_CANONICAL_UNITS. Add them to "
        "terrain_golden_snapshots.py to close the V4 Shape-A "
        "silent-corruption surface."
    )


def test_channel_canonical_units_keys_all_exist_in_channel_enum() -> None:
    """Inverse cross-registry walk: every key in
    ``_CHANNEL_CANONICAL_UNITS`` must resolve via
    ``Channel.maybe_from_name`` (i.e. exist as a ``Channel`` enum value).

    Closes the V4-reported asymmetry surface (CHECKPOINT-OPUS-ULTRA
    P1-CCU-A2) where channels added to one registry without the other
    silently bypass unit-drift validation. The pre-existing
    ``test_cross_registry_consistency_with_golden_snapshots`` walks
    ``Channel → _CHANNEL_CANONICAL_UNITS`` only and skips on miss; this
    test closes the inverse direction.

    Pinning this prevents reintroduction of the 2 dict-only channels
    reported in the V4 audit: vb_aspect_deg, macro_color.
    """
    from veilbreakers_terrain.handlers._channels import Channel
    from veilbreakers_terrain.handlers.terrain_golden_snapshots import (
        _CHANNEL_CANONICAL_UNITS,
    )

    enum_values = {c.value for c in Channel}
    missing_in_enum = [
        name for name in _CHANNEL_CANONICAL_UNITS if name not in enum_values
    ]
    assert not missing_in_enum, (
        f"Cross-registry drift: {missing_in_enum} are in "
        "_CHANNEL_CANONICAL_UNITS but NOT in Channel enum. "
        "Add them to handlers/_channels.py Channel class + "
        "_CHANNEL_INFO to close the V4 Shape-A silent-corruption "
        "surface."
    )


def test_channel_registries_are_symmetric_set_equality() -> None:
    """Stronger summary form of the two directional tests above —
    asserts the two registries are set-equal so that any future
    additions to one MUST be added to the other in the same PR.

    This is the structural closure for CHECKPOINT-OPUS-ULTRA V4
    P1-CCU-A1 + P1-CCU-A2: the Shape-A silent-corruption class is
    closed permanently when this assertion holds and the two
    directional walks above run.
    """
    from veilbreakers_terrain.handlers._channels import Channel
    from veilbreakers_terrain.handlers.terrain_golden_snapshots import (
        _CHANNEL_CANONICAL_UNITS,
    )

    enum_names = {c.value for c in Channel}
    dict_names = set(_CHANNEL_CANONICAL_UNITS.keys())
    assert enum_names == dict_names, (
        "Channel enum vs _CHANNEL_CANONICAL_UNITS asymmetry. "
        f"Enum-only: {sorted(enum_names - dict_names)}. "
        f"Dict-only: {sorted(dict_names - enum_names)}."
    )


def test_yaw_degrees_and_vb_aspect_deg_are_distinct_axes() -> None:
    """Both Channel.YAW_DEG and Channel.VB_ASPECT_DEG carry unit "deg"
    but represent two distinct physical axes (per-instance rotation
    vs per-cell topographic aspect). Closing CHECKPOINT-OPUS-ULTRA V4
    naming-drift item #11: document the distinction; do NOT unify.
    """
    from veilbreakers_terrain.handlers._channels import Channel

    assert Channel.YAW_DEG.value == "yaw_degrees"
    assert Channel.VB_ASPECT_DEG.value == "vb_aspect_deg"
    # Both must be "deg" but are NOT the same enum member.
    assert Channel.YAW_DEG.info.unit == "deg"
    assert Channel.VB_ASPECT_DEG.info.unit == "deg"
    assert Channel.YAW_DEG is not Channel.VB_ASPECT_DEG, (
        "YAW_DEG (export-side per-instance yaw) and VB_ASPECT_DEG "
        "(mask-stack per-cell topographic aspect) are distinct axes "
        "and must not be unified — see comment block above their enum "
        "entries in handlers/_channels.py."
    )
