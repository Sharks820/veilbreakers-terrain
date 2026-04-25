"""Direct tests for terrain_materials_v2 visual-quality helpers."""

from __future__ import annotations

import numpy as np
import pytest


def test_triplanar_blend_selects_projection_from_surface_normal():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import triplanar_blend

    normal = np.zeros((1, 1, 3), dtype=np.float32)
    normal[..., 2] = 1.0
    pos = np.array([[[2.0, 3.0, 10.0]]], dtype=np.float32)

    def noise_fn(uv: np.ndarray) -> np.ndarray:
        return uv[:, 0] + uv[:, 1]

    result = triplanar_blend(normal, pos, noise_fn, sharpness=4.0)

    assert result.shape == (1, 1)
    assert result.dtype == np.float32
    assert result[0, 0] == pytest.approx(5.0)


def test_compute_normal_z_handles_flat_steep_and_invalid_height_values():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import compute_normal_z

    flat = np.zeros((4, 4), dtype=np.float32)
    steep = np.tile(np.arange(4, dtype=np.float32) * 10.0, (4, 1))
    invalid = flat.copy()
    invalid[1, 1] = np.nan
    invalid[2, 2] = np.inf

    assert np.allclose(compute_normal_z(flat), 1.0)
    assert float(compute_normal_z(steep)[1:-1, 1:-1].mean()) < 0.2
    assert np.isfinite(compute_normal_z(invalid)).all()


def test_apply_brucks_blend_returns_nonnegative_competing_weights():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import apply_brucks_blend

    blend_alpha = np.array([[0.5, 1.0]], dtype=np.float32)
    rock_height = np.array([[0.8, 0.2]], dtype=np.float32)

    rock, dirt = apply_brucks_blend(blend_alpha, rock_height)

    assert rock.shape == blend_alpha.shape
    assert dirt.shape == blend_alpha.shape
    assert np.all(rock >= 0.0)
    assert np.all(dirt >= 0.0)
    assert np.all((rock + dirt) > 0.0)
    assert rock[0, 0] > dirt[0, 0]


def test_compute_snow_line_factor_uses_altitude_and_top_facing_normal():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import compute_snow_line_factor

    height = np.array([[0.0, 1.0]], dtype=np.float32)
    slope = np.zeros_like(height)
    normal_z = np.array([[1.0, 0.0]], dtype=np.float32)

    factor = compute_snow_line_factor(
        height,
        slope,
        {"snow_altitude": 0.5, "snow_transition": 0.05},
        normal_z=normal_z,
    )

    assert factor[0, 0] < 0.01
    assert factor[0, 1] == pytest.approx(0.2, abs=0.02)


def test_sample_macro_color_wraps_world_coordinates_into_texture_space():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import sample_macro_color

    texture = np.array(
        [
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            [[0.0, 0.0, 1.0], [1.0, 1.0, 1.0]],
        ],
        dtype=np.float32,
    )
    world_x = np.array([[0.0, 75.0]], dtype=np.float32)
    world_z = np.array([[75.0, 75.0]], dtype=np.float32)

    sampled = sample_macro_color(world_x, world_z, texture, tile_size_m=100.0)

    assert sampled.shape == (1, 2, 3)
    assert np.allclose(sampled[0, 0], [0.0, 0.0, 1.0])
    assert np.allclose(sampled[0, 1], [1.0, 1.0, 1.0])


def test_apply_sdf_road_blend_preserves_sum_and_noops_without_channel():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        MaterialChannel,
        MaterialRuleSet,
        apply_sdf_road_blend,
    )

    rules = MaterialRuleSet(
        channels=(
            MaterialChannel("ground"),
            MaterialChannel("scree"),
        ),
        default_channel_id="ground",
    )
    weights = np.full((2, 2, 2), 0.5, dtype=np.float32)
    sdf = np.array([[0.0, 1.0], [2.0, 3.0]], dtype=np.float32)

    blended = apply_sdf_road_blend(weights, sdf, rules, edge_fade_width=2.0)
    nooped = apply_sdf_road_blend(weights, sdf, rules, road_channel_id="missing")

    assert np.allclose(blended.sum(axis=2), 1.0)
    assert blended[0, 0, rules.index_of("scree")] == pytest.approx(1.0)
    assert blended[1, 0, rules.index_of("scree")] == pytest.approx(0.0)
    assert np.allclose(nooped, weights)


def test_resolve_height_blend_gammas_applies_defaults_overrides_and_fallbacks():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        _resolve_height_blend_gammas,
        default_dark_fantasy_rules,
    )

    rules = default_dark_fantasy_rules()

    gammas = _resolve_height_blend_gammas(
        rules,
        {"material_height_blend_gamma": {"cliff": 3.0, "snow": "bad"}},
    )

    assert len(gammas) == len(rules.channels)
    assert gammas[rules.index_of("cliff")] == pytest.approx(3.0)
    assert gammas[rules.index_of("snow")] == pytest.approx(1.0)
    assert gammas[rules.index_of("ground")] == pytest.approx(0.95)


def test_build_material_channel_exts_applies_hero_density_and_gamma_metadata():
    from veilbreakers_terrain.handlers.terrain_materials_v2 import (
        _build_material_channel_exts,
        default_dark_fantasy_rules,
    )

    rules = default_dark_fantasy_rules()
    exts = _build_material_channel_exts(
        rules,
        {
            "hero_material_ids": ("ground",),
            "material_height_blend_gamma": {"ground": 1.7},
            "material_texel_density_m": {"scree": "bad", "snow": 2048},
        },
    )

    ground = exts[rules.index_of("ground")]
    scree = exts[rules.index_of("scree")]
    snow = exts[rules.index_of("snow")]

    assert len(exts) == len(rules.channels)
    assert ground.height_blend_gamma == pytest.approx(1.7)
    assert ground.texel_density_m == pytest.approx(1024.0)
    assert scree.texel_density_m == pytest.approx(256.0)
    assert snow.texel_density_m == pytest.approx(2048.0)
