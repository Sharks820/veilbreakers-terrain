"""Regression net for CE-2026-05-24 audit item #2 — in-pipeline ``water_level`` wiring.

`pass_road_network` reads the per-cell ``water_surface_mask`` and
``water_surface_elevation_m`` channels and forwards them to
``compute_road_network``, but historically it NEVER derived/passed the scalar
``water_level`` argument.  Both the water-cost A* penalty
(``compute_road_network`` line ~1463) and bridge detection (line ~1603) are
gated on ``water_level is not None``, so the in-pipeline road path routed
straight through water with ZERO bridges.  The MCP handler
``handle_compute_road_network`` always forwarded ``params['water_level']``, so
only the pipeline pass was affected.

These tests pin the fix: with a clear water body straddling a road corridor,
``pass_road_network`` must derive a representative ``water_level`` from the wet
cells and the bridge/water-cost path must be exercised (``bridge_count > 0``).

C4 boundary-contract fix per ``FIX_PATTERN_v1.md`` §3.

Failing-before-fix evidence: on origin/main the ``compute_road_network`` call in
``pass_road_network`` omits ``water_level``; ``result.metrics['bridge_count']``
is therefore 0 and ``test_pipeline_pass_produces_bridge_over_water`` /
``test_water_level_derived_from_wet_cells`` fail.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Fixture builder — a road corridor that must cross a deep water channel.
# ---------------------------------------------------------------------------


def _make_water_crossing_state(size: int = 24, cell_size: float = 1.0):
    """Return a TerrainPipelineState with a flooded channel across the corridor.

    Layout (rows = y, cols = x; world origin at 0,0):
      - A vertical water channel occupies the middle columns (a "river").
      - In the channel, terrain floor is low (0.0 m) and the water surface sits
        well above it (8.0 m), so it is unambiguously wet and deep.
      - The road waypoints sit on the dry banks at z = 3.0 m, which is below the
        8.0 m water surface mid-span — forcing ``_detect_bridges`` to flag a
        bridge once ``water_level`` is wired through.
    """
    from veilbreakers_terrain.handlers.terrain_semantics import (
        BBox,
        TerrainIntentState,
        TerrainMaskStack,
        TerrainPipelineState,
    )

    sz_world = size * cell_size

    # Banks high (6.0 m), channel floor low (0.0 m) across the middle columns.
    height = np.full((size, size), 6.0, dtype=np.float64)
    channel_lo = size // 2 - 3
    channel_hi = size // 2 + 3
    height[:, channel_lo:channel_hi] = 0.0

    # Water surface: wet only in the channel, surface elevation 8.0 m there.
    water_mask = np.zeros((size, size), dtype=np.float32)
    water_mask[:, channel_lo:channel_hi] = 1.0
    water_elev = np.zeros((size, size), dtype=np.float32)
    water_elev[:, channel_lo:channel_hi] = 8.0

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
            # Waypoints on the dry banks, z below the 8.0 m water surface so a
            # bridge is required to span the flooded channel.
            "road_waypoints": [
                (2.0, mid_y, 3.0),
                (sz_world - 2.0, mid_y, 3.0),
            ],
        },
    )
    return TerrainPipelineState(intent=intent, mask_stack=stack)


# ---------------------------------------------------------------------------
# The wiring regression — bridge must appear over the flooded channel.
# ---------------------------------------------------------------------------


class TestPassRoadNetworkWaterLevelWiring:
    """pass_road_network must derive + forward water_level to compute_road_network."""

    def test_pipeline_pass_produces_bridge_over_water(self) -> None:
        """A road crossing a deep flooded channel must yield >=1 bridge.

        FAILS on origin/main: water_level stays None inside compute_road_network,
        so the bridge-detection block (gated on `water_level is not None`) never
        runs and bridge_count is 0.
        """
        from veilbreakers_terrain.handlers.road_network import pass_road_network

        state = _make_water_crossing_state(size=24)
        result = pass_road_network(state, region=None)

        assert result.status == "ok", f"Pass failed: {result}"
        assert result.metrics["bridge_count"] > 0, (
            "pass_road_network must produce at least one bridge when the road "
            "corridor crosses a deep flooded channel; got "
            f"bridge_count={result.metrics['bridge_count']}. This means "
            "water_level was not wired through to compute_road_network "
            "(CE-2026-05-24 #2)."
        )

    def test_water_level_derived_from_wet_cells(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """pass_road_network must call compute_road_network with a non-None water_level.

        Spies on compute_road_network to capture the kwargs the pass forwards.
        On origin/main the captured water_level is None; after the fix it is the
        median water_surface_elevation_m over wet cells (== 8.0 m here).
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
        # Wet cells all carry water_surface_elevation_m == 8.0, so the median is 8.0.
        assert wl == pytest.approx(8.0, abs=1e-6), (
            f"water_level should be the median wet-cell elevation (8.0 m); got {wl!r}"
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
