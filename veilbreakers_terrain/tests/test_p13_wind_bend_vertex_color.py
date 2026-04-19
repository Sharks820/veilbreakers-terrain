"""Tests for Fix 13.2: wind bend vertex color for tree meshes.

REQ-P13-002: Wind bend vertex color (R=xz, G=y) for tree meshes.
Formula: wind_bend_xz = abs(dot(normal_xz, wind_dir)) * (h/tree_height)**2
         wind_bend_y  = 0.1 * wind_bend_xz
"""
import numpy as np
import pytest

from veilbreakers_terrain.handlers.terrain_unity_export import (
    compute_wind_bend_vertex_color,
)


class TestWindBendVertexColor:
    """REQ-P13-002 — compute_wind_bend_vertex_color formula verification."""

    def test_root_vertex_zero_sway(self):
        """Vertex at root (h=0) must produce zero bend — roots are rigid."""
        result = compute_wind_bend_vertex_color(
            vertex_heights=np.array([0.0]),
            tree_height=10.0,
        )
        assert result.shape == (1, 4)
        assert result[0, 0] == 0.0, "R must be 0 at root"
        assert result[0, 1] == 0.0, "G must be 0 at root"

    def test_crown_vertex_max_sway_aligned_normal(self):
        """Vertex at crown with normal fully aligned to wind -> R=1.0, G=0.1."""
        result = compute_wind_bend_vertex_color(
            vertex_heights=np.array([10.0]),
            tree_height=10.0,
            wind_dir_xz=(1.0, 0.0),
            vertex_normals_xz=np.array([[1.0, 0.0]]),
        )
        assert abs(result[0, 0] - 1.0) < 1e-5, f"R at crown should be 1.0, got {result[0,0]}"
        assert abs(result[0, 1] - 0.1) < 1e-5, f"G at crown should be 0.1, got {result[0,1]}"

    def test_g_is_always_ten_percent_of_r(self):
        heights = np.linspace(0, 10, 20)
        result = compute_wind_bend_vertex_color(heights, tree_height=10.0)
        np.testing.assert_allclose(result[:, 1], 0.1 * result[:, 0], atol=1e-6,
                                   err_msg="G must always equal 0.1 * R")

    def test_b_channel_always_zero(self):
        heights = np.linspace(0, 10, 20)
        result = compute_wind_bend_vertex_color(heights, tree_height=10.0)
        np.testing.assert_array_equal(result[:, 2], 0.0)

    def test_a_channel_always_one(self):
        heights = np.linspace(0, 10, 20)
        result = compute_wind_bend_vertex_color(heights, tree_height=10.0)
        np.testing.assert_array_equal(result[:, 3], 1.0)

    def test_zero_wind_direction_gives_all_zeros(self):
        result = compute_wind_bend_vertex_color(
            vertex_heights=np.array([5.0, 10.0]),
            tree_height=10.0,
            wind_dir_xz=(0.0, 0.0),
        )
        assert result[0, 0] == 0.0
        assert result[1, 0] == 0.0
        assert result[0, 3] == 1.0  # A still 1.0

    def test_output_shape(self):
        heights = np.linspace(0, 5, 7)
        result = compute_wind_bend_vertex_color(heights, tree_height=5.0)
        assert result.shape == (7, 4)

    def test_normal_perpendicular_to_wind_gives_zero_r(self):
        """Normal pointing 90deg from wind -> dot product = 0 -> R = 0."""
        result = compute_wind_bend_vertex_color(
            vertex_heights=np.array([10.0]),
            tree_height=10.0,
            wind_dir_xz=(1.0, 0.0),
            vertex_normals_xz=np.array([[0.0, 1.0]]),  # perpendicular
        )
        assert abs(result[0, 0]) < 1e-6, f"R should be 0 for perpendicular normal, got {result[0,0]}"

    def test_height_above_tree_height_clamped(self):
        """Heights > tree_height must not produce R > 1.0."""
        result = compute_wind_bend_vertex_color(
            vertex_heights=np.array([20.0]),
            tree_height=10.0,
            wind_dir_xz=(1.0, 0.0),
        )
        assert result[0, 0] <= 1.0

    def test_quadratic_falloff_midpoint(self):
        """At half height, R = (0.5)**2 = 0.25 of crown value (with aligned normal)."""
        result_crown = compute_wind_bend_vertex_color(
            vertex_heights=np.array([10.0]),
            tree_height=10.0,
            wind_dir_xz=(1.0, 0.0),
            vertex_normals_xz=np.array([[1.0, 0.0]]),
        )
        result_mid = compute_wind_bend_vertex_color(
            vertex_heights=np.array([5.0]),
            tree_height=10.0,
            wind_dir_xz=(1.0, 0.0),
            vertex_normals_xz=np.array([[1.0, 0.0]]),
        )
        expected_mid_r = result_crown[0, 0] * 0.25
        assert abs(result_mid[0, 0] - expected_mid_r) < 1e-5

    def test_output_dtype_float32(self):
        result = compute_wind_bend_vertex_color(np.array([5.0]), tree_height=10.0)
        assert result.dtype == np.float32

    def test_all_values_in_zero_one(self):
        rng = np.random.default_rng(99)
        heights = rng.uniform(0, 15, 500).astype(np.float32)
        normals = rng.uniform(-1, 1, (500, 2)).astype(np.float32)
        result = compute_wind_bend_vertex_color(
            heights, tree_height=10.0, wind_dir_xz=(0.7, 0.3), vertex_normals_xz=normals
        )
        assert np.all(result[:, :3] >= 0.0), "R/G/B must be >= 0"
        assert np.all(result[:, :3] <= 1.0), "R/G/B must be <= 1"
