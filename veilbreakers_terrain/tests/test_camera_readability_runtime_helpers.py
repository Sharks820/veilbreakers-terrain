"""Direct tests for camera framing and god-ray readability helpers."""

from __future__ import annotations

import math

import numpy as np


def test_bresenham_cells_cover_diagonal_and_steep_lines():
    from veilbreakers_terrain.handlers.terrain_framing import _bresenham_cells

    assert _bresenham_cells(0, 0, 3, 3) == [(0, 0), (1, 1), (2, 2), (3, 3)]
    assert _bresenham_cells(0, 0, 3, 1) == [(0, 0), (1, 0), (2, 1), (3, 1)]
    assert _bresenham_cells(3, 3, 0, 0) == [(3, 3), (2, 2), (1, 1), (0, 0)]


def test_framing_quality_gate_flags_missing_pair_metrics_only():
    from veilbreakers_terrain.handlers.terrain_framing import _framing_quality_gate
    from veilbreakers_terrain.handlers.terrain_semantics import PassResult, TerrainMaskStack

    stack = TerrainMaskStack(
        tile_size=3,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=np.zeros((3, 3), dtype=np.float32),
    )
    ok_result = PassResult(
        pass_name="framing",
        status="ok",
        duration_seconds=0.01,
        metrics={"vantage_count": 1, "feature_count": 1, "v0_f0_max_cut_m": 0.0},
    )
    missing_result = PassResult(
        pass_name="framing",
        status="ok",
        duration_seconds=0.01,
        metrics={"vantage_count": 1, "feature_count": 2, "v0_f0_max_cut_m": 0.0},
    )

    assert _framing_quality_gate(ok_result, stack) == []
    issues = _framing_quality_gate(missing_result, stack)
    assert [issue.code for issue in issues] == ["FRAMING_PAIR_MISSING"]
    assert "v0" in issues[0].message


def test_god_ray_silhouette_shadow_marks_cells_blocked_by_ridge():
    from veilbreakers_terrain.handlers.terrain_god_ray_hints import _build_terrain_silhouette_shadow

    h = np.zeros((5, 5), dtype=np.float32)
    h[:, 2] = 10.0
    shadow = _build_terrain_silhouette_shadow(h, sun_az=math.pi / 2.0, sun_alt=0.2, cell_size=1.0)

    assert shadow.dtype == bool
    assert shadow.shape == h.shape
    assert bool(shadow[2, 0])
    assert not bool(shadow[2, 4])
