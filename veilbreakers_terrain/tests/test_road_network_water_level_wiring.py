"""Regression net for CE-2026-05-24 audit item #2 — in-pipeline ``water_level`` wiring.

`pass_road_network` reads the per-cell ``water_surface_mask`` and
``water_surface_elevation_m`` channels and forwards them to
``compute_road_network``, but historically it NEVER derived/passed the scalar
``water_level`` argument.  Both the water-cost A* penalty
(``compute_road_network`` line ~1474) and bridge detection (line ~1632) are
gated on ``water_level is not None``, so the in-pipeline road path routed
straight through water with ZERO bridges.  The MCP handler
``handle_compute_road_network`` always forwarded ``params['water_level']``, so
only the pipeline pass was affected.

These tests pin a *sane* fix (not just "a bridge appeared").  The follow-up CE
review found the original wiring armed two latent defects:

  * **Flood at the root** — the water-avoidance cost layer was synthesised from
    ``hmap < water_level`` (terrain-vs-scalar), which marks the WHOLE tile 1e6
    when the derived ``water_level`` sits at/above the surrounding terrain.  A*
    then contorts and emits dozens of phantom bridges with out-of-bounds decks
    (CE measured 62 bridges / 2581 m on a 24 m tile).  Fixed in
    ``compute_road_network`` by preferring the supplied per-cell ``water_mask``
    for the cost layer; the synthetic mask is only a last resort.
  * **Shape-mismatch crash** — deriving ``water_level`` did ``we[wm]`` with no
    shape guard, so independently-shaped elevation/mask channels would raise
    IndexError, flip the pass ok->failed and roll back every road channel.
    Fixed with a ``wm.shape == we.shape`` guard (graceful degrade to None).

The discriminating contract below asserts a SANE bridge network — a bounded
bridge count, in-bounds decks, and a near-straight road — so the old 62-bridge
tangle can never pass again.

C4 boundary-contract fix per ``FIX_PATTERN_v1.md`` §3.

Failing-before-fix evidence: on origin/main the ``compute_road_network`` call in
``pass_road_network`` omits ``water_level``; the spy captures the ``'ABSENT'``
sentinel (the kwarg is absent, not None) and ``bridge_count`` is 0, so
``test_pipeline_pass_produces_sane_bridge_over_water`` /
``test_water_level_derived_from_wet_cells`` fail.  Before the flood fix the
bridge test passed on a 62-bridge garbage tangle (only ``bridge_count > 0`` was
asserted); the tightened contract now rejects it.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Fixture builder — a road corridor that must cross a wet channel.
# ---------------------------------------------------------------------------
#
# Physical model: dry, level banks with a narrow water channel whose surface
# rises ABOVE the surrounding ground (a reservoir / flooded river crossing the
# road corridor).  The road deck must therefore bridge the wet span.
#
# Why not a deeply-incised channel with steep dry banks above the water?  That
# is the literal "river in a gorge" shape, but it is structurally incompatible
# with this routing stack: A* routes on the BARE terrain (it has no concept of
# planning to bridge), so the moment the path descends a steep channel wall the
# AASHTO grade check fires parabolic hairpin switchbacks (15 m radius) that
# overshoot a small tile and yield exactly the out-of-bounds-deck tangle the CE
# review flagged.  Keeping the banks level (no steep walls -> zero switchbacks)
# isolates the water-cost behaviour under test and lets us assert a tight,
# discriminating contract.  The wet span still sits above the road deck, so the
# valley/water bridge trigger fires for a small, sane number of deck segments.
_BANK_Z = 0.0  # flat dry banks at world z = 0
_WATER_SURFACE_Z = 1.5  # water surface rises 1.5 m above the dry banks
_CHANNEL_HALF_COLS = 1  # 2-column-wide channel (a narrow river)
# The fixed routing seed used by ``pass_road_network`` (intent.seed) yields a
# stable, near-straight A* path across the channel: 7 segments, <=3 wet bridge
# decks, total length ~1.05x the straight-line waypoint distance.
_MAX_SANE_BRIDGES = 3
_MAX_LENGTH_RATIO = 2.0


def _make_water_crossing_state(size: int = 24, cell_size: float = 1.0):
    """Return a TerrainPipelineState with a sane wet crossing on the corridor.

    Layout (rows = y, cols = x; world origin at 0,0):
      - Terrain is flat dry bank at ``_BANK_Z`` (0 m) everywhere.
      - A narrow vertical channel (``2*_CHANNEL_HALF_COLS`` columns) down the
        middle is wet, with the water SURFACE at ``_WATER_SURFACE_Z`` (1.5 m) —
        i.e. the water rises above the dry banks (a reservoir / flooded river).
      - The road waypoints sit on the dry banks at z = ``_BANK_Z``; the road
        stays roughly level and bridges the wet span, so ``_detect_bridges``
        flags a small, in-bounds set of bridge decks once ``water_level`` is
        wired through — without the flood/switchback tangle the CE review found.
    """
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )

    sz_world = size * cell_size

    # Flat dry banks; water lives only in the narrow middle channel.
    height = np.full((size, size), _BANK_Z, dtype=np.float64)
    channel_lo = size // 2 - _CHANNEL_HALF_COLS
    channel_hi = size // 2 + _CHANNEL_HALF_COLS

    # Water surface: wet only in the channel, surface above the dry banks.
    water_mask = np.zeros((size, size), dtype=np.float32)
    water_mask[:, channel_lo:channel_hi] = 1.0
    water_elev = np.zeros((size, size), dtype=np.float32)
    water_elev[:, channel_lo:channel_hi] = _WATER_SURFACE_Z

    stack = TerrainMaskStack(
        tile_size=size,
        cell_size=cell_size,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    # Optional water channels read by pass_road_network.
    stack.set("water_surface_mask", water_mask, "test_fixture")
    stack.set("water_surface_elevation_m", water_elev, "test_fixture")

    mid_y = sz_world * 0.5
    intent = TerrainIntentState(
        tile_size=size,
        cell_size=cell_size,
        seed=42,
        region_bounds=BBox(0.0, 0.0, sz_world, sz_world),
        composition_hints={
            # Waypoints on the dry banks; the road must span the wet channel.
            "road_waypoints": [
                (2.0, mid_y, _BANK_Z),
                (sz_world - 2.0, mid_y, _BANK_Z),
            ],
        },
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


# ---------------------------------------------------------------------------
# The wiring regression — a SANE bridge network must appear over the channel.
# ---------------------------------------------------------------------------


class TestPassRoadNetworkWaterLevelWiring:
    """pass_road_network must derive + forward water_level to compute_road_network."""

    def test_pipeline_pass_produces_sane_bridge_over_water(self) -> None:
        """A road crossing a wet channel must yield a SANE bridge network.

        FAILS on origin/main (pre-wiring): water_level stays None inside
        compute_road_network, the bridge-detection block (gated on
        ``water_level is not None``) never runs, and bridge_count is 0.

        FAILS on the pre-flood-fix commit too: the synthetic ``hmap < water_level``
        cost layer floods the tile and produces a 62-bridge / 2581 m tangle with
        out-of-bounds decks, which the tightened contract below rejects.
        """
        import veilbreakers_terrain.handlers.road_network as rn

        size = 24
        cell_size = 1.0
        state = _make_water_crossing_state(size=size, cell_size=cell_size)

        # Capture the full compute_road_network result so we can inspect the
        # bridge decks (the pass metrics expose only the count).
        captured: dict[str, Any] = {}
        real_compute = rn.compute_road_network

        def _spy(*args: Any, **kwargs: Any) -> dict[str, Any]:
            result = real_compute(*args, **kwargs)
            captured["result"] = result
            return result

        # monkeypatch via attribute swap (no fixture needed here).
        rn.compute_road_network = _spy  # type: ignore[assignment]
        try:
            result = rn.pass_road_network(state, region=None)
        finally:
            rn.compute_road_network = real_compute  # type: ignore[assignment]

        assert result.status == "ok", f"Pass failed: {result}"

        bridge_count = result.metrics["bridge_count"]
        assert bridge_count > 0, (
            "pass_road_network must produce at least one bridge when the road "
            "corridor crosses a wet channel; got bridge_count=0. This means "
            "water_level was not wired through to compute_road_network "
            "(CE-2026-05-24 #2)."
        )
        # TIGHT bound: a sane crossing is a handful of deck spans, NOT the
        # 62-bridge flood tangle the pre-fix water-cost layer produced.
        assert bridge_count <= _MAX_SANE_BRIDGES, (
            f"bridge_count={bridge_count} exceeds the sane bound "
            f"({_MAX_SANE_BRIDGES}); the water-cost layer is flooding the tile "
            "and A* is emitting phantom bridges (CE-2026-05-24 #1 flood bug)."
        )

        # Every bridge deck endpoint must lie within the terrain bounds — the
        # flood tangle produced out-of-bounds decks (e.g. (-1.6, 23.8)).
        sz_world = size * cell_size
        compute_result = captured["result"]
        bridges = compute_result["bridges"]
        assert len(bridges) == bridge_count
        for b in bridges:
            for deck_pt in (b["deck_start"], b["deck_end"]):
                x, y = float(deck_pt[0]), float(deck_pt[1])
                assert 0.0 <= x <= sz_world and 0.0 <= y <= sz_world, (
                    f"bridge deck endpoint {deck_pt!r} is outside terrain bounds "
                    f"[0, {sz_world}]^2 — flood/switchback contortion."
                )

        # Total road length must stay near the straight-line waypoint distance;
        # the flood tangle inflated it >100x.
        waypoints = state.intent.composition_hints["road_waypoints"]
        straight_line = math.dist(waypoints[0][:2], waypoints[1][:2])
        total_length = result.metrics["total_length_m"]
        assert total_length <= _MAX_LENGTH_RATIO * straight_line, (
            f"total road length {total_length:.1f} m exceeds "
            f"{_MAX_LENGTH_RATIO}x the straight-line distance "
            f"({straight_line:.1f} m) — A* is contorting around a flooded tile."
        )

    def test_water_level_derived_from_wet_cells(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """pass_road_network must call compute_road_network with a non-None water_level.

        Spies on compute_road_network to capture the kwargs the pass forwards.
        On origin/main the captured water_level is the ``'ABSENT'`` sentinel (the
        kwarg is omitted entirely); after the fix it is the median
        water_surface_elevation_m over wet cells (== ``_WATER_SURFACE_Z``).
        """
        import veilbreakers_terrain.handlers.road_network as rn

        captured: dict[str, object] = {}
        real_compute = rn.compute_road_network

        def _spy(*args: Any, **kwargs: Any) -> dict[str, Any]:
            captured["water_level"] = kwargs.get("water_level", "ABSENT")
            return real_compute(*args, **kwargs)

        monkeypatch.setattr(rn, "compute_road_network", _spy)

        state = _make_water_crossing_state(size=24)
        rn.pass_road_network(state, region=None)

        wl = captured.get("water_level")
        assert wl is not None and wl != "ABSENT", (
            "pass_road_network must forward a non-None water_level kwarg to "
            f"compute_road_network; captured={wl!r}"
        )
        # Wet cells all carry water_surface_elevation_m == _WATER_SURFACE_Z, so
        # the median is exactly that.
        assert wl == pytest.approx(_WATER_SURFACE_Z, abs=1e-6), (
            f"water_level should be the median wet-cell elevation "
            f"({_WATER_SURFACE_Z} m); got {wl!r}"
        )

    def test_shape_mismatch_degrades_to_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mismatched elevation/mask shapes must degrade to water_level=None, not crash.

        CE-2026-05-24 #2 robustness regression: ``we[wm]`` with mismatched shapes
        raises IndexError, which would flip the pass ok->failed and roll back the
        road channels.  The shape guard must instead leave water_level None
        (byte-identical to the pre-wiring graceful path) and keep status == ok.
        """
        import veilbreakers_terrain.handlers.road_network as rn
        from veilbreakers_terrain.handlers.terrain_semantics import (
            BBox,
            TerrainIntentState,
            TerrainMaskStack,
            TerrainPipelineState,
        )

        captured: dict[str, object] = {}
        real_compute = rn.compute_road_network

        def _spy(*args: Any, **kwargs: Any) -> dict[str, Any]:
            captured["water_level"] = kwargs.get("water_level", "ABSENT")
            return real_compute(*args, **kwargs)

        monkeypatch.setattr(rn, "compute_road_network", _spy)

        size = 16
        # Height/mask at full size, but the elevation channel is a DIFFERENT
        # shape (simulating an upstream channel-shape drift). pass_road_network
        # must not index one with the other.
        stack = TerrainMaskStack(
            tile_size=size,
            cell_size=1.0,
            world_origin_x=0.0,
            world_origin_y=0.0,
            tile_x=0,
            tile_y=0,
            height=np.zeros((size, size), dtype=np.float64),
        )
        wm = np.ones((size, size), dtype=np.float32)
        we_wrong_shape = np.full((size, size // 2), 4.0, dtype=np.float32)
        stack.set("water_surface_mask", wm, "test_fixture")
        stack.set("water_surface_elevation_m", we_wrong_shape, "test_fixture")

        intent = TerrainIntentState(
            tile_size=size,
            cell_size=1.0,
            seed=42,
            region_bounds=BBox(0.0, 0.0, float(size), float(size)),
            composition_hints={
                "road_waypoints": [(2.0, 8.0, 0.0), (float(size) - 2.0, 8.0, 0.0)],
            },
        )
        state = TerrainPipelineState(intent=intent, mask_stack=stack)

        # Must not raise — graceful degrade.
        result = rn.pass_road_network(state, region=None)

        assert result.status == "ok", (
            f"shape mismatch must degrade gracefully, not fail the pass: {result}"
        )
        assert captured.get("water_level") is None, (
            "water_level must be None when the elevation/mask shapes differ; got "
            f"{captured.get('water_level')!r}"
        )

    def test_no_water_channels_keeps_water_level_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no water channels set, water_level must stay None (no false bridges)."""
        import numpy as _np

        import veilbreakers_terrain.handlers.road_network as rn
        from veilbreakers_terrain.handlers.terrain_semantics import (
            BBox,
            TerrainIntentState,
            TerrainMaskStack,
            TerrainPipelineState,
        )

        captured: dict[str, object] = {}
        real_compute = rn.compute_road_network

        def _spy(*args: Any, **kwargs: Any) -> dict[str, Any]:
            captured["water_level"] = kwargs.get("water_level", "ABSENT")
            return real_compute(*args, **kwargs)

        monkeypatch.setattr(rn, "compute_road_network", _spy)

        size = 12
        stack = TerrainMaskStack(
            tile_size=size,
            cell_size=1.0,
            world_origin_x=0.0,
            world_origin_y=0.0,
            tile_x=0,
            tile_y=0,
            height=_np.zeros((size, size), dtype=_np.float64),
        )
        intent = TerrainIntentState(
            tile_size=size,
            cell_size=1.0,
            seed=42,
            region_bounds=BBox(0.0, 0.0, float(size), float(size)),
            composition_hints={
                "road_waypoints": [(2.0, 6.0, 0.0), (10.0, 6.0, 0.0)],
            },
        )
        state = TerrainPipelineState(intent=intent, mask_stack=stack)

        result = rn.pass_road_network(state, region=None)

        assert result.status == "ok"
        assert captured.get("water_level") is None, (
            "water_level must be None when no wet cells are present; got "
            f"{captured.get('water_level')!r}"
        )
        assert result.metrics["bridge_count"] == 0


# ---------------------------------------------------------------------------
# CE-2026-05-24 #1 — water-cost layer must not flood dry land.
# ---------------------------------------------------------------------------


class TestWaterCostLayerNoFlood:
    """The A* water-avoidance cost layer must follow the real per-cell mask.

    Root-cause regression net for the flood bug: ``compute_road_network`` used
    to build the 1e6 cost layer from ``hmap < water_level`` (terrain-vs-scalar).
    When the derived ``water_level`` sits at/above the surrounding terrain (a
    wide or perched water surface — exactly what the median-over-wet-cells
    derivation produces for a raised water body), that floods every dry cell,
    A* contorts, and dozens of phantom bridges appear.  The fix prefers the
    supplied per-cell ``water_mask`` for the cost layer; the synthetic
    ``hmap < water_level`` is only a fallback when no mask is available.
    """

    def _capture_astar_cost_map(
        self,
        *,
        heightmap: "np.ndarray",
        water_level: float,
        water_mask: "np.ndarray | None",
        water_surface_elevation_m: "np.ndarray | None" = None,
    ) -> "np.ndarray | None":
        """Run compute_road_network and return the cost_map the A* received."""
        import veilbreakers_terrain.handlers.road_network as rn

        captured: dict[str, Any] = {}
        original_astar = rn._astar_24dir

        def _capture(
            hmap: Any,
            bounds: Any,
            start: Any,
            end: Any,
            *,
            road_type: str,
            max_grade_pct: float,
            cost_map: Any,
        ) -> list[Any]:
            captured["cost_map"] = cost_map
            return original_astar(
                hmap, bounds, start, end,
                road_type=road_type,
                max_grade_pct=max_grade_pct,
                cost_map=cost_map,
            )

        rn._astar_24dir = _capture  # type: ignore[assignment]
        try:
            size = heightmap.shape[0]
            rn.compute_road_network(
                waypoints=[(1.0, size / 2.0, 0.0), (size - 2.0, size / 2.0, 0.0)],
                water_level=water_level,
                water_mask=water_mask,
                water_surface_elevation_m=water_surface_elevation_m,
                heightmap=heightmap,
                terrain_bounds=(0.0, 0.0, float(size), float(size)),
                use_astar=True,
            )
        finally:
            rn._astar_24dir = original_astar  # type: ignore[assignment]

        return captured.get("cost_map")  # type: ignore[return-value]

    def test_cost_layer_floods_only_masked_cells_not_dry_land(self) -> None:
        """With a real water_mask + a high water_level, only masked cells get 1e6.

        FAILS on the pre-fix code: ``hmap < water_level`` (here 0 < 5) floods the
        WHOLE tile, so ``(cost >= 1e6).sum()`` would be 64, not 16, and the dry
        corner cell would be 1e6 instead of ~0.
        """
        size = 8
        hmap = np.zeros((size, size), dtype=np.float64)  # all dry land at z=0
        water_mask = np.zeros((size, size), dtype=np.float32)
        water_mask[:, 3:5] = 1.0  # narrow real channel (16 cells)
        water_elev = np.zeros((size, size), dtype=np.float32)
        water_elev[:, 3:5] = 5.0
        # Derived water_level (5.0) is far ABOVE the dry terrain (0.0) — the exact
        # condition under which the synthetic mask floods everything.
        cost_map = self._capture_astar_cost_map(
            heightmap=hmap,
            water_level=5.0,
            water_mask=water_mask,
            water_surface_elevation_m=water_elev,
        )

        assert cost_map is not None, "A* must have received a cost_map"
        flooded = np.asarray(cost_map) >= 1e6
        assert int(flooded.sum()) == int((water_mask > 0.5).sum()), (
            "the water-cost layer must flood ONLY the masked wet cells, not dry "
            f"land below water_level; flooded={int(flooded.sum())}, "
            f"mask={int((water_mask > 0.5).sum())} (CE-2026-05-24 #1)."
        )
        assert np.array_equal(flooded, water_mask > 0.5), (
            "flooded cells must match the supplied water_mask exactly."
        )
        # A dry corner cell (outside the mask, but below water_level) stays cheap.
        assert float(np.asarray(cost_map)[0, 0]) < 1e6, (
            "dry land outside the water_mask must not be flooded with 1e6 cost."
        )

    def test_cost_layer_falls_back_to_synthetic_mask_without_water_mask(self) -> None:
        """With no water_mask supplied, the legacy ``hmap < water_level`` synth applies.

        Preserves the pre-existing MCP-path behaviour (``handle_compute_road_network``
        may forward water_level without a mask): every cell below water_level is
        marked 1e6, accumulated onto any caller cost_map.
        """
        size = 8
        hmap = np.zeros((size, size), dtype=np.float64)  # all below water_level
        cost_map = self._capture_astar_cost_map(
            heightmap=hmap,
            water_level=1.0,
            water_mask=None,
        )
        assert cost_map is not None
        flooded = np.asarray(cost_map) >= 1e6
        # 0 < 1.0 everywhere → legacy synth floods the whole tile.
        assert int(flooded.sum()) == size * size, (
            "without a water_mask the synthetic hmap<water_level fallback must "
            f"still flood all sub-surface cells; flooded={int(flooded.sum())}."
        )
