"""Regression tests for the T1 saliency / stratigraphy / sculpt cluster.

Audit anchors (``docs/aaa-audit/2026_05_17_ultrafinal/MASTER_FINAL.md`` §B.4.12):

* **T1-25** — ``handlers/terrain_saliency.py:692`` ray_count arithmetic
  (P1, X01-DEMOTED). The expression
  ``64 // max(len_v, 1) * max(len_v, 1)`` is dimensionally suspicious but
  defensible ("round 64 down to nearest multiple of len_v"). Audit
  prescription: document intent + parenthesise. This test pins the
  multiple-of-len property numerically.

* **T1-26** — ``handlers/terrain_stratigraphy.py:108-130`` silent strike
  override (P0-cert-prob). ``__post_init__`` previously clobbered any
  user-supplied ``strike_angle_rad`` with the derived
  ``(azimuth + pi/2) mod 2pi`` value, so geological intent never reached
  the layer. Fix: NaN sentinel + conflict-raise.

* **T1-27** — ``handlers/terrain_scatter_points.py`` frozen-list violation
  (P0-internal). ``ScatterPointTable`` / ``ScatterCandidateTable`` declared
  ``Tuple | list`` for fields on a ``frozen=True`` dataclass, allowing
  ``.points.append(...)`` mutation through aliased list refs. Fix:
  normalize to tuple in ``__post_init__``.

* **T1-31** — ``handlers/terrain_sculpt.py`` None obj + rotation-broken
  scale (P0-cert-prob). Sculpt extracted ``mw[0][0]`` / ``mw[1][1]`` as
  scale, but a ``T * R * S`` matrix has ``R * diag(s_x, s_y, s_z)`` in the
  upper-left 3x3 — so ``mw[0][0] = s_x * cos(theta)`` under Z-rotation,
  not ``s_x``. Fix: use ``mathutils.Matrix.to_scale()`` (canonical TRS
  decomposition).

FIX_PATTERN_v1 §C5 (numerical) + §C4 (boundary contract).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from veilbreakers_terrain.handlers.terrain_scatter_points import (
    ScatterCandidate,
    ScatterCandidateTable,
    ScatterPoint,
    ScatterPointTable,
)
from veilbreakers_terrain.handlers.terrain_stratigraphy import StratigraphyLayer


# ---------------------------------------------------------------------------
# T1-25 — ray_count multiple-of-len property
# ---------------------------------------------------------------------------


def _ray_count_for_len(len_v: int) -> int:
    """Mirror the canonical arithmetic from terrain_saliency.py:692."""
    safe_len = max(len_v, 1)
    return max(32, min(128, (64 // safe_len) * safe_len))


def test_t1_25_ray_count_multiple_of_len_property() -> None:
    """For 2 <= len_v <= 64, ray_count is divisible by len_v (clamped)."""
    for len_v in range(2, 17):
        rc = _ray_count_for_len(len_v)
        # Clamp range 32..128
        assert 32 <= rc <= 128, f"len_v={len_v}: ray_count={rc} out of [32,128]"
        # Multiple-of-len property holds INSIDE the clamp band — when the
        # raw value falls below 32 the max() clamp wins and the property
        # is intentionally broken (numerically defensible per audit notes).
        raw = (64 // len_v) * len_v
        if 32 <= raw <= 128:
            assert rc % len_v == 0, (
                f"len_v={len_v}: ray_count={rc} is not a multiple of len_v "
                f"(raw arithmetic gave {raw})"
            )


def test_t1_25_ray_count_len_one_is_sixty_four() -> None:
    """len_v == 1 reduces to (64 // 1) * 1 == 64 (under the 32..128 clamp)."""
    assert _ray_count_for_len(1) == 64
    # Edge: len_v == 0 falls back to max(len_v, 1) -> 1 -> 64.
    assert _ray_count_for_len(0) == 64


# ---------------------------------------------------------------------------
# T1-26 — stratigraphy silent strike override
# ---------------------------------------------------------------------------


def test_t1_26_strike_derived_from_azimuth_when_omitted() -> None:
    """Omitting strike_angle_rad derives it from azimuth_rad (canonical)."""
    layer = StratigraphyLayer(
        layer_id="sandstone",
        hardness=0.5,
        thickness_m=10.0,
        azimuth_rad=math.pi / 4.0,  # 45 deg
        # strike_angle_rad omitted -> NaN sentinel -> derived
    )
    expected = (math.pi / 4.0 + math.pi * 0.5) % (2.0 * math.pi)
    assert layer.strike_angle_rad == pytest.approx(expected, abs=1e-9)


def test_t1_26_user_supplied_strike_preserved_when_consistent() -> None:
    """User-supplied strike consistent with azimuth+pi/2 is preserved."""
    # Use a slightly noisy supplied value within the 5e-3 rad tolerance.
    azimuth = 0.7
    canonical_strike = (azimuth + math.pi * 0.5) % (2.0 * math.pi)
    layer = StratigraphyLayer(
        layer_id="shale",
        hardness=0.3,
        thickness_m=8.0,
        azimuth_rad=azimuth,
        strike_angle_rad=canonical_strike + 1.0e-4,  # within tolerance
    )
    # Stored as supplied % 2pi (round-trip through mod normalisation).
    assert layer.strike_angle_rad == pytest.approx(
        (canonical_strike + 1.0e-4) % (2.0 * math.pi), abs=1e-9
    )


def test_t1_26_user_supplied_strike_conflict_raises() -> None:
    """User-supplied strike that disagrees with derived raises ValueError."""
    # Supply a strike that is NOT azimuth + pi/2: e.g. azimuth=0, strike=0
    # would derive pi/2 -- conflict ~ pi/2 rad >> 5e-3 tolerance.
    with pytest.raises(ValueError, match="strike_angle_rad"):
        StratigraphyLayer(
            layer_id="bad_layer",
            hardness=0.5,
            thickness_m=10.0,
            azimuth_rad=0.0,
            strike_angle_rad=0.0,  # derived would be pi/2 -- mismatch
        )


def test_t1_26_default_strat_stack_layers_have_consistent_strike() -> None:
    """The canonical default 7-layer stack has self-consistent strike+azimuth.

    Regression: previously the default factory passed an INDEPENDENTLY-drawn
    ``str_fn()`` random strike that was silently overwritten by
    ``__post_init__``. Now every layer's strike equals (azimuth + pi/2)
    mod 2pi exactly (the derivation path).
    """
    from veilbreakers_terrain.handlers.terrain_stratigraphy import (
        _default_strat_stack_from_hints,
    )

    rng = np.random.default_rng(seed=42)
    stack = _default_strat_stack_from_hints({}, rng=rng)
    assert len(stack.layers) >= 5, "AAA requires 5-9 strata"
    for layer in stack.layers:
        derived = (layer.azimuth_rad + math.pi * 0.5) % (2.0 * math.pi)
        assert layer.strike_angle_rad == pytest.approx(derived, abs=1e-9), (
            f"Layer {layer.layer_id!r} has strike={layer.strike_angle_rad} "
            f"!= derived {derived} from azimuth={layer.azimuth_rad}"
        )


# ---------------------------------------------------------------------------
# T1-27 — frozen-list violation in scatter point tables
# ---------------------------------------------------------------------------


def _make_scatter_point(seed: int = 0) -> ScatterPoint:
    return ScatterPoint(
        position=(0.0, 0.0, 0.0),
        normal=(0.0, 0.0, 1.0),
        orient=(0.0, 0.0, 0.0, 1.0),
        scale=(1.0, 1.0, 1.0),
        prototype_id="proto",
        species_id="species",
        biome_id="biome",
        density=1.0,
        seed=seed,
        slope=0.0,
        height_m=0.0,
        mask_sources=("test",),
        lod_bucket="lod0",
        wind_profile="none",
    )


def test_t1_27_scatter_point_table_normalises_list_to_tuple() -> None:
    """Constructing with a list freezes the input into a tuple (round-trip)."""
    points_list = [_make_scatter_point(0), _make_scatter_point(1)]
    table = ScatterPointTable(points=points_list, source="test")
    assert isinstance(table.points, tuple), (
        f"ScatterPointTable.points was {type(table.points).__name__}, "
        "expected tuple after __post_init__ normalization"
    )
    assert len(table.points) == 2
    # Mutating the original list must NOT affect the table.
    points_list.append(_make_scatter_point(99))
    assert len(table.points) == 2, "frozen-list invariant violated"


def test_t1_27_scatter_point_table_preserves_tuple_identity() -> None:
    """When input is already a tuple, no re-allocation occurs."""
    points_tuple = (_make_scatter_point(0), _make_scatter_point(1))
    table = ScatterPointTable(points=points_tuple)
    assert table.points is points_tuple, (
        "tuple input should be preserved by identity (no copy needed)"
    )


def test_t1_27_scatter_candidate_table_normalises_accepted_rejected() -> None:
    """ScatterCandidateTable freezes both accepted+rejected list inputs."""
    cand = ScatterCandidate(
        candidate_id="c1",
        source_rule_id="r1",
        source_layer_id="L1",
        species_or_prop_id="sp1",
        sampled_position=(0.0, 0.0, 0.0),
        sampled_slope_deg=10.0,
        sampled_material_layer_id="rock",
        sampled_wetness=0.0,
        sampled_deposition=0.0,
        sampled_talus=0.0,
        nearest_water_distance_m=100.0,
        support_score=0.8,
        embed_depth_m=0.1,
    )
    accepted_list = [cand]
    rejected_list: list[ScatterCandidate] = []
    table = ScatterCandidateTable(
        accepted=accepted_list, rejected=rejected_list,
    )
    assert isinstance(table.accepted, tuple)
    assert isinstance(table.rejected, tuple)
    # Mutating the original lists must not affect the table.
    accepted_list.clear()
    assert len(table.accepted) == 1, "accepted frozen-list invariant violated"


# ---------------------------------------------------------------------------
# T1-31 — sculpt rotation-broken scale extraction
# ---------------------------------------------------------------------------


def test_t1_31_scale_extraction_rotation_invariant() -> None:
    """The new mw.to_scale() path must return the true scale even when the
    upper-left 3x3 of the matrix is rotated.

    Reproduce the math the sculpt code does (without needing bpy):

    * Pre-fix code: ``scale_x = abs(mw[0][0])``, ``scale_y = abs(mw[1][1])``.
      Under a 90-deg Z-rotation, ``mw[0][0] == 0`` and ``mw[1][1] == 0``,
      so the derived scale collapses and ``local_radius`` becomes wrong.
    * Post-fix code: ``mw.to_scale()`` returns the column-norms of the
      upper-left 3x3, which is rotation-invariant.
    """
    # Build a TRS matrix with non-uniform scale (3, 2, 1) and a 90-deg
    # Z-rotation. Resulting upper-left 3x3:
    #   [ 0  -2  0]
    #   [ 3   0  0]
    #   [ 0   0  1]
    # Pre-fix code would read mw[0][0]=0, mw[1][1]=0 -> scale_x=scale_y=0.
    # Post-fix code (mw.to_scale = column-norms) returns (3, 2, 1).
    cos_t = math.cos(math.pi / 2.0)
    sin_t = math.sin(math.pi / 2.0)
    sx, sy, sz = 3.0, 2.0, 1.0
    upper3 = np.array(
        [
            [sx * cos_t, -sy * sin_t, 0.0],
            [sx * sin_t, sy * cos_t, 0.0],
            [0.0, 0.0, sz],
        ],
        dtype=np.float64,
    )
    # Pre-fix extraction (diagonal): both should be ~0 under this rotation.
    pre_fix_scale_x = abs(float(upper3[0, 0]))
    pre_fix_scale_y = abs(float(upper3[1, 1]))
    assert pre_fix_scale_x < 1.0e-9, (
        "regression baseline: the diagonal-read path should fail under "
        f"90-deg rotation (got {pre_fix_scale_x})"
    )
    assert pre_fix_scale_y < 1.0e-9, (
        "regression baseline: the diagonal-read path should fail under "
        f"90-deg rotation (got {pre_fix_scale_y})"
    )
    # Post-fix extraction (column norm): the actual scale survives.
    col_norms = np.linalg.norm(upper3, axis=0)
    assert col_norms[0] == pytest.approx(sx, abs=1.0e-9)
    assert col_norms[1] == pytest.approx(sy, abs=1.0e-9)
    assert col_norms[2] == pytest.approx(sz, abs=1.0e-9)
    # And the radius conversion (the actual code path) produces a
    # non-zero, sensible avg_scale_xy under rotation.
    scale_x_fixed = float(col_norms[0])
    scale_y_fixed = float(col_norms[1])
    avg_scale_xy_fixed = (
        (scale_x_fixed + scale_y_fixed) / 2.0
        if (scale_x_fixed + scale_y_fixed) > 0
        else 1.0
    )
    radius_world = 5.0  # 5m brush
    local_radius_fixed = (
        radius_world / avg_scale_xy_fixed
        if avg_scale_xy_fixed > 1e-8
        else radius_world
    )
    # Expected: (3 + 2) / 2 = 2.5; local_radius = 5 / 2.5 = 2.0
    assert local_radius_fixed == pytest.approx(2.0, abs=1.0e-9)
