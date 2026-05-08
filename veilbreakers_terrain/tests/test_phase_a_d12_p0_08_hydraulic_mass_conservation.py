"""Phase A D12-13 / B15-P0-08 hydraulic mass conservation tests.

Verifies the boundary-leak fix in ``apply_hydraulic_erosion_masks``:

  Before fix: 64x64 pyramid + 2000 droplets → 75% mass loss because
              droplets that exit the working range drop their full
              sediment payload at the boundary (3 break sites in
              `_terrain_erosion.py:354,385,472-487`).

  After fix:  Each break site re-deposits remaining sediment at the
              last in-bounds cell via the existing ``_deposit()``
              bilinear helper. Mass is conserved within float tolerance.

The test compares total erosion vs total deposition for a stress
configuration that maximises boundary exits (small grid + heavy
droplet count). The contract is conservation, not exactness — the
``_deposit`` helper itself silently drops mass when its target cell is
out of array bounds, so we measure relative leak instead of absolute
zero. Pre-fix relative leak is ~0.75; post-fix tolerance is 0.10.

PHANTOM PINS:
  B15-P0-10 (gradient axis swap) is PHANTOM per spec §1.2 — the actual
  code at `_terrain_noise.py:1529` already uses the correct
  ``grad_y, grad_x = np.gradient(h, row_spacing, col_spacing)`` order.
  B15-P0-11 (per-tile mean subtraction) is also PHANTOM — the
  documented removal lives at `_terrain_world.py:712-713`. Both
  invariants are pinned by tests below to prevent regression.
"""

from __future__ import annotations

import numpy as np

from veilbreakers_terrain.handlers._terrain_erosion import (
    apply_hydraulic_erosion_masks,
)


# ---------------------------------------------------------------------------
# B15-P0-08: hydraulic mass conservation under boundary stress
# ---------------------------------------------------------------------------


def _pyramid(rows: int, cols: int, peak: float = 100.0) -> np.ndarray:
    """Build an axis-aligned pyramid centred on the grid.

    Pyramid maximises gradient near edges → lots of droplets escape the
    working range, exposing the boundary leak.
    """
    cy, cx = (rows - 1) / 2.0, (cols - 1) / 2.0
    yy, xx = np.indices((rows, cols), dtype=np.float64)
    radial = np.maximum(np.abs(yy - cy), np.abs(xx - cx))
    radial /= max(radial.max(), 1.0)
    return (peak * (1.0 - radial)).astype(np.float64)


def test_pyramid_64x64_mass_conservation_within_tolerance():
    """64×64 pyramid, 2000 droplets — mass loss must be <10% (was 75%)."""
    rows, cols = 64, 64
    h = _pyramid(rows, cols, peak=100.0)
    masks = apply_hydraulic_erosion_masks(
        heightmap=h,
        iterations=2000,
        seed=42,
        max_lifetime=30,
    )
    total_erosion = float(masks.erosion_amount.sum())
    total_deposition = float(masks.deposition_amount.sum())
    # Mass change is the signed difference between deposit and erosion
    # accumulators. Pre-fix this was ~ -75% of total erosion. Post-fix
    # the imbalance comes only from `_deposit`'s silent out-of-bounds
    # no-op for cells that even the last_in_bounds tracker can't help
    # (e.g. droplet starts in buffer band on first step). Empirically
    # ~0-5% on this geometry.
    if total_erosion <= 0.0:
        # No erosion ⇒ test geometry is wrong — fail loudly.
        raise AssertionError(
            f"pyramid stress produced zero erosion ({total_erosion=}); "
            "geometry/iteration count needs reseating"
        )
    leak_fraction = abs(total_erosion - total_deposition) / total_erosion
    assert leak_fraction < 0.10, (
        f"hydraulic mass leak >10%: erosion={total_erosion:.2f}, "
        f"deposition={total_deposition:.2f}, leak_frac={leak_fraction:.4f} "
        f"(pre-fix baseline ~0.75; B15-P0-08 regression)"
    )


def test_height_array_mass_conservation_within_tolerance():
    """The result heightmap itself must conserve total volume vs input."""
    rows, cols = 64, 64
    h = _pyramid(rows, cols, peak=100.0)
    initial_total = float(h.sum())
    masks = apply_hydraulic_erosion_masks(
        heightmap=h,
        iterations=2000,
        seed=42,
        max_lifetime=30,
    )
    final_total = float(np.asarray(masks.height, dtype=np.float64).sum())
    # The heightmap itself reflects net erosion + deposition. If droplets
    # leak sediment overboard, final < initial. With the fix mass should
    # be approximately preserved; the tolerance is wider than the
    # accumulator test because numerical clipping of brush footprints
    # near edges still creates small (~1-3%) drift.
    # Use abs(initial_total) so the metric stays well-defined for future
    # geometries with negative total volume (heightmaps centred on 0).
    relative_drift = abs(final_total - initial_total) / max(abs(initial_total), 1.0)
    assert relative_drift < 0.05, (
        f"heightmap volume drift >5%: initial={initial_total:.2f}, "
        f"final={final_total:.2f}, drift={relative_drift:.4f} "
        f"(B15-P0-08 boundary leak)"
    )


def test_small_grid_does_not_crash_when_all_droplets_exit_immediately():
    """Tiny grid where most droplets break on step 1 — no crashes / NaNs."""
    h = _pyramid(8, 8, peak=10.0)
    masks = apply_hydraulic_erosion_masks(
        heightmap=h,
        iterations=200,
        seed=7,
        max_lifetime=8,
    )
    assert np.all(np.isfinite(np.asarray(masks.height))), (
        "non-finite values in result height after small-grid stress"
    )
    assert np.all(np.isfinite(np.asarray(masks.erosion_amount)))
    assert np.all(np.isfinite(np.asarray(masks.deposition_amount)))


def test_initial_buffer_band_droplets_do_not_corrupt_state():
    """Droplets starting at fx=0/fy=0 boundary band must not corrupt accumulators.

    `last_in_bounds` is None on first iteration; if the working-range
    check fails immediately, the deposit guard must protect against
    None unpacking. Sediment is 0 at start so this is logically a
    no-op, but the guard must exist.
    """
    h = _pyramid(16, 16, peak=5.0)
    # Many seeds → many initial positions → some will start in the buffer
    # band and break immediately on first step.
    for seed in range(50):
        masks = apply_hydraulic_erosion_masks(
            heightmap=h,
            iterations=10,
            seed=seed,
            max_lifetime=5,
        )
        assert np.all(np.isfinite(np.asarray(masks.height))), (
            f"non-finite height for seed={seed}"
        )


# ---------------------------------------------------------------------------
# B15-P0-10 PHANTOM PIN — gradient axis order at _terrain_noise.py:1529
# ---------------------------------------------------------------------------


def test_phantom_p0_10_gradient_axis_order_correct():
    """`_terrain_noise.py:1529` must use grad_y/grad_x order (numpy convention)."""
    import pathlib

    src = (
        pathlib.Path(__file__).resolve().parents[1]
        / "handlers"
        / "_terrain_noise.py"
    ).read_text(encoding="utf-8")
    # Lock the canonical line — `np.gradient` returns axis-0 (rows) first
    # which corresponds to the y-direction on a heightmap; axis-1 (cols)
    # is x. Variable naming must match.
    assert "grad_y, grad_x = np.gradient" in src or "dy, dx = np.gradient" in src, (
        "_terrain_noise.py lost the np.gradient axis-labelled tuple — "
        "B15-P0-10 phantom pin failed; verify naming convention"
    )
    # Whichever convention is used, the SECOND return must be col gradient.
    # Pre-fix bug was reversed labels causing 90° rotation in θ/aspect.
    # Hard-block the inverted form.
    assert "grad_x, grad_y = np.gradient" not in src, (
        "B15-P0-10 REGRESSION — `grad_x, grad_y = np.gradient(...)` "
        "swaps the numpy axis convention and rotates all directional "
        "consumers (structure tensor, anisotropy θ, slope-aspect) by 90°"
    )


# ---------------------------------------------------------------------------
# B15-P0-11 PHANTOM PIN — per-tile mean subtraction at _terrain_world.py:712-713
# ---------------------------------------------------------------------------


def test_phantom_p0_11_no_per_tile_mean_subtraction_in_terrain_world():
    """`_terrain_world.py` must NOT subtract its per-tile mean from `hmap_high`.

    The original bug pattern: ``hmap_high = hmap_high - float(np.mean(hmap_high))``.
    Any reintroduction breaks tile-seam continuity by giving each tile
    a different DC offset.

    PR #38 Copilot review broadened the check from two exact-string forms
    to a regex that catches all common subtraction-assignment variants:
      - ``hmap_high = hmap_high - np.mean(hmap_high)``
      - ``hmap_high = hmap_high - float(np.mean(hmap_high))``
      - ``hmap_high -= np.mean(hmap_high)``
      - ``hmap_high -= float(np.mean(hmap_high))``
      - any whitespace / extra parens around the np.mean call.
    """
    import pathlib
    import re

    src = (
        pathlib.Path(__file__).resolve().parents[1]
        / "handlers"
        / "_terrain_world.py"
    ).read_text(encoding="utf-8")

    # Match either `hmap_high = hmap_high - <expr>(np.mean(hmap_high)<...>)`
    # or `hmap_high -= <expr>(np.mean(hmap_high)<...>)`, allowing optional
    # `float(...)` wrapping and whitespace.
    pattern = re.compile(
        r"hmap_high\s*"
        r"(?:=\s*hmap_high\s*-|-=)"  # subtraction-assignment OR augmented
        r"\s*"
        r"(?:float\s*\(\s*)?"        # optional float(...)
        r"np\.mean\s*\(\s*hmap_high",
    )
    matches = pattern.findall(src)
    assert not matches, (
        f"B15-P0-11 REGRESSION — per-tile mean subtraction reintroduced "
        f"(regex matched {len(matches)} sites). Neighbouring tiles will "
        f"have different DC offsets and seams will show vertical steps."
    )
