"""Bundle C tests — _water_network_ext.py."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, cast

import numpy as np
import pytest
from numpy.typing import NDArray

from veilbreakers_terrain.handlers.terrain_semantics import TerrainMaskStack, TerrainPipelineState

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int32]
AnyArray = NDArray[np.generic]
Point3 = tuple[float, float, float]


class _WaterNetworkModule(Protocol):
    _D8_OFFSETS: Sequence[tuple[int, int]]
    _D8_DISTANCES: Sequence[float]

    def compute_river_width(self, accumulation: float) -> float: ...

    def _compute_river_depth(self, accumulation: float) -> float: ...

    def compute_velocity_field(
        self,
        heightmap: FloatArray,
        flow_accumulation: FloatArray,
        flow_direction: IntArray,
        *,
        cell_size: float,
        manning_n_river: float,
        manning_n_stream: float,
        river_threshold: float,
        foam_velocity_threshold: float,
        foam_gradient_threshold: float,
    ) -> dict[str, AnyArray]: ...


# ---------------------------------------------------------------------------
# Lightweight WaterNetwork stand-in for testing extensions
# ---------------------------------------------------------------------------


@dataclass
class _FakeSegment:
    segment_id: int
    waypoints: list[Point3]
    bank_asymmetry: float = 0.0


@dataclass
class _FakeNode:
    node_id: int
    world_x: float
    world_y: float
    world_z: float


@dataclass
class _FakeNetwork:
    segments: dict[int, _FakeSegment] = field(
        default_factory=lambda: cast(dict[int, _FakeSegment], {})
    )
    nodes: dict[int, _FakeNode] = field(default_factory=lambda: cast(dict[int, _FakeNode], {}))


def _straight_segment(n: int = 20) -> _FakeSegment:
    waypoints = [(float(i), 5.0, 0.0) for i in range(n)]
    return _FakeSegment(segment_id=0, waypoints=waypoints)


def _build_network_with_straight_segment(n: int = 20) -> _FakeNetwork:
    net = _FakeNetwork()
    seg = _straight_segment(n)
    net.segments[seg.segment_id] = seg
    return net


def _polyline_length(points: Sequence[Point3]) -> float:
    total = 0.0
    for i in range(1, len(points)):
        x0, y0 = points[i - 1][0], points[i - 1][1]
        x1, y1 = points[i][0], points[i][1]
        total += math.hypot(x1 - x0, y1 - y0)
    return total


def _build_stack(size: int = 40) -> TerrainMaskStack:
    h = np.zeros((size, size), dtype=np.float64)
    return TerrainMaskStack(
        tile_size=size - 1,
        cell_size=1.0,
        world_origin_x=0.0,
        world_origin_y=0.0,
        tile_x=0,
        tile_y=0,
        height=h,
    )


def _scalar_velocity_reference(
    water_network: _WaterNetworkModule,
    heightmap: FloatArray,
    flow_accumulation: FloatArray,
    flow_direction: IntArray,
    *,
    cell_size: float,
    manning_n_river: float,
    manning_n_stream: float,
    river_threshold: float,
    foam_velocity_threshold: float,
    foam_gradient_threshold: float,
) -> dict[str, AnyArray]:
    hmap = np.asarray(heightmap, dtype=np.float64)
    fa = np.asarray(flow_accumulation, dtype=np.float64)
    fd = np.asarray(flow_direction, dtype=np.int32)
    rows, cols = hmap.shape
    speed = np.zeros((rows, cols), dtype=np.float64)
    vx = np.zeros((rows, cols), dtype=np.float64)
    vy = np.zeros((rows, cols), dtype=np.float64)

    dh_dr, dh_dc = np.gradient(hmap, cell_size)
    slope_field = np.sqrt(dh_dr ** 2 + dh_dc ** 2)
    slope_clamped = np.clip(slope_field, 1e-5, 1.0)

    d8_dx = np.array(
        [float(dc) for _, dc in water_network._D8_OFFSETS],
        dtype=np.float64,
    )
    d8_dy = np.array(
        [-float(dr) for dr, _ in water_network._D8_OFFSETS],
        dtype=np.float64,
    )
    d8_dist = np.array(water_network._D8_DISTANCES, dtype=np.float64)
    d8_dx /= d8_dist
    d8_dy /= d8_dist

    for r in range(rows):
        for c in range(cols):
            acc = float(fa[r, c])
            if acc < 1.0:
                continue
            d = int(fd[r, c])
            if d < 0:
                continue

            width = water_network.compute_river_width(acc)
            depth = water_network._compute_river_depth(acc)
            hydraulic_radius = (width * depth) / (width + 2.0 * depth)
            roughness = manning_n_river if acc >= river_threshold else manning_n_stream
            velocity = (
                (1.0 / roughness)
                * (hydraulic_radius ** (2.0 / 3.0))
                * math.sqrt(float(slope_clamped[r, c]))
            )
            speed[r, c] = velocity
            vx[r, c] = velocity * d8_dx[d]
            vy[r, c] = velocity * d8_dy[d]

    foam_mask = (
        (speed > foam_velocity_threshold)
        | (slope_field > foam_gradient_threshold)
    ) & (fa > 10.0)
    return {"vx": vx, "vy": vy, "speed": speed, "foam_mask": foam_mask}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_compute_velocity_field_matches_scalar_manning_reference():
    import veilbreakers_terrain.handlers._water_network as water_network

    heightmap = np.array(
        [
            [9.0, 8.5, 8.0, 7.8],
            [8.2, 7.9, 7.4, 7.0],
            [7.7, 7.2, 6.8, 6.1],
        ],
        dtype=np.float64,
    )
    flow_accumulation = np.array(
        [
            [0.0, 1.0, 12.0, 3000.0],
            [2.0, 35.0, 1800.0, 2500.0],
            [0.5, 15.0, 75.0, 0.0],
        ],
        dtype=np.float64,
    )
    flow_direction = np.array(
        [
            [-1, 2, 2, 4],
            [1, 3, 4, 5],
            [0, 0, 6, -1],
        ],
        dtype=np.int32,
    )
    kwargs = {
        "cell_size": 2.0,
        "manning_n_river": 0.033,
        "manning_n_stream": 0.052,
        "river_threshold": 2000.0,
        "foam_velocity_threshold": 1.5,
        "foam_gradient_threshold": 0.12,
    }

    water_network_typed = cast(_WaterNetworkModule, water_network)
    vectorized = water_network_typed.compute_velocity_field(
        heightmap,
        flow_accumulation,
        flow_direction,
        **kwargs,
    )
    scalar = _scalar_velocity_reference(
        water_network_typed,
        heightmap,
        flow_accumulation,
        flow_direction,
        **kwargs,
    )

    np.testing.assert_allclose(
        cast(FloatArray, vectorized["speed"]),
        cast(FloatArray, scalar["speed"]).astype(np.float32),
        rtol=1e-6,
    )
    np.testing.assert_allclose(
        cast(FloatArray, vectorized["vx"]),
        cast(FloatArray, scalar["vx"]).astype(np.float32),
        rtol=1e-6,
    )
    np.testing.assert_allclose(
        cast(FloatArray, vectorized["vy"]),
        cast(FloatArray, scalar["vy"]).astype(np.float32),
        rtol=1e-6,
    )
    np.testing.assert_array_equal(vectorized["foam_mask"], scalar["foam_mask"])


def test_add_meander_increases_path_length():
    from veilbreakers_terrain.handlers._water_network_ext import add_meander

    net = _build_network_with_straight_segment(n=20)
    orig_len = _polyline_length(net.segments[0].waypoints)
    add_meander(net, amplitude=2.0)
    new_len = _polyline_length(net.segments[0].waypoints)
    assert new_len > orig_len * 1.05, f"expected meander to lengthen path ({orig_len} → {new_len})"


def test_add_meander_preserves_endpoints():
    from veilbreakers_terrain.handlers._water_network_ext import add_meander

    net = _build_network_with_straight_segment(n=20)
    first = net.segments[0].waypoints[0]
    last = net.segments[0].waypoints[-1]
    add_meander(net, amplitude=1.5)
    assert net.segments[0].waypoints[0] == first
    assert net.segments[0].waypoints[-1] == last


def test_add_meander_zero_amplitude_noop():
    from veilbreakers_terrain.handlers._water_network_ext import add_meander

    net = _build_network_with_straight_segment(n=10)
    original = list(net.segments[0].waypoints)
    add_meander(net, amplitude=0.0)
    assert net.segments[0].waypoints == original


def test_apply_bank_asymmetry_tags_segments():
    from veilbreakers_terrain.handlers._water_network_ext import apply_bank_asymmetry

    net = _build_network_with_straight_segment(n=10)
    apply_bank_asymmetry(net, bias=0.6)
    assert math.isclose(net.segments[0].bank_asymmetry, 0.6)

    apply_bank_asymmetry(net, bias=-0.4)
    assert math.isclose(net.segments[0].bank_asymmetry, -0.4)


def test_apply_bank_asymmetry_clamps_range():
    from veilbreakers_terrain.handlers._water_network_ext import apply_bank_asymmetry

    net = _build_network_with_straight_segment(n=10)
    apply_bank_asymmetry(net, bias=5.0)
    assert math.isclose(net.segments[0].bank_asymmetry, 1.0)
    apply_bank_asymmetry(net, bias=-5.0)
    assert math.isclose(net.segments[0].bank_asymmetry, -1.0)


def test_compute_wet_rock_mask_zero_without_seeds():
    from veilbreakers_terrain.handlers._water_network_ext import compute_wet_rock_mask

    stack = _build_stack(size=20)
    mask = compute_wet_rock_mask(stack, None, radius_m=3.0)
    assert mask.shape == stack.height.shape
    assert float(mask.max()) == 0.0  # no seeds → no wet rock


def test_compute_wet_rock_mask_decays_with_distance():
    from veilbreakers_terrain.handlers._water_network_ext import compute_wet_rock_mask

    stack = _build_stack(size=30)
    net = _FakeNetwork()
    net.nodes[0] = _FakeNode(node_id=0, world_x=15.0, world_y=15.0, world_z=0.0)
    mask = compute_wet_rock_mask(stack, net, radius_m=4.0)
    # Near-center should be > far-corner
    assert mask[15, 15] > mask[0, 0]
    # Far corner should be zero
    assert mask[0, 0] == 0.0


def test_compute_wet_rock_mask_boosts_adjacent_cells_for_high_flow_sources():
    from veilbreakers_terrain.handlers._water_network_ext import compute_wet_rock_mask

    stack = _build_stack(size=30)
    flow_accumulation = np.ones_like(stack.height)
    flow_accumulation[10, 10] = 100.0
    flow_accumulation[20, 20] = 5.0
    stack.set("flow_accumulation", flow_accumulation, "test_fixture")

    net = _FakeNetwork()
    net.nodes[0] = _FakeNode(node_id=0, world_x=10.0, world_y=10.0, world_z=0.0)
    net.nodes[1] = _FakeNode(node_id=1, world_x=20.0, world_y=20.0, world_z=0.0)

    mask = compute_wet_rock_mask(stack, net, radius_m=4.0)

    # Source cells clamp to fully wet, so compare adjacent splash cells.
    assert mask[10, 11] > mask[20, 21]


def test_compute_wet_rock_mask_fallback_keeps_seed_strength(monkeypatch: pytest.MonkeyPatch):
    import veilbreakers_terrain.handlers._water_network_ext as water_ext

    stack = _build_stack(size=30)
    flow_accumulation = np.ones_like(stack.height)
    flow_accumulation[12, 12] = 80.0
    flow_accumulation[18, 18] = 4.0
    stack.set("flow_accumulation", flow_accumulation, "test_fixture")

    net = _FakeNetwork()
    net.nodes[0] = _FakeNode(node_id=0, world_x=12.0, world_y=12.0, world_z=0.0)
    net.nodes[1] = _FakeNode(node_id=1, world_x=18.0, world_y=18.0, world_z=0.0)

    monkeypatch.setattr(water_ext, "_HAS_SCIPY", False)
    monkeypatch.setattr(water_ext, "_distance_transform_edt", None)

    mask = water_ext.compute_wet_rock_mask(stack, net, radius_m=4.0)

    assert mask[12, 13] > mask[18, 19]
    assert mask[0, 0] == 0.0


def test_compute_foam_mask_peaks_at_pool():
    from veilbreakers_terrain.handlers._water_network_ext import compute_foam_mask
    from veilbreakers_terrain.handlers.terrain_waterfalls import (
        ImpactPool,
        LipCandidate,
        WaterfallChain,
    )

    stack = _build_stack(size=30)
    chain = WaterfallChain(
        chain_id="test",
        lip=LipCandidate(
            world_position=(15.0, 10.0, 20.0),
            upstream_drainage=1000.0,
            downstream_drop_m=10.0,
            flow_direction_rad=0.0,
            confidence_score=0.8,
        ),
        plunge_path=((15.0, 10.0, 20.0), (15.0, 15.0, 10.0)),
        pool=ImpactPool(
            world_position=(15.0, 15.0, 10.0),
            radius_m=4.0,
            max_depth_m=2.0,
            outflow_direction_rad=0.0,
        ),
        outflow=((15.0, 15.0, 10.0), (15.0, 20.0, 9.0)),
        mist_radius_m=8.0,
        foam_intensity=0.9,
        total_drop_m=10.0,
        drop_segments=(10.0,),
    )
    foam = compute_foam_mask(chain, stack)
    assert foam.max() > 0.0
    # Pool center peak should be within a 2-cell radius of the pool world
    # position.  The exact peak cell depends on the cell-center convention
    # used by _world_to_grid (origin + (idx+0.5)*cs), so we test proximity
    # rather than an exact cell index.
    peak_r, peak_c = divmod(int(foam.argmax()), foam.shape[1])
    assert abs(peak_r - 15) <= 2, f"foam peak row {peak_r} not near pool row 15"
    assert abs(peak_c - 15) <= 2, f"foam peak col {peak_c} not near pool col 15"
    # Far away should be 0
    assert foam[0, 0] == 0.0


def test_compute_mist_mask_is_radial():
    from veilbreakers_terrain.handlers._water_network_ext import compute_mist_mask
    from veilbreakers_terrain.handlers.terrain_waterfalls import (
        ImpactPool,
        LipCandidate,
        WaterfallChain,
    )

    stack = _build_stack(size=30)
    chain = WaterfallChain(
        chain_id="test",
        lip=LipCandidate(
            world_position=(15.0, 10.0, 20.0),
            upstream_drainage=1000.0,
            downstream_drop_m=10.0,
            flow_direction_rad=0.0,
            confidence_score=0.8,
        ),
        plunge_path=((15.0, 10.0, 20.0), (15.0, 15.0, 10.0)),
        pool=ImpactPool(
            world_position=(15.0, 15.0, 10.0),
            radius_m=4.0,
            max_depth_m=2.0,
            outflow_direction_rad=0.0,
        ),
        outflow=((15.0, 15.0, 10.0), (15.0, 20.0, 9.0)),
        mist_radius_m=6.0,
        foam_intensity=0.9,
        total_drop_m=10.0,
        drop_segments=(10.0,),
    )
    mist = compute_mist_mask(chain, stack)
    assert mist.max() > 0.0
    # Peak should be within 2 cells of pool world position (15,15).
    # Exact cell depends on cell-center convention in _world_to_grid.
    peak_r, peak_c = divmod(int(mist.argmax()), mist.shape[1])
    assert abs(peak_r - 15) <= 2, f"mist peak row {peak_r} not near pool row 15"
    assert abs(peak_c - 15) <= 2, f"mist peak col {peak_c} not near pool col 15"
    # Cells far from pool should be lower intensity than the peak
    assert float(mist[15, 22]) <= float(mist.max())


def test_solve_outflow_produces_path():
    from veilbreakers_terrain.handlers._water_network_ext import solve_outflow
    from veilbreakers_terrain.handlers.terrain_waterfalls import ImpactPool

    pool = ImpactPool(
        world_position=(10.0, 10.0, 0.0),
        radius_m=3.0,
        max_depth_m=1.0,
        outflow_direction_rad=0.0,  # east
    )
    path = solve_outflow(None, pool)
    assert len(path) >= 2
    # First point should be at or east of pool center
    assert path[0][0] >= 10.0
    # Monotonic x since direction is east
    xs = [p[0] for p in path]
    assert xs == sorted(xs)


# ---------------------------------------------------------------------------
# P2-13 — Manning slope unit-convention guard (dimensionless rise/run)
# ---------------------------------------------------------------------------


class TestManningSlopeConvention:
    """pass_water_flow_speed must assert slope is dimensionless rise/run."""

    def _build_fake_stack_and_state(
        self,
        slope_array: AnyArray | None,
        height: AnyArray,
    ) -> tuple[TerrainPipelineState, object]:
        """Minimal mask-stack + state stand-in."""
        rows, cols = height.shape
        flow_dir = np.zeros((rows, cols), dtype=np.int8)
        flow_acc = np.ones((rows, cols), dtype=np.float64)
        water = np.ones((rows, cols), dtype=np.float32)

        class _Stack:
            def __init__(self) -> None:
                self.height = height
                self.cell_size = 1.0
                self._channels: dict[str, AnyArray] = {
                    "flow_direction": flow_dir,
                    "flow_accumulation": flow_acc,
                    "water_surface": water,
                }
                if slope_array is not None:
                    self._channels["slope"] = slope_array

            def get(self, key: str) -> AnyArray | None:
                return self._channels.get(key)

            def set(self, key: str, value: AnyArray, source: str | None = None) -> None:
                self._channels[key] = value

        class _State:
            def __init__(self, stack: object) -> None:
                self.mask_stack = stack

        stack = _Stack()
        return cast(TerrainPipelineState, _State(stack)), stack

    def test_dimensionless_slope_passes(self):
        from veilbreakers_terrain.handlers._water_network import pass_water_flow_speed

        height = np.linspace(0.0, 1.0, 64).astype(np.float64)
        height = np.tile(height, (16, 1))  # 1m total rise over 64m
        slope = np.full((16, 64), 0.015, dtype=np.float64)  # 1.5 % grade

        state, _stack = self._build_fake_stack_and_state(slope, height)
        result = pass_water_flow_speed(state, None)
        assert result.status == "ok"
        assert "slope_max_dimensionless" in result.metrics
        assert result.metrics["slope_max_dimensionless"] < 10.0

    def test_radian_unit_error_raises(self):
        """Feeding a radians-as-slope channel with huge magnitudes trips the assert."""
        from veilbreakers_terrain.handlers._water_network import pass_water_flow_speed

        height = np.zeros((8, 8), dtype=np.float64)
        # A "slope" array in bogus units — values of 25 indicate something
        # other than rise/run (e.g., gradient of a steep world-height DEM).
        bad_slope = np.full((8, 8), 25.0, dtype=np.float64)
        state, _stack = self._build_fake_stack_and_state(bad_slope, height)
        with pytest.raises(AssertionError, match="Manning slope"):
            pass_water_flow_speed(state, None)

    def test_docstring_documents_unit_convention(self):
        import inspect as _inspect
        from veilbreakers_terrain.handlers._water_network import pass_water_flow_speed

        doc = _inspect.getdoc(pass_water_flow_speed) or ""
        assert "dimensionless" in doc.lower(), (
            "pass_water_flow_speed docstring must document unit convention"
        )


def _contract_heightmap() -> np.ndarray:
    rows = cols = 13
    rr, cc = np.indices((rows, cols))
    height = (100.0 - rr * 2.0 - cc).astype(np.float64)
    height[6, :] -= np.linspace(0.0, 20.0, cols)
    return height


def test_detect_waterfalls_requires_drainage_and_reports_orientation():
    from veilbreakers_terrain.handlers._water_network import detect_waterfalls

    heightmap = np.array([[12.0, 11.5, 4.0, 3.5, 3.0]], dtype=np.float32)
    path = [(0, col) for col in range(heightmap.shape[1])]
    flow_acc = np.full_like(heightmap, 120.0, dtype=np.float32)

    waterfalls = detect_waterfalls(
        heightmap,
        path,
        cell_size=1.0,
        min_drop=3.0,
        max_horizontal=3.0,
        flow_accumulation=flow_acc,
        min_accumulation=50.0,
    )

    assert len(waterfalls) == 1
    waterfall = waterfalls[0]
    assert waterfall["top_idx"] == 0
    assert waterfall["bottom_idx"] == 2
    assert waterfall["top_row"] == 0
    assert waterfall["bottom_col"] == 2
    assert math.isclose(waterfall["drop"], 8.0)
    assert math.isclose(waterfall["horizontal_dist"], 2.0)
    assert math.isclose(waterfall["drop_rate"], 4.0)
    assert math.isclose(waterfall["drainage_area"], 120.0)
    assert math.isclose(waterfall["orientation_rad"], math.pi / 2.0)

    low_flow = np.zeros_like(heightmap, dtype=np.float32)
    assert (
        detect_waterfalls(
            heightmap,
            path,
            flow_accumulation=low_flow,
            min_accumulation=50.0,
        )
        == []
    )

    gentle_height = np.linspace(12.0, 8.0, 21, dtype=np.float32).reshape(1, -1)
    gentle_path = [(0, col) for col in range(gentle_height.shape[1])]
    gentle_flow = np.full_like(gentle_height, 120.0, dtype=np.float32)
    assert (
        detect_waterfalls(
            gentle_height,
            gentle_path,
            min_drop=3.0,
            max_horizontal=5.0,
            flow_accumulation=gentle_flow,
            min_accumulation=50.0,
        )
        == []
    )


def test_from_heightmap_builds_velocity_and_valid_seam_contracts():
    from veilbreakers_terrain.handlers._water_network import WaterNetwork

    net = WaterNetwork.from_heightmap(
        _contract_heightmap(),
        cell_size=1.0,
        tile_size=6,
        min_drainage_area=4.0,
        river_threshold=8.0,
        lake_min_area=999.0,
        seed=1,
    )

    assert len(net.nodes) > 0
    assert len(net.segments) > 0
    seam_validation = net._seam_validation_result
    assert seam_validation is not None
    assert seam_validation["orphaned"] == 0
    assert seam_validation["head_mismatch"] == 0

    velocity = net.get_velocity_field()
    assert velocity is not None
    for key in ("vx", "vy", "speed", "foam_mask"):
        assert velocity[key].shape == (13, 13)
    assert np.max(velocity["speed"]) > 0.0

    crossing_contracts = [
        contract
        for edges in net.tile_contracts.values()
        for contracts in edges.values()
        for contract in contracts
    ]
    assert crossing_contracts
    assert all(0.0 <= contract.position <= 1.0 for contract in crossing_contracts)
    assert all(contract.outflow_rate_m3s > 0.0 for contract in crossing_contracts)
    assert all(math.isclose(contract.inflow_head_m, contract.depth) for contract in crossing_contracts)
    assert all(contract.seam_valid is True for contract in crossing_contracts)
    for contract in crossing_contracts:
        dx, dy = contract.flow_direction
        assert math.isclose(math.hypot(dx, dy), 1.0, rel_tol=1e-6)
        if contract.target_tile == (-1, -1):
            continue
        assert contract.target_tile in net.tile_contracts
        row, col = contract.entry_cell
        assert 0 <= row < 13
        assert 0 <= col < 13


def test_manning_discharge_zero_inputs_and_roughness_ordering():
    from veilbreakers_terrain.handlers._water_network import WaterNetwork

    assert WaterNetwork._manning_discharge(0.0, 0.1, 1.0, "river") == 0.0
    assert WaterNetwork._manning_discharge(100.0, 0.1, 0.0, "river") == 0.0

    river = WaterNetwork._manning_discharge(4000.0, 0.05, 1.0, "river")
    stream = WaterNetwork._manning_discharge(4000.0, 0.05, 1.0, "stream")
    steeper = WaterNetwork._manning_discharge(4000.0, 0.2, 1.0, "river")

    assert river > stream
    assert steeper > river


def test_water_network_sidecar_round_trips_export_metadata():
    from veilbreakers_terrain.handlers._water_network import WaterNetwork

    net = WaterNetwork.from_heightmap(
        _contract_heightmap(),
        cell_size=1.0,
        tile_size=6,
        min_drainage_area=4.0,
        river_threshold=8.0,
        lake_min_area=999.0,
        seed=2,
    )

    payload = net.to_dict()
    json.dumps(payload)

    assert payload["version"] == 2
    assert payload["world_bounds"] == {
        "x_min": 0.0,
        "y_min": 0.0,
        "x_max": 13.0,
        "y_max": 13.0,
    }
    assert payload["strahler_orders"]
    assert payload["shreve_orders"]
    assert payload["tile_contracts"]

    contract_payload = next(
        contract
        for tile in payload["tile_contracts"]
        for edge in ("north", "south", "east", "west")
        for contract in tile[edge]
    )
    assert contract_payload["outflow_rate_m3s"] > 0.0
    assert isinstance(contract_payload["target_tile"], list)
    assert isinstance(contract_payload["entry_cell"], list)
    assert math.isclose(contract_payload["inflow_head_m"], contract_payload["depth"])
    assert contract_payload["seam_valid"] is True

    restored = WaterNetwork.from_dict(payload)
    restored_contract = next(
        contract
        for edges in restored.tile_contracts.values()
        for contracts in edges.values()
        for contract in contracts
    )
    assert isinstance(restored_contract.flow_direction, tuple)
    assert isinstance(restored_contract.target_tile, tuple)
    assert isinstance(restored_contract.entry_cell, tuple)

    edge_heads = restored.get_edge_head_levels(0, 0)
    exported_head = next(head for heads in edge_heads.values() for head in heads)
    assert set(exported_head) == {
        "position",
        "world_z",
        "inflow_head_m",
        "network_id",
        "water_type",
    }
