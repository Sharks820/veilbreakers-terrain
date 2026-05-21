"""HOTFIX-7c regression — biome_names must survive to_npz/from_npz round-trip.

Verifier A 2026-05-21 #7: prior to HOTFIX-7c, ``pass_compute_biome_channels``
stamped the Voronoi-cell biome name list onto the stack via
``setattr(stack, "biome_names", ...)`` which bypassed the channel registry.
The list was silently dropped on any ``to_npz`` checkpoint / rollback
restore — downstream macro-color and Unity-export consumers then reverted
to the legacy "biome_id as raw palette index" branch and painted the
wrong material everywhere.

After HOTFIX-7c, ``biome_names`` is a declared dataclass field on
``TerrainMaskStack`` and registered in ``_OPAQUE_CHANNELS`` so the value
participates in ``compute_hash`` / ``to_npz`` / ``from_npz``.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np


def _make_stack(size: int = 4):
    """Tile-local stack used by every test in this module."""
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

    return TerrainMaskStack(
        tile_size=size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=np.zeros((size + 1, size + 1), dtype=np.float64),
    )


# ---------------------------------------------------------------------------
# Channel-registry presence (HOTFIX-7c)
# ---------------------------------------------------------------------------


class TestBiomeNamesChannelRegistry:
    def test_biome_names_is_declared_field(self) -> None:
        """``biome_names`` is a proper dataclass field, not a runtime bolt-on."""
        stack = _make_stack()
        # Default value is None — field exists on every new stack.
        assert hasattr(stack, "biome_names")
        assert stack.biome_names is None

    def test_biome_names_in_opaque_channels(self) -> None:
        """Channel is registered with the opaque-channel persistence path."""
        from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

        assert "biome_names" in TerrainMaskStack._OPAQUE_CHANNELS, (
            "biome_names must be in _OPAQUE_CHANNELS so to_npz / from_npz / "
            "compute_hash all observe writes to the list. Without this "
            "registration the value is silently dropped on checkpoint restore."
        )

    def test_biome_names_accepts_set_protocol(self) -> None:
        """``stack.set("biome_names", ...)`` succeeds without provenance error."""
        stack = _make_stack()
        stack.set("biome_names", ["thornwood_forest", "mountain_pass"], "test_pass")
        assert stack.biome_names == ["thornwood_forest", "mountain_pass"]
        # Provenance is recorded.
        assert stack.populated_by_pass.get("biome_names") == "test_pass"


# ---------------------------------------------------------------------------
# to_npz / from_npz round-trip — the headline regression (HOTFIX-7c)
# ---------------------------------------------------------------------------


class TestBiomeNamesRoundTrip:
    def test_biome_names_survives_npz_round_trip(self, tmp_path: "Path") -> None:
        """The list of biome names survives a checkpoint save/restore.

        Headline Verifier A #7 regression: prior code path used
        ``setattr(stack, "biome_names", ...)`` which DID set the attribute
        in-memory but the channel was NOT in any registry, so ``to_npz``
        skipped it and ``from_npz`` left it as the dataclass default
        (``None``). Downstream consumers (``compute_macro_color``,
        ``terrain_caves``, ``terrain_unity_export``) then took the
        legacy "no name list available" branch and painted using
        biome_id as a raw palette index.
        """
        from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

        stack = _make_stack(size=4)
        names = ["thornwood_forest", "mountain_pass", "frozen_hollows"]
        stack.set("biome_names", names, "biome_channels")

        out_path = tmp_path / "biome_names_round_trip.npz"
        stack.to_npz(out_path)

        restored = TerrainMaskStack.from_npz(out_path)
        assert restored.biome_names is not None, (
            "biome_names dropped on from_npz — HOTFIX-7c regression. "
            "Channel must be in _OPAQUE_CHANNELS for the to_npz "
            "meta['opaque_channels'] block to persist it."
        )
        assert restored.biome_names == names, (
            f"biome_names round-trip mismatch: saved={names!r}, "
            f"restored={restored.biome_names!r}"
        )

    def test_biome_names_none_round_trips_as_none(self, tmp_path: "Path") -> None:
        """When biome_names is never set, restoration leaves it as None.

        Guards against accidentally promoting unset channels to an
        empty list / sentinel on the way through opaque-channels meta.
        """
        from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack

        stack = _make_stack()
        assert stack.biome_names is None
        out_path = tmp_path / "biome_names_unset.npz"
        stack.to_npz(out_path)
        restored = TerrainMaskStack.from_npz(out_path)
        assert restored.biome_names is None

    def test_biome_names_participates_in_content_hash(self) -> None:
        """compute_hash() observes biome_names writes — required so two
        stacks that differ only in biome_names produce different hashes,
        which the rollback path uses to detect divergence."""
        stack_a = _make_stack()
        stack_b = _make_stack()
        # Identical heightmaps -> identical baseline hashes.
        hash_baseline_a = stack_a.compute_hash()
        hash_baseline_b = stack_b.compute_hash()
        assert hash_baseline_a == hash_baseline_b

        # Diverge on biome_names only.
        stack_a.set("biome_names", ["forest"], "test")
        stack_b.set("biome_names", ["desert"], "test")
        hash_a = stack_a.compute_hash()
        hash_b = stack_b.compute_hash()
        assert hash_a != hash_b, (
            "compute_hash MUST observe biome_names writes. If two stacks "
            "with different biome_names produce the same hash, rollback "
            "cannot detect divergence — corrupted biome state will "
            "silently leak into downstream passes."
        )

    def test_biome_names_survives_pass_compute_biome_channels(self) -> None:
        """End-to-end: the production producer writes biome_names through the
        proper channel path, so the value is hash-observed and survives
        serialization.
        """
        from veilbreakers_terrain.handlers.terrain_pipeline import (
            pass_compute_biome_channels,
        )
        from veilbreakers_terrain.handlers.terrain_semantics import (
            TerrainIntentState,
            TerrainPipelineState,
            BBox,
        )

        stack = _make_stack(size=8)
        intent = TerrainIntentState(
            seed=42,
            region_bounds=BBox(0.0, 0.0, 8.0, 8.0),
            tile_size=8,
            cell_size=1.0,
            composition_hints={"biome_count": 3},
        )
        state = TerrainPipelineState(intent=intent, mask_stack=stack)

        result = pass_compute_biome_channels(state, region=None)
        assert result.status == "ok"
        # The list of canonical biome names IS attached, NOT via setattr
        # bolt-on (which would defeat the registry).
        assert stack.biome_names is not None
        assert isinstance(stack.biome_names, list)
        assert len(stack.biome_names) >= 1
        # The list is hash-observed (post-fix); writing it bumps content_hash.
        assert stack.populated_by_pass.get("biome_names") == "biome_channels"
