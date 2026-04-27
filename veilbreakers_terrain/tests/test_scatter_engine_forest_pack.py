"""Tests for Forest Pack Pro equivalent functions in _scatter_engine.

Covers:
  - cluster_density_map  (Cluster Mode)
  - edge_scatter         (Edge Mode)
  - apply_collision_exclusion (Collision system)
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from veilbreakers_terrain.handlers._scatter_engine import (
    apply_collision_exclusion,
    cluster_density_map,
    edge_scatter,
)


# ---------------------------------------------------------------------------
# cluster_density_map
# ---------------------------------------------------------------------------

class TestClusterDensityMap:
    def test_shape(self):
        m = cluster_density_map(100.0, 100.0, 64, cluster_size=20.0)
        assert m.shape == (64, 64)

    def test_dtype(self):
        m = cluster_density_map(100.0, 100.0, 64, cluster_size=20.0)
        assert m.dtype == np.float32

    def test_values_in_unit_range(self):
        m = cluster_density_map(100.0, 100.0, 64, cluster_size=20.0)
        assert float(m.min()) >= 0.0
        assert float(m.max()) <= 1.0

    def test_reproducible_with_seed(self):
        a = cluster_density_map(100.0, 100.0, 32, cluster_size=15.0, seed=42)
        b = cluster_density_map(100.0, 100.0, 32, cluster_size=15.0, seed=42)
        np.testing.assert_array_equal(a, b)

    def test_different_seeds_produce_different_maps(self):
        a = cluster_density_map(100.0, 100.0, 32, cluster_size=15.0, seed=1)
        b = cluster_density_map(100.0, 100.0, 32, cluster_size=15.0, seed=2)
        assert not np.array_equal(a, b)

    def test_noise_amount_one_produces_uniform_ones(self):
        # When noise_amount=1.0 the formula is: cluster_map * 0 + 1.0 → all 1.0
        m = cluster_density_map(100.0, 100.0, 32, cluster_size=20.0, noise_amount=1.0)
        np.testing.assert_allclose(m, np.ones((32, 32), dtype=np.float32), rtol=1e-5)

    def test_noise_amount_zero_has_variance(self):
        # With no noise blending the fBm varies spatially; std > 0
        m = cluster_density_map(100.0, 100.0, 64, cluster_size=10.0, noise_amount=0.0)
        assert float(m.std()) > 0.01

    def test_resolution_one(self):
        m = cluster_density_map(100.0, 100.0, 1, cluster_size=20.0)
        assert m.shape == (1, 1)
        assert 0.0 <= float(m[0, 0]) <= 1.0

    def test_tiny_cluster_size_does_not_crash(self):
        # cluster_size → 0 is guarded by max(cluster_size, 1e-6)
        m = cluster_density_map(100.0, 100.0, 16, cluster_size=0.0)
        assert m.shape == (16, 16)

    def test_larger_resolution_produces_larger_map(self):
        m32 = cluster_density_map(100.0, 100.0, 32, cluster_size=20.0, seed=7)
        m64 = cluster_density_map(100.0, 100.0, 64, cluster_size=20.0, seed=7)
        assert m32.shape == (32, 32)
        assert m64.shape == (64, 64)


# ---------------------------------------------------------------------------
# edge_scatter
# ---------------------------------------------------------------------------

class TestEdgeScatter:
    """Arc-length parameterized scatter along a polyline."""

    def _horizontal(self, length=100.0):
        return [(0.0, 0.0), (length, 0.0)]

    def _vertical(self, length=100.0):
        return [(0.0, 0.0), (0.0, length)]

    def _l_shape(self):
        return [(0.0, 0.0), (50.0, 0.0), (50.0, 50.0)]

    def test_returns_list_of_tuples(self):
        pts = edge_scatter(self._horizontal(), spacing=10.0, jitter=0.0)
        assert isinstance(pts, list)
        for item in pts:
            assert len(item) == 3

    def test_count_matches_arc_length_over_spacing(self):
        pts = edge_scatter(self._horizontal(100.0), spacing=10.0, jitter=0.0)
        # 100 / 10 = 10 intervals → 10 or 11 placements depending on boundary
        assert 9 <= len(pts) <= 11

    def test_zero_jitter_places_on_horizontal_line(self):
        pts = edge_scatter(self._horizontal(50.0), spacing=10.0, jitter=0.0)
        for x, y, _ in pts:
            assert abs(y) < 1e-9, f"y={y} should be 0 for horizontal line"
            assert 0.0 <= x <= 50.0

    def test_zero_jitter_places_on_vertical_line(self):
        pts = edge_scatter(self._vertical(50.0), spacing=10.0, jitter=0.0)
        for x, y, _ in pts:
            assert abs(x) < 1e-9, f"x={x} should be 0 for vertical line"
            assert 0.0 <= y <= 50.0

    def test_angle_for_horizontal_segment(self):
        pts = edge_scatter(self._horizontal(30.0), spacing=10.0, jitter=0.0)
        for _, _, angle_deg in pts:
            assert abs(angle_deg) < 1e-9, f"angle should be 0° for horizontal, got {angle_deg}"

    def test_angle_for_vertical_segment(self):
        pts = edge_scatter(self._vertical(30.0), spacing=10.0, jitter=0.0)
        for _, _, angle_deg in pts:
            assert abs(angle_deg - 90.0) < 1e-9, f"angle should be 90° for vertical, got {angle_deg}"

    def test_reproducible_with_seed(self):
        poly = [(0.0, 0.0), (80.0, 40.0)]
        a = edge_scatter(poly, spacing=10.0, jitter=1.0, seed=99)
        b = edge_scatter(poly, spacing=10.0, jitter=1.0, seed=99)
        assert a == b

    def test_different_seeds_produce_different_jitter(self):
        poly = [(0.0, 0.0), (100.0, 0.0)]
        a = edge_scatter(poly, spacing=10.0, jitter=5.0, seed=1)
        b = edge_scatter(poly, spacing=10.0, jitter=5.0, seed=2)
        # Should differ due to RNG state
        assert a != b

    def test_single_point_polyline_returns_empty(self):
        pts = edge_scatter([(5.0, 5.0)], spacing=10.0)
        assert pts == []

    def test_empty_polyline_returns_empty(self):
        pts = edge_scatter([], spacing=10.0)
        assert pts == []

    def test_spacing_controls_density(self):
        poly = self._horizontal(100.0)
        sparse = edge_scatter(poly, spacing=20.0, jitter=0.0)
        dense = edge_scatter(poly, spacing=5.0, jitter=0.0)
        assert len(dense) > len(sparse)

    def test_multi_segment_polyline(self):
        pts_straight = edge_scatter(self._horizontal(100.0), spacing=10.0, jitter=0.0)
        pts_l = edge_scatter(self._l_shape(), spacing=10.0, jitter=0.0)
        # L-shape has 50+50=100 m of arc length → comparable count
        assert abs(len(pts_l) - len(pts_straight)) <= 2

    def test_zero_length_segment_skipped(self):
        # Degenerate segment (duplicate point) should not crash
        poly = [(0.0, 0.0), (0.0, 0.0), (50.0, 0.0)]
        pts = edge_scatter(poly, spacing=10.0, jitter=0.0)
        assert len(pts) >= 1

    def test_large_spacing_returns_few_points(self):
        pts = edge_scatter(self._horizontal(10.0), spacing=100.0, jitter=0.0)
        # Only the start point (accumulated=0 ≤ seg_len=10) may be placed
        assert len(pts) <= 1


# ---------------------------------------------------------------------------
# apply_collision_exclusion
# ---------------------------------------------------------------------------

class TestApplyCollisionExclusion:
    def _pt(self, x, y, vtype="tree"):
        return {"position": (x, y), "vegetation_type": vtype}

    def test_empty_input_returns_empty(self):
        assert apply_collision_exclusion([], {}) == []

    def test_single_item_always_kept(self):
        result = apply_collision_exclusion([self._pt(0, 0)], {"tree": 2.0})
        assert len(result) == 1

    def test_non_colliding_pair_both_kept(self):
        radii = {"tree": 1.0}
        # Distance = 10.0; radius_sum = 2.0 → no collision
        items = [self._pt(0.0, 0.0), self._pt(10.0, 0.0)]
        result = apply_collision_exclusion(items, radii)
        assert len(result) == 2

    def test_colliding_pair_first_wins(self):
        radii = {"tree": 2.0}
        # Distance = 1.0; radius_sum = 4.0 → collision
        first = self._pt(0.0, 0.0)
        second = self._pt(1.0, 0.0)
        result = apply_collision_exclusion([first, second], radii)
        assert len(result) == 1
        assert result[0] is first

    def test_no_kept_pair_violates_radius_sum(self):
        radii = {"tree": 3.0, "bush": 1.5}
        items = []
        rng = __import__("random").Random(0)
        for _ in range(50):
            x, y = rng.uniform(0, 100), rng.uniform(0, 100)
            vt = rng.choice(["tree", "bush"])
            items.append(self._pt(x, y, vt))
        kept = apply_collision_exclusion(items, radii)
        for i, a in enumerate(kept):
            for b in kept[i + 1:]:
                ax, ay = float(a["position"][0]), float(a["position"][1])
                bx, by = float(b["position"][0]), float(b["position"][1])
                ra = radii.get(str(a.get("vegetation_type", "")), 1.5)
                rb = radii.get(str(b.get("vegetation_type", "")), 1.5)
                dist = math.hypot(ax - bx, ay - by)
                assert dist >= (ra + rb) - 1e-6, (
                    f"Collision not resolved: dist={dist:.3f} < r_sum={ra + rb:.3f}"
                )

    def test_unknown_vegetation_type_uses_default_radius(self):
        # "oak" not in radii dict → falls back to default_radius=5.0
        items = [self._pt(0.0, 0.0, "oak"), self._pt(3.0, 0.0, "oak")]
        result = apply_collision_exclusion(items, {}, default_radius=5.0)
        # radius_sum = 10.0; dist = 3.0 → collision → only first kept
        assert len(result) == 1
        assert result[0] is items[0]

    def test_well_separated_cluster_all_kept(self):
        radii = {"tree": 1.0}
        items = [self._pt(float(i * 10), 0.0) for i in range(10)]
        result = apply_collision_exclusion(items, radii)
        assert len(result) == 10

    def test_identical_positions_only_first_kept(self):
        radii = {"tree": 1.0}
        items = [self._pt(5.0, 5.0), self._pt(5.0, 5.0), self._pt(5.0, 5.0)]
        result = apply_collision_exclusion(items, radii)
        assert len(result) == 1
        assert result[0] is items[0]

    def test_mixed_radii_inter_species(self):
        # Large tree (r=5) and small bush (r=0.5) 3m apart → tree wins (placed first)
        radii = {"tree": 5.0, "bush": 0.5}
        tree = self._pt(0.0, 0.0, "tree")
        bush = self._pt(3.0, 0.0, "bush")
        result = apply_collision_exclusion([tree, bush], radii)
        assert len(result) == 1
        assert result[0] is tree

    def test_large_placement_set_performance(self):
        # 1000 placements should complete in reasonable time (not hang)
        import time
        radii = {"tree": 2.0}
        items = [self._pt(float(i % 100) * 3.0, float(i // 100) * 3.0) for i in range(1000)]
        t0 = time.perf_counter()
        result = apply_collision_exclusion(items, radii)
        elapsed = time.perf_counter() - t0
        assert elapsed < 5.0, f"Too slow: {elapsed:.2f}s"
        assert len(result) >= 1
