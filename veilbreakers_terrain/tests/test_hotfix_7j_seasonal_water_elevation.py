"""Tests for HOTFIX-7j — seasonal water_surface_elevation_m sync.

Verifier A 2026-05-21 #24: apply_seasonal_water_state was mutating
water_surface_mask without updating water_surface_elevation_m, so caustic
rendering read stale elevations against the new seasonal mask.

Contract under test
-------------------
After apply_seasonal_water_state returns:
1. water_surface_elevation_m is present on the stack (not absent / stale).
2. For any cell where water_surface_mask is wet (canonical ``> 0.5``),
   water_surface_elevation_m >= stack.height (wsfm invariant); dry cells
   carry the 0.0 sentinel.
3. The spill-rim elevation is recomputed against the current mask, so it
   differs from an artificially-seeded pre-season elevation.
4. Edge case: if the mask is all-zero, the elevation sentinel is 0.0
   everywhere (not NaN / Inf / stale).

CE-2026-05-24 #1/#9 note: seasonal state adjusts wetness / tidal / ice but
does NOT change the open-water *extent* (that needs a hydro sim).  The old
additive nudges that mutated the binary ``water_surface_mask`` extent
silently flooded the whole tile (WET/FROZEN ``> 0.0`` leak) or erased it
(DRY ``*0.5`` under the canonical ``> 0.5``); the extent is now preserved
exactly across seasons.  See test_seasonal_water_flood_regression.py.
"""

from __future__ import annotations

import numpy as np
import pytest

from veilbreakers_terrain.handlers.terrain_water_variants import (
    SeasonalState,
    apply_seasonal_water_state,
)
from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stack(
    shape: tuple[int, int] = (16, 16),
    *,
    wet_fraction: float = 0.25,
    seed: int = 42,
) -> TerrainMaskStack:
    """Build a minimal TerrainMaskStack with height + water channels set."""
    rng = np.random.default_rng(seed)
    rows, cols = shape
    height = rng.uniform(0.0, 50.0, size=shape).astype(np.float32)
    # Make a basin in the lower-left quadrant so wet cells are topographically
    # coherent (elevation lower than surrounding cells).
    height[: rows // 2, : cols // 2] -= 20.0
    height = np.clip(height, 0.0, None)

    # Simple binary mask: lower-left quadrant is wet
    mask = np.zeros(shape, dtype=np.float32)
    mask[: rows // 2, : cols // 2] = 1.0

    # Seed elevation with a plausible spill-rim value above the terrain max
    # in the wet region — exact value doesn't matter; we're testing that the
    # seasonal pass overwrites it correctly.
    stale_elev = np.where(mask > 0.5, height + 5.0, 0.0).astype(np.float32)

    wetness = (mask * 0.8).astype(np.float32)
    tidal = np.zeros(shape, dtype=np.float32)

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
    stack.set("water_surface_elevation_m", stale_elev, "setup")
    stack.set("wetness", wetness, "setup")
    stack.set("tidal", tidal, "setup")
    return stack


# ---------------------------------------------------------------------------
# Core correctness tests
# ---------------------------------------------------------------------------


def test_dry_season_updates_elevation() -> None:
    """DRY season recomputes elevation against the (extent-preserved) mask.

    CE-2026-05-24 #1/#9: DRY no longer shrinks the open-water extent (it only
    lowers wetness); elevation is still recomputed from the spill rim, so it
    differs from the artificial pre-season ``stale_elev``.
    """
    stack = _make_stack()
    stale_elev = np.asarray(stack.get("water_surface_elevation_m"), dtype=np.float32).copy()

    apply_seasonal_water_state(stack, SeasonalState.DRY)

    new_mask = np.asarray(stack.get("water_surface_mask"), dtype=np.float32)
    new_elev = stack.get("water_surface_elevation_m")
    assert new_elev is not None, "water_surface_elevation_m must be set after seasonal pass"
    new_elev = np.asarray(new_elev, dtype=np.float32)

    # The elevation array must differ from the stale one (mask changed).
    assert not np.array_equal(new_elev, stale_elev), (
        "DRY season did not update water_surface_elevation_m"
    )

    # Invariant: wsfm >= height for all wet cells (or wsfm == 0.0 for dry).
    wet = new_mask > 0.5  # canonical wet predicate (matches _WET_THRESHOLD)
    if wet.any():
        h = np.asarray(stack.height, dtype=np.float32)
        assert np.all(new_elev[wet] >= h[wet]), (
            "wsfm < height for some wet cells after DRY season"
        )
    # Dry-cell sentinel: every non-wet cell carries the 0.0 elevation sentinel
    # (the whole-tile flood bug lifted these to the global terrain max).
    assert np.all(new_elev[~wet] == 0.0), (
        "DRY season left non-zero water_surface_elevation_m on dry cells"
    )


def test_wet_season_updates_elevation() -> None:
    """WET season recomputes elevation against the (extent-preserved) mask.

    CE-2026-05-24 #1/#9: WET no longer expands the open-water extent (it only
    raises wetness); the spill-rim elevation is still recomputed and differs
    from the artificial pre-season ``stale_elev``.
    """
    stack = _make_stack()
    stale_elev = np.asarray(stack.get("water_surface_elevation_m"), dtype=np.float32).copy()

    apply_seasonal_water_state(stack, SeasonalState.WET)

    new_mask = np.asarray(stack.get("water_surface_mask"), dtype=np.float32)
    new_elev = stack.get("water_surface_elevation_m")
    assert new_elev is not None
    new_elev = np.asarray(new_elev, dtype=np.float32)

    assert not np.array_equal(new_elev, stale_elev), (
        "WET season did not update water_surface_elevation_m"
    )

    wet = new_mask > 0.5  # canonical wet predicate (matches _WET_THRESHOLD)
    if wet.any():
        h = np.asarray(stack.height, dtype=np.float32)
        assert np.all(new_elev[wet] >= h[wet]), (
            "wsfm < height for some wet cells after WET season"
        )
    # Dry-cell sentinel: dry cells stay at 0.0 (the flood bug raised them to the
    # global terrain max).
    assert np.all(new_elev[~wet] == 0.0), (
        "WET season left non-zero water_surface_elevation_m on dry cells — flood bug"
    )


def test_frozen_season_updates_elevation() -> None:
    """FROZEN season recomputes elevation against the (extent-preserved) mask.

    CE-2026-05-24 #1/#9: FROZEN locks tidal and lowers wetness but no longer
    changes the open-water extent; the spill-rim elevation is still recomputed.
    """
    stack = _make_stack()
    stale_elev = np.asarray(stack.get("water_surface_elevation_m"), dtype=np.float32).copy()

    apply_seasonal_water_state(stack, SeasonalState.FROZEN)

    new_mask = np.asarray(stack.get("water_surface_mask"), dtype=np.float32)
    new_elev = stack.get("water_surface_elevation_m")
    assert new_elev is not None
    new_elev = np.asarray(new_elev, dtype=np.float32)

    assert not np.array_equal(new_elev, stale_elev), (
        "FROZEN season did not update water_surface_elevation_m"
    )

    wet = new_mask > 0.5  # canonical wet predicate (matches _WET_THRESHOLD)
    if wet.any():
        h = np.asarray(stack.height, dtype=np.float32)
        assert np.all(new_elev[wet] >= h[wet]), (
            "wsfm < height for some wet cells after FROZEN season"
        )
    # Dry-cell sentinel: dry cells stay at 0.0 (the flood bug raised them to the
    # global terrain max).
    assert np.all(new_elev[~wet] == 0.0), (
        "FROZEN season left non-zero water_surface_elevation_m on dry cells"
    )


def test_normal_season_elevation_present() -> None:
    """NORMAL is a no-op for mask values but elevation must still be on stack."""
    stack = _make_stack()
    original_mask = np.asarray(stack.get("water_surface_mask"), dtype=np.float32).copy()

    apply_seasonal_water_state(stack, SeasonalState.NORMAL)

    new_mask = np.asarray(stack.get("water_surface_mask"), dtype=np.float32)
    # NORMAL is pass-through: mask unchanged.
    np.testing.assert_array_equal(new_mask, original_mask)

    new_elev = stack.get("water_surface_elevation_m")
    assert new_elev is not None, "water_surface_elevation_m must be present after NORMAL"


# ---------------------------------------------------------------------------
# Cross-season consistency test
# ---------------------------------------------------------------------------


def test_dry_vs_flood_preserve_extent_and_elevation_matches_mask() -> None:
    """Dry and flood seasons keep the SAME open-water extent; elevation matches it.

    CE-2026-05-24 #1/#9 update: this test was originally an *encoded-bug*
    test — it asserted DRY and WET produce DIFFERENT masks.  That only held
    because the buggy additive nudges (WET ``+0.15``, DRY ``*0.5``) corrupted
    the binary ``water_surface_mask`` extent differently per season, which in
    turn silently flooded (WET/FROZEN) or erased (DRY) open water.  The
    corrected contract is the opposite: seasonal state adjusts wetness / ice,
    NOT open-water extent (that needs a hydro sim), so DRY and WET produce the
    SAME extent.

    The original *intent* of this test — the Verifier A #24 anti-stale-elevation
    scenario (caustics must align with the current mask) — is preserved as the
    second assertion: ``water_surface_elevation_m`` is non-zero exactly on the
    wet cells and 0.0 on dry cells, for both seasons.
    """
    stack_dry = _make_stack(seed=7)
    stack_wet = _make_stack(seed=7)  # identical initial state

    apply_seasonal_water_state(stack_dry, SeasonalState.DRY)
    apply_seasonal_water_state(stack_wet, SeasonalState.WET)

    mask_dry = np.asarray(stack_dry.get("water_surface_mask"), dtype=np.float32)
    mask_wet = np.asarray(stack_wet.get("water_surface_mask"), dtype=np.float32)
    elev_dry = np.asarray(stack_dry.get("water_surface_elevation_m"), dtype=np.float32)
    elev_wet = np.asarray(stack_wet.get("water_surface_elevation_m"), dtype=np.float32)

    # Corrected contract: open-water EXTENT is identical across seasons.
    np.testing.assert_array_equal(
        mask_dry,
        mask_wet,
        err_msg=(
            "DRY and WET seasons produced different open-water extent; seasonal "
            "state must adjust wetness/ice, not extent (the additive-nudge flood bug)."
        ),
    )

    # Anti-stale-elevation: elevation is consistent with the mask for BOTH
    # seasons — non-zero on wet cells, exactly 0.0 (the dry sentinel) elsewhere.
    h = np.asarray(stack_dry.height, dtype=np.float32)
    for mask, elev, name in (
        (mask_dry, elev_dry, "DRY"),
        (mask_wet, elev_wet, "WET"),
    ):
        wet = mask > 0.5
        dry = ~wet
        assert np.all(elev[dry] == 0.0), (
            f"{name}: water_surface_elevation_m non-zero on dry cells — the "
            f"whole-tile flood bug lifted the spill rim over dry land."
        )
        if wet.any():
            assert np.all(elev[wet] >= h[wet]), (
                f"{name}: wsfm < height on some wet cells (caustic misalignment)."
            )


# ---------------------------------------------------------------------------
# Invariant: wet cells have finite, non-stale elevation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("season", [SeasonalState.DRY, SeasonalState.WET, SeasonalState.FROZEN])
def test_wet_cells_have_finite_elevation(season: SeasonalState) -> None:
    """For every cell where mask > 0 after the season pass, elevation must be
    finite (not NaN, not Inf) and >= the underlying terrain height.
    """
    stack = _make_stack(seed=99)
    apply_seasonal_water_state(stack, season)

    mask = np.asarray(stack.get("water_surface_mask"), dtype=np.float32)
    elev = stack.get("water_surface_elevation_m")
    assert elev is not None
    elev = np.asarray(elev, dtype=np.float32)
    h = np.asarray(stack.height, dtype=np.float32)

    wet = mask > 0.5  # canonical wet predicate (matches _WET_THRESHOLD)
    if not wet.any():
        return  # DRY may drain all cells — nothing to check

    wet_elev = elev[wet]
    assert np.all(np.isfinite(wet_elev)), (
        f"Non-finite elevation in wet cells after {season.value} season"
    )
    assert np.all(wet_elev >= h[wet]), (
        f"wsfm < height for some wet cells after {season.value} season"
    )


# ---------------------------------------------------------------------------
# Edge case: empty mask → sentinel is 0.0 everywhere
# ---------------------------------------------------------------------------


def test_empty_mask_sentinel_is_zero() -> None:
    """When the mask is all-zero (fully drained), elevation should be 0.0 everywhere.

    _compute_spill_rim_elevation returns all-zero when wet_mask.any() is False,
    which is the sentinel contract used throughout pass_water_variants.
    """
    stack = TerrainMaskStack(
        tile_size=0,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=np.ones((8, 8), dtype=np.float32) * 10.0,
    )
    # Start with a completely dry mask.
    stack.set("water_surface_mask", np.zeros((8, 8), dtype=np.float32), "setup")
    stack.set("water_surface_elevation_m", np.full((8, 8), 99.0, dtype=np.float32), "setup")
    stack.set("wetness", np.zeros((8, 8), dtype=np.float32), "setup")
    stack.set("tidal", np.zeros((8, 8), dtype=np.float32), "setup")

    # Any season applied to an already-dry mask should leave elevation at 0.0.
    apply_seasonal_water_state(stack, SeasonalState.DRY)

    elev = stack.get("water_surface_elevation_m")
    assert elev is not None
    elev = np.asarray(elev, dtype=np.float32)
    assert np.all(elev == 0.0), (
        "Empty-mask elevation sentinel should be 0.0, got non-zero values"
    )
