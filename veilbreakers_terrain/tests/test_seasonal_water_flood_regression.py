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

import numpy as np

from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack
from veilbreakers_terrain.handlers.terrain_water_variants import (
    SeasonalState,
    apply_seasonal_water_state,
)

SHAPE = (33, 33)


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
