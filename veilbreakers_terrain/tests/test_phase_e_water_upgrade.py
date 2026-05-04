"""Phase E — AAA water system upgrade tests.

Covers:
    - bake_flow_direction_vertex_color round-trip (R,G pack/unpack)
    - compute_riverbed_caustics: depth attenuation + tileable seams
    - water_shader_manifest shape (HDRP / Unreal fields)
    - validate_flow_direction_continuity: catches induced reversals
    - build_braided_polylines: wide channel splits into 2+ polylines
"""

from __future__ import annotations


import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _DictStack:
    """Lightweight stand-in for TerrainMaskStack (test-only)."""

    def __init__(self, height: np.ndarray, *, cell_size: float = 1.0):
        self.height = height
        self.cell_size = cell_size
        self.world_origin_x = 0.0
        self.world_origin_y = 0.0
        self._channels: dict[str, object] = {}
        self.particle_emitter_specs = None

    def get(self, key: str):
        return self._channels.get(key)

    def set(self, key: str, value, _pass_name=None):
        self._channels[key] = value


def _simple_flow_direction(h: int = 6, w: int = 6) -> np.ndarray:
    """Return a flow_direction grid that flows uniformly east (d=2)."""
    return np.full((h, w), 2, dtype=np.int32)


# ---------------------------------------------------------------------------
# test_flow_direction_vertex_color_round_trip
# ---------------------------------------------------------------------------


class TestFlowDirectionVertexColorRoundTrip:
    def test_round_trip_east_flow(self):
        from veilbreakers_terrain.handlers._water_network import (
            bake_flow_direction_vertex_color,
        )

        fd = _simple_flow_direction(4, 4)
        fs = np.full((4, 4), 0.7, dtype=np.float32)
        foam = np.zeros((4, 4), dtype=np.float32)
        foam[2, 2] = 0.9

        stack = _DictStack(np.zeros((4, 4), dtype=np.float32))
        stack.set("flow_direction", fd)
        stack.set("flow_speed", fs)
        stack.set("foam", foam)

        # Bake whole grid
        rgba = bake_flow_direction_vertex_color(np.zeros((0, 0), dtype=np.int32), stack)
        assert rgba.shape == (16, 4)
        # Unpack R back into fx — should be ~+1.0 (east) => R = 1.0
        fx = rgba[:, 0] * 2.0 - 1.0
        fy = rgba[:, 1] * 2.0 - 1.0
        np.testing.assert_allclose(fx, 1.0, atol=1e-5)
        np.testing.assert_allclose(fy, 0.0, atol=1e-5)
        # B channel carries the speed
        np.testing.assert_allclose(rgba[:, 2], 0.7, atol=1e-5)
        # A channel carries foam
        assert rgba.reshape(4, 4, 4)[2, 2, 3] == pytest.approx(0.9, abs=1e-5)

    def test_per_vertex_sampling(self):
        from veilbreakers_terrain.handlers._water_network import (
            bake_flow_direction_vertex_color,
        )

        stack = _DictStack(np.zeros((4, 4), dtype=np.float32))
        # 4 = south (dr=+1), D8 index 4
        fd = np.full((4, 4), 4, dtype=np.int32)
        stack.set("flow_direction", fd)

        vertices_rc = np.array([[0, 0], [1, 1], [3, 3]], dtype=np.int32)
        rgba = bake_flow_direction_vertex_color(vertices_rc, stack)
        assert rgba.shape == (3, 4)
        # South flow → fy = -1 (our convention: north positive), so G = 0.0
        np.testing.assert_allclose(rgba[:, 1], 0.0, atol=1e-5)

    def test_missing_flow_direction_yields_neutral_packing(self):
        from veilbreakers_terrain.handlers._water_network import (
            bake_flow_direction_vertex_color,
        )

        stack = _DictStack(np.zeros((4, 4), dtype=np.float32))
        vertices_rc = np.array([[0, 0], [1, 1]], dtype=np.int32)
        rgba = bake_flow_direction_vertex_color(vertices_rc, stack)
        assert rgba.shape == (2, 4)
        np.testing.assert_allclose(rgba[:, 0], 0.5, atol=1e-6)
        np.testing.assert_allclose(rgba[:, 1], 0.5, atol=1e-6)
        np.testing.assert_allclose(rgba[:, 2], 0.0, atol=1e-6)

    def test_compute_flow_direction_field_shape(self):
        from veilbreakers_terrain.handlers._water_network import (
            compute_flow_direction_field,
        )

        fd = _simple_flow_direction(5, 7)
        field = compute_flow_direction_field(fd)
        assert field.shape == (5, 7, 4)
        assert field.dtype == np.float32
        # Pits (-1) should zero out
        fd_pit = fd.copy()
        fd_pit[2, 2] = -1
        field_pit = compute_flow_direction_field(fd_pit)
        assert field_pit[2, 2, 0] == 0.0
        assert field_pit[2, 2, 1] == 0.0


# ---------------------------------------------------------------------------
# test_caustics_depth_attenuation
# ---------------------------------------------------------------------------


class TestRiverbedCausticsDepthAttenuation:
    def test_shallow_brighter_than_deep(self):
        from veilbreakers_terrain.handlers._water_network_ext import (
            compute_riverbed_caustics,
        )

        h = np.zeros((32, 32), dtype=np.float32)
        ws = np.full((32, 32), 2.0, dtype=np.float32)
        # Left half shallow (depth=0.5), right half deep (depth=3.5)
        h[:, 16:] = -1.5
        # ws - h = depth. Left: 2.0; right: 3.5
        h[:, :16] = 1.5  # depth 0.5 left

        stack = _DictStack(h)
        stack.set("water_surface_elevation_m", ws)

        caustics = compute_riverbed_caustics(stack, seed=7)
        assert caustics.shape == (32, 32)
        shallow_mean = float(caustics[:, :16].mean())
        deep_mean = float(caustics[:, 16:].mean())
        assert shallow_mean > deep_mean, f"shallow={shallow_mean}, deep={deep_mean}"

    def test_dry_cells_zero(self):
        from veilbreakers_terrain.handlers._water_network_ext import (
            compute_riverbed_caustics,
        )

        h = np.zeros((16, 16), dtype=np.float32)
        ws = np.zeros((16, 16), dtype=np.float32)  # no water anywhere
        stack = _DictStack(h)
        stack.set("water_surface_elevation_m", ws)

        caustics = compute_riverbed_caustics(stack, seed=0)
        assert float(caustics.max()) == 0.0

    def test_range_in_unit_interval(self):
        from veilbreakers_terrain.handlers._water_network_ext import (
            compute_riverbed_caustics,
        )

        h = np.zeros((24, 24), dtype=np.float32)
        ws = np.full((24, 24), 1.0, dtype=np.float32)
        stack = _DictStack(h)
        stack.set("water_surface_elevation_m", ws)

        caustics = compute_riverbed_caustics(stack, seed=42)
        assert float(caustics.min()) >= 0.0
        assert float(caustics.max()) <= 1.0

    def test_deterministic_given_seed(self):
        from veilbreakers_terrain.handlers._water_network_ext import (
            compute_riverbed_caustics,
        )

        h = np.zeros((16, 16), dtype=np.float32)
        ws = np.full((16, 16), 1.0, dtype=np.float32)
        stack = _DictStack(h)
        stack.set("water_surface_elevation_m", ws)

        a = compute_riverbed_caustics(stack, seed=5)
        b = compute_riverbed_caustics(stack, seed=5)
        np.testing.assert_allclose(a, b)


# ---------------------------------------------------------------------------
# test_water_shader_manifest_shape
# ---------------------------------------------------------------------------


class TestWaterShaderManifestShape:
    def _stack(self) -> _DictStack:
        h = np.zeros((8, 8), dtype=np.float32)
        stack = _DictStack(h)
        stack.set("foam", np.full((8, 8), 0.3, dtype=np.float32))
        stack.set("flow_direction", np.full((8, 8), 2, dtype=np.int32))
        return stack

    def test_has_expected_materials(self):
        from veilbreakers_terrain.handlers.terrain_unity_export import (
            _water_shader_manifest_json,
        )

        payload = _water_shader_manifest_json(self._stack(), profile="hero_shot")
        assert payload["schema_version"] == "1.0"
        ids = {m["material_id"] for m in payload["materials"]}
        assert {"lake", "river", "waterfall"}.issubset(ids)
        assert payload["hero_profile"] is True

    def test_material_required_fields(self):
        from veilbreakers_terrain.handlers.terrain_unity_export import (
            _water_shader_manifest_json,
        )

        payload = _water_shader_manifest_json(self._stack())
        required = {
            "base_color", "deep_color", "caustic_texture", "normal_map",
            "flow_map_channel", "foam_channel", "transparency_curve",
            "fresnel_params", "shader_target",
        }
        for m in payload["materials"]:
            missing = required - set(m.keys())
            assert not missing, f"material {m['material_id']} missing {missing}"

    def test_transparency_curve_monotonic_depth(self):
        from veilbreakers_terrain.handlers.terrain_unity_export import (
            _water_shader_manifest_json,
        )

        payload = _water_shader_manifest_json(self._stack())
        for m in payload["materials"]:
            depths = [p["depth_m"] for p in m["transparency_curve"]]
            assert depths == sorted(depths), f"{m['material_id']}: not monotonic"

    def test_fresnel_params_physical(self):
        from veilbreakers_terrain.handlers.terrain_unity_export import (
            _water_shader_manifest_json,
        )

        payload = _water_shader_manifest_json(self._stack())
        for m in payload["materials"]:
            f0 = m["fresnel_params"]["f0"]
            assert 0.01 <= f0 <= 0.1, (
                f"{m['material_id']}: fresnel f0={f0} outside water IOR range"
            )

    def test_flow_channel_present_when_flow_direction_exists(self):
        from veilbreakers_terrain.handlers.terrain_unity_export import (
            _water_shader_manifest_json,
        )

        payload = _water_shader_manifest_json(self._stack())
        for m in payload["materials"]:
            assert m["flow_map_channel"] == "Color2"


# ---------------------------------------------------------------------------
# test_flow_continuity_validator_catches_reversals
# ---------------------------------------------------------------------------


class TestFlowContinuityValidator:
    def test_uniform_east_flow_clean(self):
        from veilbreakers_terrain.handlers._water_network import (
            validate_flow_direction_continuity,
        )

        h = np.zeros((8, 8), dtype=np.float32)
        stack = _DictStack(h)
        stack.set("flow_direction", _simple_flow_direction(8, 8))
        issues = validate_flow_direction_continuity(stack)
        # fallback scan should find no reversals (uniform east)
        assert issues == []

    def test_reversal_detected_by_fallback(self):
        from veilbreakers_terrain.handlers._water_network import (
            validate_flow_direction_continuity,
        )

        fd = np.full((6, 6), 2, dtype=np.int32)  # east
        # Induce a receiver that flows west back at its source
        fd[3, 4] = 6  # west
        stack = _DictStack(np.zeros((6, 6), dtype=np.float32))
        stack.set("flow_direction", fd)
        issues = validate_flow_direction_continuity(stack)
        assert len(issues) > 0
        assert any("reversal" in s.lower() or "back" in s.lower() for s in issues)

    def test_missing_flow_direction_returns_issue(self):
        from veilbreakers_terrain.handlers._water_network import (
            validate_flow_direction_continuity,
        )

        stack = _DictStack(np.zeros((4, 4), dtype=np.float32))
        issues = validate_flow_direction_continuity(stack)
        assert len(issues) == 1
        assert "flow_direction" in issues[0]

    def test_polyline_reversal_detected(self):
        """Detect reversal along a fabricated WaterSegment polyline."""
        from veilbreakers_terrain.handlers._water_network import (
            validate_flow_direction_continuity,
        )

        # Build a fd field: left half east, right half west (strict reversal
        # at the seam).  Walk a polyline from left to right through the seam.
        fd = np.full((8, 10), 2, dtype=np.int32)  # east
        fd[:, 5:] = 6  # west
        stack = _DictStack(np.zeros((8, 10), dtype=np.float32), cell_size=1.0)
        stack.set("flow_direction", fd)

        class _Seg:
            segment_id = 0
            segment_type = "river"
            waypoints = [(float(c), 4.0, 0.0) for c in range(10)]
            braided_polylines: list = []

        class _Net:
            segments = {0: _Seg()}

        stack.water_network = _Net()
        issues = validate_flow_direction_continuity(stack, reversal_angle_deg=90.0)
        assert any("segment_0" in s for s in issues), issues


# ---------------------------------------------------------------------------
# Braided flow polylines
# ---------------------------------------------------------------------------


class TestBraidedPolylines:
    def test_narrow_channel_no_braiding(self):
        from veilbreakers_terrain.handlers._water_network import (
            build_braided_polylines,
        )

        waypoints = [(float(i), 0.0, 0.0) for i in range(20)]
        branches = build_braided_polylines(
            waypoints, channel_width=5.0, braiding_width_threshold=20.0
        )
        assert branches == []

    def test_wide_channel_yields_two_or_more_branches(self):
        from veilbreakers_terrain.handlers._water_network import (
            build_braided_polylines,
        )

        waypoints = [(float(i), 0.0, 0.0) for i in range(25)]
        branches = build_braided_polylines(
            waypoints, channel_width=30.0, braiding_width_threshold=20.0, seed=1
        )
        assert len(branches) >= 2
        # Endpoints pinned to primary
        for b in branches:
            assert b[0] == waypoints[0]
            assert b[-1] == waypoints[-1]

    def test_branches_differ_laterally(self):
        from veilbreakers_terrain.handlers._water_network import (
            build_braided_polylines,
        )

        waypoints = [(float(i), 0.0, 0.0) for i in range(30)]
        branches = build_braided_polylines(
            waypoints, channel_width=40.0, braiding_width_threshold=10.0, seed=3
        )
        assert len(branches) >= 2
        mid = len(waypoints) // 2
        # At least one branch should have non-zero lateral (y) offset at the midpoint
        offsets = [abs(b[mid][1]) for b in branches]
        assert max(offsets) > 0.5, f"branches did not diverge laterally: {offsets}"
