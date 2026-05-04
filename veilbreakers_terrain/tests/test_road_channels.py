"""Tests for Phase 8 road system rebuild — Wave 2.

Covers:
  - road_mask and road_sdf_dist fields on TerrainMaskStack
  - Both channels in _ARRAY_CHANNELS
  - to_npz/from_npz round-trip preserves road_mask
  - _apply_road_profile_to_heightmap: 3-zone carving correctness
  - road_mask is binary uint8; road_sdf_dist is float32 EDT
"""
from __future__ import annotations

import math

import numpy as np


# ---------------------------------------------------------------------------
# TestRoadMaskChannel
# ---------------------------------------------------------------------------


def _make_stack(size=5):
    from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack
    return TerrainMaskStack(
        tile_size=size,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=np.zeros((size, size), dtype=np.float64),
    )


class TestRoadMaskChannel:
    def test_road_mask_field_exists(self):
        stack = _make_stack()
        assert hasattr(stack, "road_mask")
        assert stack.road_mask is None

    def test_road_sdf_dist_field_exists(self):
        stack = _make_stack()
        assert hasattr(stack, "road_sdf_dist")
        assert stack.road_sdf_dist is None

    def test_road_mask_in_array_channels(self):
        stack = _make_stack()
        assert "road_mask" in stack._ARRAY_CHANNELS

    def test_road_sdf_dist_in_array_channels(self):
        stack = _make_stack()
        assert "road_sdf_dist" in stack._ARRAY_CHANNELS

    def test_set_road_mask_does_not_raise(self):
        stack = _make_stack()
        mask = np.zeros((5, 5), dtype=np.uint8)
        stack.set("road_mask", mask, "test_pass")
        assert stack.road_mask is not None

    def test_set_road_sdf_dist_does_not_raise(self):
        stack = _make_stack()
        sdf = np.zeros((5, 5), dtype=np.float32)
        stack.set("road_sdf_dist", sdf, "test_pass")
        assert stack.road_sdf_dist is not None

    def test_to_npz_from_npz_roundtrip_road_mask(self, tmp_path):
        """road_mask values are preserved through to_npz/from_npz."""
        from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack
        stack = _make_stack(size=4)
        mask = np.array([[1, 0, 1, 0],
                         [0, 1, 0, 1],
                         [1, 0, 1, 0],
                         [0, 1, 0, 1]], dtype=np.uint8)
        stack.set("road_mask", mask, "test_pass")
        out_path = tmp_path / "test_stack.npz"
        stack.to_npz(out_path)
        stack2 = TerrainMaskStack.from_npz(out_path)
        assert stack2.road_mask is not None
        np.testing.assert_array_equal(stack2.road_mask, mask)


# ---------------------------------------------------------------------------
# TestThreeZoneCarving
# ---------------------------------------------------------------------------


class TestThreeZoneCarving:
    """Tests for _apply_road_profile_to_heightmap."""

    def _make_hump_hmap(self, size=30):
        """Heightmap with a hump in the middle."""
        hmap = np.zeros((size, size), dtype=np.float64)
        for r in range(size):
            for c in range(size):
                hmap[r, c] = 0.5 + 0.4 * math.sin(math.pi * r / size) * math.sin(math.pi * c / size)
        return hmap

    def test_returns_three_tuple(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _apply_road_profile_to_heightmap
        hmap = np.zeros((10, 10), dtype=np.float64) + 0.5
        path = [(5, c) for c in range(10)]
        result = _apply_road_profile_to_heightmap(hmap, path)
        assert len(result) == 3
        carved, road_mask, road_sdf_dist = result
        assert isinstance(carved, np.ndarray)
        assert isinstance(road_mask, np.ndarray)
        assert isinstance(road_sdf_dist, np.ndarray)

    def test_zone1_cells_flattened(self):
        """Cells within road_width of the path have near-zero variance (flattened)."""
        from veilbreakers_terrain.handlers.terrain_twelve_step import _apply_road_profile_to_heightmap
        hmap = self._make_hump_hmap(30)
        path = [(15, c) for c in range(30)]  # horizontal path at row 15
        carved, road_mask, _ = _apply_road_profile_to_heightmap(
            hmap, path, road_width=2.0, shoulder_width=3.0, influence_width=4.0
        )
        # Within road_width=2, variance should be low (all blended to road elevation)
        zone1_cells = [(r, c) for r in range(30) for c in range(30) if road_mask[r, c] == 1]
        assert len(zone1_cells) > 0, "Zone 1 should have cells"
        heights = [float(carved[r, c]) for r, c in zone1_cells]
        variance = np.var(heights)
        # Variance should be very small — zone 1 is heavily blended toward road elevation
        assert variance < 0.05, f"Zone 1 variance too high: {variance:.4f}"

    def test_zone2_between_road_and_terrain(self):
        """Zone 2 cells (shoulder) have values between road elev and original terrain."""
        from veilbreakers_terrain.handlers.terrain_twelve_step import _apply_road_profile_to_heightmap
        # Flat hmap with known values; road at row 10
        hmap = np.zeros((20, 20), dtype=np.float64)
        # Create a slope away from the road path
        for r in range(20):
            hmap[r, :] = abs(r - 10) * 0.05
        path = [(10, c) for c in range(20)]
        road_width = 1.0
        shoulder_width = 3.0
        carved, road_mask, _ = _apply_road_profile_to_heightmap(
            hmap, path, road_width=road_width, shoulder_width=shoulder_width, influence_width=4.0
        )
        # Row 3 is about 7 cells from row 10 — outside influence (well beyond zone 3)
        # Row 12 is 2 cells from row 10 — in zone 2 (shoulder)
        road_elev = float(hmap[10, 10])  # ~0.0 at the road line
        orig_row12 = float(hmap[12, 10])  # 0.1
        carved_row12 = float(carved[12, 10])
        # Should be between road elev and original
        assert road_elev <= carved_row12 <= orig_row12 + 0.01, (
            f"Zone 2 value {carved_row12:.4f} not between road {road_elev:.4f} and orig {orig_row12:.4f}"
        )

    def test_road_mask_is_uint8_binary(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _apply_road_profile_to_heightmap
        hmap = np.zeros((20, 20), dtype=np.float64) + 0.5
        path = [(10, c) for c in range(20)]
        _, road_mask, _ = _apply_road_profile_to_heightmap(hmap, path)
        assert road_mask.dtype == np.uint8
        assert set(np.unique(road_mask)).issubset({0, 1})

    def test_road_mask_zone1_is_1(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _apply_road_profile_to_heightmap
        hmap = np.zeros((20, 20), dtype=np.float64) + 0.5
        path = [(10, c) for c in range(20)]
        _, road_mask, _ = _apply_road_profile_to_heightmap(hmap, path, road_width=2.0)
        # Cells at row 10 (exactly on path) should be Zone 1 → mask=1
        assert road_mask[10, 10] == 1

    def test_road_mask_outside_zone1_is_0(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _apply_road_profile_to_heightmap
        hmap = np.zeros((20, 20), dtype=np.float64) + 0.5
        path = [(10, c) for c in range(20)]
        _, road_mask, _ = _apply_road_profile_to_heightmap(hmap, path, road_width=2.0)
        # Row 0 is far from the path — should be 0
        assert road_mask[0, 10] == 0

    def test_road_sdf_dist_dtype_float32(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _apply_road_profile_to_heightmap
        hmap = np.zeros((20, 20), dtype=np.float64) + 0.5
        path = [(10, c) for c in range(20)]
        _, _, road_sdf_dist = _apply_road_profile_to_heightmap(hmap, path)
        assert road_sdf_dist.dtype == np.float32

    def test_road_sdf_dist_zone1_is_zero(self):
        """road_sdf_dist is 0 inside Zone 1 (road_mask=1)."""
        from veilbreakers_terrain.handlers.terrain_twelve_step import _apply_road_profile_to_heightmap
        hmap = np.zeros((20, 20), dtype=np.float64) + 0.5
        path = [(10, c) for c in range(20)]
        _, road_mask, road_sdf_dist = _apply_road_profile_to_heightmap(hmap, path, road_width=2.0)
        # Cells inside road_mask should have sdf=0
        mask_cells = list(zip(*np.where(road_mask == 1)))
        for r, c in mask_cells[:5]:  # check a few
            assert road_sdf_dist[r, c] == 0.0, f"SDF at ({r},{c}) should be 0, got {road_sdf_dist[r,c]}"

    def test_road_sdf_dist_nonnegative(self):
        from veilbreakers_terrain.handlers.terrain_twelve_step import _apply_road_profile_to_heightmap
        hmap = np.zeros((20, 20), dtype=np.float64) + 0.5
        path = [(10, c) for c in range(20)]
        _, _, road_sdf_dist = _apply_road_profile_to_heightmap(hmap, path)
        assert road_sdf_dist.min() >= 0.0

    def test_road_sdf_dist_increases_with_distance(self):
        """SDF value at row 0 > SDF value at row 9 (closer to road at row 10)."""
        from veilbreakers_terrain.handlers.terrain_twelve_step import _apply_road_profile_to_heightmap
        hmap = np.zeros((20, 20), dtype=np.float64) + 0.5
        path = [(10, c) for c in range(20)]
        _, road_mask, road_sdf_dist = _apply_road_profile_to_heightmap(hmap, path, road_width=1.0)
        sdf_close = float(road_sdf_dist[9, 10])
        sdf_far = float(road_sdf_dist[0, 10])
        assert sdf_far > sdf_close, f"SDF should increase with distance: far={sdf_far}, close={sdf_close}"


# ---------------------------------------------------------------------------
# TestRoadSdfChannel
# ---------------------------------------------------------------------------


class TestRoadSdfChannel:
    def test_sdf_approx_3_cells_from_boundary(self):
        """SDF at a cell 3 cells from Zone 1 boundary is approximately 3."""
        from veilbreakers_terrain.handlers.terrain_twelve_step import _apply_road_profile_to_heightmap
        hmap = np.zeros((20, 20), dtype=np.float64) + 0.5
        # Road at column 10, road_width=0 (effectively 1-cell-wide mask)
        path = [(r, 10) for r in range(20)]
        _, road_mask, road_sdf_dist = _apply_road_profile_to_heightmap(
            hmap, path, road_width=0.5, shoulder_width=2.0, influence_width=3.0
        )
        # 3 cells to the right of column 10 should have sdf ~3
        sdf_val = float(road_sdf_dist[10, 13])
        assert abs(sdf_val - 3.0) < 1.5, f"Expected SDF ~3 at 3-cell offset, got {sdf_val:.2f}"
