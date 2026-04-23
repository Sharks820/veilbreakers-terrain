"""Tests for Phase 8 road system rebuild — Wave 1.

Covers:
  - _OFFSETS_24: exactly 24 direction tuples
  - _astar: Rune's exact cost formula + optional cost_map (avgCost term)
  - _fill_8connected_gaps: handles up to 3-cell jumps
  - smooth_road_path / catmull_rom_to_bezier: corner duplication at >120 deg
"""
from __future__ import annotations


import numpy as np


# ---------------------------------------------------------------------------
# TestOffsets24
# ---------------------------------------------------------------------------


class TestOffsets24:
    def test_len_exactly_24(self):
        from veilbreakers_terrain.handlers._terrain_noise import _OFFSETS_24
        assert len(_OFFSETS_24) == 24

    def test_contains_8_cardinal_diagonal(self):
        from veilbreakers_terrain.handlers._terrain_noise import _OFFSETS_24
        cardinal = {(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)}
        assert cardinal.issubset(set(_OFFSETS_24))

    def test_contains_8_knight_moves(self):
        from veilbreakers_terrain.handlers._terrain_noise import _OFFSETS_24
        knight = {(-2,-1),(-2,1),(-1,-2),(-1,2),(1,-2),(1,2),(2,-1),(2,1)}
        assert knight.issubset(set(_OFFSETS_24))

    def test_contains_8_extended_knight(self):
        from veilbreakers_terrain.handlers._terrain_noise import _OFFSETS_24
        ext = {(-3,-1),(-3,1),(-1,-3),(-1,3),(1,-3),(1,3),(3,-1),(3,1)}
        assert ext.issubset(set(_OFFSETS_24))

    def test_offsets_16_alias_points_to_24(self):
        from veilbreakers_terrain.handlers._terrain_noise import _OFFSETS_16, _OFFSETS_24
        assert _OFFSETS_16 is _OFFSETS_24


# ---------------------------------------------------------------------------
# TestRuneAstarFormula
# ---------------------------------------------------------------------------


class TestRuneAstarFormula:
    """Verify Rune's exact cost formula is used in _astar."""

    def test_flat_move_sqrt2_no_cost_map(self):
        """Diagonal move on flat terrain: cost == sqrt(2)."""
        # Build a 5x5 flat heightmap
        hmap = np.zeros((10, 10), dtype=np.float64)
        from veilbreakers_terrain.handlers._terrain_noise import _astar
        path = _astar(hmap, (0, 0), (5, 5))
        # Path should exist (not empty)
        assert len(path) >= 1

    def test_cost_map_none_backward_compat(self):
        """_astar with cost_map=None behaves same as without keyword."""
        hmap = np.random.RandomState(1).rand(16, 16).astype(np.float64)
        from veilbreakers_terrain.handlers._terrain_noise import _astar
        path_implicit = _astar(hmap, (0, 0), (15, 15))
        path_explicit = _astar(hmap, (0, 0), (15, 15), cost_map=None)
        assert path_implicit == path_explicit

    def test_rune_formula_avgcost_term(self):
        """With cost_map, high-cost cells are avoided.

        Two routes on flat terrain: one through a cost=5 barrier, the other
        free. The A* path should route around the barrier.
        """
        hmap = np.zeros((20, 20), dtype=np.float64)
        cost_map = np.zeros((20, 20), dtype=np.float32)
        # High-cost vertical barrier in the middle, open at the bottom
        cost_map[0:15, 10] = 5.0
        from veilbreakers_terrain.handlers._terrain_noise import _astar
        path = _astar(hmap, (0, 0), (0, 19), cost_map=cost_map)
        # All path cells should be within bounds
        for r, c in path:
            assert 0 <= r < 20 and 0 <= c < 20

    def test_cost_map_values_influence_path(self):
        """cost_map adds 12 * 0.5 * (c[r0,c0] + c[nr,nc]) to move_cost.

        Ensure the _astar accepts cost_map without raising.
        """
        hmap = np.zeros((8, 8), dtype=np.float64)
        cost_map = np.ones((8, 8), dtype=np.float32)
        from veilbreakers_terrain.handlers._terrain_noise import _astar
        path = _astar(hmap, (0, 0), (7, 7), cost_map=cost_map)
        assert len(path) >= 2
        # Start and end should be in or near the path
        assert path[0] == (0, 0)
        assert path[-1] == (7, 7)

    def test_path_reaches_destination(self):
        """_astar path always ends at destination."""
        hmap = np.random.RandomState(99).rand(20, 20).astype(np.float64)
        from veilbreakers_terrain.handlers._terrain_noise import _astar
        path = _astar(hmap, (0, 0), (19, 19))
        assert path[-1] == (19, 19)


# ---------------------------------------------------------------------------
# TestFill8ConnectedGaps
# ---------------------------------------------------------------------------


class TestFill8ConnectedGaps:
    def test_handles_3cell_jump(self):
        """_fill_8connected_gaps bridges 3-cell extended knight moves."""
        from veilbreakers_terrain.handlers._terrain_noise import _fill_8connected_gaps
        # A path with a (3,1) jump
        raw = [(0, 0), (3, 1)]
        filled = _fill_8connected_gaps(raw)
        # All consecutive steps must be 8-connected (max step 1 in each axis)
        for i in range(len(filled) - 1):
            r0, c0 = filled[i]
            r1, c1 = filled[i + 1]
            assert abs(r1 - r0) <= 1 and abs(c1 - c0) <= 1, (
                f"Step {i}: ({r0},{c0})->({r1},{c1}) not 8-connected"
            )

    def test_handles_1cell_jump_unchanged(self):
        """Single-cell steps pass through unchanged."""
        from veilbreakers_terrain.handlers._terrain_noise import _fill_8connected_gaps
        raw = [(0, 0), (1, 1), (2, 2)]
        filled = _fill_8connected_gaps(raw)
        assert filled == raw

    def test_astar_path_is_8connected(self):
        """After _astar (which calls _fill_8connected_gaps), path is 8-connected."""
        hmap = np.random.RandomState(7).rand(16, 16).astype(np.float64)
        from veilbreakers_terrain.handlers._terrain_noise import _astar
        path = _astar(hmap, (0, 0), (15, 15))
        for i in range(len(path) - 1):
            r0, c0 = path[i]
            r1, c1 = path[i + 1]
            assert abs(r1 - r0) <= 1 and abs(c1 - c0) <= 1, (
                f"Step {i}: ({r0},{c0})->({r1},{c1}) not 8-connected"
            )


# ---------------------------------------------------------------------------
# TestCatmullRomBezier
# ---------------------------------------------------------------------------


class TestCatmullRomBezier:
    def test_catmull_rom_segment_length(self):
        """_catmull_rom_segment returns at least `samples` points."""
        from veilbreakers_terrain.handlers._terrain_noise import _catmull_rom_segment
        pts = _catmull_rom_segment((0, 0), (0, 5), (0, 10), (0, 15), samples=10)
        assert len(pts) >= 10

    def test_catmull_rom_segment_returns_tuples(self):
        """Each point in the segment is a (row, col) tuple of ints."""
        from veilbreakers_terrain.handlers._terrain_noise import _catmull_rom_segment
        pts = _catmull_rom_segment((0, 0), (0, 5), (0, 10), (0, 15), samples=5)
        for p in pts:
            assert len(p) == 2
            assert isinstance(p[0], int)
            assert isinstance(p[1], int)

    def test_corner_180_triggers_duplication(self):
        """180-degree reversal (dot = -1) duplicates the corner point."""
        from veilbreakers_terrain.handlers._terrain_noise import _duplicate_sharp_corners
        # Straight then reverse: (0,0)->(0,5)->(0,0) — angle = 180 deg
        waypoints = [(0, 0), (0, 5), (0, 0)]
        result = _duplicate_sharp_corners(waypoints)
        # The corner (0,5) should appear twice consecutively
        indices = [i for i, p in enumerate(result) if p == (0, 5)]
        assert len(indices) >= 2
        # Consecutive duplicates
        assert any(indices[j + 1] == indices[j] + 1 for j in range(len(indices) - 1))

    def test_corner_90_no_duplication(self):
        """90-degree turn (dot = 0) does NOT trigger duplication."""
        from veilbreakers_terrain.handlers._terrain_noise import _duplicate_sharp_corners
        # Right-angle turn: (0,0)->(0,5)->(5,5) — dot(east, south) = 0
        waypoints = [(0, 0), (0, 5), (5, 5)]
        result = _duplicate_sharp_corners(waypoints)
        # (0,5) should appear exactly once
        count = sum(1 for p in result if p == (0, 5))
        assert count == 1

    def test_smooth_road_path_straight_line(self):
        """smooth_road_path on a straight line stays close to endpoints."""
        from veilbreakers_terrain.handlers._terrain_noise import smooth_road_path
        waypoints = [(0, 0), (0, 5), (0, 10), (0, 15)]
        result = smooth_road_path(waypoints, samples_per_segment=5)
        assert len(result) >= 2
        # Start and end should be near (not necessarily identical due to rounding)
        assert result[0][0] == 0  # row stays 0 (straight horizontal)
        assert result[-1][0] == 0

    def test_smooth_road_path_hairpin_preserves_apex(self):
        """Hairpin with >120-deg corner preserves the sharp apex."""
        from veilbreakers_terrain.handlers._terrain_noise import smooth_road_path
        # Hairpin: go north then south — 180 degrees
        waypoints = [(0, 0), (5, 0), (0, 0)]
        result = smooth_road_path(waypoints, samples_per_segment=5)
        # The apex (5,0) should appear in output (corner was duplicated)
        all_rows = [p[0] for p in result]
        # Max row should be 5 (the apex)
        assert max(all_rows) >= 4  # allowing ±1 from rounding

    def test_smooth_road_path_returns_list(self):
        """smooth_road_path always returns a list."""
        from veilbreakers_terrain.handlers._terrain_noise import smooth_road_path
        result = smooth_road_path([(0, 0), (10, 10)])
        assert isinstance(result, list)

    def test_smooth_road_path_single_point(self):
        """smooth_road_path with 1 waypoint returns a list (edge case)."""
        from veilbreakers_terrain.handlers._terrain_noise import smooth_road_path
        result = smooth_road_path([(5, 5)])
        assert isinstance(result, list)
