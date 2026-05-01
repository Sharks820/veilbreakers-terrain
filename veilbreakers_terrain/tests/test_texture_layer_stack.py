"""Terrain texture layer stack contract tests."""

from __future__ import annotations

import numpy as np

from veilbreakers_terrain.handlers.terrain_texture_layer_stack import (
    TerrainTextureLayerStack,
    TextureLayer,
)


def _layer(layer_id: str, weight: np.ndarray | None) -> TextureLayer:
    shape = (2, 2) if weight is None else weight.shape
    return TextureLayer(
        layer_id=layer_id,
        terrain_mask_source=f"{layer_id}_mask",
        weight_map=weight,
        normal=np.zeros((*shape, 3), dtype=np.float32),
        roughness=np.full(shape, 0.5, dtype=np.float32),
        ambient_occlusion=np.ones(shape, dtype=np.float32),
        no_displacement_reason="flat reference test layer",
    )


def test_normalized_weights_sum_to_one_per_nonzero_pixel():
    stack = TerrainTextureLayerStack(
        layers=[
            _layer("rock", np.array([[1.0, 0.0], [2.0, 1.0]], dtype=np.float32)),
            _layer("moss", np.array([[1.0, 3.0], [2.0, 0.0]], dtype=np.float32)),
        ]
    )

    weights = stack.normalized_weights()

    assert weights.shape == (2, 2, 2)
    assert weights.dtype == np.float32
    assert np.allclose(weights.sum(axis=-1), 1.0)
    assert np.allclose(weights[0, 0], [0.5, 0.5])
    assert np.allclose(weights[0, 1], [0.0, 1.0])


def test_normalized_weights_zero_total_pixel_stays_zero():
    stack = TerrainTextureLayerStack(
        layers=[
            _layer("rock", np.zeros((2, 2), dtype=np.float32)),
            _layer("moss", None),
        ]
    )

    weights = stack.normalized_weights()

    assert weights.shape == (2, 2, 2)
    assert np.all(weights == 0.0)


def test_normalized_weights_empty_stack_has_zero_layer_axis():
    stack = TerrainTextureLayerStack()

    weights = stack.normalized_weights()

    assert weights.shape == (1, 1, 0)
    assert weights.dtype == np.float32


def test_validate_uses_stack_get_for_mask_sources():
    class GetOnlyStack:
        def __init__(self) -> None:
            self._channels = {"rock_mask": np.ones((2, 2), dtype=np.float32)}

        def get(self, name: str):
            return self._channels.get(name)

    stack = TerrainTextureLayerStack(layers=[_layer("rock", np.ones((2, 2), dtype=np.float32))])

    assert stack.validate(GetOnlyStack()) == []


def test_validate_reports_missing_pbr_maps_mask_sources_and_bad_weight_ranges():
    class EmptyStack:
        def get(self, name: str):
            return None

    stack = TerrainTextureLayerStack(
        layers=[
            TextureLayer(
                layer_id="broken",
                terrain_mask_source="missing_mask",
                weight_map=None,
            ),
            TextureLayer(
                layer_id="bad_weight",
                terrain_mask_source="bad_weight_mask",
                weight_map=np.array([[1.2, -0.1], [0.5, 0.0]], dtype=np.float32),
                normal=np.zeros((2, 2, 3), dtype=np.float32),
                roughness=np.full((2, 2), 0.5, dtype=np.float32),
                ambient_occlusion=np.ones((2, 2), dtype=np.float32),
                height_displacement=np.zeros((2, 2), dtype=np.float32),
            ),
        ]
    )

    issues = stack.validate(EmptyStack())

    assert "broken: terrain_mask_source 'missing_mask' not found on stack" in issues
    assert "broken: missing weight_map" in issues
    assert "broken: missing normal map" in issues
    assert "broken: missing roughness" in issues
    assert "broken: missing AO (recommend adding)" in issues
    assert "broken: missing displacement, set no_displacement_reason if intentional" in issues
    assert "bad_weight: terrain_mask_source 'bad_weight_mask' not found on stack" in issues
    assert "bad_weight: weight_map out of [0,1] range" in issues
