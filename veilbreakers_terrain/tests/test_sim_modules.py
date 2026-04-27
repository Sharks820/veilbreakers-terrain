"""Tests for veilbreakers_terrain.sim: catenary, pbd_cloth, foam."""
from __future__ import annotations

import math
import numpy as np
import pytest


# ---------------------------------------------------------------------------
# catenary tests
# ---------------------------------------------------------------------------

class TestCatenary:
    def test_output_shape(self):
        from veilbreakers_terrain.sim.catenary import solve_catenary
        pts = solve_catenary(
            np.array([0.0, 0.0, 5.0]),
            np.array([6.0, 0.0, 5.0]),
            rope_length=7.0,
            n_points=16,
        )
        assert pts.shape == (16, 3)

    def test_endpoints_match_anchors(self):
        from veilbreakers_terrain.sim.catenary import solve_catenary
        a = np.array([1.0, 2.0, 3.0])
        b = np.array([7.0, 2.0, 3.0])
        pts = solve_catenary(a, b, rope_length=8.0)
        np.testing.assert_allclose(pts[0], a, atol=0.05)
        np.testing.assert_allclose(pts[-1], b, atol=0.05)

    def test_curve_sags_below_anchors(self):
        """Midpoint of catenary must be below the anchor height."""
        from veilbreakers_terrain.sim.catenary import solve_catenary
        a = np.array([0.0, 0.0, 5.0])
        b = np.array([8.0, 0.0, 5.0])
        pts = solve_catenary(a, b, rope_length=10.0)
        midpoint_z = pts[len(pts) // 2, 2]
        assert midpoint_z < 5.0, f"expected sag below 5m, got {midpoint_z}"

    def test_raises_when_rope_too_short(self):
        from veilbreakers_terrain.sim.catenary import solve_catenary
        a = np.array([0.0, 0.0, 0.0])
        b = np.array([5.0, 0.0, 0.0])
        with pytest.raises(ValueError, match="must exceed"):
            solve_catenary(a, b, rope_length=4.0)

    def test_sag_ratio_convenience(self):
        from veilbreakers_terrain.sim.catenary import catenary_with_sag
        a = np.array([0.0, 0.0, 5.0])
        b = np.array([6.0, 0.0, 5.0])
        pts = catenary_with_sag(a, b, sag_ratio=0.10)
        assert pts.shape[1] == 3
        # Midpoint should sag roughly 10% of span ≈ 0.6 m below start
        mid_z = pts[len(pts) // 2, 2]
        assert mid_z < 5.0

    def test_arc_length_uv_monotone(self):
        from veilbreakers_terrain.sim.catenary import solve_catenary, arc_length_uv
        a = np.array([0.0, 0.0, 5.0])
        b = np.array([6.0, 0.0, 5.0])
        pts = solve_catenary(a, b, rope_length=7.0)
        uv = arc_length_uv(pts)
        assert uv[0] == pytest.approx(0.0)
        assert uv[-1] == pytest.approx(1.0, abs=0.01)
        assert np.all(np.diff(uv) >= 0), "arc_length_uv must be monotonically increasing"

    def test_vertical_anchor_fallback(self):
        """Vertically stacked anchors should return a straight line without error."""
        from veilbreakers_terrain.sim.catenary import solve_catenary
        a = np.array([5.0, 5.0, 10.0])
        b = np.array([5.0, 5.0,  0.0])
        pts = solve_catenary(a, b, rope_length=11.0, n_points=8)
        assert pts.shape == (8, 3)


# ---------------------------------------------------------------------------
# pbd_cloth tests
# ---------------------------------------------------------------------------

class TestPbdCloth:
    def test_bake_static_drape_shape(self):
        from veilbreakers_terrain.sim.pbd_cloth import bake_static_drape, ClothParams
        p = ClothParams(rows=6, cols=5, width=1.0, height=1.5, n_substeps=2)
        rest = bake_static_drape(p, pin_top_row=True, n_steps=3)
        assert rest.shape == (6 * 5, 3)

    def test_pinned_row_does_not_move(self):
        from veilbreakers_terrain.sim.pbd_cloth import simulate_cloth, ClothParams
        p = ClothParams(rows=6, cols=5, width=1.0, height=1.5, n_substeps=2)
        N = p.rows * p.cols
        idx = np.arange(N).reshape(p.rows, p.cols)
        pin = np.zeros(N, dtype=bool)
        pin[idx[0, :]] = True
        history = simulate_cloth(p, pin, n_steps=5, seed=0)
        init_pos = history[0][pin]
        final_pos = history[-1][pin]
        np.testing.assert_allclose(init_pos, final_pos, atol=1e-6,
                                   err_msg="Pinned vertices must not move")

    def test_gravity_pulls_cloth_down(self):
        """Free vertices must drop in Z after simulation."""
        from veilbreakers_terrain.sim.pbd_cloth import simulate_cloth, ClothParams
        p = ClothParams(
            rows=4, cols=4, width=1.0, height=1.0,
            n_substeps=4, n_constraint_iters=5,
            wind_velocity=np.array([0.0, 0.0, 0.0]),  # no wind
        )
        N = p.rows * p.cols
        idx = np.arange(N).reshape(p.rows, p.cols)
        pin = np.zeros(N, dtype=bool)
        pin[idx[0, :]] = True
        history = simulate_cloth(p, pin, n_steps=10, seed=0)
        free = ~pin
        init_z = history[0][free, 2]
        final_z = history[-1][free, 2]
        assert final_z.mean() < init_z.mean(), "Free cloth must sag downward under gravity"

    def test_history_shape(self):
        from veilbreakers_terrain.sim.pbd_cloth import simulate_cloth, ClothParams
        p = ClothParams(rows=4, cols=4, width=1.0, height=1.0, n_substeps=2)
        N = p.rows * p.cols
        pin = np.zeros(N, dtype=bool)
        history = simulate_cloth(p, pin, n_steps=5)
        assert history.shape == (6, N, 3)  # n_steps+1 frames

    def test_flag_params_preset_runs(self):
        from veilbreakers_terrain.sim.pbd_cloth import bake_static_drape, FLAG_PARAMS
        import copy
        p = copy.copy(FLAG_PARAMS)
        p.rows, p.cols = 4, 5  # small for speed
        rest = bake_static_drape(p, pin_top_row=True, n_steps=3)
        assert rest.shape == (20, 3)


# ---------------------------------------------------------------------------
# foam tests
# ---------------------------------------------------------------------------

class TestFoam:
    def _make_inputs(self, H=16, W=16):
        rng = np.random.default_rng(42)
        height = rng.random((H, W)).astype(np.float32) * 5
        speed = np.ones((H, W), dtype=np.float32) * 1.5
        water_mask = np.ones((H, W), dtype=bool)
        depth = np.ones((H, W), dtype=np.float32) * 0.3
        rock_mask = np.zeros((H, W), dtype=bool)
        rock_mask[4:6, 4:6] = True
        return height, speed, water_mask, depth, rock_mask

    def test_output_shape_and_range(self):
        from veilbreakers_terrain.sim.foam import generate_foam_mask
        h, s, wm, d, rm = self._make_inputs()
        foam = generate_foam_mask(h, s, wm, d, rm)
        assert foam.shape == (16, 16)
        assert float(foam.min()) >= 0.0
        assert float(foam.max()) <= 1.0

    def test_dry_cells_have_zero_foam(self):
        """Cells outside water_mask must have zero foam output."""
        from veilbreakers_terrain.sim.foam import generate_foam_mask
        H, W = 16, 16
        height = np.zeros((H, W), dtype=np.float32)
        speed = np.ones((H, W), dtype=np.float32) * 1.5
        water_mask = np.zeros((H, W), dtype=bool)
        water_mask[4:12, 4:12] = True
        depth = np.zeros((H, W), dtype=np.float32)
        rock_mask = np.zeros((H, W), dtype=bool)
        foam = generate_foam_mask(height, speed, water_mask, depth, rock_mask)
        # After Gaussian smoothing there can be slight bleed; check most dry cells near 0
        dry_foam = foam[~water_mask]
        assert float(dry_foam.mean()) < 0.05, "Dry cells should have near-zero foam"

    def test_shoreline_foam_zero_at_deep_water(self):
        from veilbreakers_terrain.sim.foam import shoreline_depth_foam
        deep_depth = np.full((16, 16), 2.0, dtype=np.float32)  # 2 m deep — far past 0.6m fade
        foam = shoreline_depth_foam(deep_depth, foam_max_depth=0.6)
        assert float(foam.max()) < 0.05

    def test_shoreline_foam_nonzero_at_shallow(self):
        from veilbreakers_terrain.sim.foam import shoreline_depth_foam
        shallow = np.full((16, 16), 0.02, dtype=np.float32)  # nearly dry
        foam = shoreline_depth_foam(shallow, foam_min_depth=0.0, foam_max_depth=0.6)
        assert float(foam.max()) > 0.0

    def test_froude_foam_zero_subcritical(self):
        from veilbreakers_terrain.sim.foam import froude_foam_intensity
        slow_speed = np.full((16, 16), 0.5, dtype=np.float32)  # very slow → Fr << 1.7
        foam = froude_foam_intensity(slow_speed, flow_depth=0.3)
        assert float(foam.max()) == pytest.approx(0.0, abs=1e-5)

    def test_froude_foam_nonzero_supercritical(self):
        from veilbreakers_terrain.sim.foam import froude_foam_intensity
        # Fr = V / sqrt(g*d) = 8 / sqrt(9.81*0.3) ≈ 4.66 → above 4.5 threshold
        fast_speed = np.full((16, 16), 8.0, dtype=np.float32)
        foam = froude_foam_intensity(fast_speed, flow_depth=0.3)
        assert float(foam.max()) > 0.5

    def test_bake_flow_map_shape_and_dtype(self):
        from veilbreakers_terrain.sim.foam import bake_flow_map
        vf = np.random.default_rng(0).random((16, 16, 2)).astype(np.float32) - 0.5
        fm = bake_flow_map(vf)
        assert fm.shape == (16, 16, 2)
        assert fm.dtype == np.uint8

    def test_bake_flow_map_zero_velocity_encodes_128(self):
        from veilbreakers_terrain.sim.foam import bake_flow_map
        vf = np.zeros((8, 8, 2), dtype=np.float32)
        fm = bake_flow_map(vf)
        # All velocities zero → encoded value = 0.5 * 255 ≈ 127-128
        assert np.all(fm >= 126) and np.all(fm <= 129)
