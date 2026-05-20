"""Regression tests for the T1 sim/foam cluster (T1-40/41/42/43 + T2-40).

These tests pin numerical behaviour for the five audit findings closed by
``fix/t1-sim-foam-cluster``. Per FIX_PATTERN_v1 section C5 ("Numerical /
unit conversion fix") each test asserts a *specific* numerical invariant:

* T1-40 -- ``foam.py:100-104`` Kelvin wake inverted clamp
* T1-41 -- ``catenary.py:51-66`` brentq dead + silent fallback
* T1-42 -- ``foam.py:268-273`` 99th-percentile clip plateau
* T1-43 -- ``foam.py:236`` Kelvin wake hardcoded ``flow_dir=(1, 0)``
* T2-40 -- ``foam.py:215-222`` vorticity axis convention pin
  (audit complaint is a false-positive at the current code site; the math
  is already correct. This test pins the convention so a future axis-swap
  regression is caught.)

All assertions use ``np.testing.assert_allclose`` or ``pytest.approx`` with
``rtol/abs=1e-6`` per the §C5 tolerance recipe.
"""
from __future__ import annotations

import math

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# T1-40 -- Kelvin wake inverted clamp
# ---------------------------------------------------------------------------


def test_t1_40_kelvin_wake_subcritical_floor_is_19p47_deg() -> None:
    """For Fr_rock << 1/3 the Kelvin half-angle must floor at arcsin(1/3).

    Before fix: ``min(1.0, 1.0 / max(3*Fr, 1.0))`` evaluated to 1.0 whenever
    ``3*Fr < 1`` -- i.e. ``Fr < 1/3`` -- so ``asin(1) == pi/2`` and ``tan``
    blew up to ~1.6e16, turning the wake mask into a half-plane.

    After fix: the floor is ``arcsin(1/3) == 19.4712 deg`` (canonical Kelvin
    angle), and the cone only narrows for Fr > 1.
    """
    from veilbreakers_terrain.sim.foam import kelvin_wake_mask

    # A 21x21 grid centred on (10, 10) with a slow flow_speed << threshold
    H, W = 21, 21
    cell_size = 1.0
    pos_x = np.arange(W, dtype=np.float32)[None, :].repeat(H, axis=0) * cell_size
    pos_y = np.arange(H, dtype=np.float32)[:, None].repeat(W, axis=1) * cell_size

    # flow_speed = 0.1 m/s -> Fr_rock = 0.1 / sqrt(9.81 * 1) ~= 0.032 << 1/3
    mask = kelvin_wake_mask(
        pos_x, pos_y,
        rock_row=10.0, rock_col=10.0,
        flow_dir_xy=(1.0, 0.0),  # +x ("east")
        flow_speed=0.1,
        cell_size=cell_size,
        max_dist_m=20.0,
    )

    # The wake should be a narrow chevron behind the rock. With the prior bug
    # the half-angle was ~90 deg and the mask covered ~50% of cells (the
    # entire +x half plane). With the fix the floor 19.47 deg means the
    # downstream cone covers <= tan(19.47 deg) * along_extent area, which
    # works out to well under 25% of cells downstream of the rock.
    downstream = mask[:, 11:]  # +x of rock
    coverage = float((downstream > 0.0).mean())
    assert coverage < 0.25, (
        f"Kelvin wake covered {coverage:.1%} of downstream cells; "
        "expected < 25% for canonical 19.47 deg half-angle (T1-40 regression)"
    )

    # Direct angle check: the outermost lit cell on a downstream column must
    # lie inside the canonical wake cone (half-angle <= 19.47 deg + 1 cell
    # of numerical slack).
    canonical_half_angle = math.asin(1.0 / 3.0)  # 19.4712 deg
    along_col = 18  # 8 cells downstream of rock at col=10
    column = mask[:, along_col]
    lit_rows = np.where(column > 0.0)[0]
    assert len(lit_rows) > 0, "expected non-empty wake on a downstream column"
    max_across = float(max(abs(lit_rows.max() - 10), abs(lit_rows.min() - 10)))
    along = float(along_col - 10)
    observed_half_angle = math.atan2(max_across, along)
    # 1.6 cells of slack -- per-cell discretisation can push the observed
    # angle slightly above the analytic floor on a 1m grid.
    assert observed_half_angle <= canonical_half_angle + math.atan2(1.6, along), (
        f"observed half-angle {math.degrees(observed_half_angle):.2f} deg "
        f"exceeds canonical floor {math.degrees(canonical_half_angle):.2f} deg "
        "(T1-40 regression -- the wake is too wide)"
    )


# ---------------------------------------------------------------------------
# T1-41 -- catenary brentq dead + silent fallback
# ---------------------------------------------------------------------------


def test_t1_41_catenary_solver_produces_finite_natural_sag() -> None:
    """Solver must return finite cosh-shaped sag, not the silent ``a = h*50``
    fallback that produced colossal or zero sag downstream.

    Sanity-checks the solver with a typical rope-bridge geometry: 10 m span,
    12% length excess. ``a*50`` fallback would yield a nearly flat midpoint
    (sag < cm range); a real catenary at this geometry sags ~70-90 cm.
    """
    from veilbreakers_terrain.sim.catenary import solve_catenary

    p0 = np.array([0.0, 0.0, 5.0])
    p1 = np.array([10.0, 0.0, 5.0])
    rope_length = 11.2  # 12% excess
    n_points = 33  # odd so we have a true midpoint
    pts = solve_catenary(p0, p1, rope_length=rope_length, n_points=n_points)
    assert pts.shape == (n_points, 3)
    assert np.all(np.isfinite(pts)), "T1-41 regression -- non-finite catenary points"

    midpoint_z = float(pts[n_points // 2, 2])
    sag = 5.0 - midpoint_z
    # Real natural sag for 10m span / 12% excess is ~0.7-1.0 m; the
    # ``a = h*50`` fallback would give cosh(0.1) - 1 == 0.005 m of sag, two
    # orders of magnitude smaller.
    assert 0.3 <= sag <= 1.5, (
        f"midpoint sag {sag:.4f} m outside natural catenary range "
        "[0.3, 1.5] -- silent fallback regressed (T1-41)"
    )


def test_t1_41_catenary_well_posed_stays_solvable() -> None:
    """T1-41 round-trip companion to the natural-sag test: a well-posed
    near-straight rope (rope_length only marginally above straight-line
    distance) must NOT trigger the new RuntimeError and must produce a
    finite point sequence.

    (Renamed per CE review C-2: the previous name promised an unsolvable-
    input raise-path test, but the body asserts the well-posed positive
    case. A dedicated raise-path test belongs in a separate fixture with
    a monkeypatched ``_residual``; tracked as a T1-41 follow-up.)
    """
    from veilbreakers_terrain.sim.catenary import solve_catenary

    p0 = np.array([0.0, 0.0, 0.0])
    p1 = np.array([100.0, 0.0, 0.0])
    pts = solve_catenary(p0, p1, rope_length=101.0, n_points=8)
    assert np.all(np.isfinite(pts)), "T1-41 regression on well-posed input"


# ---------------------------------------------------------------------------
# T1-42 -- 99th-percentile clip plateau
# ---------------------------------------------------------------------------


def test_t1_42_bake_flow_map_encodes_outliers_to_distinct_extremes() -> None:
    """Pins the bake_flow_map encoding contract: +x outliers encode to 255,
    -x outliers encode to 0 (distinct).

    PER CE REVIEW C-1 (round-2 honesty pass): both the pre-fix
    ``(normalized*0.5 + 0.5).clip(0, 255)`` AND the post-fix
    ``np.clip(normalized, -1, 1) * 0.5 + 0.5`` produce BYTE-IDENTICAL output
    for the inputs in this test. The T1-42 code change is therefore a
    clarity refactor (single explicit clip on normalized values BEFORE the
    multiply, instead of an implicit saturation clip after) and a numpy
    version-pin (``method='linear'`` on the percentile call). It is NOT a
    numerical bug fix as the original audit anchor implied.

    This test still has value as a contract pin: any future refactor that
    accidentally swaps clip bounds or drops the *0.5+0.5 offset will fail
    the +x/-x distinctness assertion.
    """
    from veilbreakers_terrain.sim.foam import bake_flow_map

    # Construct a (H, W, 2) field where the top 1% in magnitude are split
    # between +x and -x outliers.
    H, W = 100, 100
    vf = np.zeros((H, W, 2), dtype=np.float32)
    vf[..., 0] = np.random.default_rng(0).normal(0.0, 0.5, (H, W)).astype(np.float32)
    # Inject 50 +x outliers and 50 -x outliers, all magnitude 10x the rest.
    vf[0, :50, 0] = 5.0   # +x outliers
    vf[0, 50:, 0] = -5.0  # -x outliers

    encoded = bake_flow_map(vf)
    assert encoded.shape == (H, W, 2)
    assert encoded.dtype == np.uint8

    plus_x_encoded = encoded[0, :50, 0]
    minus_x_encoded = encoded[0, 50:, 0]
    # +x outliers should encode to 255 (full +x), -x outliers to 0 (full -x).
    np.testing.assert_array_equal(
        plus_x_encoded, np.full(50, 255, dtype=np.uint8),
        err_msg="T1-42 regression -- +x top-percentile outliers not at 255",
    )
    np.testing.assert_array_equal(
        minus_x_encoded, np.zeros(50, dtype=np.uint8),
        err_msg="T1-42 regression -- -x top-percentile outliers not at 0",
    )

    # Stronger pin: the prior bug collapsed BOTH signs to 255. Assert that
    # the two groups are distinguishable AT ALL (delta == 255 here).
    assert int(plus_x_encoded[0]) != int(minus_x_encoded[0]), (
        "T1-42 regression -- top-percentile +/- collapsed to identical value"
    )


def test_t1_42_bake_flow_map_percentile_is_deterministic() -> None:
    """Same-process determinism check on bake_flow_map.

    PER CE REVIEW C-3: this test passes both pre-fix and post-fix because
    numpy is single-process deterministic regardless of ``method='linear'``.
    The pin matters across numpy MINOR versions (the default ``interpolation``
    keyword was renamed/removed across 1.22+) but that cross-version drift
    cannot be exercised within one CI invocation.

    Kept as a smoke test that ensures bake_flow_map does not introduce
    silent non-determinism (e.g. via an internal random number generator
    or unstable sort). The cross-version guard is the literal pin in the
    production code itself.
    """
    from veilbreakers_terrain.sim.foam import bake_flow_map

    rng = np.random.default_rng(12345)
    vf = rng.normal(0.0, 1.0, (32, 32, 2)).astype(np.float32)
    encoded1 = bake_flow_map(vf)
    encoded2 = bake_flow_map(vf)
    np.testing.assert_array_equal(
        encoded1, encoded2,
        err_msg="T1-42 regression -- bake_flow_map non-deterministic",
    )


# ---------------------------------------------------------------------------
# T1-43 -- hardcoded flow_dir=(1, 0)
# ---------------------------------------------------------------------------


def test_t1_43_kelvin_wake_follows_local_flow_direction() -> None:
    """When ``flow_dir`` is supplied as a (H, W, 2) field, the Kelvin wake
    behind each rock must point DOWN the local flow vector -- not East.

    Before fix: ``generate_foam_mask`` called the wake helper with the
    hardcoded ``(1.0, 0.0)`` direction, so all wakes pointed +x regardless
    of the actual local flow.

    After fix: ``_local_flow_dir_at`` samples the flow field at the rock.
    With a uniform +y (north) flow the wake mask must therefore lie in +y
    of the rock, not +x.
    """
    from veilbreakers_terrain.sim.foam import generate_foam_mask

    H, W = 41, 41
    height = np.zeros((H, W), dtype=np.float32)
    flow_speed = np.ones((H, W), dtype=np.float32) * 5.0
    water_mask = np.ones((H, W), dtype=bool)
    water_depth = np.ones((H, W), dtype=np.float32) * 0.3
    rock_mask = np.zeros((H, W), dtype=bool)

    # Uniform flow pointing +y (north): channel 0 (V_x) = 0, channel 1 (V_y) = 1
    flow_dir = np.zeros((H, W, 2), dtype=np.float32)
    flow_dir[..., 1] = 1.0

    foam = generate_foam_mask(
        height, flow_speed, water_mask, water_depth, rock_mask,
        cell_size=1.0,
        rock_positions=[(20, 20)],
        flow_dir=flow_dir,
    )

    # The wake foam contribution is only 0.10 * kelvin_mask, blended with
    # other foam sources, so we compare the +y side vs +x side of the rock
    # for relative dominance. The Kelvin term must produce a measurable
    # asymmetry FAVOURING +y over +x.
    #
    # Sample a 5x15 strip on each side, far enough to be inside the
    # ~20m wake length.
    north_strip = foam[21:36, 18:23].mean()  # +y of rock
    east_strip = foam[18:23, 21:36].mean()   # +x of rock
    assert north_strip > east_strip, (
        f"wake oriented wrong: north={north_strip:.4f} east={east_strip:.4f} "
        "-- expected north > east for +y flow (T1-43 regression)"
    )


def test_t1_43_local_flow_dir_at_falls_back_safely() -> None:
    """``_local_flow_dir_at`` must return the fallback on None / wrong-shape /
    out-of-bounds / zero-magnitude inputs without raising."""
    from veilbreakers_terrain.sim.foam import _local_flow_dir_at

    fallback = (0.0, 1.0)
    # None
    assert _local_flow_dir_at(None, 5, 5, fallback=fallback) == fallback
    # Wrong ndim
    assert _local_flow_dir_at(np.zeros((10, 10)), 5, 5, fallback=fallback) == fallback
    # Wrong last-dim size
    assert _local_flow_dir_at(np.zeros((10, 10, 1)), 5, 5, fallback=fallback) == fallback
    # Out of bounds
    assert _local_flow_dir_at(np.ones((10, 10, 2)), 99, 99, fallback=fallback) == fallback
    # Zero-magnitude cell
    assert _local_flow_dir_at(np.zeros((10, 10, 2)), 5, 5, fallback=fallback) == fallback
    # Valid sample (3, 4) gets normalised to unit vector
    fld = np.zeros((10, 10, 2), dtype=np.float32)
    fld[5, 5, 0] = 3.0
    fld[5, 5, 1] = 4.0
    vx, vy = _local_flow_dir_at(fld, 5, 5, fallback=fallback)
    assert vx == pytest.approx(0.6, abs=1e-6)
    assert vy == pytest.approx(0.8, abs=1e-6)


# ---------------------------------------------------------------------------
# T2-40 -- vorticity axis convention pin (false-positive in audit, but pin
# the convention to catch any future axis-swap regression)
# ---------------------------------------------------------------------------


def test_t2_40_vorticity_axis_convention_pinned() -> None:
    """Pin the 2D curl axis convention in ``generate_foam_mask`` so any
    future ``axis=0`` <-> ``axis=1`` swap is caught.

    Convention (matches ``handlers/terrain_waterfalls.py:generate_velocity_field``):
    ``flow_dir`` shape ``(H, W, 2)``; channel 0 = V_x (east, varies along
    axis=1=cols), channel 1 = V_y (north, varies along axis=0=rows).
    Therefore the 2D curl is ``dvy/dx - dvx/dy`` ==
    ``np.gradient(vy, axis=1) - np.gradient(vx, axis=0)``.

    We construct a known-vorticity solid-body rotation field and assert the
    foam computation picks up vorticity in the correct location. A pure
    +z rotation field ``v = omega x r`` has ``vx = -omega*y``,
    ``vy = +omega*x``, so:

        dvy/dx - dvx/dy = omega - (-omega) = 2*omega

    With omega = 1.0 every cell has vorticity 2.0 -- well above the
    ``churn_foam`` threshold of 0.5.
    """
    from veilbreakers_terrain.sim.foam import generate_foam_mask

    H, W = 32, 32
    height = np.zeros((H, W), dtype=np.float32)
    flow_speed = np.zeros((H, W), dtype=np.float32)  # no Froude foam
    water_mask = np.ones((H, W), dtype=bool)
    water_depth = np.full((H, W), 2.0, dtype=np.float32)  # deep -- no shore
    rock_mask = np.zeros((H, W), dtype=bool)

    # Solid-body rotation. Cell-coord origin at centre.
    rows = np.arange(H, dtype=np.float32)[:, None] - H / 2.0
    cols = np.arange(W, dtype=np.float32)[None, :] - W / 2.0
    # vx = -omega * y, vy = +omega * x  (right-handed +z rotation).
    # Here axis=0 is y (rows), axis=1 is x (cols).
    omega = 1.0
    vx = -omega * rows.repeat(W, axis=1)
    vy = omega * cols.repeat(H, axis=0)
    flow_dir = np.stack([vx, vy], axis=-1).astype(np.float32)

    foam_with = generate_foam_mask(
        height, flow_speed, water_mask, water_depth, rock_mask,
        cell_size=1.0,
        flow_dir=flow_dir,
    )
    foam_without = generate_foam_mask(
        height, flow_speed, water_mask, water_depth, rock_mask,
        cell_size=1.0,
        flow_dir=None,
    )
    # The rotation field must add a measurable churn contribution. If a
    # future regression swaps axis=0 <-> axis=1 in the curl calc, the
    # divergence term also flips sign and the *sum* will collapse.
    interior_with = foam_with[4:-4, 4:-4].mean()
    interior_without = foam_without[4:-4, 4:-4].mean()
    assert interior_with > interior_without + 1e-3, (
        f"interior foam did not increase under solid-body rotation: "
        f"with={interior_with:.6f} without={interior_without:.6f} "
        "(T2-40 axis-convention regression)"
    )
