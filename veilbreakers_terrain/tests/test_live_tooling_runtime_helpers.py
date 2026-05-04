"""Direct runtime-helper coverage for live terrain tooling gaps.

These tests intentionally target small callables that feed MCP/editor tooling:
hot reload, addon health, vertex paint, feature-tier parsing, and world-map
geometry helpers. They avoid pytest tmp fixtures because local temp access can
be restricted in this workspace.
"""

from __future__ import annotations

import random
import math
from typing import Any, cast

import numpy as np
import pytest


def test_import_addon_package_returns_live_terrain_package():
    from veilbreakers_terrain.handlers.terrain_addon_health import (
        _import_addon_package,
    )

    pkg = _import_addon_package()

    assert getattr(pkg, "__name__") == "veilbreakers_terrain"
    bl_info = cast(dict[str, Any], getattr(pkg, "bl_info"))
    assert bl_info["version"] >= (1, 0, 0)


def test_feature_tier_from_str_normalizes_case_and_defaults_secondary():
    from veilbreakers_terrain.handlers.terrain_hierarchy import FeatureTier

    assert FeatureTier.from_str(" PRIMARY ") == FeatureTier.PRIMARY
    assert FeatureTier.from_str("ambient") == FeatureTier.AMBIENT
    assert FeatureTier.from_str("author_typo") == FeatureTier.SECONDARY


def test_reload_biome_rules_and_reload_material_rules_report_successes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from veilbreakers_terrain.handlers import terrain_hot_reload as hot_reload

    calls: list[str] = []

    def fake_safe_reload(name: str) -> tuple[bool, None]:
        calls.append(name)
        return (not name.endswith("terrain_banded"), None)

    monkeypatch.setattr(hot_reload, "_safe_reload", fake_safe_reload)

    biome = hot_reload.reload_biome_rules()
    material = hot_reload.reload_material_rules()

    assert "veilbreakers_terrain.handlers.terrain_ecotone_graph" in biome
    assert "veilbreakers_terrain.handlers.terrain_banded" not in biome
    assert material == list(hot_reload._MATERIAL_RULE_MODULES)
    assert calls == list(hot_reload._BIOME_RULE_MODULES + hot_reload._MATERIAL_RULE_MODULES)


def test_hot_reload_watcher_clear_errors_resets_error_state():
    from veilbreakers_terrain.handlers.terrain_hot_reload import HotReloadWatcher

    watcher = HotReloadWatcher()
    watcher.last_errors["broken.module"] = RuntimeError("bad reload")

    watcher.clear_errors()

    assert watcher.last_errors == {}


def test_vertex_paint_dist3d_dist2d_and_falloff_weight_boundaries():
    from veilbreakers_terrain.handlers.vertex_paint_live import (
        _dist2d,
        _dist3d,
        _falloff_weight,
    )

    assert math.isclose(_dist3d((0, 0, 0), (2, 3, 6)), 7.0)
    assert math.isclose(_dist2d((0, 0), (3, 4)), 5.0)
    assert math.isclose(cast(float, _falloff_weight(0.0, 10.0, "LINEAR")), 1.0)
    assert math.isclose(cast(float, _falloff_weight(10.0, 10.0, "CONSTANT")), 0.0)
    assert _falloff_weight(10.1, 10.0, "SMOOTH") is None
    assert _falloff_weight(0.0, 0.0, "SMOOTH") is None


def test_vertex_paint_empty_inputs_return_empty_and_invalid_shapes_fail():
    from veilbreakers_terrain.handlers.vertex_paint_live import (
        compute_paint_weights,
        compute_paint_weights_uv,
    )

    assert compute_paint_weights([], (0.0, 0.0, 0.0), 5.0, "SMOOTH") == []
    assert compute_paint_weights_uv([], (0.0, 0.0), 5.0, "SMOOTH") == []
    assert compute_paint_weights([(0.0, 0.0, 0.0)], (0.0, 0.0, 0.0), -1.0, "SMOOTH") == []
    assert compute_paint_weights_uv([(0.0, 0.0)], (0.0, 0.0), -1.0, "SMOOTH") == []

    with pytest.raises(ValueError, match="triples"):
        compute_paint_weights(cast(Any, [(0.0, 0.0)]), (0.0, 0.0, 0.0), 5.0, "SMOOTH")
    with pytest.raises(ValueError, match="pairs"):
        compute_paint_weights_uv(cast(Any, [(0.0, 0.0, 0.0)]), (0.0, 0.0), 5.0, "SMOOTH")


def test_blend_colors_array_clamps_weights_and_rejects_shape_mismatch():
    from veilbreakers_terrain.handlers.vertex_paint_live import blend_colors_array

    colors = np.array(
        [
            [0.2, 0.4, 0.6, 0.8],
            [0.8, 0.6, 0.4, 0.2],
        ],
        dtype=np.float32,
    )
    weights = np.array([-1.0, 2.0], dtype=np.float32)

    blended = blend_colors_array(colors, weights)

    assert blended.dtype == np.float32
    assert np.allclose(blended[0], [0.0, 0.0, 0.0, 0.0])
    assert np.allclose(blended[1], colors[1])
    with pytest.raises(ValueError, match="weights"):
        blend_colors_array(colors, np.array([0.5], dtype=np.float32))
    with pytest.raises(ValueError, match="colors"):
        blend_colors_array(np.array([1.0, 0.5]), np.array([0.5]))


def test_world_map_dist2d_and_nearest_region_contract():
    from veilbreakers_terrain.handlers.world_map import (
        Region,
        _dist2d,
        _nearest_region,
    )

    regions = [
        Region("a", "dark_forest", (0.0, 0.0), (0.0, 0.0, 1.0, 1.0), 1.0),
        Region("b", "frozen_tundra", (10.0, 0.0), (9.0, 0.0, 11.0, 1.0), 2.0),
    ]

    assert math.isclose(_dist2d((0.0, 0.0), (6.0, 8.0)), 10.0)
    assert _nearest_region((8.0, 0.0), regions).name == "b"
    with pytest.raises(ValueError, match="regions"):
        _nearest_region((0.0, 0.0), [])


def test_world_map_place_seed_points_bounds_and_validation():
    from veilbreakers_terrain.handlers.world_map import _place_seed_points

    points = _place_seed_points(5, 100.0, random.Random(7))

    assert len(points) == 5
    assert all(0.0 <= x <= 100.0 and 0.0 <= y <= 100.0 for x, y in points)
    assert _place_seed_points(0, 100.0, random.Random(7)) == []
    with pytest.raises(ValueError, match="map_size"):
        _place_seed_points(1, 0.0, random.Random(7))


def test_world_map_compute_voronoi_bounds_are_bounded_and_validate_inputs():
    from veilbreakers_terrain.handlers.world_map import _compute_voronoi_bounds

    centers = [(10.0, 10.0), (90.0, 10.0), (50.0, 90.0)]

    min_x, min_y, max_x, max_y = _compute_voronoi_bounds(
        0,
        centers,
        100.0,
        resolution=8,
    )

    assert 0.0 <= min_x < max_x <= 100.0
    assert 0.0 <= min_y < max_y <= 100.0
    with pytest.raises(ValueError, match="idx"):
        _compute_voronoi_bounds(3, centers, 100.0)
    with pytest.raises(ValueError, match="map_size"):
        _compute_voronoi_bounds(0, centers, -1.0)


def test_world_map_build_connections_creates_connected_unique_graph():
    from veilbreakers_terrain.handlers.world_map import Region, _build_connections

    regions = [
        Region(f"r{i}", "dark_forest", (float(i) * 10.0, 0.0), (0, 0, 1, 1), 1.0)
        for i in range(5)
    ]

    connections = _build_connections(regions, random.Random(3), map_size=100.0)
    edge_keys = {
        tuple(sorted((conn.from_region, conn.to_region)))
        for conn in connections
    }

    assert len(connections) >= len(regions) - 1
    assert len(edge_keys) == len(connections)
    assert all(conn.distance > 0.0 for conn in connections)
    assert _build_connections([regions[0]], random.Random(3), map_size=100.0) == []


def test_world_map_generate_world_map_rejects_nonpositive_map_size():
    from veilbreakers_terrain.handlers.world_map import generate_world_map

    with pytest.raises(ValueError, match="map_size"):
        generate_world_map(map_size=0.0)
