"""Regression: seasonal water state must NOT flood the whole tile.

CE 5-agent audit 2026-05-24 items #1 + #9.

Root cause
----------
``apply_seasonal_water_state`` mutated the *binary* ``water_surface_mask``
channel with additive nudges (WET ``+0.15``, FROZEN ``+0.1``) and then
recomputed ``water_surface_elevation_m`` from ``water_surface_mask > 0.0``.

After WET (``+0.15``) every *dry* cell holds ``0.15`` and therefore satisfies
``> 0.0``.  ``_compute_spill_rim_elevation`` then treats the WHOLE TILE as a
single connected wet body, collapses the surface elevation to the global
terrain maximum, and ``pass_water_depth`` floods every basin to mountain
height.  The corruption is silent (no NaN, no raise) and fires whenever
``composition_hints['seasonal_state']`` is ``wet`` or ``frozen``.

Item #9: the wet-threshold also diverged across the codebase
(``> 0.0`` here, ``> 0.5`` in ``pass_bathymetry``, ``<= 0.0`` in
``procedural_grass``).  After the fix the canonical threshold is ``0.5``.

Contract these tests pin
------------------------
1. Seasonal state changes wetness / tidal / ice but NOT the open-water
   *extent* (that requires a hydro sim, not an additive nudge).  The number
   of wet cells after WET / FROZEN must stay ~= the original wet set, NOT
   explode to ~the whole tile.
2. ``water_surface_elevation_m`` on clearly-dry high cells stays at the
   ``0.0`` sentinel (not lifted to the global terrain max).
3. The stored ``water_surface_mask`` is a clean binary ``{0, 1}`` channel.

These tests FAIL on origin/main (the buggy additive path floods the tile)
and PASS after the binarize fix.
"""

from __future__ import annotations

from typing import Generator

import numpy as np
import pytest

from veilbreakers_terrain.handlers.terrain_pipeline import (
    TerrainPassController,
    pass_water_depth,
    register_pass_water_depth,
)
from veilbreakers_terrain.handlers.terrain_semantics import (
    BBox,
    TerrainIntentState,
    TerrainMaskStack,
    TerrainPipelineState,
)
from veilbreakers_terrain.handlers.terrain_water_variants import (
    SeasonalState,
    apply_seasonal_water_state,
    pass_bathymetry,
    register_bathymetry_pass,
)

SHAPE = (33, 33)


@pytest.fixture(autouse=True)
def clean_registry() -> Generator[None, None, None]:
    """Isolate the pass registry — the full-chain test registers passes."""
    TerrainPassController.clear_registry()
    yield
    TerrainPassController.clear_registry()


def _make_basin_stack() -> TerrainMaskStack:
    """A high plateau with one small, low, wet basin in the corner.

    The basin is a 3x3 dip near (3, 3); everything else is a high dry
    plateau.  Only the 9 basin cells are wet in the initial mask.
    """
    # High dry plateau everywhere.
    height = np.full(SHAPE, 100.0, dtype=np.float32)
    # Carve a small low basin: a 3x3 block of low terrain near the corner.
    height[2:5, 2:5] = 1.0

    # Binary wet mask: ONLY the 3x3 basin floor is wet.
    mask = np.zeros(SHAPE, dtype=np.float32)
    mask[2:5, 2:5] = 1.0

    # Spill-rim elevation seeded only over the wet basin.
    elev = np.where(mask > 0.0, 2.0, 0.0).astype(np.float32)

    stack = TerrainMaskStack(
        tile_size=0,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    stack.set("water_surface_mask", mask, "setup")
    stack.set("water_surface_elevation_m", elev, "setup")
    stack.set("wetness", (mask * 0.8).astype(np.float32), "setup")
    stack.set("tidal", np.zeros(SHAPE, dtype=np.float32), "setup")
    return stack


def _wet_cell_count(stack: TerrainMaskStack) -> int:
    mask = np.asarray(stack.get("water_surface_mask"), dtype=np.float32)
    # Canonical wet threshold is 0.5.
    return int(np.count_nonzero(mask > 0.5))


def _dry_high_cell_elevations(stack: TerrainMaskStack) -> np.ndarray:
    """water_surface_elevation_m sampled on the clearly-dry high plateau.

    The plateau cells (height == 100.0) are unambiguously dry land; under a
    correct seasonal pass their water-surface elevation must stay at the 0.0
    dry sentinel.  The flood bug lifted them to the GLOBAL terrain max because
    the spill-rim treated the whole tile as one connected wet body.  This is
    the channel the flood actually lives in (the wet-CELL-COUNT under ``> 0.5``
    never changes on origin/main — see NIT 2 in PR #146), so asserting on it is
    what makes these tests fail on origin/main.
    """
    elev = np.asarray(
        stack.get("water_surface_elevation_m"), dtype=np.float32
    )
    height = np.asarray(stack.height, dtype=np.float32)
    plateau = height >= 99.0
    return elev[plateau]


def test_wet_season_does_not_flood_whole_tile() -> None:
    """WET season must not turn the entire 33x33 tile into one wet body."""
    stack = _make_basin_stack()
    original_wet = _wet_cell_count(stack)
    assert original_wet == 9, "test setup: exactly the 3x3 basin should be wet"

    apply_seasonal_water_state(stack, SeasonalState.WET)

    new_wet = _wet_cell_count(stack)
    total_cells = SHAPE[0] * SHAPE[1]  # 1089

    # (a) wet-cell count must NOT explode toward the whole tile.
    assert new_wet < total_cells // 2, (
        f"WET season flooded the tile: {new_wet}/{total_cells} cells wet "
        f"(started with {original_wet}). Seasonal nudge corrupted the binary "
        f"mask and the spill-rim saw the whole tile as one wet body."
    )
    # Open-water extent is preserved exactly across the season (no hydro sim).
    assert new_wet == original_wet, (
        f"WET season changed open-water extent from {original_wet} to {new_wet}; "
        f"seasonal state must adjust wetness/ice, not open-water extent."
    )

    # (b) THE flood actually lives in the ELEVATION channel — the wet-cell
    # count above never moves on origin/main (the +0.15 nudge lands at 0.15,
    # below the canonical 0.5 reader). The dry high plateau's
    # water_surface_elevation_m must stay at the 0.0 dry sentinel; on
    # origin/main it is lifted to the global terrain max (100.0). This
    # assertion is what makes the test FAIL on origin/main and PASS after fix.
    dry_high_elev = _dry_high_cell_elevations(stack)
    assert np.all(dry_high_elev == 0.0), (
        f"WET season raised water_surface_elevation_m on dry high plateau cells "
        f"(max={float(dry_high_elev.max())}, expected 0.0); the additive-nudge "
        f"flood collapsed the whole-tile spill rim onto dry land."
    )


def test_frozen_season_does_not_flood_whole_tile() -> None:
    """FROZEN season (+0.1 nudge) must not flood the tile either."""
    stack = _make_basin_stack()
    original_wet = _wet_cell_count(stack)

    apply_seasonal_water_state(stack, SeasonalState.FROZEN)

    new_wet = _wet_cell_count(stack)
    total_cells = SHAPE[0] * SHAPE[1]
    assert new_wet < total_cells // 2, (
        f"FROZEN season flooded the tile: {new_wet}/{total_cells} cells wet "
        f"(started with {original_wet})."
    )
    assert new_wet == original_wet

    # The flood lives in the ELEVATION channel (the FROZEN +0.1 nudge lands at
    # 0.1, below the canonical 0.5 reader, so the wet-cell count never moves on
    # origin/main). Dry high plateau cells must keep the 0.0 sentinel; on
    # origin/main they are lifted to the global terrain max — this is what makes
    # the test FAIL on origin/main and PASS after the fix.
    dry_high_elev = _dry_high_cell_elevations(stack)
    assert np.all(dry_high_elev == 0.0), (
        f"FROZEN season raised water_surface_elevation_m on dry high plateau "
        f"cells (max={float(dry_high_elev.max())}, expected 0.0); the additive-"
        f"nudge flood collapsed the whole-tile spill rim onto dry land."
    )


def test_dry_high_cells_elevation_stays_zero_after_wet_season() -> None:
    """Clearly-dry high plateau cells must keep the 0.0 elevation sentinel.

    The buggy additive path lifted EVERY cell's water_surface_elevation_m to
    the global terrain max (100.0) because the spill-rim treated the whole
    tile as wet.  After the fix, dry plateau cells stay at the 0.0 sentinel.
    """
    stack = _make_basin_stack()
    apply_seasonal_water_state(stack, SeasonalState.WET)

    elev = np.asarray(stack.get("water_surface_elevation_m"), dtype=np.float32)
    height = np.asarray(stack.height, dtype=np.float32)

    # A clearly-dry high plateau cell far from the basin.
    far_corner = elev[-1, -1]
    assert far_corner == 0.0, (
        f"Dry plateau corner elevation lifted to {far_corner} (terrain there "
        f"= {height[-1, -1]}); seasonal flood bug raised the spill rim over dry "
        f"land instead of leaving it at the 0.0 dry sentinel."
    )

    # No dry plateau cell (height == 100.0) should carry water elevation.
    plateau = height >= 99.0
    assert np.all(elev[plateau] == 0.0), (
        "Some dry plateau cells carry non-zero water_surface_elevation_m after "
        "WET season — the whole-tile flood bug."
    )


def test_stored_mask_is_clean_binary_after_each_season() -> None:
    """water_surface_mask must remain a clean {0, 1} binary after any season."""
    for season in (
        SeasonalState.DRY,
        SeasonalState.NORMAL,
        SeasonalState.WET,
        SeasonalState.FROZEN,
    ):
        stack = _make_basin_stack()
        apply_seasonal_water_state(stack, season)
        mask = np.asarray(stack.get("water_surface_mask"), dtype=np.float32)
        uniques = np.unique(mask)
        assert np.all(np.isin(uniques, (0.0, 1.0))), (
            f"{season.value} season left non-binary values {uniques.tolist()} "
            f"in water_surface_mask; the binary extent contract was violated."
        )


def test_dry_season_does_not_erase_water_extent() -> None:
    """DRY season's *0.5 must not silently erase the open-water extent.

    On origin/main DRY did ``mask *= 0.5`` (1.0 -> 0.5), and the canonical
    ``> 0.5`` readers (bathymetry) would then see ZERO wet cells — water
    silently vanishes.  After the fix DRY preserves the wet extent.
    """
    stack = _make_basin_stack()
    original_wet = _wet_cell_count(stack)

    apply_seasonal_water_state(stack, SeasonalState.DRY)

    new_wet = _wet_cell_count(stack)
    assert new_wet == original_wet, (
        f"DRY season erased water extent: {original_wet} -> {new_wet} wet cells "
        f"under the canonical >0.5 threshold."
    )


# ---------------------------------------------------------------------------
# Full production-chain integration (NIT 3): seasonal -> bathymetry -> depth
# ---------------------------------------------------------------------------


_BASIN_SPILL_RIM_M = 28.0
_TERRAIN_MAX_M = 190.0


def _make_graded_basin_stack() -> TerrainMaskStack:
    """A graded valley basin: a radial bowl rising from a low wet floor.

    Terrain is a smooth radial bowl — low (~5 m) at the centre, rising to
    ~190 m at the rim corners.  Open water fills only the floor below the
    basin spill rim (~28 m).  This is the GRADED-terrain analogue of the
    showcase scene (valley basin in a mountain bowl) the PR is protecting.
    """
    rows = cols = 48
    yy, xx = np.meshgrid(
        np.linspace(-1.0, 1.0, rows),
        np.linspace(-1.0, 1.0, cols),
        indexing="ij",
    )
    radius = np.sqrt(xx * xx + yy * yy)
    height = (
        5.0 + (_TERRAIN_MAX_M - 5.0) * np.clip(radius, 0.0, 1.0) ** 1.3
    ).astype(np.float32)

    # Wet only where the terrain floor sits below the basin spill rim.
    mask = (height < _BASIN_SPILL_RIM_M).astype(np.float32)
    elev = np.where(mask > 0.5, _BASIN_SPILL_RIM_M, 0.0).astype(np.float32)

    stack = TerrainMaskStack(
        tile_size=0,
        cell_size=4.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=height,
    )
    stack.set("water_surface_mask", mask, "setup")
    stack.set("water_surface_elevation_m", elev, "setup")
    stack.set("wetness", (mask * 0.8).astype(np.float32), "setup")
    stack.set("tidal", np.zeros((rows, cols), dtype=np.float32), "setup")
    return stack


def test_full_chain_wet_season_depth_stays_bounded_by_basin_rim() -> None:
    """Real chain seasonal -> pass_bathymetry -> pass_water_depth must stay bounded.

    On origin/main, WET season inflates ``water_surface_elevation_m`` to the
    GLOBAL terrain max; ``pass_bathymetry`` then carries that inflated surface
    onto the (still-wet) basin cells, and ``pass_water_depth`` computes
    ``depth = max(ws_elev - h, 0)`` ~= the full bowl height (~183 m on a 190 m
    bowl) instead of the basin depth (~26 m below the ~28 m spill rim).

    This is the production blast radius of the seasonal bug — it floods the
    basin to mountain height.  The test runs the REAL registered passes (not a
    reimplementation), asserting the resulting surface/depth stays bounded by
    the basin spill rim, NOT the global terrain max.  It FAILS on origin/main
    (depth ~= 183 m) and PASSES after the binarize fix (depth ~= 26 m).
    """
    register_bathymetry_pass()
    register_pass_water_depth()

    stack = _make_graded_basin_stack()
    height = np.asarray(stack.height, dtype=np.float32)
    rows, cols = height.shape

    # The real production pass order.
    apply_seasonal_water_state(stack, SeasonalState.WET)

    region = BBox(
        0.0, 0.0, float(cols) * stack.cell_size, float(rows) * stack.cell_size
    )
    intent = TerrainIntentState(
        seed=1,
        region_bounds=region,
        tile_size=rows,
        cell_size=stack.cell_size,
    )
    state = TerrainPipelineState(intent=intent, mask_stack=stack)

    bathy_result = pass_bathymetry(state, region)
    depth_result = pass_water_depth(state, region)
    assert bathy_result.status == "ok"
    assert depth_result.status == "ok"

    ws_elev = np.asarray(
        stack.get("water_surface_elevation_m"), dtype=np.float32
    )
    depth = np.asarray(stack.get("water_depth_m"), dtype=np.float32)

    # The basin spill rim is ~28 m; the flood-fill rim may sit a little above
    # it because it uses the highest DRY rim neighbour (a band of cells just
    # above 28 m). Allow a generous margin and still be far below the 190 m
    # global terrain max, so the test is unambiguous.
    rim_bound = _BASIN_SPILL_RIM_M + 10.0  # 38 m — still << 190 m

    assert float(ws_elev.max()) <= rim_bound, (
        f"water_surface_elevation_m inflated to {float(ws_elev.max()):.1f} m "
        f"(basin spill rim ~{_BASIN_SPILL_RIM_M:.0f} m, global terrain max "
        f"{_TERRAIN_MAX_M:.0f} m); the seasonal flood collapsed the surface to "
        f"the whole-bowl rim."
    )
    assert float(depth.max()) <= rim_bound, (
        f"water_depth_m inflated to {float(depth.max()):.1f} m through the real "
        f"seasonal -> bathymetry -> depth chain (expected <= {rim_bound:.0f} m, "
        f"basin floor to spill rim). On origin/main this floods to ~"
        f"{_TERRAIN_MAX_M - 5.0:.0f} m (mountain height) — the production bug."
    )
    # Sanity: the basin is genuinely wet (the test isn't vacuously passing on an
    # empty mask) and the depth is a real, positive pool.
    assert float(depth.max()) > 1.0, (
        "expected a real water pool in the basin floor; got near-zero depth — "
        "the chain produced no water at all."
    )
