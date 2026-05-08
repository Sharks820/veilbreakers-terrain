"""Phase A D15.5 hotfix regression — hydraulic mass conservation on
gentle-slope geometry where droplets exit via natural end-of-lifetime
rather than via boundary or evaporation.

The B15-P0-08 fix landed in PR #38 closed THREE of four exit paths in
``apply_hydraulic_erosion_masks``:

    1. Working-range exit at start of step (`if ix < 1 or ix >= cols-2 ...`)
    2. Post-move out-of-array exit (`if nix < 0 or nix >= cols-1 ...`)
    3. Water-evaporation exit (`if water < 0.001`)

It did NOT close the FOURTH path: natural completion of the
``for _step in range(max_lifetime):`` loop. With default
``max_lifetime=30`` and ``evaporation=0.01``, water decays only to
``0.99 ** 30 ≈ 0.74`` — far above the 0.001 evaporation threshold —
so a droplet wandering interior cells through all 30 steps exits the
for-loop naturally without ever depositing.

The original 64×64 pyramid mass-conservation test masked this failure
because pyramid geometry has steep gradients near the centre →
droplets escape to the boundary within ~5 steps and hit exit path #1
or #2 before max_lifetime. On gentle slopes the failure mode dominates:
V2 verifier reproduced 94.5% mass leak on a 512×512 ramp with
``height = (y + x) * 0.1``.

This regression file pins the hotfix:

    - test_gentle_slope_mass_conservation: 512×512 ramp, 2000 droplets,
      max_lifetime=30 — leak <10% (was 94.5% pre-hotfix).
    - test_eol_deposit_honours_deposition_mask: residual sediment at
      end-of-lifetime must respect ``deposition_mask`` (matching the
      Codex P1 contract from PR #38).
    - test_eol_deposit_honours_hero_exclusion: residual sediment at
      end-of-lifetime must respect ``hero_exclusion``.
"""

from __future__ import annotations

import numpy as np

from veilbreakers_terrain.handlers._terrain_erosion import (
    apply_hydraulic_erosion_masks,
)


def _gentle_ramp(rows: int, cols: int, slope: float = 0.1) -> np.ndarray:
    """Linear gradient ramp where each cell is `slope * (y + x)`.

    Steepest descent path is uniform — droplets follow the gradient
    interior for many steps before hitting any boundary, exposing the
    end-of-lifetime exit path.
    """
    yy, xx = np.indices((rows, cols), dtype=np.float64)
    return (slope * (yy + xx)).astype(np.float64)


def test_gentle_slope_mass_conservation():
    """Gentle 512×512 ramp + 2000 droplets — mass leak must be <10% (was 94.5%).

    V2 verifier P0 repro:
        h = (y + x).astype(np.float64) * 0.1   # gentle uniform slope
        m = apply_hydraulic_erosion_masks(h, iterations=2000, seed=42, max_lifetime=30)
        # pre-hotfix: ero=5998.7, dep=329.6 → 94.5% leak
    """
    rows, cols = 512, 512
    h = _gentle_ramp(rows, cols, slope=0.1)
    masks = apply_hydraulic_erosion_masks(
        heightmap=h,
        iterations=2000,
        seed=42,
        max_lifetime=30,
    )
    total_erosion = float(np.asarray(masks.erosion_amount, dtype=np.float64).sum())
    total_deposition = float(np.asarray(masks.deposition_amount, dtype=np.float64).sum())
    if total_erosion <= 0.0:
        raise AssertionError(
            f"gentle ramp produced zero erosion ({total_erosion=}); "
            "geometry/iteration count needs reseating"
        )
    leak_fraction = abs(total_erosion - total_deposition) / total_erosion
    assert leak_fraction < 0.10, (
        f"gentle-slope mass leak >10%: erosion={total_erosion:.2f}, "
        f"deposition={total_deposition:.2f}, leak_frac={leak_fraction:.4f} "
        f"(pre-hotfix baseline was 94.5%)"
    )


def test_short_max_lifetime_stress():
    """Tighter test: max_lifetime=15 forces almost every droplet through end-of-life path.

    With max_lifetime=15 and evaporation=0.01, water decays to
    0.99^15 ≈ 0.86 — still well above 0.001. ALMOST every droplet
    that doesn't exit a boundary will end via the for-loop natural
    end. This stress configuration is where the hotfix is load-bearing.
    """
    rows, cols = 256, 256
    h = _gentle_ramp(rows, cols, slope=0.05)  # very gentle
    masks = apply_hydraulic_erosion_masks(
        heightmap=h,
        iterations=1500,
        seed=123,
        max_lifetime=15,
    )
    total_erosion = float(np.asarray(masks.erosion_amount, dtype=np.float64).sum())
    total_deposition = float(np.asarray(masks.deposition_amount, dtype=np.float64).sum())
    leak_fraction = (
        abs(total_erosion - total_deposition) / max(total_erosion, 1e-9)
    )
    assert leak_fraction < 0.10, (
        f"short-lifetime mass leak >10%: ero={total_erosion:.2f}, "
        f"dep={total_deposition:.2f}, leak={leak_fraction:.4f}"
    )


def test_eol_deposit_honours_deposition_mask():
    """End-of-life deposit must respect deposition_mask=zeros (no deposit).

    With deposition_mask=0 everywhere and heroes-disabled, NO sediment
    should land anywhere — the EOL closure must short-circuit via
    `_boundary_deposit_blocked`. If it bypassed the guard, sediment
    would leak into protected cells.
    """
    rows, cols = 128, 128
    h = _gentle_ramp(rows, cols, slope=0.05)
    deposition_mask = np.zeros((rows, cols), dtype=np.float64)  # everywhere blocked
    masks = apply_hydraulic_erosion_masks(
        heightmap=h,
        iterations=500,
        seed=7,
        max_lifetime=30,
        deposition_mask=deposition_mask,
        deposition_mask_threshold=0.5,
    )
    total_deposition = float(
        np.asarray(masks.deposition_amount, dtype=np.float64).sum()
    )
    # With deposition_mask=0 the only legal deposit volume is 0.
    # Allow a tiny tolerance for accumulated FP error in `_deposit`'s
    # bilinear weights; pre-fix this test would record many units of
    # deposition because the EOL deposit path bypassed the mask check.
    assert total_deposition < 1e-6, (
        f"end-of-life deposit bypassed deposition_mask; "
        f"recorded {total_deposition:.6f} units of deposition where "
        f"mask=0 should silence everything"
    )


def test_eol_deposit_honours_hero_exclusion():
    """End-of-life deposit must respect hero_exclusion bitmap."""
    rows, cols = 128, 128
    h = _gentle_ramp(rows, cols, slope=0.05)
    # Hero-exclude every cell — nothing should accumulate sediment.
    hero_exclusion = np.ones((rows, cols), dtype=bool)
    masks = apply_hydraulic_erosion_masks(
        heightmap=h,
        iterations=500,
        seed=11,
        max_lifetime=30,
        hero_exclusion=hero_exclusion,
    )
    total_deposition = float(
        np.asarray(masks.deposition_amount, dtype=np.float64).sum()
    )
    total_erosion = float(np.asarray(masks.erosion_amount, dtype=np.float64).sum())
    # When every cell is hero-excluded, both erosion and deposition
    # should be ~0. Accept a tiny FP tolerance.
    assert total_deposition < 1e-6, (
        f"end-of-life deposit bypassed hero_exclusion; "
        f"recorded {total_deposition:.6f} deposition under all-heroes mask"
    )
    assert total_erosion < 1e-6, (
        f"hero_exclusion did not block erosion either; "
        f"erosion={total_erosion:.6f}"
    )


def test_no_regression_on_steep_pyramid_geometry():
    """The original 64×64 pyramid test from PR #38 must still pass.

    The hotfix must not break the original boundary-exit deposit
    semantics. Pyramid geometry produces fast-escape droplets that
    primarily hit exit paths #1/#2 — the hotfix's `else` clause does
    not fire on those paths.
    """
    rows, cols = 64, 64
    cy, cx = (rows - 1) / 2.0, (cols - 1) / 2.0
    yy, xx = np.indices((rows, cols), dtype=np.float64)
    radial = np.maximum(np.abs(yy - cy), np.abs(xx - cx))
    radial /= max(radial.max(), 1.0)
    h = (100.0 * (1.0 - radial)).astype(np.float64)
    masks = apply_hydraulic_erosion_masks(
        heightmap=h,
        iterations=2000,
        seed=42,
        max_lifetime=30,
    )
    total_erosion = float(np.asarray(masks.erosion_amount, dtype=np.float64).sum())
    total_deposition = float(np.asarray(masks.deposition_amount, dtype=np.float64).sum())
    leak_fraction = abs(total_erosion - total_deposition) / max(total_erosion, 1e-9)
    # Same threshold as the original PR #38 test.
    assert leak_fraction < 0.10, (
        f"pyramid regression: leak={leak_fraction:.4f} (was <0.10 in PR #38)"
    )
